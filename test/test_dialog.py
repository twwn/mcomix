# -*- coding: utf-8 -*-

"""The window MComix' dialogs are built out of.

Gtk.Dialog is deprecated as of GTK 4.10 and has no replacement for what
MComix uses it for: Gtk.AlertDialog answers for a message and two
buttons, and anything else is meant to be an ordinary window that lays
its own buttons out. These pin the shape all of them shared.
"""

from gi.repository import Gtk

from . import MComixTest, pump, wait_for

from mcomix import dialog
from mcomix import message_dialog
from mcomix.dialog import Response
from mcomix.preferences import prefs


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
        button = self.dialog.add_button('_Apply', Response.APPLY)
        button.emit('clicked')
        self.assertEqual(self.answers, [Response.APPLY])

    def test_the_button_for_a_response_can_be_found_again(self):
        button = self.dialog.add_button('_Close', Response.CLOSE)
        self.assertIs(
            self.dialog.get_widget_for_response(Response.CLOSE),
            button)
        self.assertIsNone(
            self.dialog.get_widget_for_response(Response.OK))

    def test_a_button_is_in_the_window_too(self):
        button = self.dialog.add_button('_OK', Response.OK)
        self.assertIs(button.get_root(), self.dialog)

    def test_the_default_response_is_the_default_widget(self):
        self.dialog.add_button('_Cancel', Response.CANCEL)
        ok = self.dialog.add_button('_OK', Response.OK)
        self.dialog.set_default_response(Response.OK)
        self.assertIs(self.dialog.get_default_widget(), ok)

    def test_a_default_response_nobody_added_a_button_for_is_ignored(self):
        self.dialog.set_default_response(Response.OK)
        self.assertIsNone(self.dialog.get_default_widget())

    def test_a_response_can_be_disabled_and_enabled(self):
        button = self.dialog.add_button('_OK', Response.OK)
        self.dialog.set_response_sensitive(Response.OK, False)
        self.assertFalse(button.get_sensitive())
        self.dialog.set_response_sensitive(Response.OK, True)
        self.assertTrue(button.get_sensitive())

    def test_answering_it_directly_reaches_whoever_is_listening(self):
        self.dialog.response(Response.YES)
        self.assertEqual(self.answers, [Response.YES])

    def test_closing_the_window_answers_the_dialog(self):
        self.dialog.emit('close-request')
        self.assertEqual(self.answers, [Response.DELETE_EVENT])

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
            button = subclass.add_button('_OK', Response.OK)
            subclass.set_default_response(Response.OK)
            self.assertIs(
                subclass.get_widget_for_response(Response.OK), button)
            self.assertEqual(subclass._buttons, [])
        finally:
            subclass.destroy()

    def test_add_buttons_adds_each_label_and_response_in_turn(self):
        self.dialog.add_buttons('_Cancel', Response.CANCEL,
                                '_OK', Response.OK)
        for response in (Response.CANCEL, Response.OK):
            self.assertIsNotNone(
                self.dialog.get_widget_for_response(response))

    def test_a_widget_in_the_button_row_answers_when_it_is_clicked(self):
        button = Gtk.Button(label='Reset')
        self.dialog.add_action_widget(button, Response.REJECT)
        button.emit('clicked')
        self.assertEqual(self.answers, [Response.REJECT])

    def test_escape_answers_the_dialog_the_way_closing_it_does(self):
        """Escape closed a Gtk.Dialog, so what it answered with is what
        its delete event answered with. Anything written against that -
        the enhancement dialog is - hears nothing from a CANCEL."""
        self.dialog.present()
        pump()
        self.assertTrue(self.dialog._escaped())
        self.assertEqual(self.answers, [Response.DELETE_EVENT])


class ResponseTest(MComixTest):

    """The numbers a dialog answers with.

    An answer the user has asked to have remembered is written to the
    preferences file as its number, so these are a storage format and
    not only an internal vocabulary.  They were Gtk.ResponseType, which
    GTK deprecated in 4.20; anyone renumbering them would silently turn
    every answer already stored into a different one.
    """

    def test_the_numbers_are_the_ones_already_in_preferences_files(self):
        self.assertEqual(
            {member.name: int(member) for member in dialog.Response},
            {'NONE': -1, 'REJECT': -2, 'ACCEPT': -3, 'DELETE_EVENT': -4,
             'OK': -5, 'CANCEL': -6, 'CLOSE': -7, 'YES': -8, 'NO': -9,
             'APPLY': -10, 'HELP': -11})


class MessageDialogTest(MComixTest):

    """What the dialog that carries a message is told when it is built.

    A Gtk.DialogFlags bitfield and a Gtk.MessageType used to say; GTK
    deprecated the first in 4.20, the second picked an icon this dialog
    has never drawn, and only one bit of the first was ever read.
    """

    def setUp(self):
        super(MessageDialogTest, self).setUp()
        self.parent = Gtk.Window()
        self.dialogs = []

    def tearDown(self):
        for built in self.dialogs:
            built.destroy()
        self.parent.destroy()
        pump()
        super(MessageDialogTest, self).tearDown()

    def _build(self, **kwargs):
        built = message_dialog.MessageDialog(self.parent, **kwargs)
        self.dialogs.append(built)
        return built

    def test_a_dialog_holds_no_input_and_outlives_its_parent_by_default(self):
        built = self._build()
        self.assertFalse(built.get_modal())
        self.assertFalse(built.get_destroy_with_parent())

    def test_a_dialog_asked_to_be_modal_is(self):
        self.assertTrue(self._build(modal=True).get_modal())

    def test_a_dialog_can_be_told_to_go_when_its_parent_does(self):
        """The library's cover-size dialog asked for this through the
        flags and never got it: the one bit that was read was modality,
        and the rest of the bitfield went nowhere."""
        self.assertTrue(
            self._build(destroy_with_parent=True).get_destroy_with_parent())

    def test_the_buttons_asked_for_are_the_buttons_built(self):
        built = self._build(buttons=Gtk.ButtonsType.YES_NO)
        self.assertIsNotNone(built.get_widget_for_response(Response.YES))
        self.assertIsNotNone(built.get_widget_for_response(Response.NO))

    # -- Answers the reader asked not to be asked for again ---------------

    def _remembering(self, dialog_id='a-dialog'):
        """A dialog offering to remember an OK, as the ones that delete
        something do."""
        built = self._build(buttons=Gtk.ButtonsType.OK_CANCEL)
        built.set_should_remember_choice(dialog_id, (Response.OK,))
        return built

    def test_an_answer_that_was_remembered_is_given_without_asking(self):
        prefs['stored dialog choices']['a-dialog'] = int(Response.OK)
        built = self._remembering()
        answers = []
        built.run_async(answers.append)
        self.assertFalse(built.get_visible(), 'it asked anyway')
        self.assertTrue(wait_for(lambda: answers), 'it never answered')
        self.assertEqual([int(Response.OK)], answers)

    def test_clearing_the_choices_makes_it_ask_again(self):
        """Emptying the dictionary is what the preferences dialog's
        "Clear dialog choices" does, and it is the only way back."""
        prefs['stored dialog choices']['a-dialog'] = int(Response.OK)
        prefs['stored dialog choices'] = {}
        built = self._remembering()
        built.run_async(lambda response: None)
        pump()
        self.assertTrue(built.get_visible(),
                        'it answered out of a choice that was cleared')

    def test_only_the_answers_it_was_told_to_remember_are_kept(self):
        """The tick is offered beside every button, and a Cancel that
        was remembered would be a dialog that can never say yes again."""
        built = self._remembering()
        built.run_async(lambda response: None)
        built.remember_checkbox.set_active(True)
        built.response(Response.CANCEL)
        pump()
        self.assertEqual({}, prefs['stored dialog choices'])

    def test_the_answer_it_was_told_to_remember_is_kept(self):
        built = self._remembering()
        built.run_async(lambda response: None)
        built.remember_checkbox.set_active(True)
        built.response(Response.OK)
        pump()
        self.assertEqual({'a-dialog': int(Response.OK)},
                         prefs['stored dialog choices'])

    def test_nothing_is_remembered_without_the_tick(self):
        built = self._remembering()
        built.run_async(lambda response: None)
        built.response(Response.OK)
        pump()
        self.assertEqual({}, prefs['stored dialog choices'])

    def test_the_shape_it_used_to_be_called_in_is_refused(self):
        """Everything after the parent is keyword-only, so a call left
        in the old order raises rather than quietly reading a button set
        as a bitfield of flags."""
        with self.assertRaises(TypeError):
            message_dialog.MessageDialog(self.parent, 0, 0,
                                         Gtk.ButtonsType.OK)

# vim: expandtab:sw=4:ts=4
