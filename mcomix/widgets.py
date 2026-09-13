"""widgets.py - Small helpers for widgets whose API changed in GTK4."""

from gi.repository import Gdk, Gtk

from typing import Any


def pack(box: Any, child: Any, expand: bool = False, fill: bool = True,
         padding: int = 0, end: bool = False) -> None:
    """Add <child> to <box>, the way Gtk.Box.pack_start/pack_end did.

    GTK4 boxes only append and prepend.  What the old arguments said is
    now said by the child: whether it takes the slack is hexpand or
    vexpand depending on which way the box runs, not filling its share is
    an alignment, and padding is a margin on the two ends that matter.
    """
    # Gtk.CellLayout - tree view columns, combo boxes - has a pack_start()
    # of its own that GTK4 keeps; only boxes lost theirs.
    assert isinstance(box, Gtk.Box), '%r is not a box' % (box,)
    if expand:
        if box.get_orientation() == Gtk.Orientation.HORIZONTAL:
            child.set_hexpand(True)
        else:
            child.set_vexpand(True)
    if not fill:
        if box.get_orientation() == Gtk.Orientation.HORIZONTAL:
            child.set_halign(Gtk.Align.CENTER)
        else:
            child.set_valign(Gtk.Align.CENTER)
    if padding:
        if box.get_orientation() == Gtk.Orientation.HORIZONTAL:
            child.set_margin_start(padding)
            child.set_margin_end(padding)
        else:
            child.set_margin_top(padding)
            child.set_margin_bottom(padding)
    box.append(child)


def set_border(widget: Any, width: int) -> None:
    """Put <width> pixels of margin around <widget>.

    Gtk.Container.set_border_width() is gone in GTK4; the space around a
    widget is the widget's own margin there.
    """
    widget.set_margin_top(width)
    widget.set_margin_bottom(width)
    widget.set_margin_start(width)
    widget.set_margin_end(width)


def popup_at(popover: Any, widget: Any, x: float, y: float) -> None:
    """Show <popover> over <widget>, pointing at (<x>, <y>) within it.

    A Gtk.Menu was popped up at the pointer with an event; a
    Gtk.PopoverMenu is parented to a widget and pointed at a rectangle in
    its coordinates.
    """
    if popover.get_parent() is None:
        popover.set_parent(widget)
    area = Gdk.Rectangle()
    area.x, area.y, area.width, area.height = int(x), int(y), 1, 1
    popover.set_pointing_to(area)
    popover.set_has_arrow(False)
    popover.popup()

# vim: expandtab:sw=4:ts=4
