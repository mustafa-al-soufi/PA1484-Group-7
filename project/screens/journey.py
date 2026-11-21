"""Journey screen (US5.1-US5.3B): search two stops, see journeys, best first."""

import lvgl as lv

from screens.departure import (
    ATTRIBUTION, COLOR_CANCELED, COLOR_MUTED, COLOR_OK, COLOR_TEXT, FONT_BIG,
    FONT_SMALL, _make_row, make_button, make_label, safe_text, setup_page,
)
from screens.settings import _make_dropdown, _make_section, make_search_field, show_selected

COLOR_SEARCH = 0x2E5E9E


def _stop_card(screen, row, side, title, on_search):
    """Half-width card: search field (US5.2B) above a dropdown."""
    card = _make_section(row, title, 126)  # 10 + 18 + 6 + 38 + 6 + 38 + 10
    card.set_width(270)
    make_search_field(card, lv.pct(100), lambda text: on_search(side, text))
    dropdown = _make_dropdown(card, "Loading...", 0, lambda _e: _show(screen, side), FONT_SMALL)
    screen[side] = dropdown
    screen[side + "_names"] = []


def _show(screen, side):
    show_selected(screen[side], screen[side + "_names"], screen)


def create_journey_screen(parent, on_search, on_stop_search=None):
    """Build the screen in ``parent`` (a tile). ``on_stop_search(side, text)``
    is called for a stop search in the From ("from") or To ("to") card."""
    setup_page(parent, 4)
    screen = {}

    # From and To side by side, then Search with a message (US5.2)
    stop_row = _make_row(parent, 134)
    for side, title in (("from", "From"), ("to", "To")):
        _stop_card(screen, stop_row, side, title, on_stop_search or (lambda side, text: None))
    button_row = _make_row(parent, 52)
    make_button(button_row, "Search", COLOR_SEARCH, (150, 40), on_search, 10)
    screen["message"] = make_label(button_row, "", 0, FONT_SMALL, COLOR_MUTED, wrap=True)

    # The journeys (US5.3). Only vertical scrolling, so swipes reach the tiles.
    results = screen["results"] = lv.obj(parent)
    results.set_width(lv.pct(100))
    results.set_flex_grow(1)
    results.set_style_bg_opa(lv.OPA.TRANSP, 0)
    results.set_style_border_width(0, 0)
    results.set_scroll_dir(lv.DIR.VER)
    results.set_scrollbar_mode(lv.SCROLLBAR_MODE.ACTIVE)
    results.set_flex_flow(lv.FLEX_FLOW.COLUMN)

    make_label(parent, ATTRIBUTION, 0, FONT_SMALL, COLOR_MUTED)  # NF3
    return screen


def set_journey_side(screen, side, names, selected=0):
    """Fill the "from" or "to" dropdown."""
    screen[side + "_names"] = [safe_text(name) for name in names]
    screen[side].set_options("\n".join(screen[side + "_names"]))
    screen[side].set_selected(selected)
    _show(screen, side)


def set_journey_stops(screen, names):
    """Fill both dropdowns; To starts on the second stop."""
    set_journey_side(screen, "from", names)
    set_journey_side(screen, "to", names, 1 if len(names) > 1 else 0)


def get_journey_selection(screen):
    """(from_index, to_index) selected."""
    return screen["from"].get_selected(), screen["to"].get_selected()


def show_journey_message(screen, text, ok=True):
    """A message next to Search, green if ``ok``, else red."""
    screen["message"].set_text(safe_text(text))
    screen["message"].set_style_text_color(lv.color_hex(COLOR_OK if ok else COLOR_CANCELED), 0)


def show_trips(screen, trips, text=""):
    """The journeys, or only ``text`` if ``trips`` is None (US5.3). One line
    per ride: its time at the start and every change. "Best" (US5.3B) in green."""
    results = screen["results"]
    results.clean()
    if trips == []:
        text = "No journeys found"
    if not trips:
        make_label(results, text, lv.pct(100), FONT_BIG, COLOR_MUTED, wrap=True)
        return
    for trip in trips:
        changes = str(trip["changes"]) + " change(s)" if trip["changes"] else "Direct"
        best = trip.get("best")
        header = ("Best  " if best else "") + trip["departure"] + " -> " + trip["arrival"] + "   " + changes
        make_label(results, header, lv.pct(100), FONT_BIG, COLOR_OK if best else COLOR_TEXT, wrap=True)
        rides = [r["time"] + "  " + r["line"] + "  from " + r["stop"] for r in trip["rides"]]
        make_label(results, "\n".join(rides), lv.pct(100), FONT_SMALL, COLOR_MUTED, wrap=True)