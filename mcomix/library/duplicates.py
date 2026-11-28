"""duplicates.py - Which books of the library are copies of each other.

Read off the fingerprints (mcomix.library.fingerprint), three ways, from
the surest:

- the same file: of the same size, and the same hash of every byte,
  which is made only for books whose size another book shares;
- the same pages packed again: the same number of pages, and the same
  files for the pages sampled - a CBR made a CBZ, a book unpacked and
  packed again;
- similar: at least two of the pages sampled of one book are close to
  two of the other's (difference() no more than NEAR), each pair in the
  same order, all turned or mirrored the same way - a book scanned
  again, compressed again, resized, in grey, with a frame, a page put in
  front or added at the end, or mirrored for the other reading
  direction.  A book of a single sampled page needs that page alone.

Two books are compared only where pages of one share three of the five
parts of a coarse hash with pages of the other, so the search does not
compare every page with every other: a library of 20,000 books has
200 million pairs.  A page that a great many books share - a group's
credits, a publisher's blank - tells nothing about whether they are
copies, and is passed over; so is a page with nothing on it, which
every other page with nothing on it matches.
"""

import collections
import dataclasses
import enum
import itertools
import operator
import threading

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

from PIL import Image, ImageStat

from mcomix.library.fingerprint import PICTURE_SIDE, Fingerprint, Sample
from mcomix.library.fingerprint import difference

#: The most two pages may differ (fingerprint.difference(), of 255) and
#: still be the same page.  Copies of one page made the ways the module
#: says lie under 5 apart, other pages over 60.
NEAR = 12.0

#: A page close to pages of more books than this is one they share
#: without being copies, and is no reason to take them for copies.
_COMMON = 32

#: How far the grey levels of a page's picture must spread, as their
#: standard deviation, for it to count as a page with something on it.
_LEAST_SPREAD = 8.0

#: The side of the grid of a page's coarse hash, a bit for each cell:
#: whether the cell is lighter than the page's median.
_HASH_SIDE = 8

#: The bits of each part of the coarse hash, and how many of the parts
#: two pages must share to be compared.  Measured on drawn pages and
#: their copies (half the size, a third the size as JPEG at quality
#: 20, JPEG and WebP compressed again, in grey, in a frame): the copies
#: kept 3 to 5 of the 5 parts, and pages that are not copies shared two
#: in 3 of 10,000 pairs.  A page is filed under each choice of that
#: many parts, so that a page found under one of them shares them.
_PART_BITS = 12
_PARTS_SHARED = 3

#: A choice of parts of the coarse hash that this many pages share is
#: left out of the search, to keep it from comparing all of them with
#: each other; their other parts still bring a page and its copy
#: together.
_CROWDED = 256

#: The ways a page may be turned or mirrored, the first leaving it be.
_TURNS = (None, Image.Transpose.FLIP_LEFT_RIGHT,
          Image.Transpose.FLIP_TOP_BOTTOM, Image.Transpose.ROTATE_90,
          Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_270,
          Image.Transpose.TRANSPOSE, Image.Transpose.TRANSVERSE)


def _cell_order(turn: Image.Transpose | None) -> Callable[
        [bytes], tuple[int, ...]]:
    """What picks out of the cells of the coarse hash's grid those of
    the grid turned <turn>, in order."""
    cells = bytes(range(_HASH_SIDE ** 2))
    if turn is not None:
        cells = Image.frombytes('L', (_HASH_SIDE, _HASH_SIDE), cells) \
            .transpose(turn).tobytes()
    return operator.itemgetter(*cells)


_CELL_ORDERS = tuple(_cell_order(turn) for turn in _TURNS)


class Likeness(enum.IntEnum):
    """How sure it is that books are copies, the surest least."""
    SAME_FILE = 0
    SAME_PAGES = 1
    SIMILAR = 2


@dataclasses.dataclass(frozen=True)
class Group:
    """Books that are copies of each other, by their ids in order, and
    how sure that is: as sure as the least sure of the links that joined
    them."""
    books: tuple[int, ...]
    likeness: Likeness


def find(fingerprints: Mapping[int, Fingerprint],
         digest_of: Callable[[int, Fingerprint], bytes | None],
         stop: threading.Event | None = None) -> list[Group]:
    """The groups of copies among the books of <fingerprints>, by their
    ids, the largest group first.

    <digest_of> answers with the hash of a book's whole file, or None
    where it has none (the file is gone, or the search was stopped); it
    is asked only of books whose size another shares.  Once <stop> is
    set the search ends with the groups found so far.
    """
    joined = _Joins()
    _join_same_files(fingerprints, digest_of, joined, stop)
    _join_same_pages(fingerprints, joined)
    if stop is None or not stop.is_set():
        _join_similar(fingerprints, joined, stop)
    groups = [Group(tuple(sorted(books)), likeness)
              for books, likeness in joined.groups()]
    groups.sort(key=lambda group: (-len(group.books), group.books))
    return groups


def to_keep(books: Sequence[int],
            fingerprints: Mapping[int, Fingerprint],
            links: Collection[int] = ()) -> int:
    """Which of <books>, copies of each other, to keep: the one of most
    pages, then of the largest first page, then the smallest file, then
    one not among <links>, the books whose paths go through a symbolic
    link; the first of those alike in all four.

    A link and the file it leads to are alike in the first three, and
    the link must be the one offered for the trash: trashing the file
    would lose the book and leave the link leading nowhere."""
    def rank(book: int) -> tuple[int, int, int, bool]:
        made = fingerprints[book]
        cover = made.samples[0] if made.samples else None
        area = cover.width * cover.height if cover is not None else 0
        return made.pages, area, -made.size, book not in links
    return max(books, key=rank)


class _Joins:
    """The books joined so far, and how surely, as a union-find."""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._likeness: dict[int, Likeness] = {}

    def _root(self, book: int) -> int:
        parent = self._parent.setdefault(book, book)
        while parent != book:
            grand = self._parent[parent]
            self._parent[book] = grand
            book, parent = parent, grand
        return book

    def same(self, one: int, other: int) -> bool:
        return self._root(one) == self._root(other)

    def join(self, one: int, other: int, likeness: Likeness) -> None:
        one, other = self._root(one), self._root(other)
        weakest = max([likeness, *(self._likeness[root] for root in
                                   (one, other) if root in self._likeness)])
        if one != other:
            self._parent[other] = one
            self._likeness.pop(other, None)
        self._likeness[one] = weakest

    def groups(self) -> Iterable[tuple[list[int], Likeness]]:
        members: dict[int, list[int]] = collections.defaultdict(list)
        for book in self._parent:
            members[self._root(book)].append(book)
        for root, books in members.items():
            if len(books) > 1:
                yield books, self._likeness[root]


def _join_runs(runs: Iterable[list[int]], joined: _Joins,
               likeness: Likeness) -> None:
    for books in runs:
        for book in books[1:]:
            joined.join(books[0], book, likeness)


def _join_same_files(fingerprints: Mapping[int, Fingerprint],
                     digest_of: Callable[[int, Fingerprint], bytes | None],
                     joined: _Joins, stop: threading.Event | None) -> None:
    by_size: dict[int, list[int]] = collections.defaultdict(list)
    for book, fingerprint in fingerprints.items():
        by_size[fingerprint.size].append(book)
    by_digest: dict[tuple[int, bytes], list[int]] = \
        collections.defaultdict(list)
    for size, books in by_size.items():
        if len(books) < 2:
            continue
        for book in books:
            if stop is not None and stop.is_set():
                return
            digest = digest_of(book, fingerprints[book])
            if digest is not None:
                by_digest[size, digest].append(book)
    _join_runs(by_digest.values(), joined, Likeness.SAME_FILE)


def _join_same_pages(fingerprints: Mapping[int, Fingerprint],
                     joined: _Joins) -> None:
    by_pages: dict[tuple[int, tuple[bytes, ...]], list[int]] = \
        collections.defaultdict(list)
    for book, fingerprint in fingerprints.items():
        if fingerprint.samples:
            by_pages[fingerprint.pages, tuple(
                sample.file_hash for sample in fingerprint.samples)
            ].append(book)
    _join_runs(by_pages.values(), joined, Likeness.SAME_PAGES)


@dataclasses.dataclass(frozen=True)
class _Page:
    """A page sampled, as the search for similar ones reads it: its
    file's hash, its picture (no bytes where Pillow could not read it or
    there is nothing on it to compare), the bits of its coarse hash, in
    the grid's order, and whether it is <plain>: read, and nothing on it.
    A plain page is the same as no other, whatever its file."""
    file_hash: bytes
    picture: bytes
    bits: bytes
    plain: bool = False

    def keys(self, turn: int) -> list[tuple[int, bytes]]:
        """What the page turned the <turn>th way of _TURNS is filed
        under: each choice of _PARTS_SHARED parts of its coarse hash,
        by the choice and their bits, a byte each."""
        bits = bytes(_CELL_ORDERS[turn](self.bits))
        parts = [bits[start:start + _PART_BITS]
                 for start in range(0, len(bits) - _PART_BITS + 1,
                                    _PART_BITS)]
        return [(choice, b''.join(parts[at] for at in chosen))
                for choice, chosen in enumerate(itertools.combinations(
                    range(len(parts)), _PARTS_SHARED))]

    def turned(self, turn: int) -> bytes:
        """The picture turned the <turn>th way of _TURNS."""
        how = _TURNS[turn]
        if how is None:
            return self.picture
        return Image.frombytes('L', (PICTURE_SIDE, PICTURE_SIDE),
                               self.picture).transpose(how).tobytes()


def _page(sample: Sample) -> _Page:
    picture = sample.picture
    if len(picture) != PICTURE_SIDE ** 2:
        return _Page(sample.file_hash, b'', b'')
    image = Image.frombytes('L', (PICTURE_SIDE, PICTURE_SIDE), picture)
    if ImageStat.Stat(image).stddev[0] < _LEAST_SPREAD:
        return _Page(sample.file_hash, b'', b'', plain=True)
    cells = image.resize((_HASH_SIDE, _HASH_SIDE),
                         Image.Resampling.BOX).tobytes()
    median = sorted(cells)[len(cells) // 2]
    return _Page(sample.file_hash, picture,
                 bytes(level > median for level in cells))


#: A page sampled, by its book and where it is among the book's samples.
_At = tuple[int, int]


def _join_similar(fingerprints: Mapping[int, Fingerprint], joined: _Joins,
                  stop: threading.Event | None) -> None:
    pages_of = {book: [_page(sample) for sample in fingerprint.samples]
                for book, fingerprint in fingerprints.items()
                if fingerprint.samples}

    # Each page is filed under its keys as it is, and looked up under
    # them turned each way.
    filed: dict[tuple[int, bytes], list[_At]] = \
        collections.defaultdict(list)
    holders: dict[bytes, set[int]] = collections.defaultdict(set)
    for book, pages in pages_of.items():
        for index, page in enumerate(pages):
            holders[page.file_hash].add(book)
            if page.bits:
                for key in page.keys(0):
                    filed[key].append((book, index))

    # The pages of other books each page may be, by turn.
    close: dict[tuple[int, int, int], set[tuple[int, int]]] = \
        collections.defaultdict(set)
    near: dict[_At, list[tuple[int, int, int]]] = \
        collections.defaultdict(list)
    for book, pages in pages_of.items():
        if stop is not None and stop.is_set():
            return
        for index, page in enumerate(pages):
            if not page.bits:
                continue
            for turn in range(len(_TURNS)):
                found: set[_At] = set()
                for key in page.keys(turn):
                    others = filed.get(key, ())
                    if len(others) < _CROWDED:
                        found.update(others)
                for other, at in found:
                    if other != book:
                        close[book, other, turn].add((index, at))
                        near[book, index].append((other, at, turn))

    told: dict[_At, bool] = {}

    def telling(book: int, index: int) -> bool:
        """Whether the page is one that no more than _COMMON other
        books hold, by its file or a page close to it."""
        if (book, index) not in told:
            page = pages_of[book][index]
            holding = holders[page.file_hash] - {book}
            if len(holding) <= _COMMON:
                holding |= {other for other, at, turn in near[book, index]
                            if other not in holding and _same_page(
                                page, pages_of[other][at], turn)}
            told[book, index] = len(holding) <= _COMMON
        return told[book, index]

    # Pages of the same file are close whatever their pictures (plain
    # ones apart, which _same_page() leaves out).
    for books in holders.values():
        if 1 < len(books) <= _COMMON + 1:
            for book in books:
                for other in books:
                    if other != book:
                        for index, page in enumerate(pages_of[book]):
                            for at, its in enumerate(pages_of[other]):
                                if page.file_hash == its.file_hash:
                                    close[book, other, 0].add((index, at))

    for (book, other, turn), pairs in close.items():
        if stop is not None and stop.is_set():
            return
        if joined.same(book, other):
            continue
        if _alike(pages_of[book], pages_of[other], turn, pairs,
                  lambda index, at: telling(book, index)
                  and telling(other, at)):
            joined.join(book, other, Likeness.SIMILAR)


def _alike(one: list[_Page], other: list[_Page], turn: int,
           pairs: set[tuple[int, int]],
           telling: Callable[[int, int], bool]) -> bool:
    """Whether the pages <one> book sampled, turned the <turn>th way,
    match enough of the <other>'s pages, in order, of the <pairs> of
    them that may (the index of one's page, of the other's), counting
    only those pairs that are <telling>."""
    wanted = min(2, len(one), len(other))
    if len({index for index, _ in pairs}) < wanted:
        return False
    matched = 0
    last = -1
    for index, at in sorted(pairs):
        if at <= last:
            continue
        if _same_page(one[index], other[at], turn) and telling(index, at):
            matched += 1
            last = at
            if matched >= wanted:
                return True
    return False


def _same_page(page: _Page, other: _Page, turn: int) -> bool:
    if page.plain or other.plain:
        return False
    if turn == 0 and page.file_hash == other.file_hash:
        return True
    if not page.picture or not other.picture:
        return False
    return difference(page.turned(turn), other.picture) <= NEAR
