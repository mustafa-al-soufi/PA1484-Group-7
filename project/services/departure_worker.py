"""Background worker that fetches departures without blocking the UI.

LVGL is not thread safe, so the worker never touches the UI. It only stores
its results in plain attributes. The UI thread polls ``take_result`` and
``take_stops`` from an LVGL timer and updates the screens itself.
"""

import _thread
import gc

from services import trafiklab, wifi

# TLS needs more stack than the MicroPython default for new threads
WORKER_STACK_SIZE = 24 * 1024


class DepartureWorker:
    """Runs Wi-Fi connection, stop list and departure fetching in a thread."""

    def __init__(self, town, stop_id=None, limit=15):
        """Create a worker.

        Args:
            town: Town whose stops can be selected, e.g. 'Karlskrona'.
            stop_id: Stop to show from the start. If None, the busiest stop
                in ``town`` is used.
            limit: Maximum number of departures to fetch.
        """
        self.town = town
        self.stop_id = stop_id
        self.stop_name = None  # name of the selected stop, known once loaded
        self.limit = limit

        self.busy = False  # True while a fetch is running
        self._has_result = False  # True when a result is waiting to be read
        self._departures = None
        self._error = ""

        self._stops = None  # list of selectable stops waiting to be read
        self._stops_loaded = False  # True once the list has been fetched

    def set_stop(self, stop_id, stop_name):
        """Change the stop that departures are fetched for.

        Takes effect the next time a fetch is started.

        Args:
            stop_id: Id of the new stop area.
            stop_name: Name of the new stop area.
        """
        self.stop_id = stop_id
        self.stop_name = stop_name

    def start(self):
        """Start a background fetch.

        Returns:
            True if a new fetch was started, False if one is already running.
        """
        if self.busy:
            return False
        self.busy = True
        self._has_result = False
        try:
            _thread.stack_size(WORKER_STACK_SIZE)
        except Exception:
            pass  # keep the default stack size if it cannot be changed
        _thread.start_new_thread(self._run, ())
        return True

    def take_result(self):
        """Return the finished result once, or None if nothing is ready.

        Returns:
            None, or a tuple ``(departures, error)`` where ``departures`` is
            a list (possibly empty) or None on failure, and ``error`` is a
            short error text ('' if there was no error).
        """
        if not self._has_result:
            return None
        self._has_result = False
        return self._departures, self._error

    def take_stops(self):
        """Return the list of selectable stops once, or None if not ready.

        Returns:
            None, or a list of dicts with the keys 'id' and 'name'.
        """
        stops = self._stops
        self._stops = None
        return stops

    def _run(self):
        """Thread body: connect, load the stop list, fetch departures."""
        try:
            gc.collect()

            # Step 1: make sure Wi-Fi is connected
            if not wifi.is_connected() and not wifi.connect():
                self._finish(None, "No Wi-Fi connection")
                return

            # Step 2: load the selectable stops once and pick the default stop
            if not self._stops_loaded:
                stops = trafiklab.find_stops(self.town)
                if not stops:
                    self._finish(None, trafiklab.get_last_error() or "No stops found")
                    return

                # Set the default stop before the list is published, so the
                # UI always finds a selected stop when it receives the list
                if self.stop_id is None:
                    self.stop_id = stops[0]["id"]
                    self.stop_name = stops[0]["name"]
                self._stops = stops
                self._stops_loaded = True

            # Step 3: fetch the departures for the selected stop
            departures = trafiklab.get_departures(self.stop_id, self.limit)
            self._finish(departures, trafiklab.get_last_error())
        except Exception as error:
            self._finish(None, type(error).__name__)

    def _finish(self, departures, error):
        """Publish the result. The flags are set last so readers see all data."""
        self._departures = departures
        self._error = error
        self._has_result = True
        self.busy = False
