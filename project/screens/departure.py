"""Departure screen (US1.2B, US4.2): live departures and a refresh button."""

import lvgl as lv

# Number of reusable rows. The list scrolls vertically if it does not fit.
MAX_ROWS = 15

# LVGL's built-in fonts have no å, ä or ö. Set to False for a font with them.
REPLACE_SWEDISH_CHARS = True

FONT_BIG = lv.font_montserrat_20
FONT_SMALL = getattr(lv, "font_montserrat_14", lv.font_montserrat_20)

COLOR_BG = 0x000000
COLOR_TEXT = 0xFFFFFF
COLOR_MUTED = 0x9E9E9E
COLOR_OK = 0x4CAF50
COLOR_DELAYED = 0xFFA000
COLOR_CANCELED = 0xF44336
COLOR_REFRESH = 0x2E5E9E

# Column widths in pixels
COL_TIME = 90
COL_LINE = 70
COL_DEST = 250
COL_STATUS = 150

# Width of the title, which pushes the Refresh button to the right edge
TITLE_WIDTH = 430

STATUS_COLORS = {
    "On time": COLOR_OK,
    "Delayed": COLOR_DELAYED,
    "Canceled": COLOR_CANCELED,
}

# Required by the Trafiklab license (NF3)
ATTRIBUTION = "Data: Trafiklab.se (CC BY 4.0)"

_CHAR_MAP = {"å": "a", "ä": "a", "ö": "o", "Å": "A", "Ä": "A", "Ö": "O"}


def _safe(text):
    """Return ``text`` with å/ä/ö replaced if the font cannot draw them."""
    text = str(text)
    if not REPLACE_SWEDISH_CHARS:
        return text
    result = ""
    for char in text:
        result += _CHAR_MAP.get(char, char)
    return result


def _make_label(parent, text, width, font, color):
    """Create a styled label. A ``width`` of 0 keeps the automatic width."""
    label = lv.label(parent)
    if width:
        label.set_width(width)
    label.set_text(_safe(text))
    label.set_style_text_font(font, 0)
    label.set_style_text_color(lv.color_hex(color), 0)
    return label


def _make_row(parent, height):
    """Create a transparent horizontal row."""
    row = lv.obj(parent)
    row.set_size(580, height)
    row.set_style_bg_opa(lv.OPA.TRANSP, 0)
    row.set_style_border_width(0, 0)
    row.set_style_pad_all(4, 0)
    row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    row.set_flex_flow(lv.FLEX_FLOW.ROW)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    return row


def _make_refresh_button(parent, on_refresh):
    """Create the manual refresh button (US4.2)."""
    # LVGL 9 calls the widget 'button', older bindings call it 'btn'
    button_class = getattr(lv, "button", None) or lv.btn
    button = button_class(parent)
    button.set_size(130, 38)
    button.set_style_bg_color(lv.color_hex(COLOR_REFRESH), 0)
    label = _make_label(button, "Refresh", 0, FONT_BIG, COLOR_TEXT)
    label.center()
    if on_refresh is not None:
        button.add_event_cb(on_refresh, lv.EVENT.CLICKED, None)


def create_departure_screen(parent, on_refresh=None):
    """Build the screen once and return the widgets the updates need.

    Args:
        parent: Tile that will contain the screen.
        on_refresh: CLICKED event callback for the Refresh button.
    """
    parent.set_style_bg_opa(lv.OPA.COVER, 0)
    parent.set_style_bg_color(lv.color_hex(COLOR_BG), 0)

    root = lv.obj(parent)
    root.set_size(600, 450)
    root.set_style_bg_opa(lv.OPA.TRANSP, 0)
    root.set_style_border_width(0, 0)
    root.set_style_pad_all(8, 0)
    root.set_style_pad_row(4, 0)
    root.remove_flag(lv.obj.FLAG.SCROLLABLE)
    root.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    # Title on the left, refresh button on the right
    title_row = _make_row(root, 44)
    _make_label(title_row, "Departures", TITLE_WIDTH, FONT_BIG, COLOR_TEXT)
    _make_refresh_button(title_row, on_refresh)

    header = _make_row(root, 30)
    _make_label(header, "Time", COL_TIME, FONT_SMALL, COLOR_MUTED)
    _make_label(header, "Line", COL_LINE, FONT_SMALL, COLOR_MUTED)
    _make_label(header, "Destination", COL_DEST, FONT_SMALL, COLOR_MUTED)
    _make_label(header, "Status", COL_STATUS, FONT_SMALL, COLOR_MUTED)

    # Vertical scrolling only, so horizontal swipes reach the tileview (US2.1)
    list_box = lv.obj(root)
    list_box.set_width(lv.pct(100))
    list_box.set_flex_grow(1)
    list_box.set_style_bg_opa(lv.OPA.TRANSP, 0)
    list_box.set_style_border_width(0, 0)
    list_box.set_style_pad_all(0, 0)
    list_box.set_style_pad_row(2, 0)
    list_box.set_scroll_dir(lv.DIR.VER)
    list_box.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    # All rows are created once, hidden; update_departures fills them
    rows = []
    for _ in range(MAX_ROWS):
        row = _make_row(list_box, 50)
        rows.append(
            {
                "row": row,
                "time": _make_label(row, "", COL_TIME, FONT_BIG, COLOR_TEXT),
                "line": _make_label(row, "", COL_LINE, FONT_BIG, COLOR_TEXT),
                "dest": _make_label(row, "", COL_DEST, FONT_BIG, COLOR_TEXT),
                "status": _make_label(row, "", COL_STATUS, FONT_BIG, COLOR_TEXT),
            }
        )
        row.add_flag(lv.obj.FLAG.HIDDEN)

    # Message shown instead of the rows (loading, empty list, errors)
    message = _make_label(list_box, "", 0, FONT_BIG, COLOR_MUTED)
    message.set_width(lv.pct(100))
    message.add_flag(lv.obj.FLAG.HIDDEN)

    _make_label(root, ATTRIBUTION, 0, FONT_SMALL, COLOR_MUTED)
    return {"root": root, "list": list_box, "rows": rows, "message": message}


def show_message(screen, text):
    """Hide all departure rows and show ``text`` in their place."""
    for item in screen["rows"]:
        item["row"].add_flag(lv.obj.FLAG.HIDDEN)
    screen["message"].set_text(_safe(text))
    screen["message"].remove_flag(lv.obj.FLAG.HIDDEN)


def update_departures(screen, departures, error=""):
    """Show departures. None means the fetch failed, [] that none are due."""
    if departures is None:
        text = "Could not fetch departures"
        if error:
            text += "\n" + error
        show_message(screen, text)
        return
    if len(departures) == 0:
        show_message(screen, "No departures right now")
        return

    screen["message"].add_flag(lv.obj.FLAG.HIDDEN)
    for index, item in enumerate(screen["rows"]):
        if index >= len(departures):
            item["row"].add_flag(lv.obj.FLAG.HIDDEN)
            continue
        departure = departures[index]
        status = departure.get("status") or ""

        # Truncate long destinations so they stay on one line
        destination = str(departure.get("destination") or "")
        if len(destination) > 16:
            destination = destination[:15] + "."

        item["time"].set_text(_safe(departure.get("time") or "--:--"))
        item["line"].set_text(_safe(departure.get("line") or ""))
        item["dest"].set_text(_safe(destination))
        item["status"].set_text(_safe(status))
        item["status"].set_style_text_color(
            lv.color_hex(STATUS_COLORS.get(status, COLOR_TEXT)), 0
        )
        item["row"].remove_flag(lv.obj.FLAG.HIDDEN)
