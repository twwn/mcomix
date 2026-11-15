"""An outside program that could not write a page for want of room says
so in words of its own, if at all; the handler says it as the system
does, so that the reader is told the folder is full."""

import collections
import errno
import os
import unittest
from unittest import mock

from mcomix import process
from mcomix.archive import (
    archive_base,
    djvu_external,
    pdf_external,
    rar_external,
    sevenzip_external,
)

from . import MComixTest, get_testfile_path

_Usage = collections.namedtuple('_Usage', 'total used free')


def _room(free):
    return mock.patch.object(archive_base.shutil, 'disk_usage',
                             return_value=_Usage(10 ** 9, 10 ** 9 - free, free))


class RoomTest(MComixTest):

    def _raised(self, *args):
        try:
            archive_base.raise_if_no_room(*args)
        except OSError as error:
            return error.errno
        return None

    def test_less_room_than_the_file_takes_is_no_room(self):
        path = os.path.join(self.tmp_dir, 'page.jpg')
        with _room(299):
            self.assertEqual(errno.ENOSPC, self._raised(path, 300))
            self.assertEqual(errno.ENOSPC, self._raised(path))
            self.assertIsNone(self._raised(path, 299))
            # An empty file takes none.
            self.assertIsNone(self._raised(path, 0))

    def test_a_file_of_unknown_size_needs_the_folder_all_but_full(self):
        path = os.path.join(self.tmp_dir, 'page.png')
        with _room(1 << 20):
            self.assertIsNone(self._raised(path))

    def test_a_folder_that_cannot_be_asked_is_not_called_full(self):
        self.assertIsNone(self._raised(
            os.path.join(self.tmp_dir, 'gone', 'page.png')))


class HandlerTest(MComixTest):

    """Each handler, with its program failing: over a full folder it
    raises as the system does, and with room to spare it does not."""

    def _extract(self, archive, name, free):
        self.addCleanup(archive.close)
        destination = os.path.join(self.tmp_dir, 'out%d' % free)
        with _room(free):
            archive.extract(name, destination)

    def _both(self, make, name, failing):
        with failing:
            with self.assertRaises(OSError) as raised:
                self._extract(make(), name, 0)
            self.assertEqual(errno.ENOSPC, raised.exception.errno)
            try:
                self._extract(make(), name, 10 ** 9)
            except OSError as error:
                self.assertNotEqual(errno.ENOSPC, error.errno)
            except sevenzip_external.ExtractionError:
                pass

    @unittest.skipUnless(rar_external.RarArchive.is_available(),
                         'needs unrar')
    def test_unrar(self):
        def make():
            archive = rar_external.RarArchive(
                get_testfile_path('archives', '03-RAR-Normal.rar'))
            self.name = archive.list_contents()[0]
            return archive
        make().close()
        self._both(make, self.name,
                   mock.patch.object(process, 'call', return_value=False))

    @unittest.skipUnless(sevenzip_external.SevenZipArchive.is_available(),
                         'needs 7z')
    def test_7z(self):
        """7z leaves with an error, as it does over a write that
        failed."""
        ready = []
        for _ in range(2):
            archive = sevenzip_external.SevenZipArchive(
                get_testfile_path('archives', '04-7Z-Normal.7z'))
            name = archive.list_contents()[0]
            ready.append(archive)
        failed = mock.Mock(returncode=2, stderr=b'ERROR: errno=28')
        self._both(ready.pop, name, mock.patch.object(
            sevenzip_external.subprocess, 'run', return_value=failed))

    @unittest.skipUnless(pdf_external.PdfArchive.is_available(),
                         'needs mutool')
    def test_mutool(self):
        path = os.path.join(self.tmp_dir, 'book.pdf')
        with open(path, 'wb') as fp:
            fp.write(b'%PDF-1.4\n')
        self._both(lambda: pdf_external.PdfArchive(path), '1.png',
                   mock.patch.object(process, 'call', return_value=False))

    @unittest.skipUnless(djvu_external.DjvuArchive.is_available(),
                         'needs DjVuLibre')
    def test_ddjvu(self):
        path = os.path.join(self.tmp_dir, 'book.djvu')
        with open(path, 'wb') as fp:
            fp.write(b'AT&TFORM')
        self._both(lambda: djvu_external.DjvuArchive(path), '1.tif',
                   mock.patch.object(process, 'call', return_value=False))
