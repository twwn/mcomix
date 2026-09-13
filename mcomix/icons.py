"""icons.py - Load MComix specific icons."""

from gi.repository import Gdk, GdkPixbuf, Gtk
import os

from typing import Any



def icon_search_path() -> str:
    """Return the directory holding MComix' own icons.

    They are laid out as an icon theme - hicolor/<size>/actions/<name>.png -
    so that the icon theme can find them by name, the way it finds every
    other icon.  Gtk.IconFactory, which used to register them as stock
    items, is gone in GTK4.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'images', 'icons')


def icon_theme() -> Any:
    """The icon theme of the default display.

    GTK4 has no single default theme: it keeps one per display, so this
    needs a display to have been opened, which rules out module level.
    """
    return Gtk.IconTheme.get_for_display(Gdk.Display.get_default())


def load_icons() -> None:
    """Make MComix' own icons available by name."""
    icon_theme().add_search_path(icon_search_path())


def load_pixbuf(name: str, size: int) -> Any:
    """Return the icon <name> from the icon theme, at <size> pixels.

    GTK4's icon theme hands back a Gtk.IconPaintable rather than a pixbuf,
    and MComix works in pixbufs throughout, so the file behind it is
    loaded at the size asked for.
    """
    paintable = icon_theme().lookup_icon(
        name, None, size, 1, Gtk.TextDirection.NONE, Gtk.IconLookupFlags(0))
    file = paintable.get_file() if paintable is not None else None
    if file is None or file.get_path() is None:
        return None
    return GdkPixbuf.Pixbuf.new_from_file_at_size(file.get_path(), size, size)

# vim: expandtab:sw=4:ts=4
