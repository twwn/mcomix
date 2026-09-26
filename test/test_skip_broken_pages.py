""" "Skip pages that cannot be shown": turning past a page that will not
load, the way the reader was going, rather than showing the picture of
a missing page in its place. """

import os
import shutil
import zipfile

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

    def _archive(self, name, pages):
        """A zip archive beside the others, of pages as _book() makes
        them.  Returns its path."""
        book = os.path.join(self.tmp_dir, 'book')
        paths = self._book(pages)
        archive = os.path.join(self.tmp_dir, name)
        with zipfile.ZipFile(archive, 'w') as zipped:
            for path in paths:
                zipped.write(path, os.path.basename(path))
        shutil.rmtree(book)
        return archive

    def _in(self, archive):
        """The page on screen once <archive> is the book open."""
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.get_path_to_base() == archive
            and self.window.imagehandler.get_number_of_pages() > 0))
        return self._settled()

    def test_turning_forward_past_the_last_good_page_opens_the_next_book(self):
        """Pages that will not load, up to the end, are as good as none."""
        first = self._archive('1.zip', 'ooxx')
        second = self._archive('2.zip', 'oo')
        self._open(first)
        self.assertEqual(2, self._turn(self.window.set_page, 2))
        self.window.flip_page(1)
        self.assertEqual(1, self._in(second))

    def test_turning_back_past_the_first_good_page_opens_the_previous(self):
        first = self._archive('1.zip', 'oo')
        second = self._archive('2.zip', 'xxoo')
        self.assertEqual(3, self._open(second))
        self.window.flip_page(-1)
        self.assertEqual(2, self._in(first))

    def test_with_nothing_to_open_the_reader_stays_where_they_were(self):
        prefs['auto open next archive'] = False
        first = self._archive('1.zip', 'ooxx')
        self._archive('2.zip', 'oo')
        self._open(first)
        self.assertEqual(2, self._turn(self.window.set_page, 2))
        for _turn in range(2):
            self.assertEqual(2, self._turn(self.window.flip_page, 1))
            self.assertEqual(first, self.window.filehandler.get_path_to_base())

    def test_a_slideshow_goes_past_them_into_the_next_book(self):
        """A slideshow turns pages through flip_page() as a key does,
        and may open the next book where the reader's turns would not."""
        prefs['auto open next archive'] = False
        prefs['slideshow delay'] = 60000
        prefs['number of pixels to scroll per slideshow event'] = 0
        first = self._archive('1.zip', 'ooxx')
        second = self._archive('2.zip', 'oo')
        self._open(first)
        self.assertEqual(2, self._turn(self.window.set_page, 2))
        slideshow = self.window.slideshow
        slideshow._start()
        try:
            slideshow._next()
            self.assertEqual(1, self._in(second))
        finally:
            slideshow._stop()

    def test_end_onto_a_page_that_will_not_load_still_turns_back(self):
        """End is a jump, not a turn: it stays in the book."""
        first = self._archive('1.zip', 'ooxx')
        self._archive('2.zip', 'oo')
        self._open(first)
        self.assertEqual(2, self._turn(self.window.last_page))
        self.assertEqual(first, self.window.filehandler.get_path_to_base())


class SkipBrokenPagesInTheSidebarTest(MComixTest):
    """The thumbnail sidebar leaves out the pages the reader skips."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['skip broken pages'] = True
        prefs['default double page'] = False
        prefs['show thumbnails'] = True
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.sidebar = self.window.thumbnailsidebar
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    _book = SkipBrokenPagesTest._book
    _settled = SkipBrokenPagesTest._settled

    def _open(self, pages):
        """Open a book of <pages>, as _book() spells them, once every
        thumbnail on screen has been made."""
        self.window.filehandler.open_file(self._book(pages)[0])
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.file_loaded
            and self.window.imagehandler.get_number_of_pages() > 0))
        self.sidebar.load_thumbnails()
        self.assertTrue(wait_for(lambda: all(
            item.thumbnail is not None
            for item in self.sidebar._list.store)))
        return self._settled()

    def _rows(self):
        return [item.uid for item in self.sidebar._list.each_item()]

    def test_a_page_that_will_not_load_has_no_row(self):
        self._open('oxxo')
        self.assertEqual([1, 4], self._rows())

    def test_without_the_preference_every_page_has_its_row(self):
        prefs['skip broken pages'] = False
        self._open('oxxo')
        self.assertEqual([1, 2, 3, 4], self._rows())

    def test_turning_the_preference_on_or_off_lists_them_again(self):
        self._open('oxxo')
        prefs['skip broken pages'] = False
        self.sidebar.refilter()
        self.assertEqual([1, 2, 3, 4], self._rows())
        prefs['skip broken pages'] = True
        self.sidebar.refilter()
        self.assertEqual([1, 4], self._rows())

    def test_the_row_selected_is_the_page_being_read(self):
        self.assertEqual(1, self._open('oxxo'))
        self.window.flip_page(1)
        self.assertEqual(4, self._settled())
        row = self.sidebar._list.get_selected_row()
        self.assertEqual((1, 4), (row, self.sidebar._list.page_at(row)))

    def test_a_row_turns_to_its_own_page(self):
        self._open('oxoxo')
        self.assertEqual([1, 3, 5], self._rows())
        self.sidebar._row_activated(self.sidebar._list, 2)
        self.assertEqual(5, self._settled())
