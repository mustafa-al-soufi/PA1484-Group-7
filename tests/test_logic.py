"""Tests for settings and Trafiklab handling.

Run on the computer (not the ESP32) from the project folder:
    python -m unittest tests/test_logic.py -v
"""

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

# These modules only exist on the board, so we fake them here
sys.modules["urequests"] = types.ModuleType("urequests")
secrets = types.ModuleType("secrets")
secrets.TRAFIKLAB_API_KEY = "test"
sys.modules["secrets"] = secrets

from config import settings_manager
from services import trafiklab


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
    """Make the app get this answer instead of calling Trafiklab."""
    trafiklab.urequests.get = lambda url, timeout=10: FakeResponse(body, status)


def departure(time, mode="BUS"):
    return {
        "scheduled": "2026-10-11T" + time + ":00",
        "route": {"designation": "1", "direction": "Lyckeby", "transport_mode": mode},
    }


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
    def test_stop_inside_and_outside_karlskrona(self):
        karlskrona = {"stops": [{"lat": 56.16, "lon": 15.59}]}
        malmo = {"stops": [{"lat": 55.60, "lon": 13.00}]}
        self.assertTrue(trafiklab._in_area(karlskrona))
        self.assertFalse(trafiklab._in_area(malmo))

    def test_swedish_letters_in_url(self):
        self.assertEqual(trafiklab._url_encode("Nättraby"), "N%C3%A4ttraby")


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
