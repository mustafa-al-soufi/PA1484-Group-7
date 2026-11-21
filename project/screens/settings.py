"""Settings screen (US3.1): stop and stop search, transport type, save/reset,
connection. It also saves and loads the defaults (US3.4, US3.5).
"""

import json

import lvgl as lv

from screens.departure import (
    COLOR_BG, COLOR_CANCELED, COLOR_MUTED, COLOR_OK, COLOR_TEXT, FONT_BIG,
    FONT_SMALL, _line_height, _make_row, _set_hidden, make_button, make_label,
    safe_text, setup_page, ui_font,
)

# Same order as in the dropdown (US3.3)
TRANSPORT_TYPES = ("All", "Bus", "Train", "Ferry")

# ---------------------------------------------------------------------------
# Saved defaults (US3.4, US3.5). Stored as JSON in the flash, so they survive
# a restart. A missing or broken file is not an error: the defaults are used.
# ---------------------------------------------------------------------------

SETTINGS_FILE = "settings.json"
VALID_TRANSPORTS = TRANSPORT_TYPES
DEFAULTS = {"stop_id": None, "stop_name": "", "transport": "All"}  # None = first stop


def defaults():
    return dict(DEFAULTS)


def _clean(data):
    """Valid settings from ``data``: unknown keys dropped, bad values = defaults."""
    settings = defaults()
    if not isinstance(data, dict):
        return settings
    if data.get("stop_id") is not None:
        settings["stop_id"] = str(data["stop_id"])
        settings["stop_name"] = str(data.get("stop_name") or "")
    if data.get("transport") in VALID_TRANSPORTS:
        settings["transport"] = data["transport"]
    return settings


def load():
    """The saved settings, or the defaults if there are none."""
    try:
        with open(SETTINGS_FILE) as file:
            return _clean(json.load(file))
    except OSError:
        return defaults()  # nothing saved yet
    except ValueError:
        print("Settings file is damaged, using defaults")
        return defaults()


def save(settings):
    """Save ``settings`` as the new defaults. True if it worked."""
    try:
        with open(SETTINGS_FILE, "w") as file:
            json.dump(_clean(settings), file)
        return True
    except Exception as error:
        print("Could not save settings:", error)
        return False


# ---------------------------------------------------------------------------
# The screen
# ---------------------------------------------------------------------------

COLOR_CARD = 0x1B2A41
COLOR_SAVE = 0x2E7D32
COLOR_RESET = 0x455A64
COLOR_SEARCH = 0x2E5E9E
DROPDOWN_LIST_HEIGHT = 220  # height of an opened dropdown list
# Fixed heights, so a card is title + one row of these: 10 + 18 + 6 + 38 + 10
CONTROL_HEIGHT = 38  # dropdowns, the search field and its button
CARD_HEIGHT = 82
STOP_TEXT_CHARS = 24  # longer names are cut with "..." in the closed stop dropdown

# On-screen keyboard keys with å ä ö (US3.2C). Module level: they must stay alive.
_LOWER = ["1#", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "å", lv.SYMBOL.BACKSPACE, "\n",
          "ABC", "a", "s", "d", "f", "g", "h", "j", "k", "l", "ö", "ä", lv.SYMBOL.NEW_LINE, "\n",
          "_", "-", "z", "x", "c", "v", "b", "n", "m", ".", ",", ":", "\n",
          lv.SYMBOL.KEYBOARD, lv.SYMBOL.LEFT, " ", lv.SYMBOL.RIGHT, lv.SYMBOL.OK, ""]
_UPPER = [{"å": "Å", "ä": "Ä", "ö": "Ö", "ABC": "abc"}.get(k, k.upper() if isinstance(k, str) and k.isalpha() else k)
          for k in _LOWER]
_WIDE = ("1#", "ABC", "abc", lv.SYMBOL.BACKSPACE, lv.SYMBOL.NEW_LINE)
_CTRL = [10 if k == " " else 6 if k in _WIDE else 4 for k in _LOWER if k not in ("\n", "")]


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


def _dark(widget, font):
    """The dark look of the dropdowns and the search field."""
    widget.set_style_text_font(ui_font(font), 0)
    widget.set_style_pad_ver(max(0, (CONTROL_HEIGHT - _line_height(ui_font(font)) - 4) // 2), 0)
    widget.set_style_text_color(lv.color_hex(COLOR_TEXT), 0)
    widget.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
    widget.set_style_border_color(lv.color_hex(COLOR_MUTED), 0)


def _make_dropdown(parent, options, selected, on_changed, font=FONT_BIG):
    """Create a dropdown (one option per line) that calls ``on_changed``."""
    dropdown = lv.dropdown(parent)
    dropdown.set_size(lv.pct(100), CONTROL_HEIGHT)
    dropdown.set_options(options)
    dropdown.set_selected(selected)
    _dark(dropdown, font)
    try:  # the opened list; some LVGL builds lack some of these
        option_list = dropdown.get_list()
        _dark(option_list, font)
        option_list.set_style_pad_ver(4, 0)
        option_list.set_style_max_height(DROPDOWN_LIST_HEIGHT, 0)
    except Exception as error:
        print("Dropdown list style skipped:", error)
    dropdown.add_event_cb(on_changed, lv.EVENT.VALUE_CHANGED, None)
    return dropdown


def _make_stop_search(row, on_search):
    """Search field, Search button and keyboard for any stop (US3.2C).

    ``on_search(text)`` is called on Search or on Enter of the keyboard.
    """
    field = lv.textarea(row)
    field.set_one_line(True)
    field.set_placeholder_text("Search for a stop")
    field.set_size(190, CONTROL_HEIGHT)
    _dark(field, FONT_SMALL)
    keyboard = lv.keyboard(lv.layer_top())
    keyboard.set_textarea(field)
    keyboard.set_style_text_font(ui_font(FONT_SMALL), 0)
    keyboard.add_flag(lv.obj.FLAG.HIDDEN)
    try:
        for mode, keys in ((lv.keyboard.MODE.TEXT_LOWER, _LOWER), (lv.keyboard.MODE.TEXT_UPPER, _UPPER)):
            keyboard.set_map(mode, keys, _CTRL)
    except Exception as error:
        print("Keyboard without å ä ö:", error)

    def search(_event):
        _set_hidden(keyboard, True)
        if on_search is not None:
            on_search(field.get_text())

    field.add_event_cb(lambda _e: _set_hidden(keyboard, False), lv.EVENT.CLICKED, None)
    keyboard.add_event_cb(search, lv.EVENT.READY, None)
    keyboard.add_event_cb(lambda _e: _set_hidden(keyboard, True), lv.EVENT.CANCEL, None)
    make_button(row, "Search", COLOR_SEARCH, (100, CONTROL_HEIGHT), search, 10)
    return field, keyboard


def _show_stop(screen):
    """The closed stop dropdown shows the selected name, cut so it never
    reaches the arrow. The opened list keeps the full names."""
    names, index = screen["stop_names"], screen["stop_dropdown"].get_selected()
    if index < len(names):
        name = names[index]
        if len(name) > STOP_TEXT_CHARS:
            name = name[: STOP_TEXT_CHARS - 3] + "..."
        screen["stop_text"] = name  # LVGL keeps only a pointer: keep it alive
        screen["stop_dropdown"].set_text(name)


def _show_status(label, text, ok):
    """Set the text green (ok) or red. Nothing is redrawn if it is the same."""
    if label.get_text() == text:
        return
    label.set_text(text)
    label.set_style_text_color(lv.color_hex(COLOR_OK if ok else COLOR_CANCELED), 0)


def create_settings_screen(parent, stop_text, on_stop_changed, on_transport_changed,
                           on_save, on_reset, transport="All", on_search=None):
    """Build the screen in ``parent`` (a tile) and return its widgets.

    ``stop_text`` is shown until the stops are set. The on_... functions are
    called on a change, on Save (US3.4), Reset (US3.5) and a stop search (US3.2C).
    """
    setup_page(parent, 8)
    make_label(parent, "Settings", 0, FONT_BIG, COLOR_TEXT)

    # Stop (US3.2B), with the stop search next to it (US3.2C)
    stop_row = _make_row(_make_section(parent, "Stop", CARD_HEIGHT), CONTROL_HEIGHT)
    stop_row.set_width(lv.pct(100))
    stop_row.set_style_pad_all(0, 0)
    stop_dropdown = _make_dropdown(stop_row, safe_text(stop_text), 0, on_stop_changed, FONT_SMALL)
    stop_dropdown.set_width(250)
    search, keyboard = _make_stop_search(stop_row, on_search)

    transport_card = _make_section(parent, "Transport type", CARD_HEIGHT)  # US3.3
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

    screen = {"root": parent, "stop_dropdown": stop_dropdown, "search": search,
              "keyboard": keyboard, "transport_dropdown": transport_dropdown,
              "wifi": wifi_label, "data": data_label, "message": message, "stop_names": []}
    stop_dropdown.add_event_cb(lambda _e: _show_stop(screen), lv.EVENT.VALUE_CHANGED, None)
    return screen


def set_stops(screen, names, selected):
    """Fill the stop dropdown with ``names`` and select ``selected``."""
    if names:
        screen["stop_names"] = [safe_text(n) for n in names]
        screen["stop_dropdown"].set_options("\n".join(screen["stop_names"]))
        screen["stop_dropdown"].set_selected(selected)
        _show_stop(screen)


def set_selected_stop(screen, index):
    screen["stop_dropdown"].set_selected(index)
    _show_stop(screen)


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