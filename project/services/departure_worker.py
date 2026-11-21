"""Background worker: departures, journeys, stop searches, Wi-Fi. No display or
files; one reused thread (saves RAM for TLS)."""

import _thread
import gc
import time

import network

from secrets import WIFI_PASSWORD, WIFI_SSID
from services import trafiklab

WORKER_STACK_SIZE = 32 * 1024
IDLE_MS = 100  # sleep when idle

# No sleep_ms in PC tests: the thread ends when idle
_sleep_ms = getattr(time, "sleep_ms", None)


def is_connected():
    return network.WLAN(network.STA_IF).isconnected()


def connect(timeout_ms=15_000):
    """Wi-Fi from secrets.py. Blocks: worker only (no log())."""
    print("connecting to Wi-Fi SSID: " + WIFI_SSID)
    station = network.WLAN(network.STA_IF)
    station.active(True)
    if not station.isconnected():
        station.connect(WIFI_SSID, WIFI_PASSWORD)
    started = time.ticks_ms()
    while not station.isconnected() and time.ticks_diff(time.ticks_ms(), started) < timeout_ms:
        time.sleep_ms(250)
    print("Wi-Fi connected" if station.isconnected() else "Wi-Fi: timeout")


class DepartureWorker:
    def __init__(self, town, stop_id=None, limit=15):
        self.town = town
        first = trafiklab.STOPS[0]  # default
        self.stop_id = stop_id or first["id"]
        self.stop_name = "" if stop_id else first["name"]
        self.transport = trafiklab.TRANSPORT_ALL
        self.limit = limit
        self.busy = False  # from start() until the result is ready
        self._alive = False
        self._result = self._journey_result = self._stops = None
        self._journey = self._search = None  # US5.3, US3.2C

    def set_stop(self, stop_id, stop_name):
        self.stop_id = stop_id
        self.stop_name = stop_name

    def set_transport(self, transport):
        self.transport = transport  # US3.3

    def start(self, journey=None, search=None):
        """Departures, trips (journey=(from, to)) or stops (search). False if busy."""
        if self.busy:
            return False
        self._journey, self._search = journey, search
        self.busy = True
        if self._alive:
            return True  # the thread picks up the job
        try:
            self._alive = True
            _thread.stack_size(WORKER_STACK_SIZE)
            _thread.start_new_thread(self._loop, ())
        except Exception as error:
            self._alive = self.busy = False  # never stuck busy
            print("Worker: no thread:", error)
            return False
        return True

    # take_...(): once, then None
    def take_result(self):
        result, self._result = self._result, None
        return result

    def take_journey(self):
        result, self._journey_result = self._journey_result, None
        return result

    def take_stops(self):  # US3.2C
        result, self._stops = self._stops, None
        return result

    def _loop(self):
        while True:
            if self.busy:
                self._run()
            elif _sleep_ms is None:
                self._alive = False
                return
            else:
                _sleep_ms(IDLE_MS)

    def _run(self):
        journey, search = self._journey, self._search
        data, error = None, ""
        try:
            if not is_connected():
                connect()
            if not is_connected():
                error = "No Wi-Fi"
            elif search is not None:
                data = trafiklab.search_stops(search)
            elif journey is not None:
                data = trafiklab.get_trips(journey[0], journey[1])
            else:
                data = trafiklab.get_departures(self.stop_id, self.limit, self.transport)
            if data is None and not error:
                error = trafiklab.get_last_error()
        except Exception as exc:
            error = type(exc).__name__
        if search is not None:
            self._stops = (data, error)
        elif journey is None:
            self._result = (data, error)
        else:
            self._journey_result = (data, error)
        trafiklab.yield_to_ui()  # no gc during a swipe
        gc.collect()
        self.busy = False 