"""preview.py - How large a preview of a page should be drawn."""

import itertools

from gi.repository import Gtk

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


#: The classes draw_cells_at() hands out, one per view it is asked to
#: style.
_cell_classes = ('mcomix-preview-cells-%d' % number
                 for number in itertools.count())


def draw_cells_at(view: Any, size: int) -> None:
    """Let <view>'s cells draw their pictures <size> pixels tall.

    GTK4 draws whatever a Gtk.CellRendererPixbuf holds as an icon.  The
    picture's own dimensions still decide how much room the cell is
    given, so a page thumbnail was measured at its full size and then
    drawn as an eleven by sixteen pixel speck in the middle of it.  The
    drawing is capped at the icon size the style asks for, and nothing
    but CSS says what that is.
    """
    if getattr(view, '_preview_cell_size', None) == size:
        return
    provider = getattr(view, '_preview_cell_provider', None)
    if provider is None:
        provider = Gtk.CssProvider()
        view._preview_cell_provider = provider
        # A style provider belongs to a display rather than to a widget,
        # so every view styled here carries a class of its own for its
        # rule to single it out.  Views ask for different sizes, and one
        # of them is the library's, which is already wearing a class for
        # its background.
        view._preview_cell_class = next(_cell_classes)
        view.add_css_class(view._preview_cell_class)
        Gtk.StyleContext.add_provider_for_display(
            view.get_display(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    provider.load_from_string('.%s { -gtk-icon-size: %dpx; }'
                              % (view._preview_cell_class, size))
    view._preview_cell_size = size
