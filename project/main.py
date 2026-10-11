import sys
import time

import lvgl as lv
import network

from board_lvgl import start_board
from debug_log import log

from secrets import WIFI_SSID, WIFI_PASSWORD

from screens.departure import (
    MAX_ROWS,
    create_departure_screen,
    show_message,
    update_departures,
)

from screens.settings import create_settings_screen, update_connection_status

from services import wifi
from services.departure_worker import DepartureWorker

# Stop area to show departures for (US1.2B)
STOP_NAME = "Karlskrona"
# Set a stop id (as a string) to skip the name lookup
STOP_ID = None
# Automatic refresh interval (US4.1). Trafiklab caches responses for 60 s.
REFRESH_MS = 60_000
# How often the UI checks if the background fetch has finished
POLL_MS = 250


class Application:
    def __init__(self):
        self.display, self.touch, self.handler = start_board()
        self.worker = DepartureWorker(STOP_NAME, STOP_ID, MAX_ROWS)
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
        # Tile 2 can now be swiped both ways: back to start, on to settings
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

        # Departure screen (US1.2B)
        self.departure_list = create_departure_screen(self.tile2)
        show_message(self.departure_list, "Loading...")

        # Settings screen (US3.1)
        self.settings_screen = create_settings_screen(self.tile3, STOP_NAME)

    def request_refresh(self, timer=None):
        "Function: Starts a background fetch of the departures (US4.1)"
        if not self.worker.start():
            log("refresh skipped: previous fetch still running")

    def poll_worker(self, timer=None):
        "Function: Updates the screens when a fetch has finished"
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
