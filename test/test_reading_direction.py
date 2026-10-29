"""A book whose ComicInfo.xml says it is read right to left.

Other readers open such a book in manga mode; MComix read it left to
right unless the reader turned manga mode on, which then held for every
book after it.  The book now puts itself in manga mode, for itself
alone, as a book of long strips puts itself in continuous mode.
"""

import os
import zipfile

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import comicinfo
from mcomix import constants
from mcomix import icons
from mcomix import main
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

