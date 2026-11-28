"""fingerprint.py - What the library keeps of a book to find its copies.

A fingerprint is read from a book's file without asking for a password,
and stored by the backend with the file's size and time, so that it is
read again only once the file changes.  It holds:

- the number of pages;
- for each of the first SAMPLED pages, in the order they are read, a
  hash of the page's file, which a copy packed again (a CBR made a CBZ)
  holds unchanged, and a small picture of the page - in grey, its plain
  borders cut off, its levels stretched, PICTURE_SIDE pixels square -
  which a copy scanned again, compressed again or resized still matches
  closely (difference()).

The pages sampled are the first ones because a copy shares its cover
whatever was added at its end; a copy with a page of credits put in
front still shares the rest of them, a sample further on.

A hash of the whole file reads every byte of it, so it is not part of
the fingerprint: digest() makes it only for books that could be the
same file, those of the same size.
"""

import concurrent.futures
import contextlib
import dataclasses
import hashlib
import io
import operator
import os
import struct
import tempfile
import threading

from collections.abc import Callable, Mapping

from PIL import Image, ImageOps

from mcomix import archive_tools
from mcomix import image_tools
from mcomix import log
from mcomix import tools
from mcomix.archive import password as archive_password

#: How many pages of a book are sampled, from its first on.
SAMPLED = 4

#: The side, in pixels, of the picture kept of a page sampled.
PICTURE_SIDE = 16

#: The side the page is shrunk to before its borders are looked for,
#: which also evens out the grain of a scan and of JPEG blocks.
_WORKING_SIDE = 128

#: How far, in grey levels of 0 to 255, a pixel may lie from the colour
#: of the corners and still count as border.
_BORDER_TOLERANCE = 24

#: A border is cut only where what is left is at least this share of
#: the page each way: a page that is mostly plain, a panel on white,
#: keeps its white.
_LEAST_LEFT = 0.5

#: The bytes of a page's file hash.
_HASH_SIZE = 8

#: The first byte of a stored list of samples: how it is laid out.
_LAYOUT = 1

#: How a page's width and height are stored.
_SIZE = struct.Struct('>II')

#: The bytes of the whole file read at a time by digest().
_CHUNK = 1 << 20


@dataclasses.dataclass(frozen=True)
class Sample:
    """One page sampled: <file_hash> of its file, <picture>, its
    PICTURE_SIDE squared grey levels, and its <width> and <height> in
    pixels; no bytes and no size where Pillow could not read the
    page."""
    file_hash: bytes
    picture: bytes
    width: int = 0
    height: int = 0


@dataclasses.dataclass(frozen=True)
class Fingerprint:
    """What is kept of a book's file, whose <size> and <mtime> (in
    nanoseconds) it was read at, of <pages> pages; <digest>, the hash of
    the whole file, only once digest() was asked for it."""
    size: int
    mtime: int
    pages: int
    samples: tuple[Sample, ...]
    digest: bytes | None = None

    def packed_samples(self) -> bytes:
        """The samples as one blob for the database."""
        parts = [bytes((_LAYOUT,))]
        for sample in self.samples:
            parts.append(sample.file_hash)
            parts.append(_SIZE.pack(sample.width, sample.height))
            parts.append(bytes((len(sample.picture) // PICTURE_SIDE,)))
            parts.append(sample.picture)
        return b''.join(parts)

    @staticmethod
    def unpacked_samples(blob: bytes) -> tuple[Sample, ...] | None:
        """The samples packed_samples() wrote into <blob>, or None for
        a blob of another layout, which is read again."""
        if blob[:1] != bytes((_LAYOUT,)):
            return None
        samples = []
        at = 1
        while at < len(blob):
            file_hash = blob[at:at + _HASH_SIZE]
            at += _HASH_SIZE
            width, height = _SIZE.unpack_from(blob, at)
            at += _SIZE.size
            rows = blob[at]
            at += 1
            picture = blob[at:at + rows * PICTURE_SIDE]
            at += rows * PICTURE_SIDE
            samples.append(Sample(file_hash, picture, width, height))
        return tuple(samples)


def stamp(path: str) -> tuple[int, int]:
    """The size and time, in nanoseconds, of the file at <path>, which
    a fingerprint is read again for once they change."""
    status = os.stat(path)
    return status.st_size, status.st_mtime_ns


def is_current(fingerprint: Fingerprint, path: str) -> bool:
    """Whether <fingerprint> was read from the file at <path> as it is
    now; not where the file is gone."""
    try:
        return stamp(path) == (fingerprint.size, fingerprint.mtime)
    except OSError:
        return False


def make(path: str) -> Fingerprint | None:
    """The fingerprint of the book at <path>, or None where MComix
    reads no pages from it: not a book, damaged, or encrypted throughout.

    No password is asked for: a page that wants one is left out of the
    samples, as one Pillow cannot read keeps no picture.
    """
    size, mtime = stamp(path)
    mime = archive_tools.archive_mime_type(path)
    if mime is None:
        return None
    with contextlib.ExitStack() as stack:
        stack.enter_context(archive_password.never_asked())
        folder = tempfile.mkdtemp(prefix='mcomix_fingerprint.')
        stack.callback(tools.remove_tree, folder)
        archive = archive_tools.get_recursive_archive_handler(
            path, folder, type=mime)
        if archive is None:
            return None
        stack.callback(archive.close)
        pages = [name for name in archive.list_contents()
                 if image_tools.is_image_file(name)
                 and not archive_tools.is_finder_file(name)]
        tools.alphanumeric_sort(pages)
        samples = []
        for name in pages[:SAMPLED]:
            try:
                archive.extract(name, folder)
            except Exception as error:
                # Encrypted with the password withheld, or damaged: the
                # extractors raise whatever their library met.
                log.debug('Page "%s" of "%s" not sampled: %s',
                          name, path, error)
                continue
            page = os.path.join(folder, name)
            if os.path.isfile(page):
                samples.append(sample_of(page))
        return Fingerprint(size, mtime, len(pages), tuple(samples))


def sample_of(path: str) -> Sample:
    """The sample of the page whose file is at <path>."""
    with open(path, 'rb') as file:
        data = file.read()
    file_hash = hashlib.blake2b(data, digest_size=_HASH_SIZE).digest()
    try:
        picture, (width, height) = picture_of(io.BytesIO(data))
    except Exception as error:
        # Pillow refuses a picture it cannot read with whatever it met.
        log.debug('No picture kept of "%s": %s', path, error)
        return Sample(file_hash, b'')
    return Sample(file_hash, picture, width, height)


def picture_of(file: io.BytesIO) -> tuple[bytes, tuple[int, int]]:
    """The small picture kept of the page in <file>, PICTURE_SIDE
    squared grey levels row by row, and the page's size."""
    with Image.open(file) as page:
        size = page.size
        # A JPEG is decoded at a fraction of its size where that is
        # enough, which is most of the time a page takes.
        page.draft('L', (_WORKING_SIDE, _WORKING_SIDE))
        if page.mode in ('RGBA', 'LA', 'PA') or 'transparency' in page.info:
            flat = Image.new('RGBA', page.size, 'white')
            flat.alpha_composite(page.convert('RGBA'))
            grey = flat.convert('L')
        else:
            grey = page.convert('L')
    grey.thumbnail((_WORKING_SIDE, _WORKING_SIDE), Image.Resampling.BOX)
    grey = ImageOps.autocontrast(_without_borders(grey), cutoff=1)
    return grey.resize((PICTURE_SIDE, PICTURE_SIDE),
                       Image.Resampling.BOX).tobytes(), size


def _without_borders(grey: Image.Image) -> Image.Image:
    """<grey> with the plain border around it cut off: the rows and
    columns at its edges all close to the colour of its corners."""
    width, height = grey.size
    levels = grey.tobytes()
    corners = sorted(levels[at] for at in (
        0, width - 1, (height - 1) * width, height * width - 1))
    # The middle two, so that one corner drawn on does not count.
    background = (corners[1] + corners[2]) // 2
    table = [255 if abs(level - background) > _BORDER_TOLERANCE else 0
             for level in range(256)]
    box = grey.point(table).getbbox()
    if box is None:
        return grey
    left, top, right, bottom = box
    if right - left < width * _LEAST_LEFT \
            or bottom - top < height * _LEAST_LEFT:
        return grey
    return grey.crop(box)


def difference(one: bytes, other: bytes) -> float:
    """How far apart two pictures picture_of() kept lie: the mean of
    their pixels' differences, 0 for the same picture to 255; 255 where
    either is missing."""
    if not one or len(one) != len(other):
        return 255.0
    total: int = sum(map(abs, map(operator.sub, one, other)))
    return total / len(one)


def digest(path: str, stop: threading.Event | None = None) -> bytes | None:
    """The hash of the whole file at <path>, or None where <stop> was
    set while it was read."""
    hasher = hashlib.blake2b(digest_size=16)
    with open(path, 'rb') as file:
        while chunk := file.read(_CHUNK):
            if stop is not None and stop.is_set():
                return None
            hasher.update(chunk)
    return hasher.digest()


def update(books: Mapping[int, str], stored: Mapping[int, Fingerprint],
           keep: Callable[[int, Fingerprint], None],
           stop: threading.Event,
           progress: Callable[[int, int], None] | None = None,
           threads: int = 0) -> dict[int, Fingerprint]:
    """The fingerprint of each of <books> (id to path) that has one:
    the one <stored> where it is current, otherwise one read now and
    handed to <keep> as it is made.

    Several are read at once, on <threads> threads (0 for one per
    processor, as the 'max threads' preference means it).  <progress>
    is told how many of the books to read are done, of how many, as each
    is.  Once <stop> is set no other book is begun; what was read is
    kept, and the books not read are left out of the answer.
    """
    found = {book: stored[book] for book, path in books.items()
             if book in stored and is_current(stored[book], path)}
    wanted = [(book, path) for book, path in books.items()
              if book not in found]
    if not wanted:
        return found

    def read(book: int, path: str) -> Fingerprint | None:
        if stop.is_set():
            return None
        try:
            return make(path)
        except Exception as error:
            # A damaged book is a book with no fingerprint; it must not
            # end the run for the rest.
            log.debug('No fingerprint of "%s": %s', path, error)
            return None

    count = tools.thread_count(threads)
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(count, len(wanted)),
            thread_name_prefix='fingerprint') as pool:
        futures = {pool.submit(read, book, path): book
                   for book, path in wanted}
        for done, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            fingerprint = future.result()
            if fingerprint is not None:
                book = futures[future]
                keep(book, fingerprint)
                found[book] = fingerprint
            if progress is not None:
                progress(done, len(wanted))
    return found
