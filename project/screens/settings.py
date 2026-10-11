"""Settings screen (US3.1): stop selection, transport type, saving and
connection status.

Like the departure screen, the widgets are created once. Later changes only
update texts and options.
"""

import lvgl as lv

from screens.departure import (
    COLOR_BG,
    COLOR_CANCELED,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_TEXT,
    FONT_BIG,
    FONT_SMALL,
    _safe,
)

# Card background (dark blue) and dropdown list height in pixels
COLOR_CARD = 0x1B2A41
DROPDOWN_LIST_HEIGHT = 220

# Button colors: save is green, reset is blue-grey
COLOR_SAVE = 0x2E7D32
COLOR_RESET = 0x455A64

# Transport types in the order shown in the dropdown (US3.3)
TRANSPORT_TYPES = ("All", "Bus", "Train", "Ferry")


def _make_label(parent, text, font, color):
    """Create a styled label."""
    label = lv.label(parent)
    label.set_text(_safe(text))
    label.set_style_text_font(font, 0)
    label.set_style_text_color(lv.color_hex(color), 0)
    return label


def _make_section(parent, title, height):
    """Create a dark blue card with a small title and return the card."""
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
    _make_label(card, title, FONT_SMALL, COLOR_MUTED)
    return card


def _make_dropdown(parent, options, selected, on_changed):
    """Create a styled dropdown.

    Args:
        parent: Card that contains the dropdown.
        options: Text with one option per line.
        selected: Index of the option shown first.
        on_changed: Function called with the new index when the user picks
            another option.

    Returns:
        The dropdown widget.
    """
    dropdown = lv.dropdown(parent)
    dropdown.set_width(lv.pct(100))
    dropdown.set_options(options)
    dropdown.set_selected(selected)
    dropdown.set_style_text_font(FONT_BIG, 0)
    dropdown.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
    dropdown.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
    dropdown.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)

    # Style the opened list. Wrapped in try/except because some LVGL builds
    # do not expose every style function.
    try:
        option_list = dropdown.get_list()
        option_list.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
        option_list.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
        option_list.set_style_text_font(FONT_BIG, 0)
        option_list.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)
        option_list.set_style_max_height(DROPDOWN_LIST_HEIGHT, 0)
    except Exception as error:
        print("Dropdown list style skipped:", error)

    def handler(event):
        """Forward the selected index to the application."""
        on_changed(dropdown.get_selected())

    dropdown.add_event_cb(handler, lv.EVENT.VALUE_CHANGED, None)
    return dropdown


def _make_button(parent, text, color, on_click):
    """Create a rounded button with a centered label.

    Args:
        parent: Row that contains the button.
        text: Button caption.
        color: Background color of the button.
        on_click: Function called when the button is pressed.
    """
    # LVGL 9 calls the widget 'button', older bindings call it 'btn'
    button_class = getattr(lv, "button", None) or lv.btn
    button = button_class(parent)
    button.set_size(190, 44)
    button.set_style_bg_color(lv.color_hex(color), 0)
    button.set_style_radius(10, 0)

    label = _make_label(button, text, FONT_BIG, COLOR_TEXT)
    label.center()

    button.add_event_cb(on_click, lv.EVENT.CLICKED, None)
    return button


def create_settings_screen(
    parent,
    stop_text,
    on_stop_changed,
    on_transport_changed,
    on_save,
    on_reset,
    transport="All",
):
    """Build the settings screen inside ``parent`` (a tile).

    Args:
        parent: LVGL object that will contain the screen.
        stop_text: Text shown in the stop dropdown until the list is loaded.
        on_stop_changed: Called with the index of the chosen stop.
        on_transport_changed: Called with the index in ``TRANSPORT_TYPES``.
        on_save: Called when 'Save as Default' is pressed (US3.4).
        on_reset: Called when 'Reset to Default' is pressed (US3.5).
        transport: Transport type selected at start.

    Returns:
        A dict with the widgets the update functions need.
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

    _make_label(root, "Settings", FONT_BIG, COLOR_TEXT)

    # Stop selection (US3.2B)
    stop_card = _make_section(root, "Stop", 90)
    stop_dropdown = _make_dropdown(stop_card, _safe(stop_text), 0, on_stop_changed)

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
    wifi_label = _make_label(status_card, "Wi-Fi: ...", FONT_BIG, COLOR_MUTED)
    data_label = _make_label(status_card, "Live data: ...", FONT_BIG, COLOR_MUTED)

    # Save and reset buttons (US3.4, US3.5) with a short feedback text
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
    _make_button(button_row, "Save as Default", COLOR_SAVE, on_save)
    _make_button(button_row, "Reset to Default", COLOR_RESET, on_reset)
    message_label = _make_label(button_row, "", FONT_SMALL, COLOR_MUTED)

    return {
        "root": root,
        "dropdown": stop_dropdown,
        "transport": transport_dropdown,
        "wifi": wifi_label,
        "data": data_label,
        "message": message_label,
    }


def set_stops(screen, names, selected):
    """Fill the stop dropdown with ``names`` and select index ``selected``."""
    if not names:
        return
    screen["dropdown"].set_options("\n".join(_safe(name) for name in names))
    screen["dropdown"].set_selected(selected)


def set_selected_stop(screen, index):
    """Show the stop with position ``index`` as selected in the dropdown."""
    screen["dropdown"].set_selected(index)


def set_transport(screen, transport):
    """Show ``transport`` as selected in the transport dropdown."""
    if transport in TRANSPORT_TYPES:
        screen["transport"].set_selected(TRANSPORT_TYPES.index(transport))


def show_save_message(screen, text, ok=True):
    """Show a short feedback text next to the buttons ('' clears it)."""
    screen["message"].set_text(_safe(text))
    screen["message"].set_style_text_color(
        lv.color_hex(COLOR_OK if ok else COLOR_CANCELED), 0
    )


def update_connection_status(screen, wifi_connected, data_ok):
    """Show whether Wi-Fi is connected and the last data fetch succeeded."""
    screen["wifi"].set_text("Wi-Fi: Connected" if wifi_connected else "Wi-Fi: Offline")
    screen["wifi"].set_style_text_color(
        lv.color_hex(COLOR_OK if wifi_connected else COLOR_CANCELED), 0
    )
    screen["data"].set_text("Live data: OK" if data_ok else "Live data: Error")
    screen["data"].set_style_text_color(
        lv.color_hex(COLOR_OK if data_ok else COLOR_CANCELED), 0
    )
