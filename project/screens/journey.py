"""Journey screen (US5.1): plan a journey between two stops."""

import lvgl as lv

from screens.departure import (
    COLOR_BG,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BIG,
    make_label,
)


def create_journey_screen(parent):
    """Build the screen inside ``parent`` (a tile) and return its widgets."""
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

    # Shown until the stop selection is added (US5.2)
    message = make_label(
        root, "Choose a start and a destination stop", 0, FONT_BIG, COLOR_MUTED
    )

    return {"root": root, "message": message}
