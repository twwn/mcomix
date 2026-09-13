"""dialog_handler.py - Takes care of opening and closing and destroying of simple dialog windows.
   Dialog windows should only be taken care of here if they are windows that need to display
   information and then exit with no added functionality inbetween.
"""

from typing import Any

from gi.repository import Gio, Gtk

from mcomix.dialog import Dialog

from mcomix import about_dialog
from mcomix import comment_dialog
from mcomix import properties_dialog

#: What each dialog is built from, by the name the menu asks for it under.
_DIALOG_CLASSES = {
    'about-dialog': about_dialog._AboutDialog,
    'comments-dialog': comment_dialog._CommentsDialog,
    'properties-dialog': properties_dialog._PropertiesDialog,
}

#: The one that is open, by name, for as long as it is open.
_open_dialogs: dict[str, Gtk.Window] = {}


def open_dialog(action: Gio.SimpleAction,
                data: tuple[Gtk.Window, str]) -> None:
    """Create and display the given dialog."""

    window, name_of_dialog = data

    open_already = _open_dialogs.get(name_of_dialog)
    if open_already is not None:
        # One at a time: bring the open one forward rather than stacking
        # a second copy on it.
        open_already.present()
        return

    dialog = _DIALOG_CLASSES[name_of_dialog](window)
    _open_dialogs[name_of_dialog] = dialog
    # Gtk.AboutDialog is a plain Gtk.Window rather than one of MComix'
    # dialogs, so there is no response to wait for; every one of these
    # closes for good either way.
    if isinstance(dialog, Dialog):
        dialog.connect('response', _close_dialog, name_of_dialog)
    else:
        dialog.connect('close-request', _close_dialog, name_of_dialog)


def _close_dialog(dialog: Gtk.Window, *args: Any) -> None:
    """Destroy the dialog the signal came from.

    A response hands the callback the response id before the name and a
    close-request hands it nothing, so the name is read off the end.
    """

    name_of_dialog = args[-1]

    closing = _open_dialogs.pop(name_of_dialog, None)
    if closing is not None:
        closing.destroy()


# vim: expandtab:sw=4:ts=4
