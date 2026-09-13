# -*- coding: utf-8 -*-

""" A window that actually starts, with its parts where they belong.

Most of the suite exercises pieces in isolation; nothing else builds the
real window, which is where a whole class of start-up regressions hides.
"""

import os

from gi.repository import Gtk

from . import MComixTest, get_testfile_path

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.preferences import prefs


class MainWindowTest(MComixTest):

    def setUp(self):
        super(MainWindowTest, self).setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['show toolbar'] = True
        prefs['show menubar'] = True
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        self._pump()

    def tearDown(self):
        # Only terminate_program() stops the worker threads; without it the
        # interpreter will not exit.
        self.window.terminate_program()
        self._pump()
        super(MainWindowTest, self).tearDown()

    def _pump(self, rounds=2000):
        turns = 0
        while Gtk.events_pending() and turns < rounds:
            Gtk.main_iteration_do(False)
            turns += 1

    def test_the_tool_bar_has_its_buttons(self):
        buttons = [item for item in self.window.toolbar.get_children()
                   if isinstance(item, Gtk.ToolButton)]
        self.assertTrue(buttons, 'the tool bar is empty')
        self.assertTrue(all(button.get_visible() for button in buttons),
                        'a tool bar of hidden buttons collapses to nothing')

    def test_the_tool_bar_takes_up_room(self):
        # It was packed, and its buttons were not shown, so it came out
        # seven pixels tall and looked like it had gone.
        self.window.toolbar.show()
        self._pump()
        self.assertGreater(self.window.toolbar.get_allocation().height, 20)

    def test_the_menu_bar_has_its_menus(self):
        self.assertTrue(self.window.menubar.get_children())

    def test_the_window_holds_the_expected_parts(self):
        for part in (self.window.menubar, self.window.toolbar,
                     self.window.statusbar, self.window.thumbnailsidebar):
            self.assertIsNotNone(part.get_parent(),
                                 '%r was never packed' % part)

# vim: expandtab:sw=4:ts=4
