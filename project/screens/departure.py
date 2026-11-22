"""Departure screen (US1.2B, US4.2): a departure board in pages. Also the UI
helpers all screens share: fonts with å ä ö, safe_text, labels, buttons, rows.
"""

import lvgl as lv

# Pages, no scrolling: 6 rows of 50 px fit. The rows are made once; a new
# page only changes their text.
MAX_ROWS = 6
MAX_PAGES = 2
MAX_DEPARTURES = MAX_ROWS * MAX_PAGES  # also the number fetched
MAX_DESTINATION_CHARS = 16

FONT_BIG = lv.font_montserrat_20
FONT_SMALL = getattr(lv, "font_montserrat_14", lv.font_montserrat_20)

COLOR_BG = 0x000000
COLOR_TEXT = 0xFFFFFF
COLOR_MUTED = 0x9E9E9E
COLOR_OK = 0x4CAF50
COLOR_DELAYED = 0xFFA000
COLOR_CANCELED = 0xF44336
COLOR_PAGE_BUTTON = 0x2E5E9E
STATUS_COLORS = {"On time": COLOR_OK, "Delayed": COLOR_DELAYED, "Canceled": COLOR_CANCELED}

# Column widths in pixels
WIDTH_TIME = 90
WIDTH_LINE = 70
WIDTH_DESTINATION = 250
WIDTH_STATUS = 150
COLUMN_WIDTHS = (WIDTH_TIME, WIDTH_LINE, WIDTH_DESTINATION, WIDTH_STATUS)

PAGE_BUTTON_SIZE = (48, 38)
PAGE_LABEL_WIDTH = 44
ROW_HEIGHT = 50
ROW_GAP = 2
ROW_PAD = 4
FALLBACK_LINE_HEIGHT = 22  # if the font cannot tell

ATTRIBUTION = "Data: Trafiklab.se (CC BY 4.0)"  # the license asks for it (NF3)

# LVGL 9.3 calls it LONG_MODE, older versions LONG. CLIP: no line breaks.
_LONG_MODES = getattr(lv.label, "LONG_MODE", None) or getattr(lv.label, "LONG", None)
LONG_CLIP = getattr(_LONG_MODES, "CLIP", None)
_BUTTON = getattr(lv, "button", None) or lv.btn  # LVGL 9 or 8

# --- Fonts and text ---

# The built-in fonts have ASCII only. These small binfonts add the letters
# below (lv_font_conv 1.5.2, Montserrat-Medium, 4 bpp; 24/4 and 18/3 so Å
# fits), with the built-in font as fallback. zlib + base64 in the code and
# written to the flash at start-up, so the 128 KB image needs no extra file.
FONT_DIR = "/"
REPLACE_SWEDISH_CHARS = True  # until load_swedish_fonts() works
_FONT_LETTERS = "åäöÅÄÖØøÆæ"
_CHAR_MAP = {
    "å": "a", "ä": "a", "ö": "o", "Å": "A", "Ä": "A", "Ö": "O",
    "Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "é": "e", "è": "e", "ë": "e", "ü": "u",
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"',
    "”": '"', " ": " ",
}
_reported = set()  # characters without a glyph, printed once
_SV20 = (
    "eNq9VE1oE0EUfrvp5q9p2GiFHsQm0pMHs5UKKtLtIYIHaeLJg0JSWn/AlMSLWBTMwXMbPIggmNaTBCXBuzQURdFK"
    "crCIVthKvdhWNm3aWptsxvdmsmqhN8FZhm/y9n3f+2b2TTQAuHJxaERCdEAnPg22F+oMoMk6MabihDZZcSJQjoZz"
    "eHQoTev9OF/gPIpvvMimDBn2oEYQQnAQjkAf9GA0mRoeakd04/MA+qX3UkqWHTHHY4e/7WobwGucl5Njl/RQECA+"
    "8JDXTMWmOVKhHcPMcFDYAseO7U2O0SmL47RWiCHIDdBLiN4N8NUQuxdAqSNOpFEBy5gMRxacVj6fL6xCB+V4tiBe"
    "JG4TygOkVUjoIVzI77Jc2qfd24Hy8yzsOv6rxXOHqIrEs7colDNXZmdnE7gKz223HPnW45NipWwrdtAM2sGJjEJ0"
    "/BVegDjSXwG0b0Ar035HlHz+iQhO4N4FHSmgNLHkG6RgkLIrkZD259tFE7kgoR4bD+5yXFLSXKYDGWTfmaVhubvg"
    "mF6Dbjo1j8UrARgxQ+N9Mck4SS/ZaMftPJunsEdcB3Ut0gXpFq8TmWqZeCrAWRMWbmeEBSYseJmwEB4TFt4KC+5V"
    "YUFPCAufhAXPF2EhGuMWfiy1LNSEhZywIC0JC96KKN3VctLbWfUVD6fBX9Ezfx3MeXN5wMXmjQ15ClxNvrsgBAJl"
    "bRyP+HhjJFLWq9hO/avgYMes6zlTS7KXOa13nwqjM9gkpTP4ZTJ+Wp1EMsX+RfdsTxGZmttYChJ701gRCth2CqPL"
    "amBrpjKkdC0QCJdIjca3OireiUQiUVQ1qGf868j6qcINF/tszphW2YIL5gdwG1Ya+rqqrT+BVKyg7uyUE+ZHFYiz"
    "CPGvaF2lS5BL0xb0Zw26QxW+Lop4lOeIfMHtu18lHRfXvUnB+TUuWCPBFAlKiyToyZLgIBecI8HTkyTI1N+CzjoJ"
    "HuDNd4q7+wVaj6U8"
)
_SV14 = (
    "eNqtkT9oE3EUx7+/NEd61vSMsaWFWn4Gl2KHIK2LcEmhg1YXh4JkqAmp16KVaHFRsdZFooPoWjB3luIgEhfRoZBE"
    "cOikDvUvJh7hKLGUDCIdtOnP9xKpq4N3vPfufu/7/fx+9y4KYPpsalJQbUMnDDRUJ7YUoJRBa3so4Bd+jQprohTp"
    "C6mL/NxH8YpimDq7yM0KH/ZiHyQOIILDGMJBWp3JpFMdVNvpPo1nEOKUeCjeCOE76sv4AIdiauaKNb4AcS7BGy7t"
    "xs7VW+V8I8/42S+UNa/PAcJxg7KZFDU+qtqEeG1ZuXiHSw7ZK4FgdTwHhCLsfhz9m8OR/8G+/gPNnooDsYmV7C2g"
    "a8pjWsCbizPvbkCpbYnPmHtkJbFfKe6GLKtCXW0NgY1s9uZl2lyprRR9+NJzNpfGds5m2O8dCHvww3d00ZQLJbNE"
    "ezg5sgfdVm6ttLqspDMZRXKlFxjQnuSckET6VGPS1yYpUSGSyDLJkExKMOlllknvJJPUSSKJF0wKNY8y0i3uXAUW"
    "B5tvur0qu2vLRNdd/UHZi/kHvJzUPdO95unFp95ID4ZHgRWaNtd/cFx6q9ubh4p5kKhSa7BjA3qVpI1yec30BtYj"
    "EZmTQZ557Fj5zNgyIfNMPX4Eqz3z8M8v/hla8QnC9ft1bR2GW6B/eN6lYU842Bbmt34Xv36WcGKIhLMkLchw3SZp"
    "W8YtiFGS3iPpR5LGbve7GknFZBP6Gxzn7QI="
)
_swedish = {}  # id(built-in font) -> Swedish font
_fs_driver = None  # LVGL keeps only a pointer: it must stay alive


def ui_font(font):
    """The Swedish version of a built-in font, or the font itself."""
    return _swedish.get(id(font), font)


def _write_if_changed(path, data):
    """Writing the flash is slow and wears it: only when needed."""
    try:
        with open(path, "rb") as file:
            if file.read() == data:
                return
    except OSError:
        pass  # not written yet
    with open(path, "wb") as file:
        file.write(data)


def _inflate(data):
    try:
        import deflate
        import io
    except ImportError:  # PC tests
        import zlib
        return zlib.decompress(data)
    return deflate.DeflateIO(io.BytesIO(data), deflate.ZLIB).read()


def load_swedish_fonts():
    """Use the Swedish fonts (True), or on any problem the built-in ones."""
    global REPLACE_SWEDISH_CHARS, _fs_driver
    try:
        import binascii
        import fs_driver

        driver = lv.fs_drv_t()
        fs_driver.fs_register(driver, "S")
        loaded = {}
        fonts = (("sv20.bin", _SV20, FONT_BIG), ("sv14.bin", _SV14, FONT_SMALL))
        for name, data, builtin in fonts:
            path = FONT_DIR + name
            _write_if_changed(path, _inflate(binascii.a2b_base64("".join(data))))
            font = lv.binfont_create("S:" + path)
            if not font:
                raise OSError("cannot load " + path)
            font.fallback = builtin
            loaded[id(builtin)] = font
    except Exception as error:
        print("Swedish fonts not used, a/o instead:", repr(error))
        return False
    _fs_driver = driver
    _swedish.update(loaded)
    REPLACE_SWEDISH_CHARS = False
    return True


def _can_draw(char):
    if char < "\x80" or "" <= char <= "":  # ASCII, LVGL symbols
        return True
    return char in _FONT_LETTERS and not REPLACE_SWEDISH_CHARS


def safe_text(text):
    """Text the fonts can draw; a missing glyph would show as a box."""
    text = str(text)
    if len(text) == len(text.encode()):
        return text  # ASCII, the usual case: fast
    kept = []
    for char in text:
        if _can_draw(char):
            kept.append(char)
        elif char in _CHAR_MAP:
            kept.append(_CHAR_MAP[char])
        elif char not in _reported:
            _reported.add(char)
            print("safe_text: no glyph for U+%04X, removed" % ord(char))
    return "".join(kept)


# --- Shared widgets ---

_styles = {}  # shared styles use less RAM than one per widget


def _style(key, setup):
    style = _styles.get(key)
    if style is None:
        style = lv.style_t()
        style.init()
        setup(style)
        _styles[key] = style
    return style


def _label_setup(font, color):
    def setup(style):
        style.set_text_font(font)
        style.set_text_color(lv.color_hex(color))
    return setup


def _row_setup(style):
    style.set_bg_opa(lv.OPA.TRANSP)
    style.set_border_width(0)
    style.set_pad_all(ROW_PAD)


def make_label(parent, text, width, font, color, wrap=False):
    """Width 0 = automatic. Only ``wrap`` labels break lines."""
    label = lv.label(parent)
    if width:
        label.set_width(width)
    if not wrap and LONG_CLIP is not None:
        label.set_long_mode(LONG_CLIP)
    label.set_text(safe_text(text))
    font = ui_font(font)
    label.add_style(_style((id(font), color), _label_setup(font, color)), 0)
    return label


def _set_text(label, text):
    if label.get_text() != text:  # no redraw for the same text
        label.set_text(text)


def _set_hidden(widget, hidden):
    if hidden:
        widget.add_flag(lv.obj.FLAG.HIDDEN)
    else:
        widget.remove_flag(lv.obj.FLAG.HIDDEN)


def make_button(parent, text, color, size, on_click=None, radius=None):
    """A button with a centered text. ``size`` is (width, height)."""
    button = _BUTTON(parent)
    button.set_size(size[0], size[1])
    button.set_style_bg_color(lv.color_hex(color), 0)
    button.set_style_shadow_width(0, 0)  # shadows are slow to draw
    if radius is not None:
        button.set_style_radius(radius, 0)
    make_label(button, text, 0, FONT_BIG, COLOR_TEXT).center()
    if on_click is not None:
        button.add_event_cb(on_click, lv.EVENT.CLICKED, None)
    return button


def setup_page(tile, pad_row):
    """A column of widgets right in the tile: one container less to draw."""
    tile.set_style_pad_all(8, 0)
    tile.set_style_pad_row(pad_row, 0)
    tile.remove_flag(lv.obj.FLAG.SCROLLABLE)
    tile.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
    tile.set_flex_flow(lv.FLEX_FLOW.COLUMN)


def make_row(parent, height):
    """An invisible row laying out its children from left to right."""
    row = lv.obj(parent)
    row.set_size(580, height)
    row.add_style(_style("row", _row_setup), 0)
    row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    row.remove_flag(lv.obj.FLAG.CLICKABLE)  # so a swipe here moves the tileview
    row.set_flex_flow(lv.FLEX_FLOW.ROW)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    return row


def _int_or_default(value, default):
    return value if isinstance(value, int) else default


def line_height(font):
    try:
        return _int_or_default(font.get_line_height(), FALLBACK_LINE_HEIGHT)
    except Exception:
        return FALLBACK_LINE_HEIGHT


# --- The departure screen ---


def _column_x(gap):
    """x of the columns, as in a flex row with padding ROW_PAD and ``gap``."""
    positions = []
    x = ROW_PAD
    for width in COLUMN_WIDTHS:
        positions.append(x)
        x += width + gap
    return positions


def _label_y(index, height):
    """y of the labels in row ``index`` for a line ``height``, centered."""
    inner = ROW_HEIGHT - 2 * ROW_PAD
    return index * (ROW_HEIGHT + ROW_GAP) + ROW_PAD + (inner - height) // 2


def _make_cell(parent, width, x, y):
    label = make_label(parent, "", width, FONT_BIG, COLOR_TEXT)
    label.set_pos(x, y)
    return label


def create_departure_screen(parent):
    """Build the screen in ``parent`` (a tile) and return its widgets."""
    setup_page(parent, 4)

    # The title grows, so the page buttons are at the right edge
    title_row = make_row(parent, 44)
    make_label(title_row, "Departures", 0, FONT_BIG, COLOR_TEXT).set_flex_grow(1)
    screen = {"departures": [], "page": 0}
    screen["up"] = make_button(title_row, lv.SYMBOL.UP, COLOR_PAGE_BUTTON,
                               PAGE_BUTTON_SIZE, lambda _event: change_page(screen, -1))
    screen["page_label"] = make_label(title_row, "", PAGE_LABEL_WIDTH, FONT_BIG, COLOR_TEXT)
    screen["page_label"].set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
    screen["down"] = make_button(title_row, lv.SYMBOL.DOWN, COLOR_PAGE_BUTTON,
                                 PAGE_BUTTON_SIZE, lambda _event: change_page(screen, 1))

    header = make_row(parent, 30)
    for text, width in zip(("Time", "Line", "Destination", "Status"), COLUMN_WIDTHS):
        make_label(header, text, width, FONT_SMALL, COLOR_MUTED)

    list_box = lv.obj(parent)
    list_box.set_width(lv.pct(100))
    list_box.set_flex_grow(1)
    list_box.set_style_bg_opa(lv.OPA.TRANSP, 0)
    list_box.set_style_border_width(0, 0)
    list_box.set_style_pad_all(0, 0)
    list_box.remove_flag(lv.obj.FLAG.SCROLLABLE)
    list_box.remove_flag(lv.obj.FLAG.CLICKABLE)

    # A row is 4 labels placed in the list, no container: every object costs
    # draw time. The header has the row style, so its gap gives the columns.
    column_x = _column_x(_int_or_default(header.get_style_pad_column(0), 0))
    height = line_height(ui_font(FONT_BIG))
    rows = []
    for index in range(MAX_ROWS):
        y = _label_y(index, height)
        row = {"color": None}  # the status color, set only when it changes
        for key, width, x in zip(("time", "line", "dest", "status"), COLUMN_WIDTHS, column_x):
            row[key] = _make_cell(list_box, width, x, y)
        row["labels"] = (row["time"], row["line"], row["dest"], row["status"])
        _set_row_hidden(row, True)
        rows.append(row)

    # Shown instead of the rows: loading, no departures, errors
    message = make_label(list_box, "", 0, FONT_BIG, COLOR_MUTED, wrap=True)
    message.set_width(lv.pct(100))
    message.add_flag(lv.obj.FLAG.HIDDEN)

    make_label(parent, ATTRIBUTION, 0, FONT_SMALL, COLOR_MUTED)
    screen.update({"root": parent, "list": list_box, "rows": rows, "message": message})
    _update_page_controls(screen)
    return screen


def _set_row_hidden(row, hidden):
    for label in row["labels"]:
        _set_hidden(label, hidden)


def show_message(screen, text):
    """Hide the rows and the page buttons and show ``text`` instead."""
    screen["departures"] = []
    screen["page"] = 0
    for row in screen["rows"]:
        _set_row_hidden(row, True)
    _update_page_controls(screen)
    _set_text(screen["message"], safe_text(text))
    screen["message"].remove_flag(lv.obj.FLAG.HIDDEN)


def update_departures(screen, departures, error=""):
    """Show new departures from page 1. None = the fetch failed, [] = none."""
    if departures is None:
        show_message(screen, "Could not fetch departures" + ("\n" + error if error else ""))
        return
    if not departures:
        show_message(screen, "No departures right now")
        return
    screen["message"].add_flag(lv.obj.FLAG.HIDDEN)
    screen["departures"] = list(departures[:MAX_DEPARTURES])
    screen["page"] = 0
    _show_page(screen)


# --- Pages ---


def page_count(count):
    """Pages needed for ``count`` departures, at most MAX_PAGES."""
    return min((count + MAX_ROWS - 1) // MAX_ROWS, MAX_PAGES)


def page_controls(page, pages):
    """(visible, up_enabled, down_enabled). Hidden with one page or none."""
    if pages <= 1:
        return False, False, False
    return True, page > 0, page < pages - 1


def _set_enabled(button, enabled):
    if enabled:
        button.remove_state(lv.STATE.DISABLED)
    else:
        button.add_state(lv.STATE.DISABLED)


def _update_page_controls(screen):
    pages = page_count(len(screen["departures"]))
    visible, up_enabled, down_enabled = page_controls(screen["page"], pages)
    for widget in (screen["up"], screen["page_label"], screen["down"]):
        _set_hidden(widget, not visible)
    _set_enabled(screen["up"], up_enabled)
    _set_enabled(screen["down"], down_enabled)
    if visible:
        _set_text(screen["page_label"], "%d/%d" % (screen["page"] + 1, pages))


def _show_page(screen):
    """Put the current page into the existing rows. Only texts change."""
    first = screen["page"] * MAX_ROWS
    on_page = screen["departures"][first:first + MAX_ROWS]
    for index, row in enumerate(screen["rows"]):
        if index >= len(on_page):
            _set_row_hidden(row, True)
            continue
        departure = on_page[index]
        status = departure.get("status") or ""
        destination = str(departure.get("destination") or "")
        if len(destination) > MAX_DESTINATION_CHARS:
            destination = destination[: MAX_DESTINATION_CHARS - 1] + "."
        _set_text(row["time"], safe_text(departure.get("time") or "--:--"))
        _set_text(row["line"], safe_text(departure.get("line") or ""))
        _set_text(row["dest"], safe_text(destination))
        _set_text(row["status"], safe_text(status))
        color = STATUS_COLORS.get(status, COLOR_TEXT)
        if row["color"] != color:
            row["status"].set_style_text_color(lv.color_hex(color), 0)
            row["color"] = color
        _set_row_hidden(row, False)
    _update_page_controls(screen)


def change_page(screen, step):
    """Go ``step`` pages forward (1) or back (-1). True if the page changed."""
    page = screen["page"] + step
    if page < 0 or page >= page_count(len(screen["departures"])):
        return False
    screen["page"] = page
    _show_page(screen)
    return True
