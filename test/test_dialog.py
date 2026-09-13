# -*- coding: utf-8 -*-

"""The window MComix' dialogs are built out of.

Gtk.Dialog is deprecated as of GTK 4.10 and has no replacement for what
MComix uses it for: Gtk.AlertDialog answers for a message and two
buttons, and anything else is meant to be an ordinary window that lays
its own buttons out. These pin the shape all of them shared.
"""

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import dialog


class DialogTest(MComixTest):

    def setUp(self):
        super(DialogTest, self).setUp()
        self.dialog = dialog.Dialog(title='Test')
        self.answers = []
        self.dialog.connect('response', lambda _d, r: self.answers.append(r))

    def tearDown(self):
        # A dialog left on screen is answered by whatever looks for one
        # next.
        self.dialog.destroy()
        pump()
        super(DialogTest, self).tearDown()

    def test_it_is_painted_as_a_dialog_rather_than_as_a_window(self):
        """A Gtk.Dialog carried the dialog style class, and a theme -
        MComix' own included - paints window.dialog in a different
        colour from a plain window. Without it every dialog MComix
        builds stood out beside the ones GTK builds."""
        self.assertIn('dialog', self.dialog.get_css_classes())
        self.assertIn('dialog', Gtk.Dialog().get_css_classes(),
                      'a Gtk.Dialog no longer carries it either')

    def test_what_goes_in_the_content_area_is_in_the_window(self):
        label = Gtk.Label(label='hello')
        self.dialog.get_content_area().append(label)
        self.assertIs(label.get_root(), self.dialog)

    def test_a_button_answers_with_the_response_it_was_given(self):
        button = self.dialog.add_button('_Apply', Gtk.ResponseType.APPLY)
        button.emit('clicked')
        self.assertEqual(self.answers, [Gtk.ResponseType.APPLY])

    def test_the_button_for_a_response_can_be_found_again(self):
        button = self.dialog.add_button('_Close', Gtk.ResponseType.CLOSE)
        self.assertIs(
            self.dialog.get_widget_for_response(Gtk.ResponseType.CLOSE),
            button)
        self.assertIsNone(
            self.dialog.get_widget_for_response(Gtk.ResponseType.OK))

    def test_a_button_is_in_the_window_too(self):
        button = self.dialog.add_button('_OK', Gtk.ResponseType.OK)
        self.assertIs(button.get_root(), self.dialog)

    def test_the_default_response_is_the_default_widget(self):
        self.dialog.add_button('_Cancel', Gtk.ResponseType.CANCEL)
        ok = self.dialog.add_button('_OK', Gtk.ResponseType.OK)
        self.dialog.set_default_response(Gtk.ResponseType.OK)
        self.assertIs(self.dialog.get_default_widget(), ok)

    def test_a_default_response_nobody_added_a_button_for_is_ignored(self):
        self.dialog.set_default_response(Gtk.ResponseType.OK)
        self.assertIsNone(self.dialog.get_default_widget())

    def test_a_response_can_be_disabled_and_enabled(self):
        button = self.dialog.add_button('_OK', Gtk.ResponseType.OK)
        self.dialog.set_response_sensitive(Gtk.ResponseType.OK, False)
        self.assertFalse(button.get_sensitive())
        self.dialog.set_response_sensitive(Gtk.ResponseType.OK, True)
        self.assertTrue(button.get_sensitive())

    def test_answering_it_directly_reaches_whoever_is_listening(self):
        self.dialog.response(Gtk.ResponseType.YES)
        self.assertEqual(self.answers, [Gtk.ResponseType.YES])

    def test_closing_the_window_answers_the_dialog(self):
        self.dialog.emit('close-request')
        self.assertEqual(self.answers, [Gtk.ResponseType.DELETE_EVENT])

    def test_a_subclass_may_keep_a_list_of_its_own_buttons(self):
        # The file chooser does, under the name _buttons, which is what
        # this base used to keep its own responses in: it was silently
        # emptied the moment the subclass ran its constructor.
        class _WithButtons(dialog.Dialog):
            def __init__(self):
                super(_WithButtons, self).__init__()
                self._buttons = []

        subclass = _WithButtons()
        try:
            button = subclass.add_button('_OK', Gtk.ResponseType.OK)
            subclass.set_default_response(Gtk.ResponseType.OK)
            self.assertIs(
                subclass.get_widget_for_response(Gtk.ResponseType.OK), button)
            self.assertEqual(subclass._buttons, [])
        finally:
            subclass.destroy()

    def test_add_buttons_adds_each_label_and_response_in_turn(self):
        self.dialog.add_buttons('_Cancel', Gtk.ResponseType.CANCEL,
                                '_OK', Gtk.ResponseType.OK)
        for response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK):
            self.assertIsNotNone(
                self.dialog.get_widget_for_response(response))

    def test_a_widget_in_the_button_row_answers_when_it_is_clicked(self):
        button = Gtk.Button(label='Reset')
        self.dialog.add_action_widget(button, Gtk.ResponseType.REJECT)
        button.emit('clicked')
        self.assertEqual(self.answers, [Gtk.ResponseType.REJECT])

    def test_escape_answers_the_dialog_the_way_closing_it_does(self):
        """Escape closed a Gtk.Dialog, so what it answered with is what
        its delete event answered with. Anything written against that -
        the enhancement dialog is - hears nothing from a CANCEL."""
        self.dialog.present()
        pump()
        self.assertTrue(self.dialog._escaped())
        self.assertEqual(self.answers, [Gtk.ResponseType.DELETE_EVENT])

# vim: expandtab:sw=4:ts=4
