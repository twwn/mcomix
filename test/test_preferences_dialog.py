# -*- coding: utf-8 -*-

"""The preferences dialog, and the state its controls come up in.

A pair of radio buttons stands for one either/or preference. Two of them
were given a preference each instead, and the one the first button was
given is not a preference at all: nothing reads it, and reading the
preferences file drops what it does not know, so whatever the button
said went out with the wash.
"""

import os

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix import preferences_dialog
from mcomix.preferences import prefs


class PreferencesDialogTest(MComixTest):

    def setUp(self):
        super(PreferencesDialogTest, self).setUp()
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
        super(PreferencesDialogTest, self).tearDown()

    dialog = None

    def _open(self):
        self.dialog = preferences_dialog._PreferencesDialog(self.window)
        pump()
        return self.dialog

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

# vim: expandtab:sw=4:ts=4
