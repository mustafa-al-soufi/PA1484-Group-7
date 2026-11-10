"""Journey screen (US5.1-US5.3): choose two stops and see the best journeys."""

import lvgl as lv

from screens.departure import (
    ATTRIBUTION,
    COLOR_BG,
    COLOR_CANCELED,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_TEXT,
    FONT_BIG,
    FONT_SMALL,
    _make_row,
    make_button,
    make_label,
    safe_text,
)
from screens.settings import _make_dropdown, _make_section

COLOR_SEARCH = 0x2E5E9E


def _ignore(_event):
    """Used for the dropdowns: nothing happens until Search is pressed."""


def _stop_dropdown(row, title):
    """Create a half-width card with a dropdown in the small font."""
    card = _make_section(row, title, 82)
    card.set_width(270)
    dropdown = _make_dropdown(card, "Loading...", 0, _ignore)
    dropdown.set_style_text_font(FONT_SMALL, 0)
    return dropdown


def create_journey_screen(parent, on_search):
    """Build the screen inside ``parent`` (a tile)."""
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

    # From and To side by side, then Search with a message (US5.2)
    stop_row = _make_row(root, 90)
    from_dropdown = _stop_dropdown(stop_row, "From")
    to_dropdown = _stop_dropdown(stop_row, "To")
    button_row = _make_row(root, 52)
    make_button(button_row, "Search", COLOR_SEARCH, (150, 40), on_search, 10)
    message = make_label(button_row, "", 0, FONT_SMALL, COLOR_MUTED)

    # The journeys (US5.3). Only vertical scrolling, so swipes reach the tiles.
    results = lv.obj(root)
    results.set_width(lv.pct(100))
    results.set_flex_grow(1)
    results.set_style_bg_opa(lv.OPA.TRANSP, 0)
    results.set_style_border_width(0, 0)
    results.set_scroll_dir(lv.DIR.VER)
    results.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    make_label(root, ATTRIBUTION, 0, FONT_SMALL, COLOR_MUTED)  # NF3

    return {
        "from": from_dropdown,
        "to": to_dropdown,
        "message": message,
        "results": results,
    }


def set_journey_stops(screen, names):
    """Fill both dropdowns with ``names``. To starts on the second stop."""
    options = "\n".join(safe_text(name) for name in names)
    screen["from"].set_options(options)
    screen["to"].set_options(options)
    screen["to"].set_selected(1 if len(names) > 1 else 0)


def get_journey_selection(screen):
    """Return the positions of the selected stops as (from_index, to_index)."""
    return screen["from"].get_selected(), screen["to"].get_selected()


def show_journey_message(screen, text, ok=True):
    """Show a short message next to Search, green if ``ok`` and red if not."""
    screen["message"].set_text(safe_text(text))
    color = COLOR_OK if ok else COLOR_CANCELED
    screen["message"].set_style_text_color(lv.color_hex(color), 0)


def show_trips(screen, trips, text=""):
    """Show the journeys, or only ``text`` if ``trips`` is None (US5.3).

    One line per ride: the time at the start and at every change.
    """
    results = screen["results"]
    results.clean()
    if trips == []:
        text = "No journeys found"
    if not trips:
        make_label(results, text, lv.pct(100), FONT_BIG, COLOR_MUTED)
        return
    for trip in trips:
        changes = str(trip["changes"]) + " change(s)" if trip["changes"] else "Direct"
        header = trip["departure"] + " -> " + trip["arrival"] + "   " + changes
        make_label(results, header, lv.pct(100), FONT_BIG, COLOR_TEXT)
        rides = [
            r["time"] + "  " + r["line"] + "  from " + r["stop"] for r in trip["rides"]
        ]
        make_label(results, "\n".join(rides), lv.pct(100), FONT_SMALL, COLOR_MUTED)
