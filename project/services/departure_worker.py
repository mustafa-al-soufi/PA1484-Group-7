"""Background worker that fetches data from Trafiklab without blocking the UI.

LVGL is not thread safe, so the worker never touches any widget. It only
writes plain attributes; the UI thread picks them up with ``take_result``
and ``take_stops`` from an LVGL timer.
"""

import _thread

from services import trafiklab, wifi

# The streaming JSON parser and TLS need more stack than the default
WORKER_STACK_SIZE = 24 * 1024


class DepartureWorker:
    """Loads the stop list once and fetches departures on request."""

    def __init__(self, town, stop_id=None, limit=15):
        """Create the worker.

        Args:
            town: Town whose stops are offered, for example 'Karlskrona'.
            stop_id: Stop area id to start with, or None to use the busiest.
            limit: Maximum number of departures per fetch.
        """
        self.town = town
        self.stop_id = stop_id
        self.stop_name = ""
        self.transport = trafiklab.TRANSPORT_ALL
        self.limit = limit
        self.busy = False  # True while a fetch is running

        self._stops_loaded = False
        self._stops = None  # list waiting to be taken by the UI
        self._result = None  # (departures, error) waiting for the UI

    def set_stop(self, stop_id, stop_name):
        """Select the stop used by the next fetch."""
        self.stop_id = stop_id
        self.stop_name = stop_name

    def set_transport(self, transport):
        """Select the transport type used by the next fetch (US3.3)."""
        self.transport = transport

    def start(self):
        """Start a fetch in the background. Ignored while one is running.

        Returns:
            True if a new fetch was started, False if one is already busy.
        """
        if self.busy:
            return False
        self.busy = True
        _thread.stack_size(WORKER_STACK_SIZE)
        _thread.start_new_thread(self._run, ())
        return True

    def take_result(self):
        """Return ``(departures, error)`` once, or None if nothing is new."""
        result = self._result
        self._result = None
        return result

    def take_stops(self):
        """Return the freshly loaded stop list once, or None."""
        stops = self._stops
        self._stops = None
        return stops

    def _ensure_wifi(self):
        """Return True when Wi-Fi is connected, trying to connect if needed."""
        if not wifi.is_connected():
            wifi.connect()
        return wifi.is_connected()

    def _run(self):
        """Thread body: Wi-Fi check, stop list (first time), departures."""
        try:
            if not self._ensure_wifi():
                self._finish(None, "No Wi-Fi")
                return

            # The stop list is only downloaded once per start
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

            # Copy the selection so a change during the fetch cannot mix
            stop_id = self.stop_id
            transport = self.transport
            departures = trafiklab.get_departures(stop_id, self.limit, transport)
            error = "" if departures is not None else trafiklab.get_last_error()
            self._finish(departures, error)
        except Exception as exc:
            self._finish(None, type(exc).__name__)

    def _finish(self, departures, error):
        """Publish the result and mark the worker as idle."""
        self._result = (departures, error)
        self.busy = False
