''' MobiPocket handling (extract pictures) for MComix.

    Based on code from mobiunpack by Charles M. Hannum et al.
'''

import os
import re
import struct
from collections.abc import Iterator
from typing import IO

from gi.repository import Gio

from mcomix import image_tools
from mcomix.archive import archive_base

class UnpackException(Exception):
    """The file is not a MobiPocket book this handler can read."""

class Sectionizer:

    """The record index at the head of a PalmDOC file.

    A MobiPocket book is a Palm database: a header naming the records,
    then the records themselves, each of which is a stretch of the file
    between two offsets.  The images a book holds are records like any
    other; which ones they are is what MobiArchive works out.
    """

    def __init__(self, f: IO[bytes]) -> None:
        self.f = f
        header = self.f.read(78)
        self.ident = header[0x3C:0x3C+8]
        self.num_sections, = struct.unpack_from('>H', header, 76)
        sections = self.f.read(self.num_sections*8)
        self.sections = struct.unpack_from('>%dL' % (self.num_sections*2), sections, 0)[::2] + (0x7fffffff, )

    def loadSection(self, section: int, limit: int = 0x7fffffff) -> bytes:
        """The bytes of record <section>, at most <limit> of them.

        The index holds one more offset than there are records, so the
        end of the last one is known like every other one's: it is where
        the next begins.
        """
        before, after = self.sections[section:section+2]
        self.f.seek(before)
        if limit > after - before:
            limit = after - before
        return self.f.read(limit)

class MobiArchive(archive_base.NonUnicodeArchive):

    """The images in a MobiPocket book, as though they were an archive.

    The book stays open for as long as the handler does, since a page is
    read out of it on demand rather than unpacked in advance.
    """

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        f = open(archive, 'rb')
        try:
            self.file: IO[bytes] | None = f
            self.sect = Sectionizer(self.file)
            if self.sect.ident != b'BOOKMOBI':
                raise UnpackException('invalid file format')
            self.header = self.sect.loadSection(0)
            self.crypto_type, = struct.unpack_from('>H', self.header, 0xC)
            if self.crypto_type != 0:
                raise UnpackException('file is encrypted')
            self.firstimg, = struct.unpack_from('>L', self.header, 0x6C)
        except BaseException:
            # Nothing here is handled - the file is closed and the
            # failure goes on to the caller - so this catches everything
            # an interrupt included, rather than only what derives from
            # Exception.
            self.file = None
            f.close()
            raise

    def _close(self) -> None:
        """Let go of the book, if it is still open."""
        if self.file is not None:
            self.file.close()
            self.file = None

    def iter_contents(self) -> Iterator[str]:
        ''' List archive contents. '''
        supported_mimes: dict[str, str] = {}
        for mimes,exts in image_tools.get_supported_formats().values():
            ext = next(iter(exts))
            for mime in mimes:
                supported_mimes[mime] = ext
        for i in range(self.firstimg, self.sect.num_sections):
            magic = self.sect.loadSection(i, 10)
            mime, uncertain = Gio.content_type_guess(data=magic)
            mime = mime.lower()
            if mime in supported_mimes:
                ext = supported_mimes[mime]
                yield "image%05d.%s" % (1+i-self.firstimg, ext)

    def extract(self, filename: str, destination_dir: str) -> None:
        ''' Extract <filename> from the archive to <destination_dir>. '''
        destination_path = os.path.join(destination_dir, filename)
        fnparts = re.split(r'^image([0-9]*)\.', filename)
        if len(fnparts) == 3:
            i = int(fnparts[1])-1+self.firstimg
            data = self.sect.loadSection(i)
            with self._create_file(destination_path) as new:
                new.write(data)

    def close(self) -> None:
        ''' Close the archive handle '''
        self._close()
