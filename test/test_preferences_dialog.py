"""The preferences dialog, and the state its controls come up in.

A pair of radio buttons stands for one either/or preference. Two of them
were given a preference each instead, and the one the first button was
given is not a preference at all: nothing reads it, and reading the
preferences file drops what it does not know, so whatever the button
said went out with the wash.
"""

import os
import unittest.mock

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import constants
from mcomix import i18n
from mcomix import icons
from mcomix import main
from mcomix import message_dialog
from mcomix import preferences_dialog
from mcomix import image_tools
from mcomix.dialog import Response
from mcomix.preferences import prefs


class PreferencesDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    dialog = None

    def _open(self):
        self.dialog = preferences_dialog._PreferencesDialog(self.window)
        pump()
        return self.dialog

    def test_the_gap_between_two_pages_goes_up_to_the_largest_gap(self):
        """The spinner stopped at 2 pixels, too narrow a gutter to see."""
        bounds = {}
        original = preferences_dialog._PreferencesDialog._create_pref_spinner

        def record(dialog, prefkey, scale, lower, upper, *rest):
            bounds[prefkey] = (lower, upper)
            return original(dialog, prefkey, scale, lower, upper, *rest)

        with unittest.mock.patch.object(
                preferences_dialog._PreferencesDialog,
                '_create_pref_spinner', record):
            self._open()
        self.assertEqual((0, preferences_dialog.LARGEST_PAGE_GAP),
                         bounds['space between two pages'])
        self.assertEqual(100, preferences_dialog.LARGEST_PAGE_GAP)

    def _background_buttons(self):
        """The two buttons of the Background section, in the order they
        are shown: the fixed colour, then the one off the page."""
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.CheckButton):
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(self.dialog.notebook.get_nth_page(0))
        fixed = [button for button in found
                 if button.get_label() == 'Use this colour as background:']
        dynamic = [button for button in found
                   if button.get_label() == 'Use dynamic background colour']
        self.assertTrue(fixed and dynamic, 'the pair was not built')
        return fixed[0], dynamic[0]

    # -- What the pair shows ----------------------------------------------

    def test_turning_pages_by_their_metadata_turns_the_thumbnails_too(self):
        """The sidebar's thumbnails are turned as the pages are, so
        changing the preference has to make them again, not only
        redraw the page."""
        dialog = self._open()
        button = Gtk.CheckButton(active=not prefs['auto rotate from exif'])
        with unittest.mock.patch.object(self.window.thumbnailsidebar,
                                        'resize') as remade:
            dialog._check_button_cb(button, 'auto rotate from exif')
        remade.assert_called_once_with()
        self.assertEqual(prefs['auto rotate from exif'], button.get_active())

    def test_the_pair_shows_the_colour_the_preference_names(self):
        prefs['smart bg'] = False
        self._open()
        fixed, dynamic = self._background_buttons()
        self.assertTrue(fixed.get_active(),
                        'the dialog came up showing neither of the two')
        self.assertFalse(dynamic.get_active())

    def test_the_pair_shows_the_colour_off_the_page(self):
        prefs['smart bg'] = True
        self._open()
        fixed, dynamic = self._background_buttons()
        self.assertTrue(dynamic.get_active())
        self.assertFalse(fixed.get_active())

    # -- What picking one writes ------------------------------------------

    def test_picking_the_colour_off_the_page_is_remembered(self):
        prefs['smart bg'] = False
        self._open()
        _fixed, dynamic = self._background_buttons()
        dynamic.set_active(True)
        self.assertTrue(prefs['smart bg'])

    def test_picking_a_fixed_colour_is_remembered(self):
        prefs['smart bg'] = True
        self._open()
        fixed, _dynamic = self._background_buttons()
        fixed.set_active(True)
        self.assertFalse(prefs['smart bg'])

    def test_the_pair_writes_no_key_that_is_not_a_preference(self):
        """The first button had a key of its own, which is not a
        preference at all: nothing reads it, and reading the preferences
        file back drops every key it does not know."""
        known = set(prefs)
        self._open()
        fixed, dynamic = self._background_buttons()
        for button in (fixed, dynamic, fixed):
            button.set_active(True)
        self.assertEqual(set(prefs) - known, set())

    # -- The colour the fixed button stands beside -------------------------

    def _colour_buttons(self):
        """The colour buttons of the Background section, in the order
        they are shown: the page background, then the thumbnails'."""
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.ColorDialogButton):
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(self.dialog.notebook.get_nth_page(0))
        self.assertTrue(found, 'no colour button was built')
        return found

    def test_picking_a_background_colour_is_remembered(self):
        """Gtk.ColorButton said 'color-set' once a colour had been
        picked.  What replaced it says nothing of the kind: the colour
        arrives as a change to the rgba property, and a button left
        listening for the old signal would hear nothing at all."""
        prefs['bg colour'] = [0.0, 0.0, 0.0, 1.0]
        self._open()
        self._colour_buttons()[0].set_rgba(image_tools.rgba(0.25, 0.5, 0.75, 1.0))
        self.assertEqual([round(value, 2) for value in prefs['bg colour']],
                         [0.25, 0.5, 0.75, 1.0])

    def test_a_colour_button_comes_up_showing_the_colour_it_stands_for(self):
        prefs['thumb bg colour'] = [1.0, 0.0, 0.5, 1.0]
        self._open()
        rgba = self._colour_buttons()[1].get_rgba()
        self.assertEqual([round(value, 2) for value in
                          (rgba.red, rgba.green, rgba.blue, rgba.alpha)],
                         [1.0, 0.0, 0.5, 1.0])

    def test_the_thumbnail_pair_is_the_same_arrangement(self):
        prefs['smart thumb bg'] = False
        self._open()
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.CheckButton):
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(self.dialog.notebook.get_nth_page(0))
        fixed = [button for button in found
                 if button.get_label()
                 == 'Use this colour as the thumbnail background:']
        self.assertTrue(fixed and fixed[0].get_active())

    # -- Taking back a "Do not ask again" ----------------------------------

    _DELETE = message_dialog.RememberedDialog.DELETE_OPENED_FILE
    _REMOVE = message_dialog.RememberedDialog.LIBRARY_REMOVE_BOOK_FROM_DISK
    _RESUME = message_dialog.RememberedDialog.RESUME_FROM_LAST_READ_PAGE

    def _choosers(self):
        """What each prompt is answered with, by the prompt.

        The Behaviour tab builds one chooser per entry of
        message_dialog.REMEMBERED_DIALOGS, in that order.
        """
        return dict(zip(message_dialog.REMEMBERED_DIALOGS,
                        self._open()._remembered_answers))

    def test_every_prompt_that_can_be_answered_for_good_is_listed(self):
        """A prompt with nowhere to take its answer back can only be
        cleared along with every other one."""
        choosers = self._choosers()
        self.assertEqual(list(message_dialog.REMEMBERED_DIALOGS),
                         list(choosers))
        for prompt, chooser in choosers.items():
            self.assertIsNotNone(chooser.get_parent(),
                                 '%s is on no page' % prompt)

    def test_a_prompt_that_was_never_answered_asks_every_time(self):
        for prompt, chooser in self._choosers().items():
            self.assertIsNone(chooser.get_value(), prompt)

    def test_it_shows_the_answer_that_is_stored(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        self.assertEqual(int(Response.OK),
                         self._choosers()[self._DELETE].get_value())

    def test_one_answer_can_be_taken_back_on_its_own(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        prefs['stored dialog choices'][self._REMOVE] = int(Response.YES)
        self._choosers()[self._DELETE].set_value(None)
        pump()
        self.assertEqual({self._REMOVE: int(Response.YES)},
                         prefs['stored dialog choices'])

    def test_an_answer_can_be_given_here_rather_than_at_the_prompt(self):
        """Picking one is the "Do not ask again" tick, without waiting
        for the prompt to come up."""
        self._choosers()[self._RESUME].set_value(int(Response.NO))
        pump()
        self.assertEqual({self._RESUME: int(Response.NO)},
                         prefs['stored dialog choices'])
        self.assertTrue(self.dialog.reset_button.get_sensitive())

    def test_clearing_them_all_puts_every_chooser_back_to_asking(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        choosers = self._choosers()
        self.dialog.response(constants.RESPONSE_REVERT_TO_DEFAULT)
        pump()
        self.assertIsNone(choosers[self._DELETE].get_value())

    def test_the_reset_button_offers_to_clear_the_dialog_choices(self):
        """It is the only way back from a "Do not ask again" tick, and
        the button it lives on says something else on the Shortcuts
        tab."""
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        self._open()
        self.assertEqual('Clear _dialog choices',
                         self.dialog.reset_button.get_label())
        self.assertTrue(self.dialog.reset_button.get_sensitive())

    def test_with_nothing_remembered_there_is_nothing_to_clear(self):
        self._open()
        self.assertFalse(self.dialog.reset_button.get_sensitive())

    def test_pressing_it_forgets_the_answers_and_says_so(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        prefs['stored dialog choices'][self._REMOVE] = int(Response.YES)
        self._open()
        self.dialog.response(constants.RESPONSE_REVERT_TO_DEFAULT)
        pump()
        self.assertEqual({}, prefs['stored dialog choices'])
        self.assertFalse(self.dialog.reset_button.get_sensitive())

    # -- Changing the interface language -----------------------------------

    def _prompts(self):
        """The prompts the dialog has put on screen."""
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_visible()]

    def _pick_language(self, language):
        """Pick <language> in the dialog's language chooser."""
        self._open()
        self.dialog._language_chooser.set_value(language)
        pump()
        return self._prompts()

    def test_picking_another_language_offers_a_restart(self):
        """Most of the interface is translated before any window exists,
        so the language picked here cannot reach the one on screen."""
        prompts = self._pick_language('de')
        self.assertEqual(1, len(prompts))
        self.assertEqual('de', prefs['language'])
        prompts[0].destroy()

    def test_picking_the_language_in_use_offers_nothing(self):
        """A reader who picks another language and then picks the one
        they started in is back where they were."""
        self._open()
        self.dialog._language_chooser.set_value('de')
        pump()
        for prompt in self._prompts():
            prompt.destroy()
        pump()
        self.dialog._language_chooser.set_value('auto')
        pump()
        self.assertEqual([], self._prompts())
        self.assertEqual('auto', prefs['language'])

    def test_the_offer_follows_the_interface_not_the_stored_choice(self):
        """A reader who picks a language and declines the restart leaves
        the preference ahead of the interface, and this dialog is built
        afresh every time it is opened.  A second opening compared the
        next choice against the preference, so picking the language
        actually on screen offered a restart that would change nothing.
        """
        with unittest.mock.patch.object(i18n, '_language_preference',
                                        'auto'):
            # What the earlier, declined choice left behind.
            prefs['language'] = 'de'
            self._open()
            self.dialog._language_chooser.set_value('auto')
            pump()
            self.assertEqual([], self._prompts())
            self.assertEqual('auto', prefs['language'])

    def test_answering_yes_starts_mcomix_again(self):
        restarted = []
        self.window.restart_program = lambda: restarted.append(True)
        prompts = self._pick_language('de')
        prompts[0].response(Response.YES)
        pump()
        self.assertEqual([True], restarted)

    def test_answering_no_leaves_the_program_where_it_is(self):
        """The preference is kept even so: it is what the next start
        reads."""
        restarted = []
        self.window.restart_program = lambda: restarted.append(True)
        prompts = self._pick_language('de')
        prompts[0].response(Response.NO)
        pump()
        self.assertEqual([], restarted)
        self.assertEqual('de', prefs['language'])

    def test_the_shortcuts_tab_offers_the_keys_instead(self):
        """The same button resets the keyboard shortcuts there, so a
        test of one has to know which tab it is on."""
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        self._open()
        shortcuts = self.dialog.notebook.page_num(self.dialog.shortcuts)
        self.dialog.notebook.set_current_page(shortcuts)
        pump()
        self.assertEqual('_Reset keys', self.dialog.reset_button.get_label())
        self.assertEqual({self._DELETE: int(Response.OK)},
                         prefs['stored dialog choices'])

# vim: expandtab:sw=4:ts=4
