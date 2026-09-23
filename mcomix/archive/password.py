"""The prompt that asks for an encrypted archive's password."""

import contextlib
import threading

from gi.repository import Gtk

from mcomix import message_dialog
from mcomix import widgets
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Callable, Iterator


class Withheld:

    """What never_asked() found out: whether anything in its block
    wanted a password."""

    def __init__(self) -> None:
        self.wanted = False


_withholding = threading.local()


@contextlib.contextmanager
def never_asked() -> Iterator[Withheld]:
    """Answer every request for a password made on this thread inside
    the block with none, without asking.

    For what works through archives on the reader's behalf rather than
    at their asking - a thumbnail, the library's listing of a book - and
    so should not put up a prompt, let alone one for every archive it
    passes.  What it answers with says whether any archive wanted one.
    """
    withheld = Withheld()
    outer = getattr(_withholding, 'current', None)
    _withholding.current = withheld
    try:
        yield withheld
    finally:
        _withholding.current = outer
        if outer is not None and withheld.wanted:
            outer.wanted = True


def withheld_here() -> bool:
    """Whether a password wanted now, on this thread, is to be withheld
    rather than asked for; if it is, never_asked() is told it was
    wanted."""
    withheld: Withheld | None = getattr(_withholding, 'current', None)
    if withheld is None:
        return False
    withheld.wanted = True
    return True


def ask_for_password(archive: str,
                     on_password: Callable[[str | None], None]) -> None:
    """ Opens an input dialog to ask for the password to <archive>.

    Calls <on_password> with the password the user typed, or with None if
    they gave none.  It does not wait for the answer: this runs on the
    main thread, and the nested main loop Gtk.Dialog.run() waited in is
    exactly what let a second password dialog open on top of the first."""
    dialog = message_dialog.MessageDialog(
            None, modal=True, buttons=Gtk.ButtonsType.OK_CANCEL)
    dialog.set_text(
        _("The archive is password-protected:"),
        archive + '\n\n' +
        _("Please enter the password to continue:"))
    dialog.set_default_response(Response.OK)

    password_box = Gtk.Entry()
    password_box.set_visibility(False)
    password_box.set_activates_default(True)
    widgets.pack(dialog.get_content_area(), password_box, True, True, 0, end=True)
    dialog.set_focus(password_box)

    def responded(response: int) -> None:
        """Hand the caller what was typed, or None if it cannot be used.

        An empty box counts as no password, as does cancelling: both
        leave the archive unreadable, and the handlers tell the two
        apart no better than the reader would.

        The box outlives the dialog, which run_async() has already taken
        down by the time this runs.
        """
        password = password_box.get_text()
        on_password(password
                    if response == Response.OK and password
                    else None)

    dialog.run_async(responded)

# vim: expandtab:sw=4:ts=4
