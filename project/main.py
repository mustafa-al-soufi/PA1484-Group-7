"""Karlskrona Transit (Group 7): builds the screens, start screen (US1.1),
and connects them to the background worker. The skeleton's TaskHandler from
start_board() runs LVGL."""

import sys

import lvgl as lv

from board_lvgl import start_board
from debug_log import log
from screens import settings
from screens.departure import (
    COLOR_CANCELED,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BIG,
    FONT_SMALL,
    MAX_DEPARTURES,
    create_departure_screen,
    load_swedish_fonts,
    make_label,
    setup_page,
    show_message,
    update_departures,
)
from screens.journey import (
    create_journey_screen,
    get_journey_selection,
    set_journey_side,
    show_journey_message,
    show_trips,
)
from screens.settings import (
    COLOR_CARD,
    TRANSPORT_TYPES,
    create_settings_screen,
    set_selected_stop,
    set_stops,
    set_transport,
    show_save_message,
    update_connection_status,
)
from services import trafiklab
from services.departure_worker import DepartureWorker, is_connected

TOWN = "Karlskrona"  # US1.2B, US3.2B
STOP_ID = None  # None = the first fixed stop
VERSION = "5"
MEMBERS = (
    "Mustafa Ali Hussein Al-Soufi",
    "Berat Subasi",
    "Emanuel Gabro",
    "Ahmad Elhassen",
    "Ismail Alkhasara",
)
REFRESH_MS = 60_000  # automatic refresh (US4.1)
POLL_MS = 250
FIRST_FETCH_MS = 1500  # draw the start screen first
# log() writes the flash, which stalls the screen: rare events only


class Application:
    def __init__(self):
        self.display, self.touch, self.handler = start_board()
        load_swedish_fonts()
        saved = settings.load()  # US3.4
        self.worker = DepartureWorker(TOWN, saved["stop_id"] or STOP_ID, MAX_DEPARTURES)
        if saved["stop_id"]:
            self.worker.stop_name = saved["stop_name"]
        self.worker.set_transport(saved["transport"])
        self.stops = []
        self.selected_stop = self.journey_from = self.journey_to = None
        # Jobs that poll_worker starts when the worker is free
        self.refresh_pending = self.journey_pending = False
        # (side, text): side is "stop", "from" or "to"
        self.search_pending = None
        self.search_side = None  # of the running search
        self.trip_stops = {}  # From and To dropdown stops
        self.refreshing = False  # report the Refresh result (US4.2B)
        self.last_error = None

        self.create_ui()
        self.apply_stops(trafiklab.get_stops())
        self.set_trip_stops("from", trafiklab.get_stops())
        self.set_trip_stops("to", trafiklab.get_stops(), 1)
        # Kept on self, or they are garbage collected
        self.poll_timer = lv.timer_create(self.poll_worker, POLL_MS, None)
        self.refresh_timer = lv.timer_create(self.request_refresh, REFRESH_MS, None)
        self.first_timer = lv.timer_create(self.request_refresh, FIRST_FETCH_MS, None)
        self.first_timer.set_repeat_count(1)
        log("student application ready")

    # --- Screens ---

    def create_start_screen(self, tile):
        """Name, version, group and members (US1.1)."""
        setup_page(tile, 12)
        tile.set_flex_align(
            lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
        )
        make_label(tile, "Karlskrona Transit", 0, FONT_BIG, COLOR_TEXT)
        make_label(
            tile, "Version " + VERSION + " | Group 7", 0, FONT_SMALL, COLOR_MUTED
        )
        card = lv.obj(tile)
        card.remove_flag(lv.obj.FLAG.CLICKABLE)  # so swipes reach the tileview
        card.set_size(380, lv.SIZE_CONTENT)
        card.set_style_bg_color(lv.color_hex(COLOR_CARD), 0)
        card.set_style_border_width(0, 0)
        names = make_label(
            card, "\n".join(MEMBERS), 348, FONT_BIG, COLOR_TEXT, wrap=True
        )
        names.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        make_label(tile, "Swipe left for departures >", 0, FONT_SMALL, COLOR_MUTED)

    def create_ui(self):
        tiles = self.tileview = lv.tileview(lv.screen_active())
        tiles.set_size(600, 450)
        tiles.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        # Only the tileview paints a background: less to draw
        tiles.set_style_bg_opa(lv.OPA.COVER, 0)
        tiles.set_style_bg_color(lv.color_hex(0x000000), 0)
        both = lv.DIR.LEFT | lv.DIR.RIGHT
        self.create_start_screen(tiles.add_tile(0, 0, lv.DIR.RIGHT))
        self.departure_list = create_departure_screen(tiles.add_tile(1, 0, both))
        show_message(self.departure_list, "Loading...")
        self.settings_screen = create_settings_screen(
            tiles.add_tile(2, 0, both),
            "Loading...",
            self.on_stop_changed,
            self.on_transport_changed,
            self.on_save_clicked,
            self.on_reset_clicked,
            self.worker.transport,
            self.on_stop_search,
            self.on_refresh_clicked,
        )
        self.journey_screen = create_journey_screen(
            tiles.add_tile(3, 0, lv.DIR.LEFT), self.on_search_clicked, self.stop_search
        )

        for widget in (tiles, self.journey_screen["results"]):
            widget.add_event_cb(self.on_scroll, lv.EVENT.SCROLL_BEGIN, None)
            widget.add_event_cb(self.on_scroll, lv.EVENT.SCROLL_END, None)

    def on_scroll(self, event):
        trafiklab.set_scrolling(event.get_code() == lv.EVENT.SCROLL_BEGIN)

    # --- Departures and settings (US3, US4) ---

    def request_refresh(self, _timer=None):
        self.worker.start()

    def reload(self):
        """Show Loading..., then fetch again (US4.2)."""
        show_message(self.departure_list, "Loading...")
        self.refresh_pending = True

    def on_refresh_clicked(self, _event):
        show_save_message(self.settings_screen, "Refreshing...")
        self.refreshing = True
        self.reload()

    def select_stop(self, index):
        self.selected_stop = self.stops[index]
        self.worker.set_stop(self.selected_stop["id"], self.selected_stop["name"])

    def on_stop_changed(self, _event):
        index = self.settings_screen["stop_dropdown"].get_selected()
        if index < len(self.stops):
            self.select_stop(index)
            self.changed()

    def on_transport_changed(self, _event):
        index = self.settings_screen["transport_dropdown"].get_selected()
        if index < len(TRANSPORT_TYPES):
            self.worker.set_transport(TRANSPORT_TYPES[index])
            self.changed()

    def changed(self):
        show_save_message(self.settings_screen, "")
        self.reload()

    def on_save_clicked(self, _event):  # US3.4
        if self.selected_stop is None:
            show_save_message(self.settings_screen, "No stop to save yet", False)
            return
        ok = settings.save(
            {
                "stop_id": self.selected_stop["id"],
                "stop_name": self.selected_stop["name"],
                "transport": self.worker.transport,
            }
        )
        show_save_message(
            self.settings_screen, "Saved as default" if ok else "Could not save", ok
        )
        log("settings saved" if ok else "settings save failed")

    def on_reset_clicked(self, _event):  # US3.5
        saved = settings.load()
        self.worker.set_transport(saved["transport"])
        set_transport(self.settings_screen, saved["transport"])
        if saved["stop_id"]:  # may be a searched stop that is not in the list
            self.worker.set_stop(saved["stop_id"], saved["stop_name"])
            self.apply_stops(self.stops)
        elif self.stops:
            self.select_stop(0)
            set_selected_stop(self.settings_screen, 0)
        show_save_message(self.settings_screen, "Reset to default")
        self.reload()

    def stop_index(self, stop_id):
        for index, stop in enumerate(self.stops):
            if stop["id"] == stop_id:
                return index
        return -1

    def apply_stops(self, stops):
        """Fill the stop dropdown. The current stop stays in it, on top."""
        self.stops = stops
        selected = self.stop_index(self.worker.stop_id)
        if selected < 0:
            name = self.worker.stop_name or "Selected stop"
            stops.insert(0, {"id": self.worker.stop_id, "name": name})
            selected = 0
        self.selected_stop = stops[selected]
        set_stops(self.settings_screen, [stop["name"] for stop in stops], selected)

    # --- Stop search (US3.2C, US5.2B) ---

    def set_trip_stops(self, side, stops, selected=0):
        self.trip_stops[side] = stops
        set_journey_side(
            self.journey_screen, side, [stop["name"] for stop in stops], selected
        )

    def on_stop_search(self, text):
        self.stop_search("stop", text)

    def stop_search(self, side, text):
        """An empty text gives the fixed stops."""
        text = text.strip()
        if text:
            self.search_pending = (side, text)
            self.search_message(side, "Searching...")
        else:
            self.show_found_stops(side, trafiklab.get_stops(), "")

    def search_message(self, side, text, ok=True):
        if side == "stop":
            show_save_message(self.settings_screen, text, ok)
        else:
            show_journey_message(self.journey_screen, text, ok)

    def show_found_stops(self, side, stops, text=None):
        """Put the stops in the dropdown of ``side`` and open it."""
        if not stops:
            self.search_message(
                side, "Search failed" if stops is None else "No stops found", False
            )
            return
        self.search_message(
            side, "%d stops found" % len(stops) if text is None else text
        )
        if side == "stop":
            self.apply_stops(stops)
            dropdown = self.settings_screen["stop_dropdown"]
        else:
            self.set_trip_stops(side, stops)
            dropdown = self.journey_screen[side]
        if text is None:
            dropdown.open()

    # --- Journey search (US5.2, US5.3) ---

    def on_search_clicked(self, _event):
        screen, trip_stops = self.journey_screen, self.trip_stops
        if not (trip_stops.get("from") and trip_stops.get("to")):
            show_journey_message(screen, "Stops are still loading", False)
            return
        from_index, to_index = get_journey_selection(screen)
        if from_index >= len(trip_stops["from"]) or to_index >= len(trip_stops["to"]):
            return
        self.journey_from = trip_stops["from"][from_index]
        self.journey_to = trip_stops["to"][to_index]
        if self.journey_from["id"] == self.journey_to["id"]:
            show_journey_message(screen, "Choose two different stops", False)
            return
        show_journey_message(
            screen, self.journey_from["name"] + " -> " + self.journey_to["name"]
        )
        show_trips(screen, None, "Searching...")
        self.journey_pending = True

    # --- Worker results ---

    def poll_worker(self, _timer=None):
        """An error in an LVGL timer stops all timers: show it instead."""
        try:
            self.check_worker()
        except Exception as error:
            text = "Error: %r" % (error,)
            sys.print_exception(error)
            if text != self.last_error:
                self.last_error = text
                log("poll " + text)
                show_message(self.departure_list, text)

    def check_worker(self):
        if trafiklab.is_scrolling():
            return  # drawing would make the swipe stutter
        self.show_search_results()
        if not self.start_pending_job():
            self.show_departures()

    def show_search_results(self):
        journey = self.worker.take_journey()
        if journey is not None:
            show_trips(
                self.journey_screen,
                best_first(journey[0]),
                "Could not fetch journeys\n" + journey[1],
            )
        found = self.worker.take_stops()
        if found is not None:
            self.show_found_stops(self.search_side, found[0])

    def start_pending_job(self):
        """True if a job was waiting (started or not)."""
        if self.refresh_pending:
            self.worker.take_result()  # from before the change
            self.refresh_pending = not self.worker.start()
            return True
        if self.journey_pending:
            journey = self.journey_from["id"], self.journey_to["id"]
            self.journey_pending = not self.worker.start(journey)
            return True
        if self.search_pending:
            side, text = self.search_pending
            if self.worker.start(search=text):
                self.search_side, self.search_pending = side, None
            return True
        return False

    def show_departures(self):
        result = self.worker.take_result()
        if result is None:
            return
        departures, error = result
        fetched = departures is not None
        update_departures(self.departure_list, departures, error)
        update_connection_status(self.settings_screen, is_connected(), fetched)
        if self.refreshing:
            self.refreshing = False
            show_save_message(
                self.settings_screen,
                "Departures updated" if fetched else "Refresh failed",
                fetched,
            )


def best_first(trips):
    """US5.3B: the journeys by arrival, earliest first; the first is "best"."""
    if not trips:
        return trips
    first_departure = min(trip["departure"] for trip in trips)

    # An arrival before the first departure is after midnight: sort it last
    trips = sorted(
        trips, key=lambda trip: (trip["arrival"] < first_departure, trip["arrival"])
    )
    trips[0]["best"] = True
    return trips


def show_fatal(error):
    """Show a start-up error instead of a black screen."""
    try:
        text = "Start-up error:\n%r\nSee debug.log" % (error,)
        make_label(
            lv.screen_active(), text, 560, FONT_BIG, COLOR_CANCELED, wrap=True
        ).center()
    except Exception:
        pass  # the display did not start


try:
    app = Application()
except Exception as error:
    log("FATAL: %r" % (error,))
    sys.print_exception(error)
    show_fatal(error)
    raise
