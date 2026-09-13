# -*- coding: utf-8 -*-

""" A window that actually starts, with its parts where they belong.

Most of the suite exercises pieces in isolation; nothing else builds the
real window, which is where a whole class of start-up regressions hides.
"""

import os

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

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
        # interpreter will not exit.  It leaves the window itself behind,
        # and a GTK4 toplevel that is never destroyed goes on taking part
        # in the display's layout - the next test's window came out with
        # nothing allocated to it.
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        self._pump()
        super(MainWindowTest, self).tearDown()

    def _pump(self, rounds=2000):
        pump(rounds)

    @staticmethod
    def _children(widget):
        children = []
        child = widget.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def test_the_tool_bar_has_its_buttons(self):
        buttons = [item for item in self._children(self.window.toolbar)
                   if isinstance(item, Gtk.Button)]
        self.assertTrue(buttons, 'the tool bar is empty')
        self.assertTrue(all(button.get_visible() for button in buttons),
                        'a tool bar of hidden buttons collapses to nothing')

    def test_every_tool_bar_button_answers_to_an_action(self):
        for button in self._children(self.window.toolbar):
            if not isinstance(button, Gtk.Button):
                continue
            self.assertIsNotNone(button.get_action_name(),
                                 'a tool bar button does nothing')

    def test_the_tool_bar_takes_up_room(self):
        # It was packed, and its buttons were not shown, so it came out
        # seven pixels tall and looked like it had gone.
        self.window.toolbar.set_visible(True)
        wait_for(lambda: self.window.toolbar.get_height() > 20)
        self.assertGreater(self.window.toolbar.get_height(), 20)

    def test_the_menu_bar_has_its_menus(self):
        self.assertTrue(self._children(self.window.menubar),
                        'the menu bar is empty')

    def test_the_window_holds_the_expected_parts(self):
        for part in (self.window.menubar, self.window.toolbar,
                     self.window.statusbar, self.window.thumbnailsidebar):
            self.assertIsNotNone(part.get_parent(),
                                 '%r was never packed' % part)

# vim: expandtab:sw=4:ts=4
