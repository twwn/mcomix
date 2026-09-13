""" Simple extension of Gtk.MessageDialog for consistent formating. Also
    supports remembering the dialog result.
"""

from gi.repository import GLib, Gtk

from mcomix import widgets
from mcomix.preferences import prefs
from mcomix.i18n import _

from collections.abc import Callable
from typing import Any


class MessageDialog(Gtk.MessageDialog):

    def __init__(self, parent=None, flags=0, type=0, buttons=0):
        """ Creates a dialog window.
        @param parent: Parent window
        @param flags: Dialog flags
        @param type: Dialog icon/type
        @param buttons: Dialog buttons. Can only be a predefined BUTTONS_XXX constant.
        """
        if parent is None:
            # Fix "mapped without a transient parent" Gtk warning.
            from mcomix import main
            parent = main.main_window()
        # GTK4 has no "flags" property: what MComix passes through it is
        # modality, and the parent and type are named differently too.
        super(MessageDialog, self).__init__(
            transient_for=parent,
            modal=bool(flags & Gtk.DialogFlags.MODAL),
            message_type=type, buttons=buttons)

        #: Unique dialog identifier (for storing 'Do not ask again')
        self.dialog_id = None
        #: List of response IDs that should be remembered
        self.choices = []
        #: Automatically destroy dialog after run?
        self.auto_destroy = True

        self.remember_checkbox = Gtk.CheckButton(label=_('Do not ask again.'))
        self.remember_checkbox.set_visible(False)
        self.remember_checkbox.set_can_focus(False)
        widgets.pack(self.get_message_area(), self.remember_checkbox, True, True, 6, end=True)

    def set_text(self, primary, secondary=None):
        """ Formats the dialog's text fields.
        @param primary: Main text.
        @param secondary: Descriptive text.
        """
        if primary:
            self.set_markup('<span weight="bold" size="larger">' +
                primary + '</span>')
        if secondary:
            # format_secondary_markup() is gone in GTK4; the two
            # properties it set are still there.
            self.set_property('secondary-use-markup', True)
            self.set_property('secondary-text', secondary)

    def should_remember_choice(self):
        """ Returns True when the dialog choice should be remembered. """
        return self.remember_checkbox.get_active()

    def set_should_remember_choice(self, dialog_id, choices):
        """ This method enables the 'Do not ask again' checkbox.
        @param dialog_id: Unique identifier for the dialog (a string).
        @param choices: List of response IDs that should be remembered
        """
        self.remember_checkbox.show()
        self.dialog_id = dialog_id
        self.choices = [int(choice) for choice in choices]

    def set_auto_destroy(self, auto_destroy):
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
            if self.auto_destroy:
                self.destroy()
            on_response(response)

        self.connect('response', responded)
        self.set_visible(True)
        # Prevent checkbox from grabbing focus by only enabling it after show
        self.remember_checkbox.set_can_focus(True)


# vim: expandtab:sw=4:ts=4
