"""Background worker that fetches data from Trafiklab.

LVGL is not thread safe, so the worker never touches the display. It only
stores its results in attributes. The UI picks them up with take_result()
and take_stops() from a timer.
"""

import _thread

from services import trafiklab, wifi

# The JSON parser and TLS need more stack than the default
WORKER_STACK_SIZE = 24 * 1024


class DepartureWorker:
    """Loads the stop list once and fetches departures when asked."""

    def __init__(self, town, stop_id=None, limit=15):
        self.town = town
        self.stop_id = stop_id  # None = use the busiest stop
        self.stop_name = ""
        self.transport = trafiklab.TRANSPORT_ALL
        self.limit = limit  # max departures per fetch
        self.busy = False  # True while a fetch is running

        self._stops_loaded = False
        self._stops = None  # stop list waiting for the UI
        self._result = None  # (departures, error) waiting for the UI

    def set_stop(self, stop_id, stop_name):
        """Choose the stop used by the next fetch."""
        self.stop_id = stop_id
        self.stop_name = stop_name

    def set_transport(self, transport):
        """Choose the transport type used by the next fetch (US3.3)."""
        self.transport = transport

    def start(self):
        """Start a fetch in the background.

        Returns False if a fetch is already running.
        """
        if self.busy:
            return False
        self.busy = True
        _thread.stack_size(WORKER_STACK_SIZE)
        _thread.start_new_thread(self._run, ())
        return True

    def take_result(self):
        """Return (departures, error) once, or None if there is nothing new."""
        result = self._result
        self._result = None
        return result

    def take_stops(self):
        """Return the new stop list once, or None."""
        stops = self._stops
        self._stops = None
        return stops

    def _ensure_wifi(self):
        """Return True if Wi-Fi is connected, connecting first if needed."""
        if not wifi.is_connected():
            wifi.connect()
        return wifi.is_connected()

    def _run(self):
        """Runs in the thread: Wi-Fi, stop list (first time only), departures."""
        try:
            if not self._ensure_wifi():
                self._finish(None, "No Wi-Fi")
                return

            if not self._stops_loaded:
                stops = trafiklab.find_stops(self.town)
                if stops is not None:
                    self._stops_loaded = True
                    if self.stop_id is None:
                        self.stop_id = stops[0]["id"]
                        self.stop_name = stops[0]["name"]
                    self._stops = stops

            if self.stop_id is None:
                self._finish(None, trafiklab.get_last_error())
                return

            # Copy the choices so a change during the fetch cannot mix them up
            stop_id = self.stop_id
            transport = self.transport
            departures = trafiklab.get_departures(stop_id, self.limit, transport)
            error = "" if departures is not None else trafiklab.get_last_error()
            self._finish(departures, error)
        except Exception as error:
            self._finish(None, type(error).__name__)

    def _finish(self, departures, error):
        """Store the result and mark the worker as idle."""
        self._result = (departures, error)
        self.busy = False
