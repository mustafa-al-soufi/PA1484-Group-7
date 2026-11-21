import sys
import time

import lvgl as lv

from board_lvgl import start_board
from debug_log import log

from screens.departure import (
    COLOR_MUTED, COLOR_TEXT, FONT_BIG, FONT_SMALL, MAX_DEPARTURES,
    create_departure_screen, load_swedish_fonts, make_label, setup_page,
    show_message, update_departures,
)
from screens.journey import (
    create_journey_screen, get_journey_selection, set_journey_side,
    show_journey_message, show_trips,
)
from screens.settings import (
    TRANSPORT_TYPES, create_settings_screen, set_selected_stop, set_stops,
    set_transport, show_save_message, update_connection_status,
)
from screens import settings as settings_manager  # saved defaults (US3.4)
from services import trafiklab
from services.departure_worker import DepartureWorker, is_connected

TOWN = "Karlskrona"  # US1.2B, US3.2B
STOP_ID = None  # start-up stop; None = the first fixed stop
VERSION = "4"  # US1.1
MEMBERS = ("Mustafa Ali Hussein Al-Soufi", "Berat Subasi", "Emanuel Gabro",
           "Ahmad Elhassen", "Ismail Alkhasara")
REFRESH_MS = 60_000  # automatic refresh (US4.1)
POLL_MS = 250  # the UI checks for a finished fetch
FIRST_FETCH_MS = 1500  # draw the start screen first
RENDER_PERIOD_MS = 10  # redraw and read the touch on every LVGL run
MAX_IDLE_MS = 10  # run_ui_loop: longest sleep
TICK_CHECK_MS = 2000  # then check that time is not counted twice
# log() writes the flash (stalls the screen): rare events only


class Application:
    def __init__(self):
        self.display, self.touch, self.handler = start_board()
        load_swedish_fonts()  # å ä ö, or a/o if that does not work
        saved = settings_manager.load()  # US3.4
        # Departures for all pages
        self.worker = DepartureWorker(TOWN, saved["stop_id"] or STOP_ID, MAX_DEPARTURES)
        if saved["stop_id"]:
            self.worker.stop_name = saved["stop_name"]
        self.worker.set_transport(saved["transport"])
        self.stops = []  # dicts with 'id' and 'name'
        self.selected_stop = self.journey_from = self.journey_to = None
        # Set: poll_worker starts a fetch / journey search (US5.2)
        self.refresh_pending = self.journey_pending = False
        # A stop search to start: (side, text); side = "stop" (settings, US3.2C),
        # "from" or "to" (journey, US5.2B). search_side: the one running.
        self.search_pending = self.search_side = None
        self.trip_stops = {}  # the From and To dropdowns' own stops (US5.2B)
        self.refreshing = False  # Refresh pressed: show the result (US4.2B)
        self.last_error = None  # an error is only logged once

        self.create_ui()
        self.apply_stops(trafiklab.get_stops())  # fixed stops, no search
        self.set_trip_stops("from", trafiklab.get_stops())
        self.set_trip_stops("to", trafiklab.get_stops(), 1)
        # Kept on self so they are not garbage collected
        self.poll_timer = lv.timer_create(self.poll_worker, POLL_MS, None)
        # US4.1
        self.refresh_timer = lv.timer_create(self.request_refresh, REFRESH_MS, None)
        self.first_timer = lv.timer_create(self.request_refresh, FIRST_FETCH_MS, None)
        self.first_timer.set_repeat_count(1)
        log("student application ready")

    def create_start_screen(self, tile):
        "Name, version, group and members (US1.1)"
        setup_page(tile, 12)
        tile.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        make_label(tile, "Karlskrona Transit", 0, FONT_BIG, COLOR_TEXT)
        make_label(tile, "Version " + VERSION + " | Group 7", 0, FONT_SMALL, COLOR_MUTED)
        card = lv.obj(tile)
        card.remove_flag(lv.obj.FLAG.CLICKABLE)  # swipes go to the tileview
        card.set_size(380, lv.SIZE_CONTENT)
        card.set_style_bg_color(lv.color_hex(0x1B2A41), 0)
        card.set_style_border_width(0, 0)
        names = make_label(card, "\n".join(MEMBERS), 348, FONT_BIG, COLOR_TEXT, wrap=True)
        names.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        make_label(tile, "Swipe left for departures >", 0, FONT_SMALL, COLOR_MUTED)

    def create_ui(self):
        "The four screens in a tileview"
        tiles = self.tileview = lv.tileview(lv.screen_active())
        tiles.set_size(600, 450)
        tiles.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        # Only the tileview paints a background
        tiles.set_style_bg_opa(lv.OPA.COVER, 0)
        tiles.set_style_bg_color(lv.color_hex(0x000000), 0)
        both = lv.DIR.LEFT | lv.DIR.RIGHT
        self.create_start_screen(tiles.add_tile(0, 0, lv.DIR.RIGHT))
        self.departure_list = create_departure_screen(tiles.add_tile(1, 0, both))  # US1.2B
        show_message(self.departure_list, "Loading...")
        self.settings_screen = create_settings_screen(  # US3.1
            tiles.add_tile(2, 0, both), "Loading...", self.on_stop_changed,
            self.on_transport_changed, self.on_save_clicked, self.on_reset_clicked,
            self.worker.transport, self.on_stop_search, self.on_refresh_clicked)
        self.journey_screen = create_journey_screen(  # US5.1, US5.2
            tiles.add_tile(3, 0, lv.DIR.LEFT), self.on_search_clicked, self.stop_search)

        # The fetch waits during swipes and journey scrolling
        for widget in (tiles, self.journey_screen["results"]):
            widget.add_event_cb(self.on_scroll, lv.EVENT.SCROLL_BEGIN, None)
            widget.add_event_cb(self.on_scroll, lv.EVENT.SCROLL_END, None)
        try:
            lv.display_get_default().get_refr_timer().set_period(RENDER_PERIOD_MS)
            self.touch._indev_drv.get_read_timer().set_period(RENDER_PERIOD_MS)
        except Exception as error:
            print("render tuning skipped:", error)

    def on_scroll(self, event):
        "The fetch waits while the user swipes or scrolls"
        trafiklab.set_scrolling(event.get_code() == lv.EVENT.SCROLL_BEGIN)

    def request_refresh(self, _timer=None):
        self.worker.start()

    def reload(self, _event=None):
        "Loading..., then a new fetch (US4.2)"
        show_message(self.departure_list, "Loading...")
        self.refresh_pending = True

    def on_refresh_clicked(self, _event):
        "Refresh on the settings screen (US4.2B)"
        show_save_message(self.settings_screen, "Refreshing...")
        self.refreshing = True
        self.reload()

    def select_stop(self, index):
        self.selected_stop = stop = self.stops[index]
        self.worker.set_stop(stop["id"], stop["name"])

    def on_stop_changed(self, _event):
        "Another stop picked"
        index = self.settings_screen["stop_dropdown"].get_selected()
        if index < len(self.stops):
            self.select_stop(index)
            self.changed()

    def on_transport_changed(self, _event):
        "Another transport type picked (US3.3)"
        index = self.settings_screen["transport_dropdown"].get_selected()
        if index < len(TRANSPORT_TYPES):
            self.worker.set_transport(TRANSPORT_TYPES[index])
            self.changed()

    def changed(self):
        show_save_message(self.settings_screen, "")
        self.reload()

    def on_save_clicked(self, _event):
        "Saves the stop and transport type as default (US3.4)"
        if self.selected_stop is None:
            show_save_message(self.settings_screen, "No stop to save yet", False)
            return
        ok = settings_manager.save({"stop_id": self.selected_stop["id"],
                                    "stop_name": self.selected_stop["name"],
                                    "transport": self.worker.transport})
        show_save_message(self.settings_screen, "Saved as default" if ok else "Could not save", ok)
        log("settings saved" if ok else "settings save failed")

    def on_reset_clicked(self, _event):
        "Restores the saved defaults (US3.5)"
        saved = settings_manager.load()
        self.worker.set_transport(saved["transport"])
        set_transport(self.settings_screen, saved["transport"])
        if saved["stop_id"]:  # may be a searched stop, not in the list
            self.worker.set_stop(saved["stop_id"], saved["stop_name"])
            self.apply_stops(self.stops)
        elif self.stops:  # else the first
            self.select_stop(0)
            set_selected_stop(self.settings_screen, 0)
        show_save_message(self.settings_screen, "Reset to default")
        self.reload()

    def stop_index(self, stop_id):
        "Position of ``stop_id`` in the stops, else -1"
        for index, stop in enumerate(self.stops):
            if stop["id"] == stop_id:
                return index
        return -1

    def apply_stops(self, stops):
        "Fills the stop dropdowns; the current stop stays in them, on top"
        self.stops = stops
        selected = self.stop_index(self.worker.stop_id)
        if selected < 0:
            stops.insert(0, {"id": self.worker.stop_id, "name": self.worker.stop_name or "Selected stop"})
            selected = 0
        self.selected_stop = stops[selected]
        set_stops(self.settings_screen, [stop["name"] for stop in stops], selected)

    def set_trip_stops(self, side, stops, selected=0):
        "Fills the From or To dropdown (US5.2B)"
        self.trip_stops[side] = stops
        set_journey_side(self.journey_screen, side, [stop["name"] for stop in stops], selected)

    def on_stop_search(self, text):
        self.stop_search("stop", text)

    def stop_search(self, side, text):
        "Stop search for ``side`` (see search_pending); empty = the fixed stops"
        text = text.strip()
        if text:
            self.search_pending = (side, text)  # poll_worker starts it
            self.search_message(side, "Searching...")
        else:
            self.show_found_stops(side, trafiklab.get_stops(), "")

    def search_message(self, side, text, ok=True):
        if side == "stop":
            show_save_message(self.settings_screen, text, ok)
        else:
            show_journey_message(self.journey_screen, text, ok)

    def show_found_stops(self, side, stops, text=None):
        "A stop search finished: the stops go into that side's dropdown, opened"
        if not stops:
            self.search_message(side, "Search failed" if stops is None else "No stops found", False)
            return
        self.search_message(side, "%d stops found" % len(stops) if text is None else text)
        if side == "stop":
            self.apply_stops(stops)
            dropdown = self.settings_screen["stop_dropdown"]
        else:
            self.set_trip_stops(side, stops)
            dropdown = self.journey_screen[side]
        if text is None:
            dropdown.open()

    def on_search_clicked(self, _event):
        "Search pressed on the journey screen (US5.2)"
        screen, trips = self.journey_screen, self.trip_stops
        if not (trips.get("from") and trips.get("to")):
            show_journey_message(screen, "Stops are still loading", False)
            return
        from_index, to_index = get_journey_selection(screen)
        if from_index >= len(trips["from"]) or to_index >= len(trips["to"]):
            return
        self.journey_from, self.journey_to = trips["from"][from_index], trips["to"][to_index]
        if self.journey_from["id"] == self.journey_to["id"]:
            show_journey_message(screen, "Choose two different stops", False)
            return
        show_journey_message(screen, self.journey_from["name"] + " -> " + self.journey_to["name"])
        show_trips(screen, None, "Searching...")
        self.journey_pending = True  # US5.3

    def poll_worker(self, timer=None):
        "An error is shown, it never stops the display"
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
        "Shows finished fetches"
        if trafiklab.is_scrolling():
            return  # nothing new is drawn during a swipe
        journey = self.worker.take_journey()  # US5.3
        if journey is not None:
            show_trips(self.journey_screen, best_first(journey[0]),
                       "Could not fetch journeys\n" + journey[1])
        found = self.worker.take_stops()  # US3.2C, US5.2B
        if found is not None:
            self.show_found_stops(self.search_side, found[0])
        if self.refresh_pending:  # drop the old result, fetch again
            self.worker.take_result()
            self.refresh_pending = not self.worker.start()
            return
        if self.journey_pending:
            self.journey_pending = not self.worker.start(
                (self.journey_from["id"], self.journey_to["id"]))
            return
        if self.search_pending:
            side, text = self.search_pending
            if self.worker.start(search=text):
                self.search_side, self.search_pending = side, None
            return
        result = self.worker.take_result()
        if result is not None:
            departures, error = result
            update_departures(self.departure_list, departures, error)
            update_connection_status(self.settings_screen, is_connected(), departures is not None)
            if self.refreshing:
                self.refreshing = False
                show_save_message(self.settings_screen, "Departures updated" if departures is not None
                                  else "Refresh failed", departures is not None)


def best_first(trips):
    """US5.3B: the journeys by arrival at the destination, earliest first; the
    first is marked "best". An arrival before the earliest departure is after
    midnight, so it sorts last."""
    if not trips:
        return trips
    start = min(trip["departure"] for trip in trips)
    trips = sorted(trips, key=lambda t: ("1" if t["arrival"] < start else "0") + t["arrival"])
    trips[0]["best"] = True
    return trips


def show_fatal(error):
    "Shows a start-up error instead of a black screen"
    try:
        text = "Start-up error:\n%r\nSee debug.log" % (error,)
        make_label(lv.screen_active(), text, 560, FONT_BIG, 0xF44336, wrap=True).center()
    except Exception:
        pass  # the display did not start


def run_ui_loop(handler):
    "Runs LVGL when it has work, not every 33 ms; else the TaskHandler"
    if sys.implementation.name != "micropython":
        return  # PC tests have no real LVGL
    try:
        handler.disable()
    except Exception as error:
        print("UI loop skipped:", error)
        return
    try:
        started = last = time.ticks_ms()
        started_tick = lv.tick_get()
        checked = False
        while True:
            now = time.ticks_ms()
            lv.tick_inc(time.ticks_diff(now, last))
            last = now
            wait = MAX_IDLE_MS
            try:
                wait = lv.task_handler()  # ms until LVGL has work again
            except Exception as error:
                sys.print_exception(error)
            if not isinstance(wait, int):
                wait = MAX_IDLE_MS
            # Is the time counted twice (animations twice as fast)?
            if not checked and time.ticks_diff(now, started) >= TICK_CHECK_MS:
                checked = True
                if lv.tick_elaps(started_tick) > time.ticks_diff(now, started) * 3 // 2:
                    print("UI loop stopped: LVGL time is already counted")
                    return
            time.sleep_ms(max(1, min(wait, MAX_IDLE_MS)))  # the fetch runs too
    finally:
        handler.enable()  # for example after Ctrl+C


try:
    app = Application()
except Exception as error:
    log("FATAL: %r" % (error,))
    sys.print_exception(error)
    show_fatal(error)
    raise

run_ui_loop(app.handler)