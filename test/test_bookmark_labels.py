"""The bookmarks menu tells apart books of the same name by the
folders they are in (upstream feature request 90)."""

import datetime
import unittest

from mcomix import bookmark_menu
from mcomix import constants
from mcomix.bookmark_menu_item import _Bookmark


def _bookmark(name, path, page=3, pages=20):
    return _Bookmark(None, None, name, path, page, pages, constants.ZIP,
                     datetime.datetime(2026, 1, 1))


class TellingFoldersTest(unittest.TestCase):

    def _folders(self, *bookmarks):
        return bookmark_menu.telling_folders(bookmarks)

    def test_books_of_one_name_get_their_folder(self):
        self.assertEqual(['Series A', 'Series B'], self._folders(
            _bookmark('ch01.cbz', '/comics/Series A/ch01.cbz'),
            _bookmark('ch01.cbz', '/comics/Series B/ch01.cbz')))

    def test_as_many_folders_as_it_takes(self):
        self.assertEqual(['S1/vol', 'S2/vol'], self._folders(
            _bookmark('ch01.cbz', '/comics/S1/vol/ch01.cbz'),
            _bookmark('ch01.cbz', '/comics/S2/vol/ch01.cbz')))

    def test_one_book_at_two_pages_needs_no_folder(self):
        self.assertEqual(['', ''], self._folders(
            _bookmark('ch01.cbz', '/comics/A/ch01.cbz', 3),
            _bookmark('ch01.cbz', '/comics/A/ch01.cbz', 9)))

    def test_a_name_of_its_own_needs_no_folder(self):
        self.assertEqual(['', 'A', 'B'], self._folders(
            _bookmark('other.cbz', '/comics/A/other.cbz'),
            _bookmark('ch01.cbz', '/comics/A/ch01.cbz'),
            _bookmark('ch01.cbz', '/comics/B/ch01.cbz')))

    def test_a_folder_of_pictures_is_told_by_the_folder_above(self):
        """Such a bookmark is named after its folder already."""
        self.assertEqual(['A', 'B'], self._folders(
            _bookmark('ch01', '/comics/A/ch01/003.jpg'),
            _bookmark('ch01', '/comics/B/ch01/005.jpg')))

    def test_the_label_puts_the_folders_before_the_name(self):
        bookmark = _bookmark('ch01.cbz', '/comics/A/ch01.cbz')
        self.assertEqual('A/ch01.cbz, (3 / 20)', bookmark.get_label('A'))
        self.assertEqual('ch01.cbz, (3 / 20)', bookmark.get_label())
