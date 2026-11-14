"""A TIFF of several pages, read as a book of them.

A TIFF holds any number of pictures one after the other, and a scanner
or a fax program saves a document of several pages as one such file.
TiffArchive lists each of those pictures as a page and writes it out,
when it is wanted, as a TIFF of its own, which is then read like any
other image.  Pillow does the reading and the writing.

Not every picture in a TIFF is a page: a smaller copy of one, kept for
previews, and a transparency mask are marked as such, and are left out.
A TIFF with one page is no book, and stays the image it is.
"""

import os
import re
import threading
from collections.abc import Iterator

from PIL import Image, features

from mcomix.archive import archive_base

#: How a TIFF begins, in either byte order, and a BigTIFF after them.
SIGNATURES = (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+')
#: The names a TIFF is taken for a book under.  A camera's raw file is
#: a TIFF by its first bytes too, with a preview and the sensor's data
#: as its pictures, and is no book.
_EXTENSIONS = ('.tif', '.tiff')

#: The tag that says what kind of picture one is, and its bits for a
#: reduced copy of another picture and for a transparency mask.
_NEW_SUBFILE_TYPE = 254
_REDUCED_IMAGE = 1
_MASK = 4

_PAGE_NAME = re.compile(r'^page([0-9]+)\.tif$')


def _is_page(image: Image.Image) -> bool:
    """Whether the picture <image> stands at is a page of its own."""
    kind = getattr(image, 'tag_v2', {}).get(_NEW_SUBFILE_TYPE, 0)
    return not (isinstance(kind, int) and kind & (_REDUCED_IMAGE | _MASK))


def _page_frames(image: Image.Image, at_most: int | None = None) \
        -> list[int]:
    """Which of the pictures in <image> are pages, by their position in
    the file; no more than <at_most> of them are looked for."""
    frames: list[int] = []
    frame = 0
    while at_most is None or len(frames) < at_most:
        try:
            image.seek(frame)
        except EOFError:
            break
        if _is_page(image):
            frames.append(frame)
        frame += 1
    return frames


def is_book(path: str, magic: bytes) -> bool:
    """Whether the file at <path>, which begins with <magic>, is a TIFF
    of more than one page.  Never raises: a TIFF that cannot be read is
    no book."""
    if not magic.startswith(SIGNATURES) \
            or not path.lower().endswith(_EXTENSIONS):
        return False
    try:
        with Image.open(path, formats=('TIFF',)) as image:
            return len(_page_frames(image, 2)) == 2
    except Exception:
        return False


class TiffArchive(archive_base.BaseArchive):

    """The pages of a TIFF, as though they were the files of an archive.

    The TIFF stays open for as long as the handler does: a page is read
    out of it when it is extracted.
    """

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        self._image: Image.Image | None = Image.open(
            archive, formats=('TIFF',))
        #: The position in the file of each page, in the order listed.
        self._frames: list[int] | None = None
        #: One picture of the file is current at a time, so one page is
        #: read at a time.
        self._reading = threading.Lock()

    def _pages(self) -> list[int]:
        """The position of each page; none once the file is closed.
        Called with the file to itself."""
        if self._image is None:
            return []
        if self._frames is None:
            self._frames = _page_frames(self._image)
        return self._frames

    def iter_contents(self) -> Iterator[str]:
        """Name each page after its number in the document."""
        with self._reading:
            count = len(self._pages())
        for number in range(1, count + 1):
            yield 'page%05d.tif' % number

    def extract(self, filename: str, destination_dir: str) -> None:
        """Write page <filename> to <destination_dir> as a TIFF of that
        one picture, turned the way the document says it is to be seen.
        """
        match = _PAGE_NAME.match(filename)
        if match is None:
            return
        destination_path = os.path.join(destination_dir, filename)
        with self._reading:
            image = self._image
            frames = self._pages()
            if image is None or not 0 < int(match[1]) <= len(frames):
                return
            image.seek(frames[int(match[1]) - 1])
            # Pillow checks the size of the first picture alone, when
            # it opens the file.
            width, height = image.size
            if Image.MAX_IMAGE_PIXELS is not None \
                    and width * height > Image.MAX_IMAGE_PIXELS:
                raise Image.DecompressionBombError(
                    '%s: page of %dx%d pixels' % (filename, width, height))
            # Packed without loss, whatever the document packed it
            # with: a scan of text to a hundredth of its size, anything
            # else to what costs the least time.
            compression = None
            if features.check('libtiff'):
                compression = 'group4' if image.mode == '1' else 'tiff_lzw'
            with self._create_file(destination_path) as new:
                image.save(new, format='TIFF', compression=compression)

    def close(self) -> None:
        """Let go of the file."""
        with self._reading:
            if self._image is not None:
                self._image.close()
                self._image = None


# vim: expandtab:sw=4:ts=4
