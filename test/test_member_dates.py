"""When each page was last modified, as the archive records it.

The status bar dates a page of an archive by this, since a page unpacked
from it is only as old as the unpacking (upstream feature request 94).
Each format keeps the date its own way: a zip as local time, a tarball
and a 7z as UTC, a RAR (to the library) as a DOS time.
"""

import os
import tarfile
import time
import unittest
import zipfile

from . import MComixTest, get_testfile_path

from mcomix.archive import archive_base
from mcomix.archive import rar
from mcomix.archive import rar_external
from mcomix.archive import sevenzip_external
from mcomix.archive import tar
from mcomix.archive import zip

PAGE = 'images/01-JPG-Indexed.jpg'
#: The same member as a handler lists it, with the system's separator.
LISTED = PAGE.replace('/', os.sep)


def _archive(name):
    return get_testfile_path('archives', name)


def _zip_date(name, member=PAGE):
    with zipfile.ZipFile(_archive(name)) as archive:
        return time.mktime(archive.getinfo(member).date_time + (0, 0, -1))


def _tar_date(name, member=PAGE):
    with tarfile.open(_archive(name)) as archive:
        return float(archive.getmember(member).mtime)


class MemberDateTest(MComixTest):

    def _date(self, handler, member=PAGE):
        member = member.replace('/', os.sep)
        try:
            names = list(handler.iter_contents())
            self.assertIn(member, names)
            return handler.member_date(member)
        finally:
            handler.close()

    def test_a_zip_keeps_local_time(self):
        self.assertEqual(_zip_date('01-ZIP-Normal.zip'),
                         self._date(zip.ZipArchive(_archive('01-ZIP-Normal.zip'))))

    def test_a_tarball_keeps_utc(self):
        self.assertEqual(_tar_date('02-TAR-Normal.tar'),
                         self._date(tar.TarArchive(_archive('02-TAR-Normal.tar'))))

    @unittest.skipUnless(sevenzip_external.SevenZipArchive.is_available(),
                         'no 7z')
    def test_7z_dates_a_7z_as_the_tarball_of_the_same_pages(self):
        """7z prints a time kept in UTC moved by today's offset, which put
        a winter date an hour late in summer; the same picture, packed
        alike, has the same date in the tarball."""
        self.assertEqual(
            _tar_date('02-TAR-Normal.tar'),
            self._date(sevenzip_external.SevenZipArchive(
                _archive('04-7Z-Normal.7z'))))

    @unittest.skipUnless(sevenzip_external.SevenZipArchive.is_available(),
                         'no 7z')
    def test_7z_dates_a_zip_as_python_does(self):
        self.assertEqual(
            _zip_date('01-ZIP-Normal.zip'),
            self._date(sevenzip_external.SevenZipArchive(
                _archive('01-ZIP-Normal.zip'))))

    @unittest.skipUnless(rar.RarArchive.is_available(), 'no UnRAR library')
    def test_the_unrar_library_reads_the_dos_time(self):
        date = self._date(rar.RarArchive(_archive('03-RAR-Normal.rar')),
                          'images/03-PNG-RGB.png')
        self.assertEqual('2011-01-07 14:01:40',
                         time.strftime('%Y-%m-%d %H:%M:%S',
                                       time.localtime(date)))

    @unittest.skipUnless(rar_external.RarArchive.is_available(), 'no unrar')
    def test_unrar_prints_the_full_time(self):
        """The library's DOS time has two-second steps; unrar's listing
        has the second itself."""
        date = self._date(
            rar_external.RarArchive(_archive('03-RAR-Normal.rar')),
            'images/03-PNG-RGB.png')
        self.assertEqual('2011-01-07 14:01:41',
                         time.strftime('%Y-%m-%d %H:%M:%S',
                                       time.localtime(date)))

    def test_a_member_never_listed_has_no_date(self):
        handler = zip.ZipArchive(_archive('01-ZIP-Normal.zip'))
        try:
            self.assertIsNone(handler.member_date(LISTED))
        finally:
            handler.close()


class TimestampTest(unittest.TestCase):

    def test_a_dos_time_is_unpacked(self):
        packed = ((2011 - 1980) << 25 | 1 << 21 | 7 << 16
                  | 14 << 11 | 1 << 5 | 20)
        self.assertEqual(time.mktime((2011, 1, 7, 14, 1, 40, 0, 0, -1)),
                         archive_base.dos_timestamp(packed))

    def test_text_that_is_no_time_has_none(self):
        self.assertIsNone(archive_base.local_timestamp('yesterday'))
        self.assertIsNone(archive_base.today_shifted_timestamp(''))
        self.assertIsNone(archive_base.dos_timestamp(0))
