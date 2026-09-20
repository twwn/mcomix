""" A dialog that asks a question, with consistent formatting. Also
    supports remembering the dialog result.
"""

from gi.repository import GLib, Gtk

from mcomix.dialog import Dialog
from mcomix import widgets
from mcomix import preferences
from mcomix.preferences import prefs
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Callable
from enum import StrEnum
from typing import NamedTuple

#: What each Gtk.ButtonsType asks for, as label and response. There is
#: no Gtk.MessageDialog to build them any more, and Gtk.AlertDialog -
#: which is what GTK offers instead - has no room for the "do not ask
#: again" checkbox below.
_BUTTONS = {
    Gtk.ButtonsType.NONE: (),
    Gtk.ButtonsType.OK: ((_('_OK'), Response.OK),),
    Gtk.ButtonsType.CLOSE: ((_('_Close'), Response.CLOSE),),
    Gtk.ButtonsType.CANCEL: ((_('_Cancel'), Response.CANCEL),),
    Gtk.ButtonsType.YES_NO: ((_('_No'), Response.NO),
                             (_('_Yes'), Response.YES)),
    Gtk.ButtonsType.OK_CANCEL: ((_('_Cancel'), Response.CANCEL),
                                (_('_OK'), Response.OK)),
}


class RememberedDialog(StrEnum):

    """A prompt that offers to be answered once and for all.

    A member is the key its answer is stored under in
    ``prefs['stored dialog choices']``, so the answer written by a
    dialog and the answer read back out of the preferences file are
    found under the same string.
    """

    RESUME_FROM_LAST_READ_PAGE = 'resume-from-last-read-page'
    DELETE_OPENED_FILE = 'delete-opened-file'
    REPLACE_EXISTING_BOOKMARK = 'replace-existing-bookmark'
    LIBRARY_REMOVE_BOOK_FROM_DISK = 'library-remove-book-from-disk'
    SAVE_EDITED_ARCHIVE = 'save-edited-archive'
    REMOVE_PICKED_OUT_PAGES = 'remove-picked-out-pages'
    REMOVE_BOOKMARKS_OF_DELETED_FILE = 'remove-bookmarks-of-deleted-file'


class _Prompt(NamedTuple):

    """What a remembered prompt is called, and what it can be told."""

    #: What the prompt asks about, as the preferences dialog lists it.
    label: str
    #: The answers that can be remembered, as label and response.  An
    #: answer that is not here is one the dialog keeps asking for: a
    #: remembered Cancel would be a prompt that can never say yes again.
    answers: "tuple[tuple[str, int], ...]"


#: Every prompt with a "Do not ask again" tick.  The dialogs take their
#: answers from here rather than naming them at each call site, and the
#: preferences dialog lists what is in here, so a prompt that is added
#: without an entry cannot be answered for good and one that is added
#: with one needs nothing else to be taken back.
REMEMBERED_DIALOGS = {
    RememberedDialog.RESUME_FROM_LAST_READ_PAGE: _Prompt(
        _('Opening a book that was left part-read:'),
        ((_('Continue from the last read page'), Response.YES),
         (_('Start at the first page'), Response.NO))),
    RememberedDialog.DELETE_OPENED_FILE: _Prompt(
        _('Deleting the opened file:'),
        ((_('Delete it'), Response.OK),)),
    RememberedDialog.REPLACE_EXISTING_BOOKMARK: _Prompt(
        _('Bookmarking a page that is bookmarked already:'),
        ((_('Replace the existing bookmark'), Response.YES),
         (_('Keep both bookmarks'), Response.NO))),
    RememberedDialog.LIBRARY_REMOVE_BOOK_FROM_DISK: _Prompt(
        _('Deleting books that are removed from the library:'),
        ((_('Delete them'), Response.YES),)),
    RememberedDialog.SAVE_EDITED_ARCHIVE: _Prompt(
        _('Removing a page from the book being read:'),
        ((_('Write the archive again at once'), Response.YES),
         (_('Leave the archive as it is'), Response.NO))),
    RememberedDialog.REMOVE_PICKED_OUT_PAGES: _Prompt(
        _('Leaving a book with pages still picked out:'),
        ((_('Remove them and write the archive'), Response.YES),
         (_('Leave the book as it is'), Response.NO))),
    RememberedDialog.REMOVE_BOOKMARKS_OF_DELETED_FILE: _Prompt(
        _('Deleting a file that is bookmarked:'),
        ((_('Remove its bookmarks'), Response.YES),
         (_('Keep its bookmarks'), Response.NO))),
}


class MessageDialog(Dialog):

    def __init__(self, parent: "Gtk.Window | None" = None, *,
                 buttons: Gtk.ButtonsType = Gtk.ButtonsType.NONE,
                 modal: bool = False,
                 destroy_with_parent: bool = False) -> None:
        """A dialog window under <parent>, offering <buttons>.

        <modal> holds the parent's input while the dialog is up, and
        <destroy_with_parent> takes the dialog down when the parent
        closes.

        The last two were a Gtk.DialogFlags bitfield up to GTK 4.20,
        which deprecated it and left MComix reading one bit out of it,
        and beside them stood a Gtk.MessageType that picked an icon no
        version of this dialog has drawn and that nothing else ever
        read.  Everything after <parent> is keyword-only, so a call
        left in the old shape raises rather than quietly taking a
        button set for a flag.
        """
        if parent is None:
            # Fix "mapped without a transient parent" Gtk warning.
            from mcomix import main
            parent = main.main_window()
        super().__init__(
            transient_for=parent, modal=modal,
            destroy_with_parent=destroy_with_parent)
        widgets.set_border(self, 12)

        self._primary = Gtk.Label()
        self._primary.set_xalign(0)
        self._primary.set_wrap(True)
        self._primary.add_css_class('title-4')
        self._secondary = Gtk.Label()
        self._secondary.set_xalign(0)
        self._secondary.set_wrap(True)
        self._secondary.set_visible(False)
        area = self.get_content_area()
        area.append(self._primary)
        area.append(self._secondary)

        for label, response in _BUTTONS.get(buttons, ()):
            self.add_button(label, response)

        #: Unique dialog identifier (for storing 'Do not ask again')
        self.dialog_id: "RememberedDialog | None" = None
        #: List of response IDs that should be remembered
        self.choices: list[int] = []

        self.remember_checkbox = Gtk.CheckButton(label=_('Do not ask again.'))
        self.remember_checkbox.set_visible(False)
        self.remember_checkbox.set_can_focus(False)
        area.append(self.remember_checkbox)

    def set_text(self, primary: str | None,
                 secondary: str | None = None) -> None:
        """Say what the dialog is about, in one or two lines.

        <primary> is what is being asked or reported, in bold, and
        <secondary> what that means, in ordinary type under it.  Both
        are shown as they are given; neither is markup.
        """
        if primary:
            self._primary.set_text(primary)
        if secondary:
            # Plain text, not Pango markup: what goes on this line is a
            # sentence and sometimes a file name, and a name holding an
            # ampersand or an angle bracket is neither an entity nor a
            # tag.  Markup that fails to parse leaves the label empty,
            # so the whole line would be lost rather than the character.
            self._secondary.set_text(secondary)
            self._secondary.set_visible(True)

    def should_remember_choice(self) -> bool:
        """ Returns True when the dialog choice should be remembered. """
        return self.remember_checkbox.get_active()

    def set_should_remember_choice(self, dialog_id: RememberedDialog) -> None:
        """ Show the 'Do not ask again' checkbox, for the prompt <dialog_id>.

        Which answers the tick keeps is what REMEMBERED_DIALOGS says
        about that prompt.
        """
        self.remember_checkbox.set_visible(True)
        self.dialog_id = dialog_id
        self.choices = [response for _label, response
                        in REMEMBERED_DIALOGS[dialog_id].answers]

    def run_async(self, on_response: Callable[[int], None]) -> None:
        """ Makes the dialog visible and hands its result to <on_response>.

        This is what Gtk.Dialog.run() used to do, minus the waiting: run()
        is gone in GTK4, and the nested main loop it waited in kept the
        idle queue turning, so anything queued behind the dialog - another
        dialog, say - ran before this one had been answered.

        <on_response> is always called from the main loop, never before
        this method returns, whether the answer comes from the user or
        from a choice remembered earlier.

        The dialog is destroyed before <on_response> runs, and that is
        the order the callers need: several of them go on to close the
        book or open the next one, and closing turns the main loop over
        to drain the idle queue, which would paint a dialog that had
        been answered and not yet taken down.  A widget the dialog
        carried is still readable afterwards - destroying a window
        neither unparents its children nor finalises them while Python
        holds a reference - so a caller that has to read what was typed
        reads it in the callback like any other.
        """
        if self.dialog_id in prefs['stored dialog choices']:
            remembered = prefs['stored dialog choices'][self.dialog_id]
            self.destroy()

            def deliver_remembered() -> bool:
                on_response(remembered)
                return False

            GLib.idle_add(deliver_remembered)
            return

        def responded(dialog: "MessageDialog", response: int) -> None:
            if (self.dialog_id is not None and self.should_remember_choice()
                    and int(response) in self.choices):
                prefs['stored dialog choices'][self.dialog_id] = int(response)
                # The preference is the dictionary, which is the same
                # dictionary it was: only the answer in it is new.
                preferences.changed()
            self.destroy()
            on_response(response)

        self.connect('response', responded)
        self.set_visible(True)
        # Prevent checkbox from grabbing focus by only enabling it after show
        self.remember_checkbox.set_can_focus(True)


# vim: expandtab:sw=4:ts=4
