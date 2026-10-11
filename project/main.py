import sys
import time

import lvgl as lv
import network

from board_lvgl import start_board
from debug_log import log

from secrets import WIFI_SSID, WIFI_PASSWORD

from config import settings_manager

from screens.departure import (
    MAX_ROWS,
    create_departure_screen,
    show_message,
    update_departures,
)

from screens.settings import (
    TRANSPORT_TYPES,
    create_settings_screen,
    set_selected_stop,
    set_stops,
    set_transport,
    show_save_message,
    update_connection_status,
)

from services import wifi
from services.departure_worker import DepartureWorker

# Town whose stops can be selected (US1.2B, US3.2B)
TOWN = "Karlskrona"
# Stop id to show at start-up. None = the busiest stop in TOWN.
STOP_ID = None
# Automatic refresh interval (US4.1)
REFRESH_MS = 60_000
# How often the UI checks if the background fetch has finished
POLL_MS = 250


class Application:
    def __init__(self):
        self.display, self.touch, self.handler = start_board()

        # Load the saved default settings (US3.4)
        saved = settings_manager.load()
        self.worker = DepartureWorker(TOWN, saved["stop_id"] or STOP_ID, MAX_ROWS)
        if saved["stop_id"]:
            self.worker.stop_name = saved["stop_name"]
        self.worker.set_transport(saved["transport"])

        self.stops = []  # selectable stops: dicts with 'id' and 'name'
        self.selected_stop = None  # the stop picked in the dropdown
        self.refresh_pending = False  # True when a new fetch must be started

        self.create_ui()
        self.connect_wifi()

        # Timers must be stored on self so they are not garbage collected
        self.poll_timer = lv.timer_create(self.poll_worker, POLL_MS, None)
        self.refresh_timer = lv.timer_create(self.request_refresh, REFRESH_MS, None)
        self.request_refresh()

        log("student application ready")

    @staticmethod
    def apply_tile_colors(tile, label, dark):
        tile.set_style_bg_opa(lv.OPA.COVER, 0)
        tile.set_style_bg_color(lv.color_hex(0x000000 if dark else 0xFFFFFF), 0)
        label.set_style_text_color(lv.color_hex(0xFFFFFF if dark else 0x000000), 0)

    def create_ui(self):
        "Function: Creates UI"
        self.tileview = lv.tileview(lv.screen_active())
        self.tileview.set_size(600, 450)
        self.tileview.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

        self.tile1 = self.tileview.add_tile(0, 0, lv.DIR.RIGHT)
        self.tile2 = self.tileview.add_tile(1, 0, lv.DIR.LEFT | lv.DIR.RIGHT)
        self.tile3 = self.tileview.add_tile(2, 0, lv.DIR.LEFT)

        self.tile1_label = lv.label(self.tile1)
        self.tile1_label.set_text(
            "Karlskrona Transit\n\n"
            "Version: 3\n"
            "Group 7\n\n"
            "Mustafa Ali Hussein Al-Soufi\n"
            "Berat Subasi\n"
            "Emanuel Gabro\n"
            "Ahmad Elhassen\n"
            "Ismail Alkhasara"
        )
        self.tile1_label.set_style_text_font(lv.font_montserrat_20, 0)
        self.tile1_label.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        self.tile1_label.center()
        self.apply_tile_colors(self.tile1, self.tile1_label, False)

        # Departure screen (US1.2B) with the refresh button (US4.2)
        self.departure_list = create_departure_screen(
            self.tile2, self.on_refresh_clicked
        )
        show_message(self.departure_list, "Loading...")

        # Settings screen (US3.1)
        self.settings_screen = create_settings_screen(
            self.tile3,
            "Loading...",
            self.on_stop_changed,
            self.on_transport_changed,
            self.on_save_clicked,
            self.on_reset_clicked,
            self.worker.transport,
        )

    def request_refresh(self, timer=None):
        "Function: Starts a background fetch of the departures (US4.1)"
        if not self.worker.start():
            log("refresh skipped: previous fetch still running")

    def on_refresh_clicked(self, _event):
        "Function: Called when the user presses Refresh (US4.2)"
        show_message(self.departure_list, "Loading...")
        self.refresh_pending = True  # poll_worker starts the fetch
        log("manual refresh")

    def on_stop_changed(self, _event):
        "Function: Called when the user picks another stop in the dropdown"
        index = self.settings_screen["stop_dropdown"].get_selected()
        if index >= len(self.stops):
            return  # the stop list has not been loaded yet

        self.selected_stop = self.stops[index]
        self.worker.set_stop(self.selected_stop["id"], self.selected_stop["name"])
        show_save_message(self.settings_screen, "")
        show_message(self.departure_list, "Loading...")
        self.refresh_pending = True
        log("stop selected: " + self.selected_stop["name"])

    def on_transport_changed(self, _event):
        "Function: Called when the user picks another transport type (US3.3)"
        index = self.settings_screen["transport_dropdown"].get_selected()
        if index >= len(TRANSPORT_TYPES):
            return

        self.worker.set_transport(TRANSPORT_TYPES[index])
        show_save_message(self.settings_screen, "")
        show_message(self.departure_list, "Loading...")
        self.refresh_pending = True
        log("transport selected: " + TRANSPORT_TYPES[index])

    def on_save_clicked(self, _event):
        "Function: Saves the current stop and transport type as default (US3.4)"
        if self.selected_stop is None:
            show_save_message(self.settings_screen, "No stop to save yet", False)
            return

        ok = settings_manager.save(
            {
                "stop_id": self.selected_stop["id"],
                "stop_name": self.selected_stop["name"],
                "transport": self.worker.transport,
            }
        )
        show_save_message(
            self.settings_screen,
            "Saved as default" if ok else "Could not save",
            ok,
        )
        log("settings saved" if ok else "settings save failed")

    def on_reset_clicked(self, _event):
        "Function: Restores the saved default settings (US3.5)"
        saved = settings_manager.load()
        self.worker.set_transport(saved["transport"])
        set_transport(self.settings_screen, saved["transport"])

        # Stop: the saved one, else STOP_ID, else the busiest (first in list)
        if self.stops:
            wanted_id = saved["stop_id"] or STOP_ID
            index = 0
            for position, stop in enumerate(self.stops):
                if stop["id"] == wanted_id:
                    index = position
            self.selected_stop = self.stops[index]
            self.worker.set_stop(self.selected_stop["id"], self.selected_stop["name"])
            set_selected_stop(self.settings_screen, index)

        show_save_message(self.settings_screen, "Reset to default")
        show_message(self.departure_list, "Loading...")
        self.refresh_pending = True
        log("settings reset to default")

    def apply_stops(self, stops):
        "Function: Fills the stop dropdown with the stops from Trafiklab"
        current_id = self.worker.stop_id

        # A stop set by STOP_ID or saved earlier may be missing: add it on top
        if current_id is not None and not any(s["id"] == current_id for s in stops):
            stops.insert(
                0, {"id": current_id, "name": self.worker.stop_name or "Selected stop"}
            )

        self.stops = stops
        selected = 0
        for index, stop in enumerate(stops):
            if stop["id"] == current_id:
                selected = index
        self.selected_stop = stops[selected]
        set_stops(self.settings_screen, [stop["name"] for stop in stops], selected)
        log("stops loaded: " + str(len(stops)))

    def poll_worker(self, timer=None):
        "Function: Updates the screens when a background fetch has finished"
        stops = self.worker.take_stops()
        if stops:
            self.apply_stops(stops)

        # New selection or manual refresh: drop the old result and fetch again
        if self.refresh_pending:
            self.worker.take_result()
            if self.worker.start():
                self.refresh_pending = False
            return

        result = self.worker.take_result()
        if result is None:
            return  # still fetching, or nothing new

        departures, error = result
        update_departures(self.departure_list, departures, error)
        update_connection_status(
            self.settings_screen, wifi.is_connected(), departures is not None
        )
        log("departures: " + ("error" if departures is None else str(len(departures))))

    @staticmethod
    def connect_wifi():
        "Function: Connects to WiFi"
        log("connecting to Wi-Fi SSID: " + WIFI_SSID)
        station = network.WLAN(network.STA_IF)
        station.active(True)
        station.connect(WIFI_SSID, WIFI_PASSWORD)
        started = time.ticks_ms()
        while (
            not station.isconnected()
            and time.ticks_diff(time.ticks_ms(), started) < 15_000
        ):
            time.sleep_ms(250)
        log(
            "Wi-Fi connected"
            if station.isconnected()
            else "Wi-Fi could not connect (timeout)"
        )


try:
    app = Application()
except Exception as error:
    log("FATAL: %r" % (error,))
    sys.print_exception(error)
    raise
