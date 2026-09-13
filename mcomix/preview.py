"""preview.py - How large a preview of a page should be drawn."""

from typing import Any

#: The size a preview had on the screens MComix was written for, and the
#: screen height that size was chosen for.
_REFERENCE_HEIGHT = 1080
#: A preview is never drawn smaller than it was asked for, nor more than
#: this many times larger, however tall the screen is.
_MAX_FACTOR = 3.0


def screen_factor(widget: Any) -> float:
    """How much larger than usual a preview should be drawn.

    A size that suited a 1080 pixel screen is small on a 4K one and will
    only get smaller.  This is the number to multiply such a size by:
    one on the screens it was chosen for, two on a 4K screen, and never
    more than three, whatever comes next.
    """
    display = widget.get_display() if widget is not None else None
    monitors = display.get_monitors() if display is not None else None
    height = 0
    if monitors is not None and monitors.get_n_items():
        # The first monitor; a preview is sized before the window it
        # belongs to has a surface to be asked about.
        height = monitors.get_item(0).get_geometry().height
    if not height:
        return 1.0
    return min(_MAX_FACTOR, max(1.0, height / _REFERENCE_HEIGHT))


def scaled(size: int, widget: Any) -> int:
    """<size>, as large as this screen wants a preview to be."""
    return int(round(size * screen_factor(widget)))
