"""Which books are copies of each other (mcomix.library.duplicates)."""

import hashlib
import io
import random
import threading
import time

from PIL import Image, ImageOps

from . import MComixTest, drawn_page, encoded
from mcomix.library import duplicates
from mcomix.library import fingerprint
from mcomix.library.duplicates import Group, Likeness


def _sample(data):
    """The sample fingerprint.make() takes of a page whose file holds
    <data>."""
    picture, (width, height) = fingerprint.picture_of(io.BytesIO(data))
    return fingerprint.Sample(
        hashlib.blake2b(data, digest_size=8).digest(), picture, width, height)


def _book(files, size=None, pages=None):
    """The fingerprint of a book whose first pages' files hold <files>:
    of <size> bytes, by default one no other book here has, and <pages>
    pages, by default as many as <files>."""
    if size is None:
        size = 10 ** 6 + sum(map(len, files))
    return fingerprint.Fingerprint(
        size, 0, len(files) if pages is None else pages,
        tuple(_sample(data) for data in files))


def _pngs(seeds, change=lambda page: page):
    """The files of the drawn pages of <seeds>, each <change>d."""
    return [encoded(change(drawn_page(seed)), 'PNG') for seed in seeds]


class FindTest(MComixTest):

    """find() groups the books that are copies, and no others."""

    def setUp(self):
        super().setUp()
        #: The files of a book's first four pages.
        self.pages = _pngs((1, 2, 3, 4))
        self.digests_asked = []

    def _digest(self, book, made):
        self.digests_asked.append(book)
        return made.digest

    def _found(self, books, stop=None):
        return duplicates.find(dict(enumerate(books)), self._digest, stop)

    def test_the_same_file(self):
        book = _book(self.pages, size=5000)
        same = fingerprint.Fingerprint(5000, 0, 4, book.samples, b'digest')
        found = self._found([
            same, fingerprint.Fingerprint(5000, 0, 4, (), b'digest'),
            fingerprint.Fingerprint(5000, 0, 4, (), b'another'),
            fingerprint.Fingerprint(6000, 0, 4, (), b'digest')])
        self.assertEqual([Group((0, 1), Likeness.SAME_FILE)], found)
        # Not of the one book of its size.
        self.assertEqual([0, 1, 2], sorted(self.digests_asked))

    def test_the_same_pages_packed_again(self):
        found = self._found([_book(self.pages, size=5000, pages=20),
                             _book(self.pages, size=7000, pages=20),
                             _book(self.pages, size=9000, pages=21)])
        # The third has a page more, but its first pages look the same.
        self.assertEqual([Group((0, 1, 2), Likeness.SIMILAR)], found)
        found = self._found([_book(self.pages, size=5000, pages=20),
                             _book(self.pages, size=7000, pages=20)])
        self.assertEqual([Group((0, 1), Likeness.SAME_PAGES)], found)

    def test_copies_made_again(self):
        width, height = drawn_page(1).size
        framed = Image.new('RGB', (width * 6 // 5, height * 6 // 5), 'white')

        def in_a_frame(page):
            framed.paste(page, (width // 10, height // 10))
            return framed

        copies = {
            'half the size': _pngs(
                (1, 2, 3, 4), lambda page: page.resize((width // 2,
                                                        height // 2))),
            'as JPEG': [encoded(drawn_page(seed), 'JPEG', quality=40)
                        for seed in (1, 2, 3, 4)],
            'in grey': _pngs((1, 2, 3, 4), lambda page: page.convert('L')),
            'in a frame': _pngs((1, 2, 3, 4), in_a_frame),
            'mirrored': _pngs((1, 2, 3, 4), ImageOps.mirror),
            'turned': _pngs((1, 2, 3, 4), lambda page: page.rotate(
                90, expand=True)),
            'with a page in front': _pngs((99, 1, 2, 3)),
            'with its cover only': _pngs((1,)),
        }
        for name, files in copies.items():
            with self.subTest(name):
                self.assertEqual(
                    [Group((0, 1), Likeness.SIMILAR)],
                    self._found([_book(self.pages), _book(files)]))

    def test_look_alikes(self):
        """Another volume behind the same cover, the same pages in
        another order, and books of pages that are only white."""
        white = encoded(Image.new('L', (600, 900), 255), 'PNG')
        look_alikes = {
            'the same cover': _pngs((1, 10, 11, 12)),
            'the same pages out of order': _pngs((4, 3, 2, 1)),
            'white pages': _pngs((20,)) + [white] * 3,
        }
        for name, files in look_alikes.items():
            with self.subTest(name):
                other = _pngs((21,)) + [white] * 3 if name == 'white pages' \
                    else self.pages
                self.assertEqual([], self._found([_book(other),
                                                  _book(files)]))

    def test_a_page_many_books_share_tells_nothing(self):
        """A scanner's credits, behind the cover of each of
        _COMMON + 5 books: the three that share their cover besides are
        not copies for that."""
        credits = _pngs((50,))[0]
        books = [_book(_pngs((1,)) + [credits] + _pngs((60 + book,)))
                 for book in range(3)]
        books += [_book(_pngs((100 + book,)) + [credits])
                  for book in range(duplicates._COMMON + 2)]
        self.assertEqual([], self._found(books))

    def test_a_group_is_as_sure_as_its_least_sure_link(self):
        book = _book(self.pages, size=5000)
        found = self._found([
            fingerprint.Fingerprint(5000, 0, 4, book.samples, b'digest'),
            fingerprint.Fingerprint(5000, 0, 4, book.samples, b'digest'),
            _book(_pngs((1, 2, 3, 4), ImageOps.mirror)),
            _book(_pngs((30, 31))), _book(_pngs((30, 31)), size=10)])
        self.assertEqual([Group((0, 1, 2), Likeness.SIMILAR),
                          Group((3, 4), Likeness.SAME_PAGES)], found)

    def test_a_stopped_search_reads_no_file(self):
        """What the fingerprints say without one is found all the same."""
        stop = threading.Event()
        stop.set()
        book = _book(self.pages, size=5000)
        self.assertEqual([Group((0, 1), Likeness.SAME_PAGES)],
                         self._found([book, book], stop))
        self.assertEqual([], self.digests_asked)

    def test_a_library_of_books_alike_in_nothing_is_quick(self):
        """Two thousand books, four pages each, every page another: no
        page is compared with every other, and none is taken for
        another."""
        chance = random.Random(7)

        def picture():
            # As smooth as a page shrunk to 16 pixels square is.
            cells = Image.frombytes('L', (4, 6), chance.randbytes(24))
            return ImageOps.autocontrast(cells.resize(
                (fingerprint.PICTURE_SIDE, fingerprint.PICTURE_SIDE),
                Image.Resampling.BICUBIC)).tobytes()

        books = {book: fingerprint.Fingerprint(book, 0, 4, tuple(
            fingerprint.Sample(chance.randbytes(8), picture())
            for _ in range(4))) for book in range(2000)}
        started = time.perf_counter()
        self.assertEqual([], duplicates.find(books, self._digest))
        self.assertLess(time.perf_counter() - started, 5)
