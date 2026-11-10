"""Background worker that fetches departures and journeys.

LVGL is not thread safe, so the worker never touches the display. The UI
picks up the results with the take_...() methods from a timer.
"""

import _thread

from services import trafiklab, wifi

# The JSON parser and TLS need more stack than the default
WORKER_STACK_SIZE = 24 * 1024


class DepartureWorker:
    """Loads the stop list once and fetches departures or journeys."""

    def __init__(self, town, stop_id=None, limit=15):
        self.town = town
        self.stop_id = stop_id  # None = use the first stop in the list
        self.stop_name = ""
        self.transport = trafiklab.TRANSPORT_ALL
        self.limit = limit  # max departures per fetch
        self.busy = False  # True while a fetch is running

        self._stops_loaded = False
        self._stops = None  # stop list waiting for the UI
        self._result = None  # (departures, error) waiting for the UI
        self._journey = None  # (from_id, to_id) for the next fetch (US5.3)
        self._journey_result = None  # (trips, error) waiting for the UI

    def set_stop(self, stop_id, stop_name):
        """Choose the stop used by the next fetch."""
        self.stop_id = stop_id
        self.stop_name = stop_name

    def set_transport(self, transport):
        """Choose the transport type used by the next fetch (US3.3)."""
        self.transport = transport

    def start(self, journey=None):
        """Start a fetch in the background. False if one is already running.

        ``journey`` is (from_id, to_id) for a journey search (US5.3).
        """
        if self.busy:
            return False
        self.busy = True
        self._journey = journey
        _thread.stack_size(WORKER_STACK_SIZE)
        _thread.start_new_thread(self._run, ())
        return True

    def take_result(self):
        """Return (departures, error) once, or None."""
        result, self._result = self._result, None
        return result

    def take_stops(self):
        """Return the new stop list once, or None."""
        stops, self._stops = self._stops, None
        return stops

    def take_journey(self):
        """Return (trips, error) once, or None."""
        result, self._journey_result = self._journey_result, None
        return result

    def _run(self):
        """Runs in the thread: Wi-Fi, then a journey or the departures."""
        journey = self._journey
        data, error = None, ""
        try:
            if not wifi.is_connected():
                wifi.connect()
            if not wifi.is_connected():
                error = "No Wi-Fi"
            elif journey is not None:
                data = trafiklab.get_trips(journey[0], journey[1])
            else:
                if not self._stops_loaded:
                    stops = trafiklab.find_stops(self.town)
                    if stops is not None:
                        self._stops_loaded = True
                        if self.stop_id is None:
                            self.stop_id = stops[0]["id"]
                            self.stop_name = stops[0]["name"]
                        self._stops = stops
                if self.stop_id is not None:
                    data = trafiklab.get_departures(
                        self.stop_id, self.limit, self.transport
                    )
            if data is None and not error:
                error = trafiklab.get_last_error()
        except Exception as exc:
            error = type(exc).__name__
        if journey is None:
            self._result = (data, error)
        else:
            self._journey_result = (data, error)
        self.busy = False
