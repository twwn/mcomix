""" "Skip pages that cannot be shown": turning past a page that will not
load, the way the reader was going, rather than showing the picture of
a missing page in its place. """

import os
import shutil

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.preferences import prefs


class SkipBrokenPagesTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['skip broken pages'] = True
        prefs['default double page'] = False
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _book(self, pages):
        """A directory of images, one per character of <pages>: 'o' for
        one that loads, 'x' for one that will not.  Returns the paths."""
        book = os.path.join(self.tmp_dir, 'book')
        os.makedirs(book)
        paths = []
        for number, kind in enumerate(pages, 1):
            path = os.path.join(book, '%02d.png' % number)
            if kind == 'o':
                shutil.copyfile(get_testfile_path('images', 'red.png'), path)
            else:
                with open(path, 'wb') as broken:
                    broken.write(b'\x89PNG\r\n\x1a\n not a picture')
            paths.append(path)
        return paths

    def _open(self, path):
        self.window.filehandler.open_file(path)
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.file_loaded
            and self.window.imagehandler.get_number_of_pages() > 0))
        return self._settled()

    def _settled(self):
        """The page on screen once the redraws, and the turns past pages
        that would not load, have run out."""
        for _round in range(50):
            pump()
            if not self.window._waiting_for_redraw:
                pump()
                if not self.window._waiting_for_redraw:
                    break
        return self.window.imagehandler.get_current_page()

    def _turn(self, turn, *args):
        turn(*args)
        return self._settled()

    def test_turning_forward_goes_past_a_page_that_will_not_load(self):
        paths = self._book('oxxo')
        self.assertEqual(1, self._open(paths[0]))
        self.assertEqual(4, self._turn(self.window.flip_page, 1))

    def test_turning_back_goes_past_it_the_other_way(self):
        paths = self._book('oxxo')
        self._open(paths[3])
        self.assertEqual(1, self._turn(self.window.flip_page, -1))

    def test_a_book_opened_at_a_page_that_will_not_load_moves_on(self):
        paths = self._book('xxo')
        self.assertEqual(3, self._open(paths[0]))

    def test_end_onto_a_page_that_will_not_load_turns_back(self):
        """There is nothing past the end, so the search turns around."""
        paths = self._book('ooxx')
        self._open(paths[0])
        self.assertEqual(2, self._turn(self.window.last_page))

    def test_home_onto_a_page_that_will_not_load_turns_forward(self):
        paths = self._book('xoox')
        self._open(paths[2])
        self.assertEqual(2, self._turn(self.window.first_page))

    def test_a_jump_past_the_last_good_page_turns_back_from_there(self):
        paths = self._book('ooooxx')
        self._open(paths[0])
        self.assertEqual(4, self._turn(self.window.set_page, 5))

    def test_a_book_of_pages_that_will_not_load_shows_the_one_turned_to(self):
        paths = self._book('xxxx')
        self._open(paths[0])
        self.assertEqual(3, self._turn(self.window.set_page, 3))
        self.assertTrue(self.window._skip_gave_up)

    def test_off_the_page_that_will_not_load_is_shown(self):
        prefs['skip broken pages'] = False
        paths = self._book('oxo')
        self._open(paths[0])
        self.assertEqual(2, self._turn(self.window.flip_page, 1))

    def test_in_double_page_mode_a_broken_partner_leaves_its_page_alone(self):
        prefs['default double page'] = True
        paths = self._book('oxoo')
        self.assertEqual(1, self._open(paths[0]))
        self.assertFalse(self.window.displayed_double())
        self.assertEqual(3, self._turn(self.window.flip_page, 1))
        self.assertTrue(self.window.displayed_double())
