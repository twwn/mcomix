"""Tests for Go back and Go forward over the pages jumps left (issue 72)."""

import random
import unittest.mock

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import icons
from mcomix import keybindings
from mcomix import main
from mcomix.preferences import prefs


class JumpHistoryTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.make_user_directories()
        prefs['show menubar'] = True
        icons.load_icons()
        keybindings._manager = None
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        # Only terminate_program() stops the worker threads and closes
        # the library the window opened.
        self.addCleanup(self.close_main_window)
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.file_loaded
            and self.window.imagehandler.get_number_of_pages() == 4,
            seconds=20))
        pump()
        self.assertEqual(1, self._page())

    def _page(self):
        return self.window.imagehandler.get_current_page()

    def _sensitive(self, name):
        return self.window.actiongroup.get_action(name).get_sensitive()

    def test_back_returns_to_the_page_a_jump_left(self):
        window = self.window
        window.flip_page(+1)
        self.assertEqual(2, self._page())
        window.last_page()
        self.assertEqual(4, self._page())
        window.go_back()
        self.assertEqual(2, self._page())

    def test_forward_goes_again_where_back_left(self):
        window = self.window
        window.jump_to_page(3)
        window.last_page()
        window.go_back()
        self.assertEqual(3, self._page())
        window.go_back()
        self.assertEqual(1, self._page())
        window.go_forward()
        self.assertEqual(3, self._page())
        window.go_forward()
        self.assertEqual(4, self._page())

    def test_page_turns_are_not_remembered(self):
        window = self.window
        window.flip_page(+1)
        window.flip_page(+1)
        self.assertFalse(window.can_go_back())
        window.go_back()
        self.assertEqual(3, self._page())

    def test_a_jump_drops_what_forward_could_go_to(self):
        window = self.window
        window.jump_to_page(4)
        window.go_back()
        self.assertTrue(window.can_go_forward())
        window.jump_to_page(3)
        self.assertFalse(window.can_go_forward())
        window.go_back()
        self.assertEqual(1, self._page())

    def test_a_jump_to_the_page_on_screen_is_not_remembered(self):
        self.window.first_page()
        self.assertFalse(self.window.can_go_back())

    def test_a_page_turned_to_since_is_passed_over(self):
        """Back from the page a jump left, having turned back to it,
        goes to the jump before."""
        window = self.window
        window.jump_to_page(2)
        window.jump_to_page(4)
        window.flip_page(-1)
        window.flip_page(-1)
        self.assertEqual(2, self._page())
        window.go_back()
        self.assertEqual(1, self._page())

    def test_the_menu_offers_only_what_can_be_gone_to(self):
        window = self.window
        self.assertFalse(self._sensitive('go_back'))
        self.assertFalse(self._sensitive('go_forward'))
        window.last_page()
        self.assertTrue(self._sensitive('go_back'))
        self.assertFalse(self._sensitive('go_forward'))
        window.go_back()
        self.assertFalse(self._sensitive('go_back'))
        self.assertTrue(self._sensitive('go_forward'))

    def test_go_to_page_a_thumbnail_and_a_random_page_are_jumps(self):
        window = self.window
        with unittest.mock.patch.object(random, 'choice',
                                        side_effect=lambda pages: pages[-1]):
            window.random_page()
        self.assertEqual(4, self._page())
        window.thumbnailsidebar._row_activated(None, 2)
        self.assertEqual(3, self._page())
        window.go_back()
        self.assertEqual(4, self._page())
        window.go_back()
        self.assertEqual(1, self._page())

    def test_another_book_forgets_the_pages(self):
        window = self.window
        window.last_page()
        self.assertTrue(window.can_go_back())
        window.filehandler.close_file()
        pump()
        self.assertFalse(window.can_go_back())
        self.assertFalse(self._sensitive('go_back'))

    def test_the_list_is_kept_short(self):
        pages = []
        for page in range(main._JUMPS_KEPT + 10):
            main._remember_page(pages, page % 2)
        # The same page twice in a row is remembered once.
        self.assertEqual([0, 1] * (main._JUMPS_KEPT // 2), pages)
        pages = []
        for page in range(main._JUMPS_KEPT + 10):
            main._remember_page(pages, page)
        self.assertEqual(main._JUMPS_KEPT, len(pages))
        self.assertEqual(main._JUMPS_KEPT + 9, pages[-1])
