"""Tests for settings, Trafiklab, the worker and the journey screen (US5.1-US5.3).

Run on the computer (not the ESP32) from the project folder:
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
fake_board.start_board = lambda: (None, None, None)
sys.modules["board_lvgl"] = fake_board
fake_log = types.ModuleType("debug_log")
fake_log.log = lambda text: None
sys.modules["debug_log"] = fake_log

from services import settings_manager  # noqa: E402
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
        chunk = self.data[self.pos : self.pos + self.size]
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
        self.assertEqual(settings_manager.load(), settings_manager.defaults())

    def test_save_then_load(self):
        data = {"stop_id": "9", "stop_name": "Hamnen", "transport": "Ferry"}
        settings_manager.save(data)
        self.assertEqual(settings_manager.load(), data)

    def test_broken_file_gives_defaults(self):
        with open("settings.json", "w") as f:
            f.write("{not json")
        self.assertEqual(settings_manager.load(), settings_manager.defaults())

    def test_bad_transport_becomes_all(self):
        result = settings_manager._clean({"transport": "Rocket"})
        self.assertEqual(result["transport"], "All")


class TestDepartures(unittest.TestCase):
    def test_delayed_only_from_60_seconds(self):
        self.assertEqual(trafiklab._status({"delay": 59}), "On time")
        self.assertEqual(trafiklab._status({"delay": 60}), "Delayed")

    def test_canceled(self):
        self.assertEqual(trafiklab._status({"canceled": True}), "Canceled")

    def test_transport_filter(self):
        bus = {"route": {"transport_mode": "BUS"}}
        self.assertTrue(trafiklab._matches_transport(bus, "Bus"))
        self.assertFalse(trafiklab._matches_transport(bus, "Train"))
        self.assertTrue(trafiklab._matches_transport(bus, "All"))

    def test_ferry_filter_matches_boat(self):
        # The API writes BOAT for ferries (US3.3)
        boat = {"route": {"transport_mode": "BOAT"}}
        self.assertTrue(trafiklab._matches_transport(boat, "Ferry"))
        self.assertFalse(trafiklab._matches_transport(boat, "Bus"))

    def test_time_comes_from_realtime(self):
        item = departure("17:30")
        item["realtime"] = "2026-10-11T17:35:00"
        self.assertEqual(trafiklab._to_departure(item)["time"], "17:35")

    def test_earliest_first_and_limited(self):
        items = [departure(t) for t in ("12:00", "10:00", "11:00", "09:00")]
        fake_api(json.dumps({"departures": items}).encode())
        result = trafiklab.get_departures("1", limit=2)
        self.assertEqual([d["time"] for d in result], ["09:00", "10:00"])

    def test_stops_reading_after_two_pages_and_margin(self):
        items = [departure("10:%02d" % i) for i in range(40)]
        body = json.dumps({"departures": items}).encode()
        fake_api(body)
        response = FakeResponse(body)
        trafiklab.urequests.get = lambda url, timeout=10: response
        result = trafiklab.get_departures("1", limit=12)
        self.assertEqual([d["time"] for d in result], ["10:%02d" % i for i in range(12)])
        # Only 12 + the margin were read, not all 40
        read = response.raw.pos
        self.assertLess(read, len(body))
        one_item = len(json.dumps(items[0])) + 2
        self.assertLessEqual(read, (12 + trafiklab.EXTRA_DEPARTURES + 2) * one_item)

    def test_filter_gives_only_trains(self):
        items = [departure("08:00", "BUS"), departure("09:00", "TRAIN")]
        fake_api(json.dumps({"departures": items}).encode())
        result = trafiklab.get_departures("1", transport="Train")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["time"], "09:00")

    def test_server_error_gives_none(self):
        fake_api(b"", status=403)
        self.assertIsNone(trafiklab.get_departures("1"))
        self.assertIn("403", trafiklab.get_last_error())


class TestStops(unittest.TestCase):
    def test_five_fixed_stops(self):
        names = [stop["name"] for stop in trafiklab.STOPS]
        self.assertEqual(len(names), 5)
        self.assertIn("Karlskrona Centralstation", names)
        self.assertIn("Campus Gräsvik", names)

    def test_fixed_stops_have_unique_ids(self):
        ids = [stop["id"] for stop in trafiklab.STOPS]
        self.assertEqual(len(set(ids)), 5)
        for stop_id in ids:
            # Trafiklab stop area ids are numbers sent as text
            self.assertTrue(stop_id.isdigit(), stop_id)

    def test_get_stops_gives_a_copy(self):
        stops = trafiklab.get_stops()
        self.assertEqual(stops, [dict(stop) for stop in trafiklab.STOPS])
        stops.insert(0, {"id": "1", "name": "Saved"})
        stops[1]["name"] = "Changed"
        self.assertEqual(len(trafiklab.STOPS), 5)
        self.assertEqual(trafiklab.STOPS[0]["name"], "Karlskrona Centralstation")

    def test_stop_search_code_is_removed(self):
        for name in ("find_stops", "_search", "_matches", "_padded"):
            self.assertFalse(hasattr(trafiklab, name), name)
        for stop in trafiklab.STOPS:
            self.assertEqual(sorted(stop), ["id", "name"])

    def test_stop_inside_and_outside_karlskrona(self):
        karlskrona = {"stops": [{"lat": 56.16, "lon": 15.59}]}
        malmo = {"stops": [{"lat": 55.60, "lon": 13.00}]}
        self.assertTrue(trafiklab._in_area(karlskrona))
        self.assertFalse(trafiklab._in_area(malmo))

    def test_swedish_letters_in_url(self):
        self.assertEqual(trafiklab._url_encode("Gräsvik"), "Gr%C3%A4svik")


class TestJourneys(unittest.TestCase):
    """US5.3: the best journeys between two stops from ResRobot."""

    def test_line_names_use_app_transport_types(self):
        self.assertEqual(trafiklab._line_name("Länstrafik - Buss 6"), "Bus 6")
        self.assertEqual(trafiklab._line_name("Länstrafik buss 1"), "Bus 1")
        self.assertEqual(trafiklab._line_name("Öresundståg 1076"), "Train 1076")
        self.assertEqual(trafiklab._line_name("Länstrafik - Båt 4"), "Ferry 4")
        self.assertEqual(trafiklab._line_name("Taxi"), "Taxi")

    def test_direct_journey(self):
        result = trafiklab._to_trip(
            trip(leg("JNY", "Länstrafik - Buss 6", "08:00", "08:20"))
        )
        self.assertEqual(result["departure"], "08:00")
        self.assertEqual(result["arrival"], "08:20")
        self.assertEqual(result["changes"], 0)

    def test_change_shows_time_at_each_change(self):
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
        result = trafiklab._to_trip(trip(leg("JNY", "Buss 1", "08:00", "08:10")))
        self.assertEqual(result["rides"][0]["stop"], "Karlskrona Kungsplan")

    def test_single_leg_as_object(self):
        # ResRobot can give one leg as an object instead of a list
        single = {"LegList": {"Leg": leg("JNY", "Buss 1", "08:00", "08:10")}}
        self.assertEqual(trafiklab._to_trip(single)["changes"], 0)

    def test_at_most_five_journeys(self):
        trips = [trip(leg("JNY", "Buss 1", "08:00", "08:10"))] * 7
        fake_api(json.dumps({"Trip": trips}).encode())
        self.assertEqual(len(trafiklab.get_trips("1", "2")), 5)

    def test_journey_server_error_gives_none(self):
        fake_api(b"", status=400)
        self.assertIsNone(trafiklab.get_trips("1", "2"))
        self.assertIn("400", trafiklab.get_last_error())


class TestWorker(unittest.TestCase):
    """The worker keeps departures and journeys apart."""

    def test_journey_result_is_not_a_departure_result(self):
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
        worker = DepartureWorker("Karlskrona", stop_id="1")
        worker.busy = True
        self.assertFalse(worker.start(("1", "2")))

    def test_default_stop_is_the_first_fixed_stop(self):
        worker = DepartureWorker("Karlskrona")
        self.assertEqual(worker.stop_id, trafiklab.STOPS[0]["id"])
        self.assertEqual(worker.stop_name, trafiklab.STOPS[0]["name"])

    def test_saved_stop_is_kept(self):
        worker = DepartureWorker("Karlskrona", stop_id="740020510")
        self.assertEqual(worker.stop_id, "740020510")

    def test_fetch_makes_no_stop_search(self):
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
    return [{"time": "09:%02d" % i, "line": "1", "status": status} for i in range(count)]


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
            row["time"].text for row in self.screen["rows"]
            if not self.is_hidden(row["time"])
        ]

    def test_six_rows(self):
        self.assertEqual(departure_screen.MAX_ROWS, 6)
        self.assertEqual(len(self.screen["rows"]), 6)

    def test_six_rows_fit_without_scrolling(self):
        # 450 px screen: 2 * 8 padding, title 44, header 30, attribution
        # about 16 and 3 gaps of 4 leave 332 px for the list
        room = 450 - 2 * 8 - 44 - 30 - 16 - 3 * 4
        rows = departure_screen.MAX_ROWS
        height = rows * departure_screen.ROW_HEIGHT + (rows - 1) * departure_screen.ROW_GAP
        self.assertLessEqual(height, room)
        # One row more would not fit
        self.assertGreater(height + departure_screen.ROW_HEIGHT + departure_screen.ROW_GAP, room)

    def test_rows_have_no_container(self):
        # 4 labels per row straight in the list, plus the message label
        children = self.screen["list"].children
        self.assertEqual(len(children), 6 * 4 + 1)
        for item in self.screen["rows"]:
            self.assertEqual(len(item["labels"]), 4)
            for label in item["labels"]:
                self.assertIn(label, children)

    def test_columns_like_the_old_flex_row(self):
        # Padding 4, then each column width plus the gap
        self.assertEqual(departure_screen._column_x(10), [4, 104, 184, 444])
        self.assertEqual(departure_screen._column_x(0), [4, 94, 164, 414])

    def test_labels_centered_in_their_row(self):
        # Row 50 high with padding 4: a 22 px line starts 14 px down
        self.assertEqual(departure_screen._label_y(0, 22), 14)
        # The next row starts 50 + 2 px further down
        self.assertEqual(departure_screen._label_y(1, 22), 66)

    def test_only_departures_that_exist_are_filled(self):
        departures = [
            {"time": "08:0" + str(i), "line": "1", "destination": "Lyckeby",
             "status": "On time"}
            for i in range(3)
        ]
        departure_screen.update_departures(self.screen, departures)
        rows = self.screen["rows"]
        self.assertEqual([row["time"].text for row in rows[:3]],
                         ["08:00", "08:01", "08:02"])
        self.assertEqual(rows[3]["time"].text, "")
        self.assertEqual(self.times(), ["08:00", "08:01", "08:02"])

    def test_status_color(self):
        departure_screen.update_departures(self.screen, departures_list(2, "Delayed"))
        self.assertEqual(self.screen["rows"][1]["color"], departure_screen.COLOR_DELAYED)

    # Paging

    def test_page_count(self):
        counts = {0: 0, 1: 1, 6: 1, 7: 2, 12: 2, 17: 2}
        for count, pages in counts.items():
            self.assertEqual(departure_screen.page_count(count), pages, count)

    def test_page_controls(self):
        # (visible, up enabled, down enabled)
        self.assertEqual(departure_screen.page_controls(0, 0), (False, False, False))
        self.assertEqual(departure_screen.page_controls(0, 1), (False, False, False))
        self.assertEqual(departure_screen.page_controls(0, 2), (True, False, True))
        self.assertEqual(departure_screen.page_controls(1, 2), (True, True, False))

    def test_first_page_of_two(self):
        departure_screen.update_departures(self.screen, departures_list(12))
        self.assertEqual(self.times(), ["09:0%d" % i for i in range(6)])
        self.assertEqual(self.screen["page_label"].text, "1/2")
        self.assertFalse(self.is_hidden(self.screen["down"]))

    def test_down_and_up_buttons(self):
        departure_screen.update_departures(self.screen, departures_list(12))
        self.screen["down"].callbacks[0](None)
        self.assertEqual(self.times(), ["09:%02d" % i for i in range(6, 12)])
        self.assertEqual(self.screen["page_label"].text, "2/2")
        self.screen["up"].callbacks[0](None)
        self.assertEqual(self.times(), ["09:0%d" % i for i in range(6)])
        self.assertEqual(self.screen["page_label"].text, "1/2")

    def test_no_page_before_first_or_after_last(self):
        departure_screen.update_departures(self.screen, departures_list(12))
        self.assertFalse(departure_screen.change_page(self.screen, -1))
        self.assertTrue(departure_screen.change_page(self.screen, 1))
        self.assertFalse(departure_screen.change_page(self.screen, 1))
        self.assertEqual(self.screen["page"], 1)

    def test_short_last_page_hides_the_empty_rows(self):
        departure_screen.update_departures(self.screen, departures_list(8))
        departure_screen.change_page(self.screen, 1)
        self.assertEqual(self.times(), ["09:06", "09:07"])

    def test_buttons_hidden_with_one_page(self):
        departure_screen.update_departures(self.screen, departures_list(6))
        for name in ("up", "down", "page_label"):
            self.assertTrue(self.is_hidden(self.screen[name]), name)

    def test_buttons_hidden_with_a_message(self):
        departure_screen.update_departures(self.screen, departures_list(12))
        departure_screen.show_message(self.screen, "Loading...")
        for name in ("up", "down", "page_label"):
            self.assertTrue(self.is_hidden(self.screen[name]), name)
        self.assertEqual(self.times(), [])

    def test_at_most_two_pages_are_kept(self):
        departure_screen.update_departures(self.screen, departures_list(17))
        self.assertEqual(len(self.screen["departures"]), departure_screen.MAX_DEPARTURES)
        self.assertEqual(departure_screen.MAX_DEPARTURES, 12)
        departure_screen.change_page(self.screen, 1)
        self.assertEqual(self.times()[-1], "09:11")

    def test_new_departures_start_on_page_one(self):
        departure_screen.update_departures(self.screen, departures_list(12))
        departure_screen.change_page(self.screen, 1)
        departure_screen.update_departures(self.screen, departures_list(12))
        self.assertEqual(self.screen["page"], 0)
        self.assertEqual(self.screen["page_label"].text, "1/2")
        self.assertEqual(self.times()[0], "09:00")

    def test_page_change_creates_no_objects(self):
        departure_screen.update_departures(self.screen, departures_list(12))
        labels = list(self.screen["list"].children)
        departure_screen.change_page(self.screen, 1)
        departure_screen.change_page(self.screen, -1)
        self.assertEqual(self.screen["list"].children, labels)

    def test_long_destination_is_cut(self):
        departure_screen.update_departures(
            self.screen, [{"time": "10:00", "destination": "Karlskrona Centralstation"}]
        )
        dest = self.screen["rows"][0]["dest"].text
        self.assertEqual(len(dest), departure_screen.MAX_DESTINATION_CHARS)
        self.assertTrue(dest.endswith("."))

    def test_error_shows_message(self):
        departure_screen.update_departures(self.screen, None, "No Wi-Fi")
        self.assertEqual(
            self.screen["message"].text, "Could not fetch departures\nNo Wi-Fi"
        )


class TestJourneyScreen(unittest.TestCase):
    """US5.1 and US5.2: the journey screen and the stop selection."""

    def setUp(self):
        self.searches = []
        self.tile = FakeObj()
        self.screen = journey.create_journey_screen(
            self.tile, lambda event: self.searches.append(event)
        )

    def test_screen_has_search_and_attribution(self):
        # US5.1: the screen exists, with a Search button and the Trafiklab text
        texts = self.tile.all_texts()
        self.assertIn("Search", texts)
        self.assertTrue(any("Trafiklab" in text for text in texts))

    def test_search_button_calls_on_search(self):
        buttons = [w for w in self._all_widgets(self.tile) if w.callbacks]
        search = [b for b in buttons if "Search" in b.all_texts()][0]
        search.callbacks[0]("click")
        self.assertEqual(self.searches, ["click"])

    def test_both_dropdowns_get_the_five_stops(self):
        journey.set_journey_stops(self.screen, STOP_NAMES)
        for key in ("from", "to"):
            self.assertEqual(len(self.screen[key].options.split("\n")), 5)
        self.assertIn("Campus Grasvik", self.screen["from"].options)

    def test_to_starts_on_another_stop(self):
        journey.set_journey_stops(self.screen, STOP_NAMES)
        self.assertEqual(journey.get_journey_selection(self.screen), (0, 1))

    def test_message_is_shown(self):
        journey.show_journey_message(self.screen, "Choose two different stops", False)
        self.assertEqual(self.screen["message"].text, "Choose two different stops")

    def test_journeys_are_listed(self):
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
        journey.show_trips(self.screen, [])
        self.assertEqual(self.screen["results"].all_texts(), ["No journeys found"])
        journey.show_trips(self.screen, None, "Searching...")
        self.assertEqual(self.screen["results"].all_texts(), ["Searching..."])

    def _all_widgets(self, widget):
        widgets = [widget]
        for child in widget.children:
            widgets += self._all_widgets(child)
        return widgets


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
        self.screen = self.app.journey_screen

    def test_fetch_limit_is_two_pages(self):
        self.assertEqual(self.app.worker.limit, departure_screen.MAX_DEPARTURES)
        self.assertEqual(self.app.worker.limit, 12)

    def test_stops_are_filled_at_start_up(self):
        # No search at start-up: the fixed stops are in the dropdowns at once
        options = self.app.settings_screen["stop_dropdown"].options.split("\n")
        self.assertEqual(options[0], "Karlskrona Centralstation")
        self.assertEqual(len(options), 5)
        self.assertEqual(len(self.app.stops), 5)

    def select(self, from_index, to_index):
        self.screen["from"].selected = from_index
        self.screen["to"].selected = to_index

    def test_same_stop_gives_message(self):
        self.select(2, 2)
        self.app.on_search_clicked(None)
        self.assertEqual(self.screen["message"].text, "Choose two different stops")
        self.assertFalse(self.app.journey_pending)

    def test_search_while_stops_load(self):
        self.app.stops = []
        self.app.on_search_clicked(None)
        self.assertEqual(self.screen["message"].text, "Stops are still loading")

    def test_search_starts_journey_search(self):
        self.select(0, 1)
        self.app.on_search_clicked(None)
        self.assertTrue(self.app.journey_pending)
        self.assertEqual(self.app.journey_from["name"], STOP_NAMES[0])
        self.assertEqual(self.app.journey_to["name"], STOP_NAMES[1])

    def test_journeys_reach_the_screen(self):
        fake_api(
            json.dumps(
                {"Trip": [trip(leg("JNY", "Buss 1", "08:00", "08:10"))]}
            ).encode()
        )
        self.select(0, 1)
        self.app.on_search_clicked(None)
        self.app.poll_worker()  # starts the search
        self.app.poll_worker()  # shows the result
        self.assertIn("08:00 -> 08:10   Direct", self.screen["results"].all_texts())


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
            SCROLL_BEGIN="begin", SCROLL_END="end", CLICKED="clicked",
            VALUE_CHANGED="changed")

    def tearDown(self):
        del fake_lv.EVENT
        trafiklab.set_scrolling(False)

    def scroll(self, code, target=None):
        self.app.on_scroll(FakeEvent(code, target or self.app.tileview))

    def test_swipe_pauses_the_fetch(self):
        self.scroll("begin")
        self.assertTrue(trafiklab.is_scrolling())
        self.scroll("end")
        self.assertFalse(trafiklab.is_scrolling())

    def test_journey_scroll_pauses_the_fetch(self):
        results = self.app.journey_screen["results"]
        self.scroll("begin", results)
        self.assertTrue(trafiklab.is_scrolling())
        self.scroll("end", results)
        self.assertFalse(trafiklab.is_scrolling())

    def test_no_output_during_a_swipe(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.scroll("begin")
            self.scroll("end")
        self.assertEqual(out.getvalue(), "")

    def test_departures_are_shown_after_the_swipe(self):
        self.app.refresh_pending = self.app.journey_pending = False
        self.app.departure_list["message"].text = ""
        self.app.worker._result = ([], "")
        self.scroll("begin")
        self.app.poll_worker()
        self.assertIsNotNone(self.app.worker._result)  # not during the swipe
        self.scroll("end")
        self.app.poll_worker()
        self.assertIsNone(self.app.worker._result)
        self.assertEqual(self.app.departure_list["message"].text, "No departures right now")


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
        parent = FakeObj()
        self.assertEqual(departure_screen.make_label(parent, "x", 0, None, 0).long_mode, "CLIP")
        wrapping = departure_screen.make_label(parent, "x", 0, None, 0, wrap=True)
        self.assertIsNone(wrapping.long_mode)

    def test_departure_rows_clip_and_message_wraps(self):
        screen = departure_screen.create_departure_screen(FakeObj())
        for row in screen["rows"]:
            for label in row["labels"]:
                self.assertEqual(label.long_mode, "CLIP")
        self.assertIsNone(screen["message"].long_mode)

    def test_departure_screen_has_no_root_container(self):
        tile = FakeObj()
        screen = departure_screen.create_departure_screen(tile)
        self.assertIs(screen["root"], tile)
        # Title row, column header, list and attribution straight on the tile
        self.assertEqual(len(tile.children), 4)

    def test_settings_screen_has_no_root_container(self):
        from screens import settings

        tile = FakeObj()
        screen = settings.create_settings_screen(tile, "", None, None, None, None)
        self.assertIs(screen["root"], tile)
        # Title, 3 cards and the button row
        self.assertEqual(len(tile.children), 5)

    def test_journey_screen_has_no_root_container(self):
        tile = FakeObj()
        journey.create_journey_screen(tile, None)
        # Stop row, button row, results and attribution
        self.assertEqual(len(tile.children), 4)


class TestWifi(unittest.TestCase):
    """The Wi-Fi helpers are part of the worker now."""

    def tearDown(self):
        FakeStation.connected = True

    def test_is_connected(self):
        from services import departure_worker

        self.assertTrue(departure_worker.is_connected())
        FakeStation.connected = False
        self.assertFalse(departure_worker.is_connected())

    def test_fetch_without_wifi(self):
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


class TestJsonStream(unittest.TestCase):
    def test_reads_objects_from_array(self):
        body = json.dumps(
            {"x": 1, "departures": [{"a": 1}, {"a": 2, "t": "has } inside"}]}
        ).encode()
        items = list(trafiklab._iter_json_array(FakeStream(body), b"departures"))
        self.assertEqual([i["a"] for i in items], [1, 2])
        self.assertEqual(items[1]["t"], "has } inside")

    def test_missing_array_gives_nothing(self):
        stream = FakeStream(b'{"other": []}')
        self.assertEqual(list(trafiklab._iter_json_array(stream, b"departures")), [])


if __name__ == "__main__":
    unittest.main()
