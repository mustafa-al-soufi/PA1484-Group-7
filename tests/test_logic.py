"""Unit tests for the app logic, run on a PC with a fake LVGL and a fake API.

Run from the repository root (see docs/TESTING.md):
    python -m unittest tests/test_logic.py -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest

# Find the project folder: one level up, or ../project if tests/ is next to it
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(HERE, "..")
if not os.path.isdir(os.path.join(PROJECT_DIR, "services")):
    PROJECT_DIR = os.path.join(HERE, "..", "project")
sys.path.insert(0, PROJECT_DIR)

# Do not write __pycache__ into the project, it would take space on the ESP32
sys.dont_write_bytecode = True

# These modules only exist on the board, so we fake them here
sys.modules["urequests"] = types.ModuleType("urequests")
secrets = types.ModuleType("secrets")
secrets.TRAFIKLAB_API_KEY = "test"
secrets.RESROBOT_API_KEY = "test"
secrets.WIFI_SSID = "test"
secrets.WIFI_PASSWORD = "test"
sys.modules["secrets"] = secrets

# The worker runs its thread at once here, and Wi-Fi is always connected
fake_thread = types.ModuleType("_thread")
fake_thread.stack_size = lambda size: None
fake_thread.start_new_thread = lambda function, args: function(*args)
sys.modules["_thread"] = fake_thread


class FakeStation:
    """network.WLAN: connected unless the test says otherwise."""

    connected = True

    def isconnected(self):
        return FakeStation.connected


fake_network = types.ModuleType("network")
fake_network.STA_IF = 0
fake_network.WLAN = lambda interface: FakeStation()
sys.modules["network"] = fake_network


class FakeObj:
    """Stands for any LVGL widget. It remembers what the tests look at."""

    def __init__(self, parent=None):
        self.children = []
        self.text = ""
        self.options = ""
        self.selected = 0
        self.callbacks = []
        if isinstance(parent, FakeObj):
            parent.children.append(self)

    def __getattr__(self, name):
        # Any other LVGL call (styles, sizes, flags) does nothing
        return lambda *args, **kwargs: FakeObj()

    def set_text(self, text):
        self.text = text

    def set_options(self, options):
        self.options = options

    def set_selected(self, index):
        self.selected = index

    def get_selected(self):
        return self.selected

    def add_event_cb(self, callback, *args):
        self.callbacks.append(callback)

    def clean(self):
        self.children = []

    def all_texts(self):
        """Return the text of this widget and every widget inside it."""
        texts = [self.text] if self.text else []
        for child in self.children:
            texts += child.all_texts()
        return texts


class Anything:
    """Stands for any LVGL constant, like lv.OPA.COVER or lv.DIR.LEFT."""

    def __getattr__(self, name):
        return Anything()

    def __call__(self, *args, **kwargs):
        return FakeObj()

    def __or__(self, other):
        return self


FakeObj.FLAG = Anything()
fake_lv = types.ModuleType("lvgl")
fake_lv.obj = fake_lv.label = fake_lv.dropdown = fake_lv.button = FakeObj
fake_lv.tileview = FakeObj
fake_lv.pct = lambda value: value
fake_lv.color_hex = lambda value: value
fake_lv.__getattr__ = lambda name: Anything()
sys.modules["lvgl"] = fake_lv

fake_board = types.ModuleType("board_lvgl")
FAKE_HANDLER = object()  # stands for the skeleton's TaskHandler
fake_board.start_board = lambda: (None, None, FAKE_HANDLER)
sys.modules["board_lvgl"] = fake_board
fake_log = types.ModuleType("debug_log")
fake_log.log = lambda text: None
sys.modules["debug_log"] = fake_log

from screens import settings as settings_manager  # noqa: E402
from services import trafiklab  # noqa: E402
from services.departure_worker import DepartureWorker  # noqa: E402
from screens import journey  # noqa: E402
from screens import departure as departure_screen  # noqa: E402

STOP_NAMES = [stop["name"] for stop in trafiklab.STOPS]


class FakeStream:
    """Gives out the data a few bytes at a time, like a slow connection."""

    def __init__(self, data, size=5):
        self.data = data
        self.size = size
        self.pos = 0

    def read(self, n):
        chunk = self.data[self.pos:self.pos + self.size]
        self.pos += self.size
        return chunk


class FakeResponse:
    def __init__(self, body, status=200):
        self.raw = FakeStream(body)
        self.status_code = status

    def close(self):
        pass


def fake_api(body, status=200):
    """Make the app get this answer instead of calling the API."""
    trafiklab.urequests.get = lambda url, timeout=10: FakeResponse(body, status)


def departure(time, mode="BUS"):
    return {
        "scheduled": "2026-10-11T" + time + ":00",
        "route": {"designation": "1", "direction": "Lyckeby", "transport_mode": mode},
    }


def leg(kind, name, start, end, origin="Karlskrona Kungsplan (Karlskrona kn)"):
    """A ResRobot leg. kind is JNY (a ride), WALK or TRSF (a transfer)."""
    return {
        "type": kind,
        "name": name,
        "Origin": {"name": origin, "time": start + ":00"},
        "Destination": {"name": "Somewhere", "time": end + ":00"},
    }


def trip(*legs):
    return {"LegList": {"Leg": list(legs)}}


class TestSettings(unittest.TestCase):
    def setUp(self):
        # Work in an empty folder so we never touch a real settings.json
        self.old_dir = os.getcwd()
        self.folder = tempfile.TemporaryDirectory()
        os.chdir(self.folder.name)

    def tearDown(self):
        os.chdir(self.old_dir)
        self.folder.cleanup()

    def test_no_file_gives_defaults(self):
        """US3.4: without a saved file the defaults are used."""
        self.assertEqual(settings_manager.load(), settings_manager.defaults())

    def test_save_then_load(self):
        """US3.4: saved settings are loaded again after a restart."""
        data = {"stop_id": "9", "stop_name": "Hamnen", "transport": "Ferry"}
        settings_manager.save(data)
        self.assertEqual(settings_manager.load(), data)

    def test_broken_file_gives_defaults(self):
        """US3.4: a damaged file gives the defaults, not a crash."""
        with open("settings.json", "w") as f:
            f.write("{not json")
        self.assertEqual(settings_manager.load(), settings_manager.defaults())

    def test_bad_transport_becomes_all(self):
        """US3.3, US3.4: an unknown saved transport type becomes All."""
        result = settings_manager._clean({"transport": "Rocket"})
        self.assertEqual(result["transport"], "All")

    def test_save_replaces_the_old_file(self):
        """US3.4: saving again replaces the file, no temporary file is left."""
        settings_manager.save({"stop_id": "1", "stop_name": "A", "transport": "Bus"})
        self.assertTrue(settings_manager.save({"stop_id": "2", "stop_name": "B"}))
        self.assertEqual(settings_manager.load()["stop_id"], "2")
        self.assertEqual(os.listdir("."), ["settings.json"])  # no .tmp file left


class TestDepartures(unittest.TestCase):
    def test_delayed_only_from_60_seconds(self):
        """US1.2B: a departure is Delayed from 60 seconds late."""
        self.assertEqual(trafiklab._status({"delay": 59}), "On time")
        self.assertEqual(trafiklab._status({"delay": 60}), "Delayed")

    def test_canceled(self):
        """US1.2B: a canceled departure shows Canceled."""
        self.assertEqual(trafiklab._status({"canceled": True}), "Canceled")

    def test_transport_filter(self):
        """US3.3: the transport filter; All lets every type through."""
        bus = {"route": {"transport_mode": "BUS"}}
        self.assertTrue(trafiklab._matches_transport(bus, "Bus"))
        self.assertFalse(trafiklab._matches_transport(bus, "Train"))
        self.assertTrue(trafiklab._matches_transport(bus, "All"))

    def test_ferry_filter_matches_boat(self):
        """US3.3: Ferry matches the API's BOAT."""
        # The API writes BOAT for ferries (US3.3)
        boat = {"route": {"transport_mode": "BOAT"}}
        self.assertTrue(trafiklab._matches_transport(boat, "Ferry"))
        self.assertFalse(trafiklab._matches_transport(boat, "Bus"))

    def test_time_comes_from_realtime(self):
        """US1.2B: the shown time is the live (realtime) time."""
        item = departure("17:30")
        item["realtime"] = "2026-10-11T17:35:00"
        self.assertEqual(trafiklab._to_departure(item)["time"], "17:35")

    def test_earliest_first_and_limited(self):
        """US1.2B: departures are sorted by time and limited."""
        items = [departure(t) for t in ("12:00", "10:00", "11:00", "09:00")]
        fake_api(json.dumps({"departures": items}).encode())
        result = trafiklab.get_departures("1", limit=2)
        self.assertEqual([d["time"] for d in result], ["09:00", "10:00"])

    def test_stops_reading_after_two_pages_and_margin(self):
        """US1.2B: only the needed departures are read (saves RAM)."""
        items = [departure("10:%02d" % i) for i in range(40)]
        body = json.dumps({"departures": items}).encode()
        fake_api(body)
        response = FakeResponse(body)
        trafiklab.urequests.get = lambda url, timeout=10: response
        result = trafiklab.get_departures("1", limit=12)
        self.assertEqual(
            [d["time"] for d in result], ["10:%02d" % i for i in range(12)]
        )
        # Only 12 + the margin were read, not all 40
        read = response.raw.pos
        self.assertLess(read, len(body))
        one_item = len(json.dumps(items[0])) + 2
        self.assertLessEqual(read, (12 + trafiklab.EXTRA_DEPARTURES + 2) * one_item)

    def test_filter_gives_only_trains(self):
        """US3.3: a Train filter gives only trains from the API answer."""
        items = [departure("08:00", "BUS"), departure("09:00", "TRAIN")]
        fake_api(json.dumps({"departures": items}).encode())
        result = trafiklab.get_departures("1", transport="Train")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["time"], "09:00")

    def test_server_error_gives_none(self):
        """US1.2B: an HTTP error gives None and the error text."""
        fake_api(b"", status=403)
        self.assertIsNone(trafiklab.get_departures("1"))
        self.assertIn("403", trafiklab.get_last_error())


class TestStops(unittest.TestCase):
    def test_five_fixed_stops(self):
        """US3.2B: the five fixed Karlskrona stops."""
        names = [stop["name"] for stop in trafiklab.STOPS]
        self.assertEqual(len(names), 5)
        self.assertIn("Karlskrona Centralstation", names)
        self.assertIn("Campus Gräsvik", names)

    def test_fixed_stops_have_unique_ids(self):
        """US3.2B: the fixed stops have unique numeric ids."""
        ids = [stop["id"] for stop in trafiklab.STOPS]
        self.assertEqual(len(set(ids)), 5)
        for stop_id in ids:
            # Trafiklab stop area ids are numbers sent as text
            self.assertTrue(stop_id.isdigit(), stop_id)

    def test_get_stops_gives_a_copy(self):
        """US3.2B: get_stops gives a copy, so the fixed stops never change."""
        stops = trafiklab.get_stops()
        self.assertEqual(stops, [dict(stop) for stop in trafiklab.STOPS])
        stops.insert(0, {"id": "1", "name": "Saved"})
        stops[1]["name"] = "Changed"
        self.assertEqual(len(trafiklab.STOPS), 5)
        self.assertEqual(trafiklab.STOPS[0]["name"], "Karlskrona Centralstation")

    def test_stop_search_code_is_removed(self):
        """US3.2B: the fixed stops are only id and name; the old search code is gone."""
        for name in ("find_stops", "_search", "_matches", "_padded"):
            self.assertFalse(hasattr(trafiklab, name), name)
        for stop in trafiklab.STOPS:
            self.assertEqual(sorted(stop), ["id", "name"])

    def test_stop_inside_and_outside_karlskrona(self):
        """US3.2C: a found stop must be in the Karlskrona area."""
        karlskrona = {"stops": [{"lat": 56.16, "lon": 15.59}]}
        malmo = {"stops": [{"lat": 55.60, "lon": 13.00}]}
        self.assertTrue(trafiklab._in_area(karlskrona))
        self.assertFalse(trafiklab._in_area(malmo))

    def test_swedish_letters_in_url(self):
        """US3.2C: å ä ö are %-encoded in the search URL."""
        self.assertEqual(trafiklab._url_encode("Gräsvik"), "Gr%C3%A4svik")


class TestJourneys(unittest.TestCase):
    """US5.3: the best journeys between two stops from ResRobot."""

    def test_line_names_use_app_transport_types(self):
        """US5.3: line names use the app's transport types."""
        self.assertEqual(trafiklab._line_name("Länstrafik - Buss 6"), "Bus 6")
        self.assertEqual(trafiklab._line_name("Länstrafik buss 1"), "Bus 1")
        self.assertEqual(trafiklab._line_name("Öresundståg 1076"), "Train 1076")
        self.assertEqual(trafiklab._line_name("Länstrafik - Båt 4"), "Ferry 4")
        self.assertEqual(trafiklab._line_name("Taxi"), "Taxi")

    def test_direct_journey(self):
        """US5.3: a direct journey has its departure, arrival and no changes."""
        result = trafiklab._to_trip(
            trip(leg("JNY", "Länstrafik - Buss 6", "08:00", "08:20"))
        )
        self.assertEqual(result["departure"], "08:00")
        self.assertEqual(result["arrival"], "08:20")
        self.assertEqual(result["changes"], 0)

    def test_change_shows_time_at_each_change(self):
        """US5.3: a journey with a change shows the time at each change."""
        result = trafiklab._to_trip(
            trip(
                leg("WALK", "", "07:55", "08:00"),
                leg("JNY", "Länstrafik - Buss 5", "08:00", "08:10"),
                leg("TRSF", "", "08:10", "08:14"),
                leg("JNY", "Länstrafik - Buss 1", "08:15", "08:25", "Bergåsa centrum"),
            )
        )
        self.assertEqual(result["changes"], 1)
        self.assertEqual([r["time"] for r in result["rides"]], ["08:00", "08:15"])
        self.assertEqual(result["rides"][1]["stop"], "Bergåsa centrum")
        self.assertEqual(result["departure"], "07:55")  # the walk is part of it

    def test_municipality_is_removed_from_stop_name(self):
        """US5.3: "(Karlskrona kn)" is removed from stop names."""
        result = trafiklab._to_trip(trip(leg("JNY", "Buss 1", "08:00", "08:10")))
        self.assertEqual(result["rides"][0]["stop"], "Karlskrona Kungsplan")

    def test_single_leg_as_object(self):
        """US5.3: one leg given as an object instead of a list."""
        # ResRobot can give one leg as an object instead of a list
        single = {"LegList": {"Leg": leg("JNY", "Buss 1", "08:00", "08:10")}}
        self.assertEqual(trafiklab._to_trip(single)["changes"], 0)

    def test_at_most_five_journeys(self):
        """US5.3: at most five journeys are kept."""
        trips = [trip(leg("JNY", "Buss 1", "08:00", "08:10"))] * 7
        fake_api(json.dumps({"Trip": trips}).encode())
        self.assertEqual(len(trafiklab.get_trips("1", "2")), 5)

    def test_journey_server_error_gives_none(self):
        """US5.3: an HTTP error gives None and the error text."""
        fake_api(b"", status=400)
        self.assertIsNone(trafiklab.get_trips("1", "2"))
        self.assertIn("400", trafiklab.get_last_error())


class TestWorker(unittest.TestCase):
    """The worker keeps departures and journeys apart."""

    def test_journey_result_is_not_a_departure_result(self):
        """US5.3: a journey result is kept apart from departures."""
        fake_api(
            json.dumps(
                {"Trip": [trip(leg("JNY", "Buss 1", "08:00", "08:10"))]}
            ).encode()
        )
        worker = DepartureWorker("Karlskrona", stop_id="1")
        self.assertTrue(worker.start(("1", "2")))
        self.assertIsNone(worker.take_result())
        trips, error = worker.take_journey()
        self.assertEqual(len(trips), 1)
        self.assertEqual(error, "")
        self.assertFalse(worker.busy)

    def test_no_new_fetch_while_busy(self):
        """US4.1: no second fetch starts while one is running."""
        worker = DepartureWorker("Karlskrona", stop_id="1")
        worker.busy = True
        self.assertFalse(worker.start(("1", "2")))

    def test_stop_search_is_not_a_departure_result(self):
        """US3.2C: a stop search has its own result, given once."""
        # US3.2C: a stop search has its own result
        karlskrona = [{"lat": 56.16, "lon": 15.59}]
        fake_api(
            json.dumps(
                {
                    "stop_groups": [
                        {
                            "id": "1",
                            "name": "Kungsplan",
                            "average_daily_stop_times": 50,
                            "stops": karlskrona,
                        },
                    ]
                }
            ).encode()
        )
        worker = DepartureWorker("Karlskrona", stop_id="1")
        self.assertTrue(worker.start(search="Kungs"))
        self.assertIsNone(worker.take_result())
        self.assertIsNone(worker.take_journey())
        stops, error = worker.take_stops()
        self.assertEqual([stop["name"] for stop in stops], ["Kungsplan"])
        self.assertEqual(error, "")
        self.assertIsNone(worker.take_stops())  # only once


class TestStopSearch(unittest.TestCase):
    """US3.2C: only useful stops, busiest first."""

    def test_filtered_and_sorted(self):
        """US3.2C: only useful stops in the area, one per name, busiest first."""
        here = [{"lat": 56.16, "lon": 15.59}]
        groups = [
            {"id": "1", "name": "Quiet", "average_daily_stop_times": 5, "stops": here},
            {"id": "2", "name": "Busy", "average_daily_stop_times": 500, "stops": here},
            {
                "id": "3",
                "name": "Busy",
                "average_daily_stop_times": 50,
                "stops": here,
            },  # same name
            {
                "id": "4",
                "name": "Town",
                "average_daily_stop_times": 900,
                "stops": here,
                "area_type": "META_STOP",
            },
            {
                "id": "5",
                "name": "No traffic",
                "average_daily_stop_times": 0,
                "stops": here,
            },
            {
                "id": "6",
                "name": "Malmo",
                "average_daily_stop_times": 800,
                "stops": [{"lat": 55.6, "lon": 13.0}],
            },
        ] + [
            {
                "id": str(10 + i),
                "name": "Stop %d" % i,
                "average_daily_stop_times": 10 + i,
                "stops": here,
            }
            for i in range(12)
        ]
        stops = trafiklab.useful_stops(groups)
        self.assertEqual(len(stops), 10)
        self.assertEqual(stops[0], {"id": "2", "name": "Busy", "traffic": 500})
        names = [stop["name"] for stop in stops]
        for name in ("Town", "No traffic", "Malmo", "Quiet"):
            self.assertNotIn(name, names)  # Quiet is not among the 10 busiest
        self.assertEqual(names.count("Busy"), 1)
        traffic = [stop["traffic"] for stop in stops]
        self.assertEqual(traffic, sorted(traffic, reverse=True))

    def test_default_stop_is_the_first_fixed_stop(self):
        """US3.2B: the default stop is the first fixed stop."""
        worker = DepartureWorker("Karlskrona")
        self.assertEqual(worker.stop_id, trafiklab.STOPS[0]["id"])
        self.assertEqual(worker.stop_name, trafiklab.STOPS[0]["name"])

    def test_saved_stop_is_kept(self):
        """US3.4: a saved stop id is used at start-up."""
        worker = DepartureWorker("Karlskrona", stop_id="740020510")
        self.assertEqual(worker.stop_id, "740020510")

    def test_fetch_makes_no_stop_search(self):
        """US1.2B: a departure fetch is one request, without a stop search."""
        urls = []
        body = json.dumps({"departures": [departure("08:00")]}).encode()

        def fake_get(url, timeout=10):
            urls.append(url)
            return FakeResponse(body)

        trafiklab.urequests.get = fake_get
        worker = DepartureWorker("Karlskrona")
        self.assertTrue(worker.start())
        departures, error = worker.take_result()
        self.assertEqual(len(departures), 1)
        self.assertEqual(error, "")
        # One request, straight to the departures of the first fixed stop
        self.assertEqual(len(urls), 1)
        self.assertIn("departures/" + trafiklab.STOPS[0]["id"], urls[0])
        self.assertNotIn("stops/name", urls[0])


def departures_list(count, status="On time"):
    """``count`` departures with the times 09:00, 09:01, ..."""
    return [
        {"time": "09:%02d" % i, "line": "1", "status": status} for i in range(count)
    ]


class TestDepartureScreen(unittest.TestCase):
    """US1.2B: the departure list, drawn with as few objects as possible."""

    def setUp(self):
        # Remember which widgets are hidden (the fake LVGL does not)
        self.hidden = {}
        self.real_set_hidden = departure_screen._set_hidden

        def record(widget, hidden):
            self.hidden[id(widget)] = hidden
            self.real_set_hidden(widget, hidden)

        departure_screen._set_hidden = record
        self.screen = departure_screen.create_departure_screen(FakeObj())

    def tearDown(self):
        departure_screen._set_hidden = self.real_set_hidden

    def is_hidden(self, widget):
        return self.hidden.get(id(widget), False)

    def times(self):
        """The times of the rows that are shown."""
        return [
            row["time"].text
            for row in self.screen["rows"]
            if not self.is_hidden(row["time"])
        ]

    def test_six_rows_fit_without_scrolling(self):
        """US1.2B: six rows fit on the screen without scrolling."""
        # 450 px screen: 2 * 8 padding, title 44, header 30, attribution
        # about 16 and 3 gaps of 4 leave 332 px for the list
        room = 450 - 2 * 8 - 44 - 30 - 16 - 3 * 4
        rows = departure_screen.MAX_ROWS
        height = (
            rows * departure_screen.ROW_HEIGHT + (rows - 1) * departure_screen.ROW_GAP
        )
        self.assertLessEqual(height, room)
        # One row more would not fit
        self.assertGreater(
            height + departure_screen.ROW_HEIGHT + departure_screen.ROW_GAP, room
        )

    def test_rows_have_no_container(self):
        """US1.2B: six rows of four labels, without containers."""
        # 4 labels per row straight in the list, plus the message label
        children = self.screen["list"].children
        self.assertEqual(len(children), 6 * 4 + 1)
        for item in self.screen["rows"]:
            self.assertEqual(len(item["labels"]), 4)
            for label in item["labels"]:
                self.assertIn(label, children)

    def test_columns_like_the_old_flex_row(self):
        """US1.2B: the x positions of the four columns."""
        # Padding 4, then each column width plus the gap
        self.assertEqual(departure_screen._column_x(10), [4, 104, 184, 444])
        self.assertEqual(departure_screen._column_x(0), [4, 94, 164, 414])

    def test_labels_centered_in_their_row(self):
        """US1.2B: the labels are centered in their row."""
        # Row 50 high with padding 4: a 22 px line starts 14 px down
        self.assertEqual(departure_screen._label_y(0, 22), 14)
        # The next row starts 50 + 2 px further down
        self.assertEqual(departure_screen._label_y(1, 22), 66)

    def test_only_departures_that_exist_are_filled(self):
        """US1.2B: only rows with a departure are shown."""
        departures = [
            {
                "time": "08:0" + str(i),
                "line": "1",
                "destination": "Lyckeby",
                "status": "On time",
            }
            for i in range(3)
        ]
        departure_screen.update_departures(self.screen, departures)
        rows = self.screen["rows"]
        self.assertEqual(
            [row["time"].text for row in rows[:3]], ["08:00", "08:01", "08:02"]
        )
        self.assertEqual(rows[3]["time"].text, "")
        self.assertEqual(self.times(), ["08:00", "08:01", "08:02"])

    def test_status_color(self):
        """US1.2B: the status has its color (Delayed is orange)."""
        departure_screen.update_departures(self.screen, departures_list(2, "Delayed"))
        self.assertEqual(
            self.screen["rows"][1]["color"], departure_screen.COLOR_DELAYED
        )

    # Paging

    def test_page_count(self):
        """US1.2B: the number of pages for a number of departures."""
        counts = {0: 0, 1: 1, 6: 1, 7: 2, 12: 2, 17: 2}
        for count, pages in counts.items():
            self.assertEqual(departure_screen.page_count(count), pages, count)

    def test_page_controls(self):
        """US1.2B: when the page buttons are shown and enabled."""
        # (visible, up enabled, down enabled)
        self.assertEqual(departure_screen.page_controls(0, 0), (False, False, False))
        self.assertEqual(departure_screen.page_controls(0, 1), (False, False, False))
        self.assertEqual(departure_screen.page_controls(0, 2), (True, False, True))
        self.assertEqual(departure_screen.page_controls(1, 2), (True, True, False))

    def test_first_page_of_two(self):
        """US1.2B: twelve departures start on page 1 of 2."""
        departure_screen.update_departures(self.screen, departures_list(12))
        self.assertEqual(self.times(), ["09:0%d" % i for i in range(6)])
        self.assertEqual(self.screen["page_label"].text, "1/2")
        self.assertFalse(self.is_hidden(self.screen["down"]))

    def test_down_and_up_buttons(self):
        """US1.2B: the down and up buttons change the page."""
        departure_screen.update_departures(self.screen, departures_list(12))
        self.screen["down"].callbacks[0](None)
        self.assertEqual(self.times(), ["09:%02d" % i for i in range(6, 12)])
        self.assertEqual(self.screen["page_label"].text, "2/2")
        self.screen["up"].callbacks[0](None)
        self.assertEqual(self.times(), ["09:0%d" % i for i in range(6)])
        self.assertEqual(self.screen["page_label"].text, "1/2")

    def test_no_page_before_first_or_after_last(self):
        """US1.2B: no page before the first or after the last."""
        departure_screen.update_departures(self.screen, departures_list(12))
        self.assertFalse(departure_screen.change_page(self.screen, -1))
        self.assertTrue(departure_screen.change_page(self.screen, 1))
        self.assertFalse(departure_screen.change_page(self.screen, 1))
        self.assertEqual(self.screen["page"], 1)

    def test_short_last_page_hides_the_empty_rows(self):
        """US1.2B: a short last page hides the empty rows."""
        departure_screen.update_departures(self.screen, departures_list(8))
        departure_screen.change_page(self.screen, 1)
        self.assertEqual(self.times(), ["09:06", "09:07"])

    def test_buttons_hidden_with_one_page(self):
        """US1.2B: no page buttons with only one page."""
        departure_screen.update_departures(self.screen, departures_list(6))
        for name in ("up", "down", "page_label"):
            self.assertTrue(self.is_hidden(self.screen[name]), name)

    def test_buttons_hidden_with_a_message(self):
        """US1.2B: no rows or page buttons while a message is shown."""
        departure_screen.update_departures(self.screen, departures_list(12))
        departure_screen.show_message(self.screen, "Loading...")
        for name in ("up", "down", "page_label"):
            self.assertTrue(self.is_hidden(self.screen[name]), name)
        self.assertEqual(self.times(), [])

    def test_at_most_two_pages_are_kept(self):
        """US1.2B: at most two pages (12 departures) are kept."""
        departure_screen.update_departures(self.screen, departures_list(17))
        self.assertEqual(
            len(self.screen["departures"]), departure_screen.MAX_DEPARTURES
        )
        self.assertEqual(departure_screen.MAX_DEPARTURES, 12)
        departure_screen.change_page(self.screen, 1)
        self.assertEqual(self.times()[-1], "09:11")

    def test_new_departures_start_on_page_one(self):
        """US4.1: new departures start on page 1 again."""
        departure_screen.update_departures(self.screen, departures_list(12))
        departure_screen.change_page(self.screen, 1)
        departure_screen.update_departures(self.screen, departures_list(12))
        self.assertEqual(self.screen["page"], 0)
        self.assertEqual(self.screen["page_label"].text, "1/2")
        self.assertEqual(self.times()[0], "09:00")

    def test_page_change_creates_no_objects(self):
        """US1.2B: a page change creates no new objects."""
        departure_screen.update_departures(self.screen, departures_list(12))
        labels = list(self.screen["list"].children)
        departure_screen.change_page(self.screen, 1)
        departure_screen.change_page(self.screen, -1)
        self.assertEqual(self.screen["list"].children, labels)

    def test_long_destination_is_cut(self):
        """US1.2B: a long destination is cut."""
        departure_screen.update_departures(
            self.screen, [{"time": "10:00", "destination": "Karlskrona Centralstation"}]
        )
        dest = self.screen["rows"][0]["dest"].text
        self.assertEqual(len(dest), departure_screen.MAX_DESTINATION_CHARS)
        self.assertTrue(dest.endswith("."))

    def test_error_shows_message(self):
        """US1.2B: a failed fetch shows a message with the reason."""
        departure_screen.update_departures(self.screen, None, "No Wi-Fi")
        self.assertEqual(
            self.screen["message"].text, "Could not fetch departures\nNo Wi-Fi"
        )

    def test_attribution_is_shown(self):
        """NF3: the departure screen shows the Trafiklab attribution."""
        tile = FakeObj()
        departure_screen.create_departure_screen(tile)
        self.assertIn("Data: Trafiklab.se (CC BY 4.0)", tile.all_texts())


class TestJourneyScreen(unittest.TestCase):
    """US5.1 and US5.2: the journey screen and the stop selection."""

    def setUp(self):
        self.searches = []
        self.tile = FakeObj()
        self.screen = journey.create_journey_screen(
            self.tile, lambda event: self.searches.append(event)
        )

    def test_screen_has_search_and_attribution(self):
        """US5.1, NF3: the journey screen has Search and the Trafiklab attribution."""
        # US5.1: the screen exists, with a Search button and the Trafiklab text
        texts = self.tile.all_texts()
        self.assertIn("Search", texts)
        self.assertTrue(any("Trafiklab" in text for text in texts))

    def test_search_button_calls_on_search(self):
        """US5.2: the Search button calls on_search."""
        buttons = [w for w in self._all_widgets(self.tile) if w.callbacks]
        search = [b for b in buttons if "Search" in b.all_texts()][0]
        search.callbacks[0]("click")
        self.assertEqual(self.searches, ["click"])

    def test_both_dropdowns_get_the_five_stops(self):
        """US5.2: From and To get the five fixed stops."""
        journey.set_journey_stops(self.screen, STOP_NAMES)
        for key in ("from", "to"):
            self.assertEqual(len(self.screen[key].options.split("\n")), 5)
        self.assertIn("Campus Grasvik", self.screen["from"].options)

    def test_to_starts_on_another_stop(self):
        """US5.2: To starts on another stop than From."""
        journey.set_journey_stops(self.screen, STOP_NAMES)
        self.assertEqual(journey.get_journey_selection(self.screen), (0, 1))

    def test_message_is_shown(self):
        """US5.2: a message is shown next to Search."""
        journey.show_journey_message(self.screen, "Choose two different stops", False)
        self.assertEqual(self.screen["message"].text, "Choose two different stops")

    def test_journeys_are_listed(self):
        """US5.3: journeys are listed, one line per ride."""
        trips = [
            trafiklab._to_trip(
                trip(leg("JNY", "Länstrafik - Buss 6", "08:00", "08:20"))
            )
        ]
        journey.show_trips(self.screen, trips)
        texts = self.screen["results"].all_texts()
        self.assertIn("08:00 -> 08:20   Direct", texts)
        self.assertIn("08:00  Bus 6  from Karlskrona Kungsplan", texts)

    def test_no_journeys_and_errors(self):
        """US5.3: no journeys or a running search gives a message."""
        journey.show_trips(self.screen, [])
        self.assertEqual(self.screen["results"].all_texts(), ["No journeys found"])
        journey.show_trips(self.screen, None, "Searching...")
        self.assertEqual(self.screen["results"].all_texts(), ["Searching..."])

    def _all_widgets(self, widget):
        widgets = [widget]
        for child in widget.children:
            widgets += self._all_widgets(child)
        return widgets


def main_module():
    return sys.modules["main"]


class TestSearch(unittest.TestCase):
    """US5.2 and US5.3: what happens when Search is pressed in the app."""

    @classmethod
    def setUpClass(cls):
        # Importing main starts the app. Hide its output.
        fake_api(b"{}")
        with contextlib.redirect_stdout(io.StringIO()):
            import main
        cls.app = main.app

    def setUp(self):
        self.app.journey_pending = False
        self.app.worker.busy = False
        self.app.worker.set_stop(trafiklab.STOPS[0]["id"], STOP_NAMES[0])
        self.app.apply_stops(trafiklab.get_stops())
        self.app.set_trip_stops("from", trafiklab.get_stops())
        self.app.set_trip_stops("to", trafiklab.get_stops(), 1)
        self.screen = self.app.journey_screen

    def test_skeleton_runs_lvgl(self):
        """NF4: the app uses start_board() and keeps the skeleton's TaskHandler."""
        self.assertIs(self.app.handler, FAKE_HANDLER)
        for name in ("start_fast_board", "run_ui_loop"):
            self.assertFalse(hasattr(main_module(), name), name)

    def test_fetch_limit_is_two_pages(self):
        """US1.2B: the app fetches two pages of departures."""
        self.assertEqual(self.app.worker.limit, departure_screen.MAX_DEPARTURES)
        self.assertEqual(self.app.worker.limit, 12)

    def test_stops_are_filled_at_start_up(self):
        """US3.2B: the fixed stops are in the dropdown at start-up."""
        # No search at start-up: the fixed stops are in the dropdowns at once
        options = self.app.settings_screen["stop_dropdown"].options.split("\n")
        self.assertEqual(options[0], "Karlskrona Centralstation")
        self.assertEqual(len(options), 5)
        self.assertEqual(len(self.app.stops), 5)

    def select(self, from_index, to_index):
        self.screen["from"].selected = from_index
        self.screen["to"].selected = to_index

    def test_same_stop_gives_message(self):
        """US5.2: the same stop twice gives a message and no search."""
        self.select(2, 2)
        self.app.on_search_clicked(None)
        self.assertEqual(self.screen["message"].text, "Choose two different stops")
        self.assertFalse(self.app.journey_pending)

    def test_search_while_stops_load(self):
        """US5.2: Search before the stops are loaded gives a message."""
        self.app.trip_stops = {}  # the From and To lists (US5.2B)
        self.app.on_search_clicked(None)
        self.assertEqual(self.screen["message"].text, "Stops are still loading")

    def test_from_and_to_searches_fill_their_own_dropdown(self):
        """US5.2B: a From or To search fills only its own dropdown."""
        # US5.2B: a To search fills only To, a From search only From
        here = [{"lat": 56.16, "lon": 15.59}]

        def search(side, name):
            fake_api(
                json.dumps(
                    {
                        "stop_groups": [
                            {
                                "id": name,
                                "name": name,
                                "average_daily_stop_times": 9,
                                "stops": here,
                            },
                        ]
                    }
                ).encode()
            )
            self.app.stop_search(side, name)
            self.app.poll_worker()  # starts the search
            self.app.poll_worker()  # shows the result

        search("to", "Lyckeby")
        self.assertEqual(self.screen["to"].options, "Lyckeby")
        self.assertIn("Kungsplan", self.screen["from"].options)
        self.assertEqual(self.screen["message"].text, "1 stops found")
        search("from", "Nattraby")
        self.assertEqual(self.screen["from"].options, "Nattraby")
        self.assertEqual(self.screen["to"].options, "Lyckeby")
        self.assertIn("Kungsplan", self.app.settings_screen["stop_dropdown"].options)
        self.app.stop_search("to", "")  # empty: the fixed stops again
        self.assertIn("Kungsplan", self.screen["to"].options)

    def test_search_starts_journey_search(self):
        """US5.2: Search starts a journey search for the selected stops."""
        self.select(0, 1)
        self.app.on_search_clicked(None)
        self.assertTrue(self.app.journey_pending)
        self.assertEqual(self.app.journey_from["name"], STOP_NAMES[0])
        self.assertEqual(self.app.journey_to["name"], STOP_NAMES[1])

    def test_journeys_reach_the_screen(self):
        """US5.3, US5.3B: found journeys reach the screen, the best one marked."""
        fake_api(
            json.dumps(
                {"Trip": [trip(leg("JNY", "Buss 1", "08:00", "08:10"))]}
            ).encode()
        )
        self.select(0, 1)
        self.app.on_search_clicked(None)
        self.app.poll_worker()  # starts the search
        self.app.poll_worker()  # shows the result
        self.assertIn(
            "Best  08:00 -> 08:10   Direct", self.screen["results"].all_texts()
        )

    def test_best_journey_first(self):
        """US5.3B: sorted by arrival; an arrival after midnight counts as later."""
        # US5.3B: sorted by arrival; after midnight counts as later
        trips = [
            {"departure": d, "arrival": a}
            for d, a in (("23:10", "23:58"), ("23:20", "00:15"), ("23:00", "23:40"))
        ]
        best = main_module().best_first(trips)
        self.assertEqual([t["arrival"] for t in best], ["23:40", "23:58", "00:15"])
        self.assertTrue(best[0]["best"])
        self.assertFalse(best[1].get("best"))
        self.assertEqual(main_module().best_first([]), [])


def stop_groups(*names):
    """A stop search answer with one stop in Karlskrona per name."""
    here = [{"lat": 56.16, "lon": 15.59}]
    groups = [
        {"id": name, "name": name, "average_daily_stop_times": 9, "stops": here}
        for name in names
    ]
    return json.dumps({"stop_groups": groups}).encode()


class TestAppSettings(unittest.TestCase):
    """US3.2C-US4.3: the settings screen and the refresh in the running app."""

    @classmethod
    def setUpClass(cls):
        fake_api(b"{}")
        with contextlib.redirect_stdout(io.StringIO()):
            import main
        cls.app = main.app

    def setUp(self):
        # Work in an empty folder so we never touch a real settings.json
        self.old_dir = os.getcwd()
        self.folder = tempfile.TemporaryDirectory()
        os.chdir(self.folder.name)
        app = self.app
        app.refresh_pending = app.journey_pending = app.refreshing = False
        app.search_pending = None
        app.worker.busy = False
        app.worker.take_result()
        app.worker.set_transport("All")
        app.worker.set_stop(trafiklab.STOPS[0]["id"], STOP_NAMES[0])
        app.apply_stops(trafiklab.get_stops())
        self.screen = app.settings_screen

    def tearDown(self):
        os.chdir(self.old_dir)
        self.folder.cleanup()

    def poll_twice(self):
        self.app.poll_worker()  # starts the job
        self.app.poll_worker()  # shows the result

    def test_settings_stop_search_fills_the_stop_dropdown(self):
        """US3.2C: a stop search on the settings screen fills the stop dropdown."""
        fake_api(stop_groups("Lyckeby"))
        self.app.on_stop_search("Lyckeby")
        self.assertEqual(self.screen["message"].text, "Searching...")
        self.poll_twice()
        # The current stop stays on top, the found stop below it
        self.assertEqual(
            self.screen["stop_dropdown"].options, "Karlskrona Centralstation\nLyckeby"
        )
        self.assertEqual(self.screen["message"].text, "1 stops found")

    def test_transport_change_fetches_again(self):
        """US3.3: a new transport type is used and the departures are fetched again."""
        self.screen["transport_dropdown"].selected = 3
        self.app.on_transport_changed(None)
        self.assertEqual(self.app.worker.transport, "Ferry")
        self.assertTrue(self.app.refresh_pending)
        self.assertEqual(self.app.departure_list["message"].text, "Loading...")

    def test_save_as_default(self):
        """US3.4: Save as Default stores the current stop and transport type."""
        self.app.select_stop(2)
        self.app.worker.set_transport("Bus")
        self.app.on_save_clicked(None)
        self.assertEqual(self.screen["message"].text, "Saved as default")
        self.assertEqual(
            settings_manager.load(),
            {"stop_id": trafiklab.STOPS[2]["id"], "stop_name": STOP_NAMES[2],
             "transport": "Bus"},
        )

    def test_reset_to_saved_default(self):
        """US3.5: Reset to Default brings back the saved stop and transport type."""
        stop = trafiklab.STOPS[3]
        settings_manager.save(
            {"stop_id": stop["id"], "stop_name": stop["name"], "transport": "Train"}
        )
        self.app.select_stop(1)
        self.app.on_reset_clicked(None)
        self.assertEqual(self.app.worker.transport, "Train")
        self.assertEqual(self.app.worker.stop_id, stop["id"])
        self.assertEqual(self.screen["transport_dropdown"].selected, 2)
        self.assertEqual(self.screen["stop_dropdown"].selected, 3)
        self.assertEqual(self.screen["message"].text, "Reset to default")
        self.assertTrue(self.app.refresh_pending)

    def test_reset_without_saved_default(self):
        """US3.5: Reset without saved settings gives the first stop and All."""
        self.app.select_stop(2)
        self.app.worker.set_transport("Bus")
        self.app.on_reset_clicked(None)
        self.assertEqual(self.app.worker.stop_id, trafiklab.STOPS[0]["id"])
        self.assertEqual(self.app.worker.transport, "All")
        self.assertEqual(self.screen["stop_dropdown"].selected, 0)

    def test_automatic_refresh_every_60_seconds(self):
        """US4.1: the departures are fetched again every 60 seconds."""
        self.assertEqual(main_module().REFRESH_MS, 60_000)
        fake_api(json.dumps({"departures": [departure("09:15")]}).encode())
        self.app.request_refresh()  # what the 60 s timer calls
        self.app.poll_worker()
        self.assertEqual(self.app.departure_list["rows"][0]["time"].text, "09:15")

    def test_refresh_button_updates_departures(self):
        """US4.2B, US4.3: Refresh fetches again and reports the result and status."""
        fake_api(json.dumps({"departures": [departure("08:00")]}).encode())
        self.app.on_refresh_clicked(None)
        self.assertEqual(self.screen["message"].text, "Refreshing...")
        self.assertEqual(self.app.departure_list["message"].text, "Loading...")
        self.poll_twice()
        self.assertEqual(self.screen["message"].text, "Departures updated")
        self.assertEqual(self.app.departure_list["rows"][0]["time"].text, "08:00")
        self.assertEqual(self.screen["wifi"].text, "Wi-Fi: Connected")
        self.assertEqual(self.screen["data"].text, "Live data: OK")

    def test_failed_refresh_is_shown(self):
        """US4.2B, US4.3: a failed Refresh is reported."""
        fake_api(b"", status=403)
        self.app.on_refresh_clicked(None)
        self.poll_twice()
        self.assertEqual(self.screen["message"].text, "Refresh failed")
        self.assertEqual(self.screen["data"].text, "Live data: Error")


class FakeEvent:
    def __init__(self, code, target=None):
        self.code = code
        self.target = target

    def get_code(self):
        return self.code

    def get_target_obj(self):
        return self.target


class TestScrollPause(unittest.TestCase):
    """The fetch waits during swipes and scrolling, and nothing new is drawn."""

    @classmethod
    def setUpClass(cls):
        fake_api(b"{}")
        with contextlib.redirect_stdout(io.StringIO()):
            import main
        cls.app = main.app

    def setUp(self):
        # Real event codes, so begin and end can be told apart
        fake_lv.EVENT = types.SimpleNamespace(
            SCROLL_BEGIN="begin",
            SCROLL_END="end",
            CLICKED="clicked",
            VALUE_CHANGED="changed",
        )

    def tearDown(self):
        del fake_lv.EVENT
        trafiklab.set_scrolling(False)

    def scroll(self, code, target=None):
        self.app.on_scroll(FakeEvent(code, target or self.app.tileview))

    def test_swipe_pauses_the_fetch(self):
        """US2.1: a swipe pauses the fetch until it ends."""
        self.scroll("begin")
        self.assertTrue(trafiklab.is_scrolling())
        self.scroll("end")
        self.assertFalse(trafiklab.is_scrolling())

    def test_journey_scroll_pauses_the_fetch(self):
        """US2.1, US5.3: scrolling the journeys pauses the fetch."""
        results = self.app.journey_screen["results"]
        self.scroll("begin", results)
        self.assertTrue(trafiklab.is_scrolling())
        self.scroll("end", results)
        self.assertFalse(trafiklab.is_scrolling())

    def test_no_output_during_a_swipe(self):
        """US2.1: a swipe prints nothing (printing slows the screen)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.scroll("begin")
            self.scroll("end")
        self.assertEqual(out.getvalue(), "")

    def test_departures_are_shown_after_the_swipe(self):
        """US2.1: new departures wait for the swipe to end."""
        self.app.refresh_pending = self.app.journey_pending = False
        self.app.departure_list["message"].text = ""
        self.app.worker._result = ([], "")
        self.scroll("begin")
        self.app.poll_worker()
        self.assertIsNotNone(self.app.worker._result)  # not during the swipe
        self.scroll("end")
        self.app.poll_worker()
        self.assertIsNone(self.app.worker._result)
        self.assertEqual(
            self.app.departure_list["message"].text, "No departures right now"
        )


class RecordingLabel(FakeObj):
    """A label that remembers its long mode."""

    long_mode = None

    def set_long_mode(self, mode):
        self.long_mode = mode


class TestDrawCost(unittest.TestCase):
    """Less to draw per tile: CLIP labels and no extra container per screen."""

    def setUp(self):
        self.real_label, self.real_clip = fake_lv.label, departure_screen.LONG_CLIP
        fake_lv.label = RecordingLabel
        departure_screen.LONG_CLIP = "CLIP"

    def tearDown(self):
        fake_lv.label, departure_screen.LONG_CLIP = self.real_label, self.real_clip

    def test_labels_clip_unless_they_wrap(self):
        """US2.1: labels only wrap when asked to (less to draw)."""
        parent = FakeObj()
        self.assertEqual(
            departure_screen.make_label(parent, "x", 0, None, 0).long_mode, "CLIP"
        )
        wrapping = departure_screen.make_label(parent, "x", 0, None, 0, wrap=True)
        self.assertIsNone(wrapping.long_mode)

    def test_departure_rows_clip_and_message_wraps(self):
        """US1.2B, US2.1: the rows clip, the message wraps."""
        screen = departure_screen.create_departure_screen(FakeObj())
        for row in screen["rows"]:
            for label in row["labels"]:
                self.assertEqual(label.long_mode, "CLIP")
        self.assertIsNone(screen["message"].long_mode)

    def test_departure_screen_has_no_root_container(self):
        """US2.1: the departure screen has no extra container."""
        tile = FakeObj()
        screen = departure_screen.create_departure_screen(tile)
        self.assertIs(screen["root"], tile)
        # Title row, column header, list and attribution straight on the tile
        self.assertEqual(len(tile.children), 4)

    def test_settings_screen_has_no_root_container(self):
        """US2.1, US3.1: the settings screen has no extra container."""
        from screens import settings

        tile = FakeObj()
        screen = settings.create_settings_screen(tile, "", None, None, None, None)
        self.assertIs(screen["root"], tile)
        # Title, 3 cards and the button row
        self.assertEqual(len(tile.children), 5)

    def test_journey_screen_has_no_root_container(self):
        """US2.1, US5.1: the journey screen has no extra container."""
        tile = FakeObj()
        journey.create_journey_screen(tile, None)
        # Stop row, button row, results and attribution
        self.assertEqual(len(tile.children), 4)


class TestWifi(unittest.TestCase):
    """The Wi-Fi helpers are part of the worker now."""

    def tearDown(self):
        FakeStation.connected = True

    def test_is_connected(self):
        """US4.3: is_connected follows the Wi-Fi state."""
        from services import departure_worker

        self.assertTrue(departure_worker.is_connected())
        FakeStation.connected = False
        self.assertFalse(departure_worker.is_connected())

    def test_fetch_without_wifi(self):
        """US4.3: without Wi-Fi the fetch gives "No Wi-Fi"."""
        from services import departure_worker

        FakeStation.connected = False
        real_connect = departure_worker.connect
        departure_worker.connect = lambda: None  # the real one waits 15 s
        try:
            worker = DepartureWorker("Karlskrona")
            worker.start()
            self.assertEqual(worker.take_result(), (None, "No Wi-Fi"))
        finally:
            departure_worker.connect = real_connect


class TestSafeText(unittest.TestCase):
    """Only characters the fonts can draw reach the screen."""

    def setUp(self):
        self.saved = departure_screen.REPLACE_SWEDISH_CHARS
        departure_screen.REPLACE_SWEDISH_CHARS = True  # built-in fonts only
        departure_screen._reported.clear()

    def tearDown(self):
        departure_screen.REPLACE_SWEDISH_CHARS = self.saved
        departure_screen._reported.clear()

    def safe(self, text):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = departure_screen.safe_text(text)
        self.printed = out.getvalue()
        return result

    def test_ascii_is_unchanged(self):
        """US1.2B: ASCII text is unchanged (the fast path)."""
        text = "Karlskrona C 12:05 -> Lyckeby"
        self.assertIs(self.safe(text), text)  # the fast path: no copy
        self.assertEqual(self.safe(""), "")
        self.assertEqual(self.safe(42), "42")

    def test_danish_and_other_letters(self):
        """US1.2B: Danish and other letters become ASCII without the fonts."""
        self.assertEqual(self.safe("Østerport"), "Osterport")
        self.assertEqual(self.safe("ø Æble æble"), "o AEble aeble")
        self.assertEqual(self.safe("é è ë ü"), "e e e u")

    def test_punctuation(self):
        """US1.2B: dashes and curly quotes become ASCII."""
        self.assertEqual(self.safe("Malmo – Lund — Ystad"), "Malmo - Lund - Ystad")
        self.assertEqual(self.safe("‘a’ “b”"), "'a' \"b\"")
        self.assertEqual(self.safe("12 min"), "12 min")

    def test_swedish_letters_without_the_swedish_font(self):
        """US1.2B: å ä ö become a a o without the Swedish fonts."""
        self.assertEqual(self.safe("Gräsvik Åby Örebro"), "Grasvik Aby Orebro")

    def test_swedish_letters_kept_with_the_swedish_font(self):
        """US1.2B: å ä ö are kept with the Swedish fonts."""
        departure_screen.REPLACE_SWEDISH_CHARS = False
        self.assertEqual(self.safe("ÅÄÖåäö"), "ÅÄÖåäö")
        # The Swedish font only has å ä ö: the dash still becomes ASCII
        self.assertEqual(self.safe("Malmö – Lund"), "Malmö - Lund")

    def test_danish_letters_kept_with_the_small_fonts(self):
        """US1.2B: Ø and Æ are kept with the small fonts."""
        departure_screen.REPLACE_SWEDISH_CHARS = False
        self.assertEqual(self.safe("Østerport"), "Østerport")
        self.assertEqual(self.safe("ø Æble æble"), "ø Æble æble")
        # The dash is not in the small fonts: still ASCII
        self.assertEqual(self.safe("Malmö – Østerport"), "Malmö - Østerport")

    def test_font_letters_are_the_ten_in_the_fonts(self):
        """US1.2B: safe_text keeps exactly the ten letters in the fonts."""
        self.assertEqual(sorted(departure_screen._FONT_LETTERS), sorted("åäöÅÄÖØøÆæ"))

    def test_unknown_character_is_removed_and_printed_once(self):
        """US1.2B: an unknown character is removed and printed once."""
        self.assertEqual(self.safe("10€"), "10")
        self.assertIn("U+20AC", self.printed)
        self.assertEqual(self.safe("5€"), "5")
        self.assertEqual(self.printed, "")  # not printed again

    def test_lvgl_symbols_are_kept(self):
        """US1.2B: LVGL symbols (the page arrows) are kept."""
        up = ""  # lv.SYMBOL.UP, in the built-in fonts
        self.assertEqual(self.safe(up + " Ø"), up + " O")

    def test_departure_row_shows_the_replacement(self):
        """US1.2B: a departure row shows the replaced text."""
        screen = departure_screen.create_departure_screen(FakeObj())
        departure_screen.update_departures(
            screen, [{"time": "12:05", "destination": "Østerport", "status": "On time"}]
        )
        self.assertEqual(screen["rows"][0]["dest"].text, "Osterport")


class FakeFont:
    """What lv.binfont_create returns: a font with a fallback field."""

    fallback = None


class TestSwedishFonts(unittest.TestCase):
    """å ä ö with small fonts on top of the built-in ones, else a/o."""

    def setUp(self):
        d = departure_screen
        self.saved = (
            d.REPLACE_SWEDISH_CHARS,
            dict(d._swedish),
            d._fs_driver,
            d.FONT_DIR,
        )
        self.folder = tempfile.TemporaryDirectory()
        d.FONT_DIR = self.folder.name + os.sep
        self.paths = []
        self.registered = []

        def binfont_create(path):
            self.paths.append(path)
            return FakeFont()

        fake_lv.binfont_create = binfont_create
        fake_fs = types.ModuleType("fs_driver")
        fake_fs.fs_register = lambda driver, letter: self.registered.append(letter)
        sys.modules["fs_driver"] = fake_fs

    def tearDown(self):
        d = departure_screen
        d.REPLACE_SWEDISH_CHARS, swedish, d._fs_driver, d.FONT_DIR = self.saved
        d._swedish.clear()
        d._swedish.update(swedish)
        del fake_lv.binfont_create
        sys.modules.pop("fs_driver", None)
        self.folder.cleanup()

    def load(self):
        """Run load_swedish_fonts and return (result, printed text)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = departure_screen.load_swedish_fonts()
        return result, out.getvalue()

    def font_file(self, name):
        with open(os.path.join(self.folder.name, name), "rb") as file:
            return file.read()

    def test_fonts_used_when_everything_works(self):
        """US1.2B: the Swedish fonts load, with the built-in fonts as fallback."""
        d = departure_screen
        ok, text = self.load()
        self.assertTrue(ok)
        self.assertEqual(text, "")
        self.assertEqual(self.registered, ["S"])
        self.assertEqual(
            self.paths, ["S:" + d.FONT_DIR + "sv20.bin", "S:" + d.FONT_DIR + "sv14.bin"]
        )
        big, small = d.ui_font(d.FONT_BIG), d.ui_font(d.FONT_SMALL)
        self.assertIsInstance(big, FakeFont)
        self.assertIs(big.fallback, d.FONT_BIG)  # every other letter: built-in
        self.assertIs(small.fallback, d.FONT_SMALL)

    @staticmethod
    def font_bytes(data):
        """The binfont in _SV20 / _SV14 (zlib + base64)."""
        import binascii
        import zlib

        return zlib.decompress(binascii.a2b_base64("".join(data)))

    def test_font_files_are_written(self):
        """US1.2B: the font files are written to the flash."""
        self.load()
        d = departure_screen
        self.assertEqual(self.font_file("sv20.bin"), self.font_bytes(d._SV20))
        self.assertEqual(self.font_file("sv14.bin"), self.font_bytes(d._SV14))

    def test_fonts_have_room_for_a_ring(self):
        """US1.2B: the fonts have room for the ring on Å."""
        import struct

        # LVGL: line_height = ascent - descent, base_line = -descent
        for data, line_height, base_line in (
            (departure_screen._SV20, 24, 4),
            (departure_screen._SV14, 18, 3),
        ):
            raw = self.font_bytes(data)
            self.assertEqual(raw[4:8], b"head")
            ascent, descent = struct.unpack_from("<Hh", raw, 16)
            self.assertEqual((ascent - descent, -descent), (line_height, base_line))

    def test_fonts_have_the_ten_letters(self):
        """US1.2B: the fonts hold the ten letters at 4 bpp."""
        import struct

        for data, size in ((departure_screen._SV20, 20), (departure_screen._SV14, 14)):
            raw = self.font_bytes(data)
            self.assertEqual(struct.unpack_from("<H", raw, 14)[0], size)  # font size
            self.assertEqual(raw[37], 4)  # bits per pixel, as the built-in fonts
            # Walk the tables; loca has one entry per glyph plus LVGL's glyph 0
            offset, tables = 0, {}
            while offset < len(raw):
                length, tag = struct.unpack_from("<I4s", raw, offset)
                tables[tag] = offset
                offset += length
            self.assertEqual(set(tables), {b"head", b"cmap", b"loca", b"glyf"})
            self.assertEqual(struct.unpack_from("<I", raw, tables[b"loca"] + 8)[0], 11)

    def test_correct_file_is_not_written_again(self):
        """US1.2B: a correct font file is not written again."""
        self.load()
        path = os.path.join(self.folder.name, "sv20.bin")
        old = 1_000_000_000_000_000_000  # a round time every file system can store
        os.utime(path, ns=(old, old))
        self.load()
        self.assertEqual(os.stat(path).st_mtime_ns, old)

    def test_damaged_file_is_written_again(self):
        """US1.2B: a damaged font file is written again."""
        self.load()
        path = os.path.join(self.folder.name, "sv20.bin")
        with open(path, "wb") as file:
            file.write(b"broken")
        self.load()
        self.assertNotEqual(self.font_file("sv20.bin"), b"broken")

    def assert_fallback(self, ok, text):
        d = departure_screen
        self.assertFalse(ok)
        self.assertTrue(d.REPLACE_SWEDISH_CHARS)
        self.assertEqual(d.safe_text("Gräsvik Åby Örebro"), "Grasvik Aby Orebro")
        self.assertIs(d.ui_font(d.FONT_BIG), d.FONT_BIG)
        self.assertIs(d.ui_font(d.FONT_SMALL), d.FONT_SMALL)
        # The reason is printed once
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("Swedish fonts not used", text)

    def test_no_fs_driver(self):
        """US1.2B: without fs_driver the built-in fonts and a/o are used."""
        sys.modules["fs_driver"] = None  # import fs_driver fails
        self.assert_fallback(*self.load())

    def test_no_binfont_create(self):
        """US1.2B: without binfont_create the built-in fonts are used."""
        def missing(path):
            raise AttributeError("binfont_create")

        fake_lv.binfont_create = missing
        self.assert_fallback(*self.load())

    def test_second_font_fails_so_none_is_used(self):
        """US1.2B: if one font fails, neither is used."""
        fake_lv.binfont_create = lambda path: FakeFont() if "sv20" in path else None
        self.assert_fallback(*self.load())

    def test_flash_write_fails(self):
        """US1.2B: if writing the flash fails, the built-in fonts are used."""
        departure_screen.FONT_DIR = os.path.join(self.folder.name, "missing", "")
        self.assert_fallback(*self.load())

    def test_make_label_uses_the_swedish_font(self):
        """US1.2B: labels use the Swedish font once it is loaded."""
        d = departure_screen
        self.load()
        label = d.make_label(FakeObj(), "Åby", 0, d.FONT_BIG, d.COLOR_TEXT)
        self.assertEqual(label.text, "Åby")
        self.assertIn((id(d.ui_font(d.FONT_BIG)), d.COLOR_TEXT), d._styles)


class TestJsonStream(unittest.TestCase):
    def test_reads_objects_from_array(self):
        """US1.2B: objects are read from a JSON array in small chunks."""
        body = json.dumps(
            {"x": 1, "departures": [{"a": 1}, {"a": 2, "t": "has } inside"}]}
        ).encode()
        items = list(trafiklab._iter_json_array(FakeStream(body), b"departures"))
        self.assertEqual([i["a"] for i in items], [1, 2])
        self.assertEqual(items[1]["t"], "has } inside")

    def test_missing_array_gives_nothing(self):
        """US1.2B: a missing array gives no objects."""
        stream = FakeStream(b'{"other": []}')
        self.assertEqual(list(trafiklab._iter_json_array(stream, b"departures")), [])


if __name__ == "__main__":
    unittest.main()
