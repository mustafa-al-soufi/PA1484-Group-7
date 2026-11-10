"""Journey screen (US5.1, US5.2): choose a start and a destination stop."""

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
from screens.settings import _make_dropdown, _make_section

COLOR_SEARCH = 0x2E5E9E


def _make_row(parent, height):
    """Create a transparent row that lays out its children from left to right."""
    row = lv.obj(parent)
    row.set_width(lv.pct(100))
    row.set_height(height)
    row.set_style_bg_opa(lv.OPA.TRANSP, 0)
    row.set_style_border_width(0, 0)
    row.set_style_pad_all(0, 0)
    row.set_style_pad_column(8, 0)
    row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    row.set_flex_flow(lv.FLEX_FLOW.ROW)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    return row


def _ignore(_event):
    """Used for the dropdowns: nothing happens until Search is pressed."""


def _use_small_font(dropdown):
    """Use the small font so long names like Karlskrona Centralstation fit."""
    dropdown.set_style_text_font(FONT_SMALL, 0)
    try:
        dropdown.get_list().set_style_text_font(FONT_SMALL, 0)
    except Exception as error:
        print("Dropdown list font skipped:", error)


def create_journey_screen(parent, on_search):
    """Build the screen inside ``parent`` (a tile) and return its widgets.

    ``on_search`` is called when the user presses Search.
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

    make_label(root, "Journey", 0, FONT_BIG, COLOR_TEXT)

    # From and To side by side, so there is room for the results (US5.3)
    stop_row = _make_row(root, 90)

    from_card = _make_section(stop_row, "From", 90)
    from_card.set_width(lv.pct(49))
    from_dropdown = _make_dropdown(from_card, "Loading...", 0, _ignore)
    _use_small_font(from_dropdown)

    to_card = _make_section(stop_row, "To", 90)
    to_card.set_width(lv.pct(49))
    to_dropdown = _make_dropdown(to_card, "Loading...", 0, _ignore)
    _use_small_font(to_dropdown)

    # Search button with a short message next to it
    button_row = _make_row(root, 52)
    make_button(button_row, "Search", COLOR_SEARCH, (150, 44), on_search, 10)
    message = make_label(
        button_row, "Choose a start and a destination stop", 0, FONT_SMALL, COLOR_MUTED
    )

    return {
        "root": root,
        "from_dropdown": from_dropdown,
        "to_dropdown": to_dropdown,
        "message": message,
    }


def set_journey_stops(screen, names):
    """Fill both dropdowns with ``names``. To starts on the second stop."""
    if not names:
        return
    options = "\n".join(safe_text(name) for name in names)
    screen["from_dropdown"].set_options(options)
    screen["to_dropdown"].set_options(options)
    screen["from_dropdown"].set_selected(0)
    screen["to_dropdown"].set_selected(1 if len(names) > 1 else 0)


def get_journey_selection(screen):
    """Return the positions of the selected stops as (from_index, to_index)."""
    return (
        screen["from_dropdown"].get_selected(),
        screen["to_dropdown"].get_selected(),
    )


def show_journey_message(screen, text, ok=True):
    """Show a short message next to Search, green if ``ok`` and red if not."""
    screen["message"].set_text(safe_text(text))
    screen["message"].set_style_text_color(
        lv.color_hex(COLOR_OK if ok else COLOR_CANCELED), 0
    )
