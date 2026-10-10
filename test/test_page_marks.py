"""What a reader says of single pages, kept apart from the book."""

import json
import os

from . import MComixTest

from mcomix import constants
from mcomix import page_marks


class PageMarksTest(MComixTest):

    def _file(self):
        return os.path.join(constants.DATA_DIR, 'page_marks.json')

    def test_a_mark_is_kept_for_its_page_and_its_book_alone(self):
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.SKIP, True)
        self.assertTrue(
            page_marks.marked('/books/a.cbz', 'p02.jpg', page_marks.SKIP))
        self.assertFalse(
            page_marks.marked('/books/a.cbz', 'p03.jpg', page_marks.SKIP))
        self.assertFalse(
            page_marks.marked('/books/b.cbz', 'p02.jpg', page_marks.SKIP))
        self.assertTrue(page_marks.any_marked('/books/a.cbz', page_marks.SKIP))
        self.assertFalse(page_marks.any_marked('/books/b.cbz', page_marks.SKIP))

    def test_a_page_carries_each_of_its_marks_apart(self):
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.SKIP, True)
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.ALONE, True)
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.SKIP, False)
        self.assertFalse(
            page_marks.marked('/books/a.cbz', 'p02.jpg', page_marks.SKIP))
        self.assertTrue(
            page_marks.marked('/books/a.cbz', 'p02.jpg', page_marks.ALONE))

    def test_it_follows_a_book_that_is_moved(self):
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.SKIP, True)
        page_marks.follow('/books/a.cbz', '/shelf/a.cbz')
        page_marks._loaded = None
        self.assertTrue(
            page_marks.marked('/shelf/a.cbz', 'p02.jpg', page_marks.SKIP))
        self.assertFalse(
            page_marks.marked('/books/a.cbz', 'p02.jpg', page_marks.SKIP))
        # A book nothing was said of leaves the file as it is.
        page_marks.follow('/books/b.cbz', '/shelf/b.cbz')
        with open(self._file(), encoding='utf-8') as fd:
            self.assertEqual(['/shelf/a.cbz'], list(json.load(fd)))

    def test_it_is_read_back_from_the_file(self):
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.SKIP, True)
        page_marks._loaded = None
        self.assertTrue(
            page_marks.marked('/books/a.cbz', 'p02.jpg', page_marks.SKIP))

    def test_a_mark_taken_off_leaves_nothing_behind(self):
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.SKIP, True)
        page_marks.mark('/books/a.cbz', 'p02.jpg', page_marks.SKIP, False)
        self.assertFalse(
            page_marks.marked('/books/a.cbz', 'p02.jpg', page_marks.SKIP))
        with open(self._file(), encoding='utf-8') as fd:
            self.assertEqual({}, json.load(fd))
        # Taking off what was never put on is no error.
        page_marks.mark('/books/c.cbz', 'p01.jpg', page_marks.SKIP, False)

    def test_a_damaged_file_costs_the_marks_and_nothing_else(self):
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        with open(self._file(), 'w', encoding='utf-8') as fd:
            fd.write('{"/books/a.cbz": {"p01.jpg": ["skip"]}, "x": 3')
        page_marks._loaded = None
        self.assertFalse(
            page_marks.marked('/books/a.cbz', 'p01.jpg', page_marks.SKIP))
        # What is not a mark is dropped, and what is one is kept.
        with open(self._file(), 'w', encoding='utf-8') as fd:
            json.dump({'/books/a.cbz': {'p01.jpg': ['skip', 'sideways'],
                                        'p02.jpg': 'skip',
                                        'p03.jpg': ['sideways'],
                                        'p04.jpg': [3]},
                       '/books/b.cbz': ['skip'], 'x': 3}, fd)
        page_marks._loaded = None
        self.assertTrue(
            page_marks.marked('/books/a.cbz', 'p01.jpg', page_marks.SKIP))
        self.assertEqual({'/books/a.cbz': {'p01.jpg': ['skip']}},
                         page_marks._books())
