"""icons.py - Load MComix specific icons."""

from gi.repository import Gtk
import os
import pkgutil

from collections.abc import Sequence
from typing import Any

from mcomix import image_tools


def mcomix_icons():
    """ Returns a list of differently sized pixbufs for the
    application icon. """

    sizes = ('16', '32', '48', '256')
    pixbufs = [
        image_tools.load_pixbuf_data(
            pkgutil.get_data('mcomix', f'images/mcomix-{size}.png')
        ) for size in sizes
    ]

    return pixbufs


def icon_search_path() -> str:
    """Return the directory holding MComix' own icons.

    They are laid out as an icon theme - hicolor/<size>/actions/<name>.png -
    so that the icon theme can find them by name, the way it finds every
    other icon.  Gtk.IconFactory, which used to register them as stock
    items, is gone in GTK4.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'images', 'icons')


def load_icons() -> None:
    """Set the window icon and make MComix' own icons available by name."""
    Gtk.Window.set_default_icon_list(mcomix_icons())
    Gtk.IconTheme.get_default().append_search_path(icon_search_path())


def load_pixbuf(name: str, size: int) -> Any:
    """Return the icon <name> from the icon theme, at <size> pixels."""
    return Gtk.IconTheme.get_default().load_icon(name, size, 0)


def _add(actiongroup: Any, method: str,
         entries: Sequence[Sequence[Any]], args: Sequence[Any]) -> None:
    """Add <entries> to <actiongroup> through the named add_*_actions method.

    Those methods take a stock id in the entry's second field, where the
    tables that call this carry an icon name.  Stock items are gone in
    GTK4, and a Gtk.Action falls back to its icon name only when it has no
    stock id, so hand the name to the action separately.
    """
    getattr(actiongroup, method)(
        [(entry[0], None) + tuple(entry[2:]) for entry in entries], *args)
    for entry in entries:
        if entry[1] is not None:
            actiongroup.get_action(entry[0]).set_icon_name(entry[1])


def add_actions(actiongroup: Any, entries: Sequence[Sequence[Any]],
                *args: Any) -> None:
    """Add action <entries> carrying icon names to <actiongroup>."""
    _add(actiongroup, 'add_actions', entries, args)


def add_toggle_actions(actiongroup: Any, entries: Sequence[Sequence[Any]],
                       *args: Any) -> None:
    """Add toggle action <entries> carrying icon names to <actiongroup>."""
    _add(actiongroup, 'add_toggle_actions', entries, args)


def add_radio_actions(actiongroup: Any, entries: Sequence[Sequence[Any]],
                      *args: Any) -> None:
    """Add radio action <entries> carrying icon names to <actiongroup>."""
    _add(actiongroup, 'add_radio_actions', entries, args)


# vim: expandtab:sw=4:ts=4
