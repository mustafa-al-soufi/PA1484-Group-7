"""Departure screen (US1.2B, US4.2): a paged departure board and Refresh."""

import lvgl as lv

# Pages, no scrolling: 6 rows of 50 px fit. Rows are made once, a page
# change only changes their text.
MAX_ROWS = 6
MAX_PAGES = 2
MAX_DEPARTURES = MAX_ROWS * MAX_PAGES  # kept, and so fetched

MAX_DESTINATION_CHARS = 16  # longer destinations are cut

# å ä ö Ø ø Æ æ become ASCII, unless load_swedish_fonts() works
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

PAGE_BUTTON_SIZE = (48, 38)
PAGE_LABEL_WIDTH = 44

# A departure row: height, space between rows, padding inside
ROW_HEIGHT = 50
ROW_GAP = 2
ROW_PAD = 4
FALLBACK_LINE_HEIGHT = 22  # if the font cannot tell

# CLIP: LVGL does not break the text into lines (9.3: LONG_MODE, older: LONG)
_LONG_MODES = getattr(lv.label, "LONG_MODE", None) or getattr(lv.label, "LONG", None)
LONG_CLIP = getattr(_LONG_MODES, "CLIP", None)

STATUS_COLORS = {"On time": COLOR_OK, "Delayed": COLOR_DELAYED, "Canceled": COLOR_CANCELED}

ATTRIBUTION = "Data: Trafiklab.se (CC BY 4.0)"  # license (NF3)

# Built-in fonts: ASCII and LVGL symbols only; safe_text maps the rest
_FONT_LETTERS = "åäöÅÄÖØøÆæ"  # in the small fonts: kept when they are loaded
_CHAR_MAP = {
    "å": "a", "ä": "a", "ö": "o", "Å": "A", "Ä": "A", "Ö": "O",
    "Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "é": "e", "è": "e", "ë": "e", "ü": "u",
    "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"',
    "\u201d": '"', "\u00a0": " ",
}
_reported = set()  # characters without a glyph, printed once


# Binfonts with only å ä ö Å Ä Ö Ø ø Æ æ (lv_font_conv 1.5.2, Montserrat-Medium,
# 4 bpp, 24/4 and 18/3 so Å fits), the built-in font as fallback. zlib +
# base64, written to the flash at start-up: no blocks in the 128 KB image.
FONT_DIR = "/"
_SV20 = (
    "eNq9VE1oE0EUfrvp5q9p2GiFHsQm0pMHs5UKKtLtIYIHaeLJg0JSWn/AlMSLWBTMwXMbPIggmNaTBCXBuzQURdFKcrCIVthKvdhWNm3aWptsxvdmsmqhN8FZhm/y9n3f+2b2TTQAuHJxaERCdEAnPg22F+oMoMk6MabihDZZcSJQjoZzeHQoTev9OF/gPIpvvMimDBn2oEYQQnAQjkAf9GA0mRoeakd04/MA+qX3UkqWHTHHY4e/7WobwGucl5Njl/RQECA+8JDXTMWmOVKhHcPM"
    "cFDYAseO7U2O0SmL47RWiCHIDdBLiN4N8NUQuxdAqSNOpFEBy5gMRxacVj6fL6xCB+V4tiBeJG4TygOkVUjoIVzI77Jc2qfd24Hy8yzsOv6rxXOHqIrEs7colDNXZmdnE7gKz223HPnW45NipWwrdtAM2sGJjEJ0/BVegDjSXwG0b0Ar035HlHz+iQhO4N4FHSmgNLHkG6RgkLIrkZD259tFE7kgoR4bD+5yXFLSXKYDGWTfmaVhubvgmF6Dbjo1j8UrARgxQ+N9Mck4SS/ZaMft"
    "PJunsEdcB3Ut0gXpFq8TmWqZeCrAWRMWbmeEBSYseJmwEB4TFt4KC+5VYUFPCAufhAXPF2EhGuMWfiy1LNSEhZywIC0JC96KKN3VctLbWfUVD6fBX9Ezfx3MeXN5wMXmjQ15ClxNvrsgBAJlbRyP+HhjJFLWq9hO/avgYMes6zlTS7KXOa13nwqjM9gkpTP4ZTJ+Wp1EMsX+RfdsTxGZmttYChJ701gRCth2CqPLamBrpjKkdC0QCJdIjca3OireiUQiUVQ1qGf868j6qcINF/ts"
    "zphW2YIL5gdwG1Ya+rqqrT+BVKyg7uyUE+ZHFYizCPGvaF2lS5BL0xb0Zw26QxW+Lop4lOeIfMHtu18lHRfXvUnB+TUuWCPBFAlKiyToyZLgIBecI8HTkyTI1N+CzjoJHuDNd4q7+wVaj6U8"
)
_SV14 = (
    "eNqtkT9oE3EUx7+/NEd61vSMsaWFWn4Gl2KHIK2LcEmhg1YXh4JkqAmp16KVaHFRsdZFooPoWjB3luIgEhfRoZBEcOikDvUvJh7hKLGUDCIdtOnP9xKpq4N3vPfufu/7/fx+9y4KYPpsalJQbUMnDDRUJ7YUoJRBa3so4Bd+jQprohTpC6mL/NxH8YpimDq7yM0KH/ZiHyQOIILDGMJBWp3JpFMdVNvpPo1nEOKUeCjeCOE76sv4AIdiauaKNb4AcS7BGy7txs7VW+V8I8/42S+U"
    "Na/PAcJxg7KZFDU+qtqEeG1ZuXiHSw7ZK4FgdTwHhCLsfhz9m8OR/8G+/gPNnooDsYmV7C2ga8pjWsCbizPvbkCpbYnPmHtkJbFfKe6GLKtCXW0NgY1s9uZl2lyprRR9+NJzNpfGds5m2O8dCHvww3d00ZQLJbNEezg5sgfdVm6ttLqspDMZRXKlFxjQnuSckET6VGPS1yYpUSGSyDLJkExKMOlllknvJJPUSSKJF0wKNY8y0i3uXAUWB5tvur0qu2vLRNdd/UHZi/kHvJzUPdO9"
    "5unFp95ID4ZHgRWaNtd/cFx6q9ubh4p5kKhSa7BjA3qVpI1yec30BtYjEZmTQZ557Fj5zNgyIfNMPX4Eqz3z8M8v/hla8QnC9ft1bR2GW6B/eN6lYU842Bbmt34Xv36WcGKIhLMkLchw3SZpW8YtiFGS3iPpR5LGbve7GknFZBP6Gxzn7QI="
)
_swedish = {}  # id(built-in font) -> Swedish font
_fs_driver = None  # must stay alive


def ui_font(font):
    """The Swedish version of a built-in font, or the font itself."""
    return _swedish.get(id(font), font)


def _write_if_changed(path, data):
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
        for name, data, builtin in (("sv20.bin", _SV20, FONT_BIG), ("sv14.bin", _SV14, FONT_SMALL)):
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


def safe_text(text):
    """Text the fonts can draw: the letters of the small fonts stay when they
    are loaded, else ASCII. Other characters are removed (printed once)."""
    text = str(text)
    if len(text) == len(text.encode()):
        return text  # plain ASCII (1 byte a character), the usual case: fast
    out = []
    for char in text:
        if char < "\x80" or "\uf000" <= char <= "\uf8ff" or (
                char in _FONT_LETTERS and not REPLACE_SWEDISH_CHARS):
            out.append(char)
        elif char in _CHAR_MAP:
            out.append(_CHAR_MAP[char])
        elif char not in _reported:
            _reported.add(char)
            print("safe_text: no glyph for U+%04X, removed" % ord(char))
    return "".join(out)


# Shared styles (less memory than local ones); kept alive here
_styles = {}


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
    """Create a label. Width 0 = automatic. Only ``wrap`` labels break lines."""
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
    """Change the text only if it is new (no redraw for nothing)."""
    if label.get_text() != text:
        label.set_text(text)


def make_button(parent, text, color, size, on_click=None, radius=None):
    """Create a button with a centered text. ``size`` is (width, height)."""
    button = (getattr(lv, "button", None) or lv.btn)(parent)  # LVGL 9 / 8
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
    """Lay out a tile as a page: padding 8, a column of widgets, no scrolling.
    The tile holds the widgets: no extra transparent container to draw."""
    tile.set_style_pad_all(8, 0)
    tile.set_style_pad_row(pad_row, 0)
    tile.remove_flag(lv.obj.FLAG.SCROLLABLE)
    tile.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
    tile.set_flex_flow(lv.FLEX_FLOW.COLUMN)


def _make_row(parent, height):
    """An invisible row laying out its children from left to right."""
    row = lv.obj(parent)
    row.set_size(580, height)
    row.add_style(_style("row", _row_setup), 0)
    row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    row.remove_flag(lv.obj.FLAG.CLICKABLE)  # a finger here moves the tileview
    row.set_flex_flow(lv.FLEX_FLOW.ROW)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    return row


def _int_or(value, default):
    return value if isinstance(value, int) else default


def _column_x(gap):
    """x of the 4 columns, as a flex row with padding ROW_PAD and ``gap`` gives."""
    positions = []
    x = ROW_PAD
    for width in (COL_TIME, COL_LINE, COL_DEST, COL_STATUS):
        positions.append(x)
        x += width + gap
    return positions


def _label_y(index, line_height):
    """y of the labels in row ``index``, centered in the row."""
    inner = ROW_HEIGHT - 2 * ROW_PAD
    return index * (ROW_HEIGHT + ROW_GAP) + ROW_PAD + (inner - line_height) // 2


def _line_height(font):
    try:
        return _int_or(font.get_line_height(), FALLBACK_LINE_HEIGHT)
    except Exception:
        return FALLBACK_LINE_HEIGHT


def _make_cell(parent, width, x, y):
    label = make_label(parent, "", width, FONT_BIG, COLOR_TEXT)
    label.set_pos(x, y)
    return label


def create_departure_screen(parent, on_refresh=None):
    """Build the screen in ``parent`` (a tile). Refresh calls ``on_refresh``."""
    setup_page(parent, 4)

    # Title (grows, so the rest is at the right edge), pages and Refresh
    title_row = _make_row(parent, 44)
    make_label(title_row, "Departures", 0, FONT_BIG, COLOR_TEXT).set_flex_grow(1)
    screen = {"departures": [], "page": 0}
    screen["up"] = make_button(title_row, lv.SYMBOL.UP, COLOR_REFRESH,
                               PAGE_BUTTON_SIZE, lambda _e: change_page(screen, -1))
    screen["page_label"] = make_label(title_row, "", PAGE_LABEL_WIDTH, FONT_BIG, COLOR_TEXT)
    screen["page_label"].set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
    screen["down"] = make_button(title_row, lv.SYMBOL.DOWN, COLOR_REFRESH,
                                 PAGE_BUTTON_SIZE, lambda _e: change_page(screen, 1))
    make_button(title_row, "Refresh", COLOR_REFRESH, (130, 38), on_refresh)

    header = _make_row(parent, 30)
    for text, width in (("Time", COL_TIME), ("Line", COL_LINE),
                        ("Destination", COL_DEST), ("Status", COL_STATUS)):
        make_label(header, text, width, FONT_SMALL, COLOR_MUTED)

    # Not scrollable: pages replace scrolling
    list_box = lv.obj(parent)
    list_box.set_width(lv.pct(100))
    list_box.set_flex_grow(1)
    list_box.set_style_bg_opa(lv.OPA.TRANSP, 0)
    list_box.set_style_border_width(0, 0)
    list_box.set_style_pad_all(0, 0)
    list_box.remove_flag(lv.obj.FLAG.SCROLLABLE)
    list_box.remove_flag(lv.obj.FLAG.CLICKABLE)

    # A row is 4 labels in the list, no container. The header has the row
    # style, so its gap gives the column positions.
    xs = _column_x(_int_or(header.get_style_pad_column(0), 0))
    line_height = _line_height(ui_font(FONT_BIG))  # the font actually used
    rows = []
    for index in range(MAX_ROWS):
        y = _label_y(index, line_height)
        item = {"color": None}  # status color now, only set when it changes
        for key, width, x in zip(("time", "line", "dest", "status"),
                                 (COL_TIME, COL_LINE, COL_DEST, COL_STATUS), xs):
            item[key] = _make_cell(list_box, width, x, y)
        item["labels"] = (item["time"], item["line"], item["dest"], item["status"])
        _set_row_hidden(item, True)
        rows.append(item)

    # Instead of the rows: loading, no departures, errors
    message = make_label(list_box, "", 0, FONT_BIG, COLOR_MUTED, wrap=True)
    message.set_width(lv.pct(100))
    message.add_flag(lv.obj.FLAG.HIDDEN)

    make_label(parent, ATTRIBUTION, 0, FONT_SMALL, COLOR_MUTED)
    screen.update({"root": parent, "list": list_box, "rows": rows, "message": message})
    _update_page_controls(screen)
    return screen


def _set_hidden(widget, hidden):
    if hidden:
        widget.add_flag(lv.obj.FLAG.HIDDEN)
    else:
        widget.remove_flag(lv.obj.FLAG.HIDDEN)


def _set_row_hidden(item, hidden):
    for label in item["labels"]:
        _set_hidden(label, hidden)


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
    page = screen["departures"][first : first + MAX_ROWS]
    for index, item in enumerate(screen["rows"]):
        if index >= len(page):
            _set_row_hidden(item, True)
            continue
        departure = page[index]
        status = departure.get("status") or ""
        destination = str(departure.get("destination") or "")
        if len(destination) > MAX_DESTINATION_CHARS:
            destination = destination[: MAX_DESTINATION_CHARS - 1] + "."
        _set_text(item["time"], safe_text(departure.get("time") or "--:--"))
        _set_text(item["line"], safe_text(departure.get("line") or ""))
        _set_text(item["dest"], safe_text(destination))
        _set_text(item["status"], safe_text(status))
        color = STATUS_COLORS.get(status, COLOR_TEXT)
        if item["color"] != color:
            item["status"].set_style_text_color(lv.color_hex(color), 0)
            item["color"] = color
        _set_row_hidden(item, False)
    _update_page_controls(screen)


def change_page(screen, step):
    """Go ``step`` pages forward (1) or back (-1). True if the page changed."""
    page = screen["page"] + step
    if page < 0 or page >= page_count(len(screen["departures"])):
        return False
    screen["page"] = page
    _show_page(screen)
    return True


def show_message(screen, text):
    """Hide the rows and the page buttons and show ``text`` instead."""
    screen["departures"] = []
    screen["page"] = 0
    for item in screen["rows"]:
        _set_row_hidden(item, True)
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
