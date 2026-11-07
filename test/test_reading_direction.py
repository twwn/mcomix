"""Which way round a book is read.

A book whose ComicInfo.xml says it is read right to left: other readers
open such a book in manga mode; MComix read it left to right unless the
reader turned manga mode on, which then held for every book after it.
The book now puts itself in manga mode, for itself alone, as a book of
long strips puts itself in continuous mode.

A book the reader set either way: it was read the way the toggle was
last set, so a shelf of manga beside western comics read every other
book the wrong way round.  The book now keeps the direction it was set
to, and reads so when it is opened again.
"""

import json
import os
import shutil
import zipfile

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import comicinfo
from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix import reading_directions
from mcomix.preferences import prefs


def _comicinfo(manga):
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<ComicInfo><Series>Night Watch</Series>'
            '<Manga>%s</Manga></ComicInfo>' % manga)


class ReadsRightToLeftTest(MComixTest):

    def _file(self, text):
        path = os.path.join(self.tmp_dir, 'ComicInfo.xml')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def test_only_yes_and_right_to_left_names_a_direction(self):
        for manga, read in (('YesAndRightToLeft', True),
                            (' YesAndRightToLeft\n', True),
                            ('Yes', False), ('No', False),
                            ('Unknown', False), ('', False)):
            with self.subTest(manga=manga):
                self.assertEqual(read, comicinfo.reads_right_to_left(
                    self._file(_comicinfo(manga))))

    def test_a_file_that_is_not_a_comicinfo_says_nothing(self):
        for text in ('not xml at all', '<Other><Manga>YesAndRightToLeft'
                     '</Manga></Other>'):
            with self.subTest(text=text):
                self.assertFalse(comicinfo.reads_right_to_left(
                    self._file(text)))
        self.assertFalse(comicinfo.reads_right_to_left(
            os.path.join(self.tmp_dir, 'missing.xml')))


class StoreTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.book = os.path.join(self.tmp_dir, 'Book.cbz')

    def _file(self):
        return os.path.join(constants.DATA_DIR, 'reading_directions.json')

    def _reload(self):
        reading_directions._loaded = None

    def test_a_direction_is_kept_across_a_start(self):
        self.assertIsNone(reading_directions.direction(self.book))
        reading_directions.remember(self.book, True)
        other = os.path.join(self.tmp_dir, 'Other.cbz')
        reading_directions.remember(other, False)
        self._reload()
        self.assertIs(True, reading_directions.direction(self.book))
        self.assertIs(False, reading_directions.direction(other))

    def test_what_is_not_a_direction_is_dropped_on_reading(self):
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        with open(self._file(), 'w', encoding='utf-8') as handle:
            json.dump({self.book: 'yes', 'other': 1, 'kept': False}, handle)
        self.assertIsNone(reading_directions.direction(self.book))
        self.assertIsNone(reading_directions.direction('other'))
        self.assertIs(False, reading_directions.direction('kept'))

    def test_a_file_that_is_not_json_is_read_as_none(self):
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        with open(self._file(), 'w', encoding='utf-8') as handle:
            handle.write('{not json')
        self.assertIsNone(reading_directions.direction(self.book))
        reading_directions.remember(self.book, True)
        self._reload()
        self.assertIs(True, reading_directions.direction(self.book))

    def test_a_direction_follows_its_book_and_its_folder(self):
        reading_directions.remember(self.book, True)
        moved = os.path.join(self.tmp_dir, 'moved', 'Book.cbz')
        reading_directions.follow(self.book, moved)
        self.assertIsNone(reading_directions.direction(self.book))
        self.assertIs(True, reading_directions.direction(moved))
        shelf = os.path.join(self.tmp_dir, 'shelf')
        self.assertEqual(1, reading_directions.relocate(
            os.path.join(self.tmp_dir, 'moved'), shelf))
        self._reload()
        self.assertIsNone(reading_directions.direction(moved))
        self.assertIs(True, reading_directions.direction(
            os.path.join(shelf, 'Book.cbz')))


class WindowDirectionTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        prefs['default manga mode'] = False

    def _book(self, name, manga=None):
        path = os.path.join(self.tmp_dir, name)
        with zipfile.ZipFile(path, 'w') as book:
            for page in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg'):
                book.write(get_testfile_path('images', page), page)
            if manga is not None:
                book.writestr('ComicInfo.xml', _comicinfo(manga))
        return path

    def _open(self, path):
        self.window = main.MainWindow(open_path=path)
        main.set_main_window(self.window)
        self.addCleanup(self._close)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0,
            seconds=20))
        return self.window

    def _close(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()

    def _manga_action(self):
        return self.window.actiongroup.get_action('manga_mode')

    def _comicinfo_read(self):
        """Wait until the book's ComicInfo.xml is out and was read."""
        self.assertTrue(wait_for(
            lambda: self.window._awaited_comicinfo is None, seconds=10))
        pump()

    def test_a_book_read_right_to_left_opens_in_manga_mode(self):
        window = self._open(self._book('Right.cbz', 'YesAndRightToLeft'))
        self.assertTrue(wait_for(lambda: window.is_manga_mode, seconds=10),
                        'the book was not read right to left')
        self.assertTrue(self._manga_action().get_active())
        self.assertFalse(prefs['default manga mode'],
                         'the book changed what every book opens in')

    def test_a_manga_that_names_no_direction_is_left_alone(self):
        window = self._open(self._book('Plain.cbz', 'Yes'))
        self._comicinfo_read()
        self.assertFalse(window.is_manga_mode)
        self.assertFalse(self._manga_action().get_active())

    def test_the_next_book_reads_the_way_the_reader_chose(self):
        window = self._open(self._book('Right.cbz', 'YesAndRightToLeft'))
        self.assertTrue(wait_for(lambda: window.is_manga_mode, seconds=10))
        window.filehandler.close_file()
        pump()
        self.assertFalse(window.is_manga_mode)
        self.assertFalse(self._manga_action().get_active())

    def test_the_next_book_of_a_right_to_left_series_reads_so_too(self):
        """Closing the first book puts the reader's choice back, and the
        next one's ComicInfo.xml is read for itself."""
        first = self._book('01.cbz', 'YesAndRightToLeft')
        second = self._book('02.cbz', 'YesAndRightToLeft')
        window = self._open(first)
        self.assertTrue(wait_for(lambda: window.is_manga_mode, seconds=10))
        self.assertTrue(window.filehandler.open_next_archive())
        self.assertTrue(wait_for(
            lambda: window.filehandler.get_path_to_base() == second
            and window.is_manga_mode, seconds=10),
            'the second book was not read right to left')
        self.assertFalse(prefs['default manga mode'])

    def test_turning_it_off_and_on_holds_for_that_book_alone(self):
        window = self._open(self._book('Right.cbz', 'YesAndRightToLeft'))
        self.assertTrue(wait_for(lambda: window.is_manga_mode, seconds=10))
        action = self._manga_action()
        action.set_active(False)
        pump()
        self.assertFalse(window.is_manga_mode)
        action.set_active(True)
        pump()
        self.assertTrue(window.is_manga_mode)
        self.assertFalse(prefs['default manga mode'])

    def test_a_reader_in_manga_mode_keeps_it_for_a_book_without_one(self):
        prefs['default manga mode'] = True
        window = self._open(self._book('Plain.cbz'))
        pump()
        self.assertTrue(window.is_manga_mode)
        window.filehandler.close_file()
        pump()
        self.assertTrue(window.is_manga_mode)
        self.assertTrue(prefs['default manga mode'])

    def _reopen(self, path):
        """Open <path> in the open window, in place of its book."""
        self.window.filehandler.open_file(path)
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.get_path_to_base() == path
            and self.window.imagehandler.get_number_of_pages() > 0,
            seconds=20))
        pump()

    def test_a_book_set_by_hand_reads_so_when_opened_again(self):
        """Manga beside a western comic: each is read the way it was set
        though the other was set since."""
        manga = self._book('Manga.cbz')
        western = self._book('Western.cbz')
        window = self._open(manga)
        pump()
        self._manga_action().set_active(True)
        pump()
        self._reopen(western)
        # A book never set reads the way the toggle was last set.
        self.assertTrue(window.is_manga_mode)
        self._manga_action().set_active(False)
        pump()
        self.assertFalse(prefs['default manga mode'])
        self._reopen(manga)
        self.assertTrue(window.is_manga_mode)
        self.assertTrue(self._manga_action().get_active())
        self._reopen(western)
        self.assertFalse(window.is_manga_mode)
        self.assertFalse(self._manga_action().get_active())

    def test_a_book_that_set_its_own_direction_leaves_others_alone(self):
        """Set back on a book that reads its own way, manga mode is
        changed for that book alone, as for a ComicInfo.xml's."""
        manga = self._book('Manga.cbz')
        western = self._book('Western.cbz')
        reading_directions.remember(manga, True)
        window = self._open(manga)
        pump()
        self.assertTrue(window.is_manga_mode)
        self.assertFalse(prefs['default manga mode'])
        self._manga_action().set_active(False)
        pump()
        self.assertFalse(window.is_manga_mode)
        self._manga_action().set_active(True)
        pump()
        self.assertFalse(prefs['default manga mode'])
        self._reopen(western)
        self.assertFalse(window.is_manga_mode)
        self.assertFalse(self._manga_action().get_active())

    def test_a_comicinfo_direction_turned_off_stays_off(self):
        right = self._book('Right.cbz', 'YesAndRightToLeft')
        window = self._open(right)
        self.assertTrue(wait_for(lambda: window.is_manga_mode, seconds=10))
        self._manga_action().set_active(False)
        pump()
        self._reopen(self._book('Plain.cbz'))
        self._reopen(right)
        self._comicinfo_read()
        self.assertFalse(window.is_manga_mode)
        self.assertFalse(self._manga_action().get_active())
        self.assertFalse(prefs['default manga mode'])

    def test_a_folder_of_pictures_keeps_its_direction(self):
        folder = os.path.join(self.tmp_dir, 'Folder')
        os.makedirs(folder)
        for page in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg'):
            shutil.copy(get_testfile_path('images', page), folder)
        western = self._book('Western.cbz')
        window = self._open(folder)
        pump()
        self._manga_action().set_active(True)
        pump()
        self.assertIs(True, reading_directions.direction(folder))
        self._reopen(western)
        self._manga_action().set_active(False)
        pump()
        self._reopen(folder)
        self.assertTrue(window.is_manga_mode)
