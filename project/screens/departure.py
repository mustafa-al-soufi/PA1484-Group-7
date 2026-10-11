"""Departure screen (US1.2B, US4.2): the departure list and a Refresh button."""

import lvgl as lv

# Rows are created once and reused. The list scrolls if they do not fit.
MAX_ROWS = 15

# Longest destination text before it is cut off
MAX_DESTINATION_CHARS = 16

# The built-in fonts have no å, ä or ö. Set to False if you use another font.
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

# The wide title pushes the Refresh button to the right edge
TITLE_WIDTH = 430

STATUS_COLORS = {
    "On time": COLOR_OK,
    "Delayed": COLOR_DELAYED,
    "Canceled": COLOR_CANCELED,
}

# Required by the Trafiklab license (NF3)
ATTRIBUTION = "Data: Trafiklab.se (CC BY 4.0)"

_CHAR_MAP = {"å": "a", "ä": "a", "ö": "o", "Å": "A", "Ä": "A", "Ö": "O"}


def safe_text(text):
    """Replace å, ä and ö if the font cannot draw them."""
    text = str(text)
    if not REPLACE_SWEDISH_CHARS:
        return text
    result = ""
    for char in text:
        result += _CHAR_MAP.get(char, char)
    return result


def make_label(parent, text, width, font, color):
    """Create a label. Width 0 means the width is set automatically."""
    label = lv.label(parent)
    if width:
        label.set_width(width)
    label.set_text(safe_text(text))
    label.set_style_text_font(font, 0)
    label.set_style_text_color(lv.color_hex(color), 0)
    return label


def make_button(parent, text, color, size, on_click=None, radius=None):
    """Create a button with a centered text. ``size`` is (width, height)."""
    # LVGL 9 calls it "button", older versions call it "btn"
    button_class = getattr(lv, "button", None) or lv.btn
    button = button_class(parent)
    button.set_size(size[0], size[1])
    button.set_style_bg_color(lv.color_hex(color), 0)
    if radius is not None:
        button.set_style_radius(radius, 0)

    label = make_label(button, text, 0, FONT_BIG, COLOR_TEXT)
    label.center()

    if on_click is not None:
        button.add_event_cb(on_click, lv.EVENT.CLICKED, None)
    return button


def _make_row(parent, height):
    """Create an empty row that lays out its children from left to right."""
    row = lv.obj(parent)
    row.set_size(580, height)
    row.set_style_bg_opa(lv.OPA.TRANSP, 0)
    row.set_style_border_width(0, 0)
    row.set_style_pad_all(4, 0)
    row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    row.set_flex_flow(lv.FLEX_FLOW.ROW)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    return row


def create_departure_screen(parent, on_refresh=None):
    """Build the screen inside ``parent`` (a tile) and return its widgets.

    ``on_refresh`` is called when the Refresh button is pressed (US4.2).
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

    # Title on the left, Refresh button on the right
    title_row = _make_row(root, 44)
    make_label(title_row, "Departures", TITLE_WIDTH, FONT_BIG, COLOR_TEXT)
    make_button(title_row, "Refresh", COLOR_REFRESH, (130, 38), on_refresh)

    header = _make_row(root, 30)
    make_label(header, "Time", COL_TIME, FONT_SMALL, COLOR_MUTED)
    make_label(header, "Line", COL_LINE, FONT_SMALL, COLOR_MUTED)
    make_label(header, "Destination", COL_DEST, FONT_SMALL, COLOR_MUTED)
    make_label(header, "Status", COL_STATUS, FONT_SMALL, COLOR_MUTED)

    # Only vertical scrolling, so sideways swipes reach the tileview (US2.1)
    list_box = lv.obj(root)
    list_box.set_width(lv.pct(100))
    list_box.set_flex_grow(1)
    list_box.set_style_bg_opa(lv.OPA.TRANSP, 0)
    list_box.set_style_border_width(0, 0)
    list_box.set_style_pad_all(0, 0)
    list_box.set_style_pad_row(2, 0)
    list_box.set_scroll_dir(lv.DIR.VER)
    list_box.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    # Create all rows now and hide them. update_departures fills them later.
    rows = []
    for _ in range(MAX_ROWS):
        row = _make_row(list_box, 50)
        rows.append(
            {
                "row": row,
                "time": make_label(row, "", COL_TIME, FONT_BIG, COLOR_TEXT),
                "line": make_label(row, "", COL_LINE, FONT_BIG, COLOR_TEXT),
                "dest": make_label(row, "", COL_DEST, FONT_BIG, COLOR_TEXT),
                "status": make_label(row, "", COL_STATUS, FONT_BIG, COLOR_TEXT),
            }
        )
        row.add_flag(lv.obj.FLAG.HIDDEN)

    # Text shown instead of the rows (loading, no departures, errors)
    message = make_label(list_box, "", 0, FONT_BIG, COLOR_MUTED)
    message.set_width(lv.pct(100))
    message.add_flag(lv.obj.FLAG.HIDDEN)

    make_label(root, ATTRIBUTION, 0, FONT_SMALL, COLOR_MUTED)
    return {"root": root, "list": list_box, "rows": rows, "message": message}


def show_message(screen, text):
    """Hide the departure rows and show ``text`` instead."""
    for item in screen["rows"]:
        item["row"].add_flag(lv.obj.FLAG.HIDDEN)
    screen["message"].set_text(safe_text(text))
    screen["message"].remove_flag(lv.obj.FLAG.HIDDEN)


def update_departures(screen, departures, error=""):
    """Show the departures. None means the fetch failed, [] means none left."""
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

        # Cut long destinations so they fit on one line
        destination = str(departure.get("destination") or "")
        if len(destination) > MAX_DESTINATION_CHARS:
            destination = destination[: MAX_DESTINATION_CHARS - 1] + "."

        item["time"].set_text(safe_text(departure.get("time") or "--:--"))
        item["line"].set_text(safe_text(departure.get("line") or ""))
        item["dest"].set_text(safe_text(destination))
        item["status"].set_text(safe_text(status))
        item["status"].set_style_text_color(
            lv.color_hex(STATUS_COLORS.get(status, COLOR_TEXT)), 0
        )
        item["row"].remove_flag(lv.obj.FLAG.HIDDEN)
