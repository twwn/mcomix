"""The slideshow, which turns or scrolls the page on a timer."""

import unittest.mock

from gi.repository import GLib

from . import MComixTest, NORMAL_ZIP, pump, wait_for

from mcomix.preferences import prefs


class SlideshowTest(MComixTest):

    def setUp(self):
        super().setUp()
        # A long delay, so that no tick comes of its own accord.
        prefs['slideshow delay'] = 60000
        self.open_main_window_on_a_book()
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 1,
            seconds=20))
        pump()
        self.slideshow = self.window.slideshow
        self.action = self.window.actiongroup.get_action('slideshow')

    def tearDown(self):
        self.action.set_active(False)
        self.close_main_window()
        super().tearDown()

    def _button(self):
        button = self.window.uimanager.slideshow_button
        return (button.get_child().get_icon_name(),
                button.get_tooltip_text())

    def test_the_screen_is_kept_on_for_as_long_as_it_runs(self):
        """Nobody touches a key during a slideshow, so the desktop
        dimmed and locked the screen in the middle of it."""
        screen = self.slideshow._screen
        self.assertFalse(screen.is_held())
        self.action.set_active(True)
        self.assertTrue(screen.is_held())
        self.slideshow.update_delay()
        self.assertTrue(screen.is_held())
        self.action.set_active(False)
        self.assertFalse(screen.is_held())

    def test_closing_the_book_lets_the_screen_go(self):
        self.action.set_active(True)
        self.window.filehandler.close_file()
        pump()
        self.assertFalse(self.slideshow._screen.is_held())

    def test_closing_the_book_ends_it(self):
        """It went on with no book, its toggle out of reach, and turned
        the pages of whichever book was opened next."""
        self.action.set_active(True)
        self.window.filehandler.close_file()
        pump()
        self.assertFalse(self.slideshow.is_running())
        self.assertFalse(self.action.get_active())
        self.assertEqual('media-playback-start-symbolic', self._button()[0])
        self.window.filehandler.open_file(NORMAL_ZIP)
        self.assertTrue(wait_for(lambda: self.window.filehandler.file_loaded))
        self.assertFalse(self.slideshow.is_running())
        self.assertNotIn('SLIDESHOW', self.window.get_title())

    def test_a_book_opened_over_the_last_keeps_it_going(self):
        """Which is how it goes on to the next book."""
        self.action.set_active(True)
        self.window.filehandler.open_file(NORMAL_ZIP)
        self.assertTrue(wait_for(lambda: self.window.filehandler.file_loaded))
        self.assertTrue(self.slideshow.is_running())
        self.assertTrue(self.action.get_active())

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
