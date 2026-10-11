"""Wi-Fi helpers. Keeps the network module out of the rest of the app."""

import time

import network

from debug_log import log
from secrets import WIFI_SSID, WIFI_PASSWORD


def is_connected():
    """Return True if the board is connected to Wi-Fi."""
    return network.WLAN(network.STA_IF).isconnected()


def connect(timeout_ms=15_000):
    """Connect to the Wi-Fi network from secrets.py.

    Waits until connected or until the timeout, so only call it from the
    background worker. Returns True if we are connected.
    """
    log("connecting to Wi-Fi SSID: " + WIFI_SSID)
    station = network.WLAN(network.STA_IF)
    station.active(True)

    if not station.isconnected():
        station.connect(WIFI_SSID, WIFI_PASSWORD)

    started = time.ticks_ms()
    while (
        not station.isconnected()
        and time.ticks_diff(time.ticks_ms(), started) < timeout_ms
    ):
        time.sleep_ms(250)

    connected = station.isconnected()
    log("Wi-Fi connected" if connected else "Wi-Fi could not connect (timeout)")
    return connected
