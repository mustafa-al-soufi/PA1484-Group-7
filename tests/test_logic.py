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
sys.modules["secrets"] = secrets

# The worker runs its thread at once here, and Wi-Fi is always connected
fake_thread = types.ModuleType("_thread")
fake_thread.stack_size = lambda size: None
fake_thread.start_new_thread = lambda function, args: function(*args)
sys.modules["_thread"] = fake_thread
fake_wifi = types.ModuleType("services.wifi")
fake_wifi.is_connected = lambda: True
fake_wifi.connect = lambda: True
sys.modules["services.wifi"] = fake_wifi


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

from config import settings_manager  # noqa: E402
from services import trafiklab  # noqa: E402
from services.departure_worker import DepartureWorker  # noqa: E402
from screens import journey  # noqa: E402

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

    def test_stop_inside_and_outside_karlskrona(self):
        karlskrona = {"stops": [{"lat": 56.16, "lon": 15.59}]}
        malmo = {"stops": [{"lat": 55.60, "lon": 13.00}]}
        self.assertTrue(trafiklab._in_area(karlskrona))
        self.assertFalse(trafiklab._in_area(malmo))

    def test_whole_word_match(self):
        # "Karlskrona C" must not match "Karlskrona Campus Gräsvik"
        campus = {"name": "Karlskrona Campus Gräsvik"}
        self.assertFalse(trafiklab._matches(campus, ("karlskrona c",)))
        self.assertTrue(trafiklab._matches(campus, ("gräsvik",)))

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
        # Importing main starts the app. Give it no stops and hide its output.
        fake_api(b"{}")
        with contextlib.redirect_stdout(io.StringIO()):
            import main
        cls.app = main.app

    def setUp(self):
        self.app.journey_pending = False
        self.app.worker.busy = False
        self.app.apply_stops(
            [{"id": str(i), "name": n} for i, n in enumerate(STOP_NAMES)]
        )
        self.screen = self.app.journey_screen

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
