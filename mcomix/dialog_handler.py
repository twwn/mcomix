"""dialog_handler.py - Takes care of opening and closing and destroying of simple dialog windows.
   Dialog windows should only be taken care of here if they are windows that need to display
   information and then exit with no added functionality inbetween.
"""

from gi.repository import Gtk

from mcomix import about_dialog
from mcomix import comment_dialog
from mcomix import properties_dialog

dialog_windows = {}
dialog_windows[ 'about-dialog' ] = [None, about_dialog._AboutDialog]
dialog_windows[ 'comments-dialog' ] = [None, comment_dialog._CommentsDialog]
dialog_windows[ 'properties-dialog' ] = [None, properties_dialog._PropertiesDialog]

def open_dialog(action, data):
    """Create and display the given dialog."""

    window, name_of_dialog = data

    _dialog = dialog_windows[ name_of_dialog ]

    # if the dialog window is not created then create the window
    # and connect the _close_dialog action to the dialog window
    if _dialog[0] is None:
        dialog_windows[ name_of_dialog ][0] = _dialog[1](window)
        created = dialog_windows[ name_of_dialog ][0]
        # Gtk.AboutDialog is a plain Gtk.Window in GTK4 rather than a
        # Gtk.Dialog, so there is no response to wait for; every one of
        # these closes for good either way.
        if isinstance(created, Gtk.Dialog):
            created.connect('response', _close_dialog, name_of_dialog)
        else:
            created.connect('close-request', _close_dialog, name_of_dialog)
    else:
        # if the dialog window already exists bring it to the forefront of the screen
        _dialog[0].present()

def _close_dialog(action, *args):
    name_of_dialog = args[-1]

    _dialog = dialog_windows[ name_of_dialog ]

    # if the dialog window exists then destroy it
    if _dialog[0] is not None:
        _dialog[0].destroy()
        _dialog[0] = None


# vim: expandtab:sw=4:ts=4
