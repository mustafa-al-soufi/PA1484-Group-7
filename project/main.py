import sys
import time

import lvgl as lv

from board_lvgl import start_board
from debug_log import log

from screens.departure import (
    COLOR_MUTED, COLOR_TEXT, FONT_BIG, FONT_SMALL, MAX_DEPARTURES,
    create_departure_screen, make_label, show_message, update_departures,
)
from screens.journey import (
    create_journey_screen, get_journey_selection, set_journey_stops,
    show_journey_message, show_trips,
)
from screens.settings import (
    TRANSPORT_TYPES, create_settings_screen, set_selected_stop, set_stops,
    set_transport, show_save_message, update_connection_status,
)
from services import settings_manager, trafiklab
from services.departure_worker import DepartureWorker, is_connected

TOWN = "Karlskrona"  # US1.2B, US3.2B
STOP_ID = None  # stop at start-up; None = the first fixed stop
VERSION = "4"  # start screen (US1.1)
MEMBERS = ("Mustafa Ali Hussein Al-Soufi", "Berat Subasi", "Emanuel Gabro",
           "Ahmad Elhassen", "Ismail Alkhasara")
REFRESH_MS = 60_000  # automatic refresh (US4.1)
POLL_MS = 250  # how often the UI checks for a finished fetch
FIRST_FETCH_MS = 1500  # the start screen is drawn before the first fetch
# Redraw and read the touch on every LVGL run (LVGL's 33 ms skips frames)
RENDER_PERIOD_MS = 10
MAX_IDLE_MS = 10  # run_ui_loop: longest sleep between two LVGL runs
TICK_CHECK_MS = 2000  # run_ui_loop: then check LVGL time is not counted twice

# log() writes to the flash, which stalls the screen: only for rare events.


class Application:
    def __init__(self):
        self.display, self.touch, self.handler = start_board()
        saved = settings_manager.load()  # US3.4
        # Enough departures for all pages of the departure board
        self.worker = DepartureWorker(TOWN, saved["stop_id"] or STOP_ID, MAX_DEPARTURES)
        if saved["stop_id"]:
            self.worker.stop_name = saved["stop_name"]
        self.worker.set_transport(saved["transport"])
        self.stops = []  # dicts with 'id' and 'name'
        self.selected_stop = None
        self.refresh_pending = False  # poll_worker must start a fetch
        self.journey_from = self.journey_to = None  # US5.2
        self.journey_pending = False  # poll_worker must start a journey search
        self.last_error = None  # the same error is only logged once

        self.create_ui()
        self.apply_stops(trafiklab.get_stops())  # fixed stops, no search
        # Timers are kept on self so they are not garbage collected
        self.poll_timer = lv.timer_create(self.poll_worker, POLL_MS, None)
        self.refresh_timer = lv.timer_create(self.request_refresh, REFRESH_MS, None)
        self.first_timer = lv.timer_create(self.request_refresh, FIRST_FETCH_MS, None)
        self.first_timer.set_repeat_count(1)
        log("student application ready")

    def create_start_screen(self, tile):
        "Function: Name, version, group and members (US1.1)"
        tile.remove_flag(lv.obj.FLAG.SCROLLABLE)
        tile.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        tile.set_style_pad_row(12, 0)
        tile.set_flex_flow(lv.FLEX_FLOW.COLUMN)
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
        "Function: The four screens in a tileview"
        tiles = self.tileview = lv.tileview(lv.screen_active())
        tiles.set_size(600, 450)
        tiles.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        # Only the tileview paints the background; the tiles are transparent
        tiles.set_style_bg_opa(lv.OPA.COVER, 0)
        tiles.set_style_bg_color(lv.color_hex(0x000000), 0)
        both = lv.DIR.LEFT | lv.DIR.RIGHT
        self.create_start_screen(tiles.add_tile(0, 0, lv.DIR.RIGHT))
        self.departure_list = create_departure_screen(  # US1.2B, US4.2
            tiles.add_tile(1, 0, both), self.reload)
        show_message(self.departure_list, "Loading...")
        self.settings_screen = create_settings_screen(  # US3.1
            tiles.add_tile(2, 0, both), "Loading...", self.on_stop_changed,
            self.on_transport_changed, self.on_save_clicked, self.on_reset_clicked,
            self.worker.transport)
        self.journey_screen = create_journey_screen(  # US5.1, US5.2
            tiles.add_tile(3, 0, lv.DIR.LEFT), self.on_search_clicked)

        # The fetch pauses during swipes and scrolling in the journey results
        for widget in (tiles, self.journey_screen["results"]):
            widget.add_event_cb(self.on_scroll, lv.EVENT.SCROLL_BEGIN, None)
            widget.add_event_cb(self.on_scroll, lv.EVENT.SCROLL_END, None)
        try:
            lv.display_get_default().get_refr_timer().set_period(RENDER_PERIOD_MS)
            self.touch._indev_drv.get_read_timer().set_period(RENDER_PERIOD_MS)
        except Exception as error:
            print("render tuning skipped:", error)

    def on_scroll(self, event):
        "Function: A swipe or scroll starts or ends: the fetch waits meanwhile"
        trafiklab.set_scrolling(event.get_code() == lv.EVENT.SCROLL_BEGIN)

    def request_refresh(self, timer=None):
        "Function: Starts a background fetch of the departures (US4.1)"
        self.worker.start()  # skipped if a fetch is still running

    def reload(self, _event=None):
        "Function: Refresh (US4.2) or a new selection: Loading..., then a new fetch"
        show_message(self.departure_list, "Loading...")
        self.refresh_pending = True

    def on_stop_changed(self, _event):
        "Function: Another stop picked"
        index = self.settings_screen["stop_dropdown"].get_selected()
        if index < len(self.stops):
            self.selected_stop = self.stops[index]
            self.worker.set_stop(self.selected_stop["id"], self.selected_stop["name"])
            show_save_message(self.settings_screen, "")
            self.reload()

    def on_transport_changed(self, _event):
        "Function: Another transport type picked (US3.3)"
        index = self.settings_screen["transport_dropdown"].get_selected()
        if index < len(TRANSPORT_TYPES):
            self.worker.set_transport(TRANSPORT_TYPES[index])
            show_save_message(self.settings_screen, "")
            self.reload()

    def on_save_clicked(self, _event):
        "Function: Saves the stop and transport type as default (US3.4)"
        if self.selected_stop is None:
            show_save_message(self.settings_screen, "No stop to save yet", False)
            return
        ok = settings_manager.save({"stop_id": self.selected_stop["id"],
                                    "stop_name": self.selected_stop["name"],
                                    "transport": self.worker.transport})
        show_save_message(self.settings_screen, "Saved as default" if ok else "Could not save", ok)
        log("settings saved" if ok else "settings save failed")

    def on_reset_clicked(self, _event):
        "Function: Restores the saved defaults (US3.5)"
        saved = settings_manager.load()
        self.worker.set_transport(saved["transport"])
        set_transport(self.settings_screen, saved["transport"])
        if self.stops:  # the saved stop, else STOP_ID, else the first
            index = self.stop_index(saved["stop_id"] or STOP_ID)
            self.selected_stop = self.stops[index]
            self.worker.set_stop(self.selected_stop["id"], self.selected_stop["name"])
            set_selected_stop(self.settings_screen, index)
        show_save_message(self.settings_screen, "Reset to default")
        self.reload()

    def stop_index(self, stop_id):
        "Function: Position of ``stop_id`` in the stop list, 0 if it is not there"
        for index, stop in enumerate(self.stops):
            if stop["id"] == stop_id:
                return index
        return 0

    def apply_stops(self, stops):
        "Function: Fills the stop dropdowns and selects the worker's stop"
        self.stops = stops
        selected = self.stop_index(self.worker.stop_id)
        self.selected_stop = stops[selected]
        names = [stop["name"] for stop in stops]
        set_stops(self.settings_screen, names, selected)
        set_journey_stops(self.journey_screen, names)

    def on_search_clicked(self, _event):
        "Function: Search pressed on the journey screen (US5.2)"
        screen = self.journey_screen
        if not self.stops:
            show_journey_message(screen, "Stops are still loading", False)
            return
        from_index, to_index = get_journey_selection(screen)
        if max(from_index, to_index) >= len(self.stops):
            return
        if from_index == to_index:
            show_journey_message(screen, "Choose two different stops", False)
            return
        self.journey_from = self.stops[from_index]
        self.journey_to = self.stops[to_index]
        show_journey_message(screen, self.journey_from["name"] + " -> " + self.journey_to["name"])
        show_trips(screen, None, "Searching...")
        self.journey_pending = True  # poll_worker starts the search (US5.3)

    def poll_worker(self, timer=None):
        "Function: Runs check_worker; an error is shown, it never stops the display"
        try:
            self.check_worker()
        except Exception as error:
            text = "Error: %r" % (error,)
            sys.print_exception(error)
            if text != self.last_error:  # do not fill the flash with one error
                self.last_error = text
                log("poll " + text)
                show_message(self.departure_list, text)

    def check_worker(self):
        "Function: Updates the screens when a background fetch has finished"
        if trafiklab.is_scrolling():
            return  # after the swipe, so nothing new is drawn during it
        journey = self.worker.take_journey()  # US5.3
        if journey is not None:
            show_trips(self.journey_screen, journey[0], "Could not fetch journeys\n" + journey[1])
        if self.refresh_pending:  # drop the old result and fetch again
            self.worker.take_result()
            self.refresh_pending = not self.worker.start()
            return
        if self.journey_pending:  # start the search when the worker is free
            self.journey_pending = not self.worker.start(
                (self.journey_from["id"], self.journey_to["id"]))
            return
        result = self.worker.take_result()
        if result is not None:
            departures, error = result
            update_departures(self.departure_list, departures, error)
            update_connection_status(self.settings_screen, is_connected(), departures is not None)


def show_fatal(error):
    "Function: Shows a start-up error instead of a black screen"
    try:
        label = lv.label(lv.screen_active())
        label.set_width(560)
        label.set_text("Start-up error:\n%r\nSee debug.log" % (error,))
        label.set_style_text_color(lv.color_hex(0xF44336), 0)
        label.center()
    except Exception:
        pass  # the display did not start


def run_ui_loop(handler):
    """Function: Runs LVGL as soon as it has work, not from the 33 ms TaskHandler.

    Gives the work back to the TaskHandler if something is not as expected.
    """
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
            try:
                wait = lv.task_handler()  # ms until LVGL has work again
            except Exception as error:
                sys.print_exception(error)
                wait = MAX_IDLE_MS
            if not isinstance(wait, int):
                wait = MAX_IDLE_MS
            # If the TaskHandler counts time too, animations run twice as fast
            if not checked and time.ticks_diff(now, started) >= TICK_CHECK_MS:
                checked = True
                if lv.tick_elaps(started_tick) > time.ticks_diff(now, started) * 3 // 2:
                    print("UI loop stopped: LVGL time is already counted")
                    return
            time.sleep_ms(max(1, min(wait, MAX_IDLE_MS)))  # lets the fetch run too
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
