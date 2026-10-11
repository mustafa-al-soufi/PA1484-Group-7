"""Settings screen (US3.1): stop, transport type and connection status.

Each setting lives in its own section (a rounded card). The widgets are built
once by ``create_settings_screen``. Later phases add the actual controls to
these sections: stop selection (US3.2B), transport dropdown (US3.3) and
saving/resetting (US3.4, US3.5).
"""

import lvgl as lv

# Share fonts and colors with the departure screen so both look the same
from screens.departure import (
    COLOR_BG,
    COLOR_CANCELED,
    COLOR_DELAYED,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_TEXT,
    FONT_BIG,
    FONT_SMALL,
)

# Background color of the section cards (dark blue)
COLOR_CARD = 0x1B2A41


def _make_label(parent, text, font, color):
    """Create a styled label with automatic width."""
    label = lv.label(parent)
    label.set_text(text)
    label.set_style_text_font(font, 0)
    label.set_style_text_color(lv.color_hex(color), 0)
    return label


def _make_section(parent, title, height):
    """Create a titled card that holds one group of settings.

    Args:
        parent: Container the section is added to.
        title: Small heading shown at the top of the card.
        height: Height of the card in pixels.

    Returns:
        The card object. Add the section's widgets to it.
    """
    section = lv.obj(parent)
    section.set_size(lv.pct(100), height)
    section.set_style_bg_opa(lv.OPA.COVER, 0)
    section.set_style_bg_color(lv.color_hex(COLOR_CARD), 0)
    section.set_style_border_width(0, 0)
    section.set_style_radius(10, 0)
    section.set_style_pad_all(12, 0)
    section.set_style_pad_row(6, 0)
    section.remove_flag(lv.obj.FLAG.SCROLLABLE)
    section.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    _make_label(section, title, FONT_SMALL, COLOR_MUTED)
    return section


def create_settings_screen(parent, stop_name, transport="All"):
    """Build the settings screen inside ``parent`` (a tile).

    Layout, top to bottom: title, stop section, transport type section and
    connection status section.

    Args:
        parent: LVGL object that will contain the screen.
        stop_name: Name of the currently selected stop.
        transport: Name of the currently selected transport type.

    Returns:
        A dict with the labels that ``update_connection_status`` and later
        phases need to change.
    """
    parent.set_style_bg_opa(lv.OPA.COVER, 0)
    parent.set_style_bg_color(lv.color_hex(COLOR_BG), 0)

    # Root container fills the whole tile and stacks the sections vertically
    root = lv.obj(parent)
    root.set_size(600, 450)
    root.set_style_bg_opa(lv.OPA.TRANSP, 0)
    root.set_style_border_width(0, 0)
    root.set_style_pad_all(8, 0)
    root.set_style_pad_row(10, 0)
    root.remove_flag(lv.obj.FLAG.SCROLLABLE)
    root.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    _make_label(root, "Settings", FONT_BIG, COLOR_TEXT)

    # Section 1: stop (selection is added in phase 5)
    stop_section = _make_section(root, "Stop", 80)
    stop_value = _make_label(stop_section, stop_name, FONT_BIG, COLOR_TEXT)

    # Section 2: transport type (dropdown is added in phase 6)
    transport_section = _make_section(root, "Transport type", 80)
    transport_value = _make_label(transport_section, transport, FONT_BIG, COLOR_TEXT)

    # Section 3: connection status (US4.3)
    status_section = _make_section(root, "Connection status", 120)
    wifi_value = _make_label(
        status_section, "Wi-Fi: Checking...", FONT_BIG, COLOR_MUTED
    )
    data_value = _make_label(
        status_section, "Live data: Waiting...", FONT_BIG, COLOR_MUTED
    )

    return {
        "root": root,
        "stop": stop_value,
        "transport": transport_value,
        "wifi": wifi_value,
        "data": data_value,
    }


def update_connection_status(screen, wifi_connected, data_ok):
    """Show the current Wi-Fi and live data status.

    Args:
        screen: Dict returned by ``create_settings_screen``.
        wifi_connected: True if the device is connected to Wi-Fi.
        data_ok: True if the last departure fetch worked, False if it failed,
            None if no fetch has finished yet.
    """
    if wifi_connected:
        screen["wifi"].set_text("Wi-Fi: Connected")
        screen["wifi"].set_style_text_color(lv.color_hex(COLOR_OK), 0)
    else:
        screen["wifi"].set_text("Wi-Fi: Disconnected")
        screen["wifi"].set_style_text_color(lv.color_hex(COLOR_CANCELED), 0)

    if data_ok is None:
        screen["data"].set_text("Live data: Waiting...")
        screen["data"].set_style_text_color(lv.color_hex(COLOR_DELAYED), 0)
    elif data_ok:
        screen["data"].set_text("Live data: OK")
        screen["data"].set_style_text_color(lv.color_hex(COLOR_OK), 0)
    else:
        screen["data"].set_text("Live data: Error")
        screen["data"].set_style_text_color(lv.color_hex(COLOR_CANCELED), 0)
