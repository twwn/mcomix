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
from mcomix import widgets
from mcomix.dialog import Response
from mcomix.preferences import prefs


class DialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.dialog = dialog.Dialog(title='Test')
        self.answers = []
        self.dialog.connect('response', lambda _d, r: self.answers.append(r))

    def tearDown(self):
        # A dialog left on screen is answered by whatever looks for one
        # next.
        self.dialog.destroy()
        pump()
        super().tearDown()

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

    def test_a_destroyed_dialog_lets_go_of_the_focus_before_its_surface(self):
        # On Windows the text field holding the focus registers a filter
        # for the window's messages and takes it off only when it loses
        # the focus while the window still has its surface.  Left there,
        # the filter outlived the field it belongs to, and the next
        # window's messages reached freed memory: a crash, in some later
        # test or in the reader's session.
        entry = Gtk.Entry()
        self.dialog.get_content_area().append(entry)
        self.dialog.present()
        pump()
        entry.grab_focus()
        self.assertIsNotNone(self.dialog.get_focus())
        focus_when_unrealized = []
        entry.connect('unrealize', lambda _entry: focus_when_unrealized.append(
            self.dialog.get_focus()))
        self.dialog.destroy()
        self.assertEqual(focus_when_unrealized, [None])

    def test_a_subclass_may_keep_a_list_of_its_own_buttons(self):
        # The file chooser does, under the name _buttons, which is what
        # this base used to keep its own responses in: it was silently
        # emptied the moment the subclass ran its constructor.
        class _WithButtons(dialog.Dialog):
            def __init__(self):
                super().__init__()
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
        super().setUp()
        self.parent = Gtk.Window()
        self.dialogs = []

    def tearDown(self):
        for built in self.dialogs:
            built.destroy()
        self.parent.destroy()
        pump()
        super().tearDown()

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

    def test_a_closed_dialog_lets_go_of_the_window_it_was_over(self):
        """GTK 4.14 left a window it destroyed with its parent pointing
        at that parent, which was then freed, and freeing the dialog
        afterwards disconnected its handlers from freed memory: a
        segmentation fault in gc.collect() on the CI.  A dialog that has
        closed no longer names the window it was over, whichever of the
        two goes first."""
        for destroy_with_parent in (False, True):
            with self.subTest(destroy_with_parent=destroy_with_parent):
                built = self._build(destroy_with_parent=destroy_with_parent)
                self.assertIs(built.get_transient_for(), self.parent)
                built.destroy()
                pump()
                self.assertIsNone(built.get_transient_for())

    def test_the_buttons_asked_for_are_the_buttons_built(self):
        built = self._build(buttons=Gtk.ButtonsType.YES_NO)
        self.assertIsNotNone(built.get_widget_for_response(Response.YES))
        self.assertIsNotNone(built.get_widget_for_response(Response.NO))

    # -- Answers the reader asked not to be asked for again ---------------

    #: A prompt whose only remembered answer is an OK, as the ones that
    #: delete something are.
    _PROMPT = message_dialog.RememberedDialog.DELETE_OPENED_FILE

    def _remembering(self):
        """A dialog offering to remember an OK.

        Which answers the tick keeps is not the dialog's to say: it
        comes from what message_dialog.REMEMBERED_DIALOGS records about
        the prompt, so that nothing can be answered for good without the
        preferences dialog being able to list it.
        """
        built = self._build(buttons=Gtk.ButtonsType.OK_CANCEL)
        built.set_should_remember_choice(self._PROMPT)
        return built

    def test_an_answer_that_was_remembered_is_given_without_asking(self):
        prefs['stored dialog choices'][self._PROMPT] = int(Response.OK)
        built = self._remembering()
        answers = []
        built.run_async(answers.append)
        self.assertFalse(built.get_visible(), 'it asked anyway')
        self.assertTrue(wait_for(lambda: answers), 'it never answered')
        self.assertEqual([int(Response.OK)], answers)

    def test_clearing_the_choices_makes_it_ask_again(self):
        """Emptying the dictionary is what the preferences dialog's
        "Clear dialog choices" does, and it is the only way back."""
        prefs['stored dialog choices'][self._PROMPT] = int(Response.OK)
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
        self.assertEqual({self._PROMPT: int(Response.OK)},
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

    # -- When it is taken down ---------------------------------------------

    def test_the_dialog_is_gone_before_the_answer_is_delivered(self):
        """The order the callers need: more than one of them closes the
        book or opens the next, and closing turns the main loop over,
        which would paint a dialog that had been answered and not yet
        taken down."""
        built = self._build(buttons=Gtk.ButtonsType.OK_CANCEL)
        standing = []
        built.run_async(lambda response: standing.append(built.get_visible()))
        built.response(Response.OK)
        pump()
        self.assertEqual([False], standing)

    def test_a_widget_it_carried_can_still_be_read_in_the_answer(self):
        """Which is what lets the callers that ask for something typed
        read it in the callback like any other: destroying a window
        neither unparents its children nor finalises them while there is
        still a reference to them."""
        built = self._build(buttons=Gtk.ButtonsType.OK_CANCEL)
        entry = Gtk.Entry()
        widgets.pack(built.get_content_area(), entry, True, True, 0)
        typed = []
        built.run_async(lambda response: typed.append(entry.get_text()))
        entry.set_text('a password')
        built.response(Response.OK)
        pump()
        self.assertEqual(['a password'], typed)

    def test_an_adjustment_it_carried_can_be_read_as_well(self):
        """The library's cover size dialog reads one of these, which is
        a plain object the caller holds rather than a widget at all."""
        built = self._build(buttons=Gtk.ButtonsType.OK)
        adjustment = Gtk.Adjustment.new(80, 20, 500, 10, 25, 0)
        widgets.pack(built.get_content_area(),
                     Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, adjustment),
                     True, True, 0)
        chosen = []
        built.run_async(lambda response: chosen.append(adjustment.get_value()))
        adjustment.set_value(120)
        built.response(Response.OK)
        pump()
        self.assertEqual([120.0], chosen)

# vim: expandtab:sw=4:ts=4
