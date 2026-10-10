"""The turn a reader gives a page, remembered for that page."""

import json
import os

from . import MComixTest

from mcomix import constants
from mcomix import page_rotations


class PageRotationsTest(MComixTest):

    def _file(self):
        return os.path.join(constants.DATA_DIR, 'page_rotations.json')

    def test_a_turn_is_kept_for_its_page_and_its_book_alone(self):
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 90)
        self.assertEqual(90, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))
        self.assertEqual(0, page_rotations.rotation('/books/a.cbz', 'p03.jpg'))
        self.assertEqual(0, page_rotations.rotation('/books/b.cbz', 'p02.jpg'))

    def test_it_follows_a_book_that_is_moved(self):
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 90)
        page_rotations.follow('/books/a.cbz', '/shelf/a.cbz')
        page_rotations._loaded = None
        self.assertEqual(90, page_rotations.rotation('/shelf/a.cbz', 'p02.jpg'))
        self.assertEqual(0, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))
        # A book nothing was said of leaves the file as it is.
        page_rotations.follow('/books/b.cbz', '/shelf/b.cbz')
        with open(self._file(), encoding='utf-8') as fd:
            self.assertEqual(['/shelf/a.cbz'], list(json.load(fd)))

    def test_it_follows_a_folder_of_books_that_is_moved(self):
        old = os.path.abspath(os.path.join(os.sep, 'books'))
        new = os.path.abspath(os.path.join(os.sep, 'shelf'))
        inside = os.path.join(old, 'sub', 'a.cbz')
        outside = os.path.abspath(os.path.join(os.sep, 'books-old', 'b.cbz'))
        page_rotations.remember(inside, 'p02.jpg', 90)
        page_rotations.remember(outside, 'p02.jpg', 90)
        self.assertEqual(1, page_rotations.relocate(old, new))
        page_rotations._loaded = None
        self.assertTrue(page_rotations.rotation(os.path.join(new, 'sub', 'a.cbz'), 'p02.jpg'))
        self.assertFalse(page_rotations.rotation(inside, 'p02.jpg'))
        self.assertTrue(page_rotations.rotation(outside, 'p02.jpg'))
        self.assertEqual(0, page_rotations.relocate(old, new))

    def test_it_is_read_back_from_the_file(self):
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 270)
        page_rotations._loaded = None
        self.assertEqual(270, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))

    def test_upright_again_is_forgotten(self):
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 90)
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 0)
        with open(self._file(), encoding='utf-8') as fd:
            self.assertEqual({}, json.load(fd))

    def test_a_damaged_file_costs_the_turns_and_nothing_else(self):
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        with open(self._file(), 'w', encoding='utf-8') as fd:
            fd.write('{"/books/a.cbz": {"p01.jpg": 45, "p02.jpg": 180}, "x": 3')
        page_rotations._loaded = None
        self.assertEqual(0, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))
        with open(self._file(), 'w', encoding='utf-8') as fd:
            json.dump({'/books/a.cbz': {'p01.jpg': 45, 'p02.jpg': 180},
                       'x': 3}, fd)
        page_rotations._loaded = None
        self.assertEqual(0, page_rotations.rotation('/books/a.cbz', 'p01.jpg'))
        self.assertEqual(180, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))

# vim: expandtab:sw=4:ts=4
