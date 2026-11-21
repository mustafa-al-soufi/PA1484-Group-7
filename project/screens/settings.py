"""Settings screen (US3.1): stop, transport type, save/reset, connection."""

import lvgl as lv

from screens.departure import (
    COLOR_BG, COLOR_CANCELED, COLOR_MUTED, COLOR_OK, COLOR_TEXT, FONT_BIG,
    FONT_SMALL, make_button, make_label, safe_text, setup_page, ui_font,
)

COLOR_CARD = 0x1B2A41
COLOR_SAVE = 0x2E7D32
COLOR_RESET = 0x455A64
DROPDOWN_LIST_HEIGHT = 220  # height of an opened dropdown list

# Same order as in the dropdown (US3.3)
TRANSPORT_TYPES = ("All", "Bus", "Train", "Ferry")


def _make_section(parent, title, height):
    """Create a dark card with a small title."""
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
    card.remove_flag(lv.obj.FLAG.CLICKABLE)  # swipes go to the tileview
    card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    make_label(card, title, 0, FONT_SMALL, COLOR_MUTED)
    return card


def _make_dropdown(parent, options, selected, on_changed):
    """Create a dropdown (one option per line) that calls ``on_changed``."""
    dropdown = lv.dropdown(parent)
    dropdown.set_width(lv.pct(100))
    dropdown.set_options(options)
    dropdown.set_selected(selected)
    dropdown.set_style_text_font(ui_font(FONT_BIG), 0)
    dropdown.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
    dropdown.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
    dropdown.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)
    try:  # the opened list; some LVGL builds lack some of these
        option_list = dropdown.get_list()
        option_list.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
        option_list.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
        option_list.set_style_text_font(ui_font(FONT_BIG), 0)
        option_list.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)
        option_list.set_style_max_height(DROPDOWN_LIST_HEIGHT, 0)
    except Exception as error:
        print("Dropdown list style skipped:", error)
    dropdown.add_event_cb(on_changed, lv.EVENT.VALUE_CHANGED, None)
    return dropdown


def _show_status(label, text, ok):
    """Set the text green (ok) or red. Nothing is redrawn if it is the same."""
    if label.get_text() == text:
        return
    label.set_text(text)
    label.set_style_text_color(lv.color_hex(COLOR_OK if ok else COLOR_CANCELED), 0)


def create_settings_screen(parent, stop_text, on_stop_changed, on_transport_changed,
                           on_save, on_reset, transport="All"):
    """Build the screen in ``parent`` (a tile) and return its widgets.

    ``stop_text`` is shown until the stops are set. The on_... functions are
    called on a change and on Save (US3.4) and Reset (US3.5).
    """
    setup_page(parent, 8)
    make_label(parent, "Settings", 0, FONT_BIG, COLOR_TEXT)

    stop_card = _make_section(parent, "Stop", 90)  # US3.2B
    stop_dropdown = _make_dropdown(stop_card, safe_text(stop_text), 0, on_stop_changed)

    transport_card = _make_section(parent, "Transport type", 90)  # US3.3
    selected = TRANSPORT_TYPES.index(transport) if transport in TRANSPORT_TYPES else 0
    transport_dropdown = _make_dropdown(
        transport_card, "\n".join(TRANSPORT_TYPES), selected, on_transport_changed
    )

    status_card = _make_section(parent, "Connection status", 100)  # US4.3
    wifi_label = make_label(status_card, "Wi-Fi: ...", 0, FONT_BIG, COLOR_MUTED)
    data_label = make_label(status_card, "Live data: ...", 0, FONT_BIG, COLOR_MUTED)

    # Save and Reset with a short message next to them
    button_row = lv.obj(parent)
    button_row.set_width(lv.pct(100))
    button_row.set_height(52)
    button_row.set_style_bg_opa(lv.OPA.TRANSP, 0)
    button_row.set_style_border_width(0, 0)
    button_row.set_style_pad_all(0, 0)
    button_row.set_style_pad_column(8, 0)
    button_row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    button_row.remove_flag(lv.obj.FLAG.CLICKABLE)
    button_row.set_flex_flow(lv.FLEX_FLOW.ROW)
    button_row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    make_button(button_row, "Save as Default", COLOR_SAVE, (190, 44), on_save, 10)
    make_button(button_row, "Reset to Default", COLOR_RESET, (190, 44), on_reset, 10)
    message = make_label(button_row, "", 0, FONT_SMALL, COLOR_MUTED, wrap=True)

    return {"root": parent, "stop_dropdown": stop_dropdown,
            "transport_dropdown": transport_dropdown, "wifi": wifi_label,
            "data": data_label, "message": message}


def set_stops(screen, names, selected):
    """Fill the stop dropdown with ``names`` and select ``selected``."""
    if names:
        screen["stop_dropdown"].set_options("\n".join(safe_text(n) for n in names))
        screen["stop_dropdown"].set_selected(selected)


def set_selected_stop(screen, index):
    screen["stop_dropdown"].set_selected(index)


def set_transport(screen, transport):
    if transport in TRANSPORT_TYPES:
        screen["transport_dropdown"].set_selected(TRANSPORT_TYPES.index(transport))


def show_save_message(screen, text, ok=True):
    """Show a short message next to the buttons ("" clears it)."""
    _show_status(screen["message"], safe_text(text), ok)


def update_connection_status(screen, wifi_connected, data_ok):
    """Show if Wi-Fi is connected and if the last fetch worked (US4.3)."""
    _show_status(screen["wifi"], "Wi-Fi: Connected" if wifi_connected else "Wi-Fi: Offline",
                 wifi_connected)
    _show_status(screen["data"], "Live data: OK" if data_ok else "Live data: Error", data_ok)
