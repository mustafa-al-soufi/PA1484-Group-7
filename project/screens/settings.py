"""Settings screen (US3.1): stop, transport type and connection status.

Each setting lives in its own section (a dark blue card). The widgets are
built once by ``create_settings_screen``. The stop section contains the stop
dropdown (US3.2B). Later phases add the transport dropdown (US3.3) and the
save/reset buttons (US3.4, US3.5).
"""

import lvgl as lv

# Share fonts, colors and text cleaning with the departure screen
from screens.departure import (
    COLOR_BG,
    COLOR_CANCELED,
    COLOR_DELAYED,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_TEXT,
    FONT_BIG,
    FONT_SMALL,
    _safe,
)

# Background color of the section cards (dark blue)
COLOR_CARD = 0x1B2A41

# Maximum height of the open stop list in pixels
DROPDOWN_LIST_HEIGHT = 220


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


def _make_stop_dropdown(parent, initial_text, on_stop_changed):
    """Create the dropdown used to select a stop (US3.2B).

    Args:
        parent: Section the dropdown is added to.
        initial_text: Text shown until the list of stops has been loaded.
        on_stop_changed: Function called with the LVGL event when the user
            picks another stop.

    Returns:
        The dropdown object.
    """
    dropdown = lv.dropdown(parent)
    dropdown.set_width(lv.pct(100))
    dropdown.set_options(_safe(initial_text))
    dropdown.set_style_text_font(FONT_BIG, 0)
    dropdown.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
    dropdown.set_style_bg_opa(lv.OPA.COVER, 0)
    dropdown.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
    dropdown.set_style_border_width(1, 0)
    dropdown.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)
    dropdown.add_event_cb(on_stop_changed, lv.EVENT.VALUE_CHANGED, None)

    # Style the list that opens below the dropdown. Not every LVGL build
    # allows this before the list is opened, so a failure is not fatal.
    try:
        stop_list = dropdown.get_list()
        stop_list.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
        stop_list.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
        stop_list.set_style_text_font(FONT_BIG, 0)
        stop_list.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)
        stop_list.set_style_max_height(DROPDOWN_LIST_HEIGHT, 0)
    except Exception:
        pass

    return dropdown


def create_settings_screen(parent, stop_text, on_stop_changed, transport="All"):
    """Build the settings screen inside ``parent`` (a tile).

    Layout, top to bottom: title, stop section, transport type section and
    connection status section.

    Args:
        parent: LVGL object that will contain the screen.
        stop_text: Text shown in the stop dropdown until the stops are loaded.
        on_stop_changed: Function called with the LVGL event when the user
            selects another stop in the dropdown.
        transport: Name of the currently selected transport type.

    Returns:
        A dict with the widgets that ``set_stops``,
        ``update_connection_status`` and later phases need.
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

    # Section 1: stop selection (US3.2B)
    stop_section = _make_section(root, "Stop", 110)
    dropdown = _make_stop_dropdown(stop_section, stop_text, on_stop_changed)

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
        "dropdown": dropdown,
        "transport": transport_value,
        "wifi": wifi_value,
        "data": data_value,
    }


def set_stops(screen, names, selected):
    """Fill the stop dropdown with the selectable stops.

    Changing the options from code does not trigger the change callback.

    Args:
        screen: Dict returned by ``create_settings_screen``.
        names: List of stop names, in the order they should be listed.
        selected: Index in ``names`` of the stop that is currently selected.
    """
    options = "\n".join([_safe(name) for name in names])
    screen["dropdown"].set_options(options)
    screen["dropdown"].set_selected(selected)


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
