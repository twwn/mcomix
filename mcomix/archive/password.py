# -*- coding: utf-8 -*-

from gi.repository import Gtk

from mcomix import message_dialog
from mcomix import widgets
from mcomix.i18n import _

from collections.abc import Callable

def ask_for_password(archive: str,
                     on_password: Callable[[str | None], None]) -> None:
    """ Opens an input dialog to ask for the password to <archive>.

    Calls <on_password> with the password the user typed, or with None if
    they gave none.  It does not wait for the answer: this runs on the
    main thread, and the nested main loop Gtk.Dialog.run() waited in is
    exactly what let a second password dialog open on top of the first."""
    dialog = message_dialog.MessageDialog(None, Gtk.DialogFlags.MODAL,
            Gtk.MessageType.QUESTION, Gtk.ButtonsType.OK_CANCEL)
    dialog.set_text(
        _("The archive is password-protected:"),
        archive + '\n\n' +
        ("Please enter the password to continue:"))
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.set_auto_destroy(False)

    password_box = Gtk.Entry()
    password_box.set_visibility(False)
    password_box.set_activates_default(True)
    widgets.pack(dialog.get_content_area(), password_box, True, True, 0, end=True)
    dialog.set_focus(password_box)

    def responded(response: int) -> None:
        password = password_box.get_text()
        dialog.destroy()
        on_password(password
                    if response == Gtk.ResponseType.OK and password
                    else None)

    dialog.run_async(responded)

# vim: expandtab:sw=4:ts=4
