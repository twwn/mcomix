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

from collections.abc import Callable, Sequence
from typing import Any

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


class MessageDialog(Dialog):

    def __init__(self, parent: "Gtk.Window | None" = None, *,
                 buttons: Gtk.ButtonsType = Gtk.ButtonsType.NONE,
                 modal: bool = False,
                 destroy_with_parent: bool = False) -> None:
        """ Creates a dialog window.
        @param parent: Parent window
        @param buttons: Which buttons to offer, as a Gtk.ButtonsType.
        @param modal: Whether the dialog holds the parent's input while
                      it is up.
        @param destroy_with_parent: Whether closing the parent closes
                                    this dialog with it.

        These were a Gtk.DialogFlags bitfield and a Gtk.MessageType up
        to GTK 4.20, which deprecated the first and left MComix reading
        one bit out of it.  The type picked an icon no version of this
        dialog has drawn, and nothing else ever read it.  Everything
        after <parent> is keyword-only, so a call left in the old shape
        raises rather than quietly taking a button set for a flag.
        """
        if parent is None:
            # Fix "mapped without a transient parent" Gtk warning.
            from mcomix import main
            parent = main.main_window()
        super(MessageDialog, self).__init__(
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
        self.dialog_id: str | None = None
        #: List of response IDs that should be remembered
        self.choices: list[int] = []
        #: Automatically destroy dialog after run?
        self.auto_destroy = True

        self.remember_checkbox = Gtk.CheckButton(label=_('Do not ask again.'))
        self.remember_checkbox.set_visible(False)
        self.remember_checkbox.set_can_focus(False)
        area.append(self.remember_checkbox)

    def set_text(self, primary: str | None,
                 secondary: str | None = None) -> None:
        """ Formats the dialog's text fields.
        @param primary: Main text.
        @param secondary: Descriptive text.
        """
        if primary:
            self._primary.set_text(primary)
        if secondary:
            # The secondary text is markup, which is what
            # secondary-use-markup used to say.
            self._secondary.set_markup(secondary)
            self._secondary.set_visible(True)

    def should_remember_choice(self) -> bool:
        """ Returns True when the dialog choice should be remembered. """
        return self.remember_checkbox.get_active()

    def set_should_remember_choice(self, dialog_id: str,
                                   choices: "Sequence[int]") -> None:
        """ This method enables the 'Do not ask again' checkbox.
        @param dialog_id: Unique identifier for the dialog (a string).
        @param choices: List of response IDs that should be remembered
        """
        self.remember_checkbox.set_visible(True)
        self.dialog_id = dialog_id
        self.choices = [int(choice) for choice in choices]

    def set_auto_destroy(self, auto_destroy: bool) -> None:
        """ Determines if the dialog should automatically destroy itself
        once it has been answered. """
        self.auto_destroy = auto_destroy

    def run_async(self, on_response: Callable[[int], None]) -> None:
        """ Makes the dialog visible and hands its result to <on_response>.

        This is what Gtk.Dialog.run() used to do, minus the waiting: run()
        is gone in GTK4, and the nested main loop it waited in kept the
        idle queue turning, so anything queued behind the dialog - another
        dialog, say - ran before this one had been answered.

        <on_response> is always called from the main loop, never before
        this method returns, whether the answer comes from the user or
        from a choice remembered earlier.
        """
        if self.dialog_id in prefs['stored dialog choices']:
            remembered = prefs['stored dialog choices'][self.dialog_id]
            self.destroy()

            def deliver_remembered() -> bool:
                on_response(remembered)
                return False

            GLib.idle_add(deliver_remembered)
            return

        def responded(dialog: Any, response: int) -> None:
            if self.should_remember_choice() and int(response) in self.choices:
                prefs['stored dialog choices'][self.dialog_id] = int(response)
                # The preference is the dictionary, which is the same
                # dictionary it was: only the answer in it is new.
                preferences.changed()
            if self.auto_destroy:
                self.destroy()
            on_response(response)

        self.connect('response', responded)
        self.set_visible(True)
        # Prevent checkbox from grabbing focus by only enabling it after show
        self.remember_checkbox.set_can_focus(True)


# vim: expandtab:sw=4:ts=4
