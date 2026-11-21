"""Background worker for departures, journeys and the Wi-Fi.

Never touches the display or files (not thread safe). One thread is reused:
a new one per fetch fragments the RAM that TLS needs.
"""

import _thread
import gc
import time

import network

from secrets import WIFI_PASSWORD, WIFI_SSID
from services import trafiklab

WORKER_STACK_SIZE = 32 * 1024
IDLE_MS = 100  # sleep between checks for work

# No sleep_ms on PC (tests): the thread then ends when idle
_sleep_ms = getattr(time, "sleep_ms", None)


def is_connected():
    return network.WLAN(network.STA_IF).isconnected()


def connect(timeout_ms=15_000):
    """Connect to the Wi-Fi in secrets.py. Blocks: worker only, so no log()."""
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
        self.town = town  # for the coming stop search (US3.2C)
        first = trafiklab.STOPS[0]  # default: the first fixed stop
        self.stop_id = stop_id or first["id"]
        self.stop_name = "" if stop_id else first["name"]
        self.transport = trafiklab.TRANSPORT_ALL
        self.limit = limit  # max departures per fetch
        self.busy = False  # True from start() until the result is ready
        self._alive = False  # True while the thread runs
        self._result = self._journey_result = None  # (data, error)
        self._journey = None  # (from_id, to_id) of the next search (US5.3)

    def set_stop(self, stop_id, stop_name):
        self.stop_id = stop_id
        self.stop_name = stop_name

    def set_transport(self, transport):
        self.transport = transport  # US3.3

    def start(self, journey=None):
        """Fetch departures, or trips for journey = (from_id, to_id). False if busy."""
        if self.busy:
            return False
        self._journey = journey
        self.busy = True
        if self._alive:
            return True  # the thread picks up the job
        try:
            self._alive = True
            _thread.stack_size(WORKER_STACK_SIZE)
            _thread.start_new_thread(self._loop, ())
        except Exception as error:
            self._alive = self.busy = False  # never leave busy stuck
            print("Worker: no thread:", error)
            return False
        return True

    # take_...() return a result once, then None
    def take_result(self):
        result, self._result = self._result, None
        return result

    def take_journey(self):
        result, self._journey_result = self._journey_result, None
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
        journey = self._journey
        data, error = None, ""
        try:
            if not is_connected():
                connect()
            if not is_connected():
                error = "No Wi-Fi"
            elif journey is not None:
                data = trafiklab.get_trips(journey[0], journey[1])
            else:
                data = trafiklab.get_departures(self.stop_id, self.limit, self.transport)
            if data is None and not error:
                error = trafiklab.get_last_error()
        except Exception as exc:
            error = type(exc).__name__
        if journey is None:
            self._result = (data, error)
        else:
            self._journey_result = (data, error)
        trafiklab.yield_to_ui()  # never collect during a swipe
        gc.collect()  # once per job
        self.busy = False
