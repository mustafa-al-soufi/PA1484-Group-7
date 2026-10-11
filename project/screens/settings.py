"""Settings screen (US3.1): stop, transport type, save/reset and connection status."""

import lvgl as lv

from screens.departure import (
    COLOR_BG,
    COLOR_CANCELED,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_TEXT,
    FONT_BIG,
    FONT_SMALL,
    make_button,
    make_label,
    safe_text,
)

COLOR_CARD = 0x1B2A41
COLOR_SAVE = 0x2E7D32
COLOR_RESET = 0x455A64

# Height of the opened dropdown list in pixels
DROPDOWN_LIST_HEIGHT = 220

# Same order as in the dropdown (US3.3)
TRANSPORT_TYPES = ("All", "Bus", "Train", "Ferry")


def _make_section(parent, title, height):
    """Create a dark card with a small title and return it."""
    card = lv.obj(parent)
    card.set_width(lv.pct(100))
    card.set_height(height)
    card.set_style_bg_opa(lv.OPA.COVER, 0)
    card.set_style_bg_color(lv.color_hex(COLOR_CARD), 0)
    card.set_style_border_width(0, 0)
    card.set_style_radius(10, 0)
    card.set_style_pad_all(10, 0)
    card.set_style_pad_row(6, 0)
    card.remove_flag(lv.obj.FLAG.SCROLLABLE)
    card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    make_label(card, title, 0, FONT_SMALL, COLOR_MUTED)
    return card


def _make_dropdown(parent, options, selected, on_changed):
    """Create a dropdown. ``options`` is text with one option per line.

    ``on_changed`` is called when the user picks another option.
    """
    dropdown = lv.dropdown(parent)
    dropdown.set_width(lv.pct(100))
    dropdown.set_options(options)
    dropdown.set_selected(selected)
    dropdown.set_style_text_font(FONT_BIG, 0)
    dropdown.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
    dropdown.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
    dropdown.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)

    # Style the opened list too. Some LVGL builds lack some of these functions.
    try:
        option_list = dropdown.get_list()
        option_list.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
        option_list.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
        option_list.set_style_text_font(FONT_BIG, 0)
        option_list.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)
        option_list.set_style_max_height(DROPDOWN_LIST_HEIGHT, 0)
    except Exception as error:
        print("Dropdown list style skipped:", error)

    dropdown.add_event_cb(on_changed, lv.EVENT.VALUE_CHANGED, None)
    return dropdown


def _show_status(label, text, ok):
    """Set the text of a label, green if ``ok`` and red if not."""
    label.set_text(text)
    label.set_style_text_color(lv.color_hex(COLOR_OK if ok else COLOR_CANCELED), 0)


def create_settings_screen(
    parent,
    stop_text,
    on_stop_changed,
    on_transport_changed,
    on_save,
    on_reset,
    transport="All",
):
    """Build the screen inside ``parent`` (a tile) and return its widgets.

    ``stop_text`` is shown in the stop dropdown until the stops are loaded.
    The on_... arguments are the functions called when the user changes
    something or presses Save (US3.4) or Reset (US3.5).
    """
    parent.set_style_bg_opa(lv.OPA.COVER, 0)
    parent.set_style_bg_color(lv.color_hex(COLOR_BG), 0)

    root = lv.obj(parent)
    root.set_size(600, 450)
    root.set_style_bg_opa(lv.OPA.TRANSP, 0)
    root.set_style_border_width(0, 0)
    root.set_style_pad_all(8, 0)
    root.set_style_pad_row(8, 0)
    root.remove_flag(lv.obj.FLAG.SCROLLABLE)
    root.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    make_label(root, "Settings", 0, FONT_BIG, COLOR_TEXT)

    # Stop (US3.2B)
    stop_card = _make_section(root, "Stop", 90)
    stop_dropdown = _make_dropdown(stop_card, safe_text(stop_text), 0, on_stop_changed)

    # Transport type (US3.3)
    transport_card = _make_section(root, "Transport type", 90)
    if transport in TRANSPORT_TYPES:
        selected = TRANSPORT_TYPES.index(transport)
    else:
        selected = 0
    transport_dropdown = _make_dropdown(
        transport_card, "\n".join(TRANSPORT_TYPES), selected, on_transport_changed
    )

    # Connection status (US4.3)
    status_card = _make_section(root, "Connection status", 100)
    wifi_label = make_label(status_card, "Wi-Fi: ...", 0, FONT_BIG, COLOR_MUTED)
    data_label = make_label(status_card, "Live data: ...", 0, FONT_BIG, COLOR_MUTED)

    # Save and Reset buttons with a small message next to them
    button_row = lv.obj(root)
    button_row.set_width(lv.pct(100))
    button_row.set_height(52)
    button_row.set_style_bg_opa(lv.OPA.TRANSP, 0)
    button_row.set_style_border_width(0, 0)
    button_row.set_style_pad_all(0, 0)
    button_row.set_style_pad_column(8, 0)
    button_row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    button_row.set_flex_flow(lv.FLEX_FLOW.ROW)
    button_row.set_flex_align(
        lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
    )
    make_button(button_row, "Save as Default", COLOR_SAVE, (190, 44), on_save, 10)
    make_button(button_row, "Reset to Default", COLOR_RESET, (190, 44), on_reset, 10)
    message_label = make_label(button_row, "", 0, FONT_SMALL, COLOR_MUTED)

    return {
        "root": root,
        "stop_dropdown": stop_dropdown,
        "transport_dropdown": transport_dropdown,
        "wifi": wifi_label,
        "data": data_label,
        "message": message_label,
    }


def set_stops(screen, names, selected):
    """Fill the stop dropdown with ``names`` and select position ``selected``."""
    if not names:
        return
    screen["stop_dropdown"].set_options("\n".join(safe_text(name) for name in names))
    screen["stop_dropdown"].set_selected(selected)


def set_selected_stop(screen, index):
    """Select the stop at position ``index`` in the dropdown."""
    screen["stop_dropdown"].set_selected(index)


def set_transport(screen, transport):
    """Select ``transport`` in the transport dropdown."""
    if transport in TRANSPORT_TYPES:
        screen["transport_dropdown"].set_selected(TRANSPORT_TYPES.index(transport))


def show_save_message(screen, text, ok=True):
    """Show a short message next to the buttons. An empty text clears it."""
    _show_status(screen["message"], safe_text(text), ok)


def update_connection_status(screen, wifi_connected, data_ok):
    """Show if Wi-Fi is connected and if the last fetch worked (US4.3)."""
    _show_status(
        screen["wifi"],
        "Wi-Fi: Connected" if wifi_connected else "Wi-Fi: Offline",
        wifi_connected,
    )
    _show_status(
        screen["data"],
        "Live data: OK" if data_ok else "Live data: Error",
        data_ok,
    )
