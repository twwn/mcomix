"""The turn a reader gives a page, remembered for that page."""

import json
import os

from . import MComixTest, PageStoreCases

from mcomix import constants
from mcomix import page_rotations


class PageRotationsTest(PageStoreCases, MComixTest):

    store = page_rotations

    def _file(self):
        return os.path.join(constants.DATA_DIR, 'page_rotations.json')

    def _keep(self, book, page):
        page_rotations.remember(book, page, 90)

    def _kept(self, book, page):
        return page_rotations.rotation(book, page) == 90

    def test_a_turn_is_kept_for_its_page_and_its_book_alone(self):
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 90)
        self.assertEqual(90, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))
        self.assertEqual(0, page_rotations.rotation('/books/a.cbz', 'p03.jpg'))
        self.assertEqual(0, page_rotations.rotation('/books/b.cbz', 'p02.jpg'))

    def test_upright_again_is_forgotten(self):
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 90)
        page_rotations.remember('/books/a.cbz', 'p02.jpg', 0)
        with open(self._file(), encoding='utf-8') as fd:
            self.assertEqual({}, json.load(fd))

    def test_a_damaged_file_costs_the_turns_and_nothing_else(self):
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        with open(self._file(), 'w', encoding='utf-8') as fd:
            fd.write('{"/books/a.cbz": {"p01.jpg": 45, "p02.jpg": 180}, "x": 3')
        page_rotations._store.forget()
        self.assertEqual(0, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))
        with open(self._file(), 'w', encoding='utf-8') as fd:
            json.dump({'/books/a.cbz': {'p01.jpg': 45, 'p02.jpg': 180},
                       'x': 3}, fd)
        page_rotations._store.forget()
        self.assertEqual(0, page_rotations.rotation('/books/a.cbz', 'p01.jpg'))
        self.assertEqual(180, page_rotations.rotation('/books/a.cbz', 'p02.jpg'))

# vim: expandtab:sw=4:ts=4
