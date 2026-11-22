"""Wi-Fi and network jobs in one reused thread (US3.2C, US4, US5.3)."""

import _thread
import gc
import time

import network

from secrets import WIFI_PASSWORD, WIFI_SSID
from services import trafiklab

WORKER_STACK_SIZE = 32 * 1024
IDLE_MS = 100

_sleep_ms = getattr(time, "sleep_ms", None)  # None in PC tests: thread ends


class _NoLock:  # PC tests
    __enter__ = __exit__ = lambda *a: None


def is_connected():
    return network.WLAN(network.STA_IF).isconnected()


def connect(timeout_ms=15_000):
    print("connecting to Wi-Fi SSID: " + WIFI_SSID)
    station = network.WLAN(network.STA_IF)
    station.active(True)
    try:
        if station.status() != network.STAT_CONNECTING:
            station.connect(WIFI_SSID, WIFI_PASSWORD)
    except OSError:
        station.disconnect()
        station.connect(WIFI_SSID, WIFI_PASSWORD)
    started = time.ticks_ms()
    while not station.isconnected() and time.ticks_diff(time.ticks_ms(), started) < timeout_ms:
        time.sleep_ms(250)
    print("Wi-Fi connected" if station.isconnected() else "Wi-Fi: timeout")


class DepartureWorker:
    def __init__(self, town, stop_id=None, limit=15):
        self.town = town
        first = trafiklab.STOPS[0]
        self.stop_id = stop_id or first["id"]
        self.stop_name = "" if stop_id else first["name"]
        self.transport = trafiklab.TRANSPORT_ALL
        self.limit = limit
        self.busy = False
        self._alive = False
        self._result = self._journey_result = self._stops = self._job = None
        lock = getattr(_thread, "allocate_lock", None)
        self._lock = lock() if lock else _NoLock()

    def set_stop(self, stop_id, stop_name):
        self.stop_id = stop_id
        self.stop_name = stop_name

    def set_transport(self, transport):
        self.transport = transport  # US3.3

    def start(self, journey=None, search=None):
        "False if busy"
        if self.busy:
            return False
        self._job = (journey, search, self.stop_id, self.limit, self.transport)  # snapshot
        self.busy = True
        if self._alive:
            return True
        try:
            self._alive = True
            _thread.stack_size(WORKER_STACK_SIZE)
            _thread.start_new_thread(self._loop, ())
        except Exception as error:
            self._alive = self.busy = False
            print("Worker: no thread:", error)
            return False
        return True

    def _take(self, name):
        with self._lock:
            result = getattr(self, name)
            setattr(self, name, None)
        return result

    def take_result(self):
        return self._take("_result")

    def take_journey(self):
        return self._take("_journey_result")

    def take_stops(self):  # US3.2C
        return self._take("_stops")

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
        journey, search, stop_id, limit, transport = self._job
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
                data = trafiklab.get_departures(stop_id, limit, transport)
            if data is None and not error:
                error = trafiklab.get_last_error()
        except Exception as exception:
            error = type(exception).__name__
        name = ("_stops" if search is not None
                else "_result" if journey is None else "_journey_result")
        with self._lock:
            setattr(self, name, (data, error))
        trafiklab.yield_to_ui()  # no gc during a swipe
        gc.collect()
        self.busy = False
