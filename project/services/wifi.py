"""Wi-Fi helper functions for the Karlskrona Transit application.

Keeps all network-interface handling in one place so that the UI and the
API client never need to touch the ``network`` module directly.
"""

import time

import network

from debug_log import log
from secrets import WIFI_SSID, WIFI_PASSWORD


def is_connected():
    """Return True if the station interface currently has a Wi-Fi connection."""
    return network.WLAN(network.STA_IF).isconnected()


def connect(timeout_ms=15_000):
    """Connect to the configured Wi-Fi network.

    Blocks until connected or until ``timeout_ms`` has passed, so it must
    only be called from the background worker, never from the UI thread.

    Args:
        timeout_ms: Maximum time to wait for the connection, in milliseconds.

    Returns:
        True if the device is connected when the function returns.
    """
    log("connecting to Wi-Fi SSID: " + WIFI_SSID)
    station = network.WLAN(network.STA_IF)
    station.active(True)

    # Only start a new connection attempt if we are not already connected
    if not station.isconnected():
        station.connect(WIFI_SSID, WIFI_PASSWORD)

    # Poll until connected or timed out
    started = time.ticks_ms()
    while (
        not station.isconnected()
        and time.ticks_diff(time.ticks_ms(), started) < timeout_ms
    ):
        time.sleep_ms(250)

    connected = station.isconnected()
    log("Wi-Fi connected" if connected else "Wi-Fi could not connect (timeout)")
    return connected
