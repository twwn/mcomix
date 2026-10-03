"""The slideshow, which turns or scrolls the page on a timer."""

import os
import unittest.mock

from gi.repository import GLib

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.preferences import prefs


class SlideshowTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        # A long delay, so that no tick comes of its own accord.
        prefs['slideshow delay'] = 60000
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 1,
            seconds=20))
        pump()
        self.slideshow = self.window.slideshow
        self.action = self.window.actiongroup.get_action('slideshow')

    def tearDown(self):
        self.action.set_active(False)
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _button(self):
        button = self.window.uimanager.slideshow_button
        return (button.get_child().get_icon_name(),
                button.get_tooltip_text())

    def test_starting_and_stopping_says_so_on_the_button(self):
        self.action.set_active(True)
        self.assertTrue(self.slideshow.is_running())
        self.assertEqual(('media-playback-stop-symbolic', 'Stop slideshow'),
                         self._button())
        self.action.set_active(False)
        self.assertFalse(self.slideshow.is_running())
        self.assertEqual(('media-playback-start-symbolic', 'Start slideshow'),
                         self._button())

    def test_a_tick_turns_the_page_and_keeps_going(self):
        prefs['number of pixels to scroll per slideshow event'] = 0
        page = self.window.imagehandler.get_current_page()
        self.assertTrue(self.slideshow._next())
        self.assertEqual(page + 1, self.window.imagehandler.get_current_page())

    def test_a_tick_scrolls_where_the_preferences_say_so(self):
        prefs['number of pixels to scroll per slideshow event'] = 40
        with unittest.mock.patch.object(
                self.window, 'scroll_with_flipping') as scrolled:
            self.assertTrue(self.slideshow._next())
        scrolled.assert_called_once_with(0, 40)

    def test_a_new_delay_restarts_a_running_slideshow_on_it(self):
        self.action.set_active(True)
        before = self.slideshow._id
        prefs['slideshow delay'] = 50000
        self.slideshow.update_delay()
        self.assertTrue(self.slideshow.is_running())
        self.assertNotEqual(before, self.slideshow._id)
        # The timer it replaced is gone.
        self.assertIsNone(
            GLib.MainContext.default().find_source_by_id(before))

    def test_a_new_delay_leaves_a_stopped_slideshow_stopped(self):
        self.slideshow.update_delay()
        self.assertFalse(self.slideshow.is_running())
