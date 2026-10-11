"""Background worker that fetches departures without blocking the UI.

LVGL is not thread safe, so the worker never touches the UI. It only stores
its result in plain attributes. The UI thread polls ``take_result`` from an
LVGL timer and updates the screen itself.
"""

import _thread
import gc

from services import trafiklab, wifi

# TLS needs more stack than the MicroPython default for new threads
WORKER_STACK_SIZE = 24 * 1024


class DepartureWorker:
    """Runs Wi-Fi connection, stop lookup and departure fetching in a thread."""

    def __init__(self, stop_name, stop_id=None, limit=15):
        """Create a worker.

        Args:
            stop_name: Name used to look up the stop id, e.g. 'Karlskrona'.
            stop_id: Known stop id. If given, the name lookup is skipped.
            limit: Maximum number of departures to fetch.
        """
        self.stop_name = stop_name
        self.stop_id = stop_id
        self.limit = limit

        self.busy = False  # True while a fetch is running
        self._has_result = False  # True when a result is waiting to be read
        self._departures = None
        self._error = ""

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

    def _run(self):
        """Thread body: connect, resolve the stop id, fetch departures."""
        try:
            gc.collect()

            # Step 1: make sure Wi-Fi is connected
            if not wifi.is_connected() and not wifi.connect():
                self._finish(None, "No Wi-Fi connection")
                return

            # Step 2: look up the stop id once and reuse it afterwards
            if self.stop_id is None:
                self.stop_id = trafiklab.find_stop_id(self.stop_name)
                if self.stop_id is None:
                    self._finish(None, trafiklab.get_last_error())
                    return

            # Step 3: fetch the departures
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
