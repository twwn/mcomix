"""Storing the PNG pages of books as lossless WebP (mcomix.webp_books)."""

import io
import os
import shutil
import sys
import tarfile
import threading
import unittest
import unittest.mock
import zipfile

from PIL import Image

from mcomix import archive_packer
from mcomix import archive_tools
from mcomix import webp_books

from . import (MComixTest, copy_rar_set, get_testfile_path, line_art_png,
               refuse_passwords, sample_pages)


def pixels(data):
    with Image.open(io.BytesIO(data)) as picture:
        return picture.convert('RGBA').tobytes()


class _BookTest(MComixTest):

    """A book to convert, packed by the test in a folder of its own."""

    def setUp(self):
        super().setUp()
        self.directory = os.path.join(self.tmp_dir, 'books')
        os.makedirs(self.directory)
        self.stop = threading.Event()

    def zip_book(self, members, name='book.cbz'):
        """A ZIP at <name> holding <members>, a dict of name to bytes."""
        path = os.path.join(self.directory, name)
        with zipfile.ZipFile(path, 'w') as book:
            for member, data in members.items():
                book.writestr(member, data)
        return path

    def convert(self, path):
        return webp_books.convert(path, self.stop)

    def assertSkipped(self, path, reason):
        """Converting <path> skips it, saying <reason>, and leaves its
        bytes as they were."""
        with open(path, 'rb') as book:
            before = book.read()
        with self.assertRaises(webp_books.Skipped) as raised:
            self.convert(path)
        self.assertEqual(reason, str(raised.exception))
        with open(path, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertEqual([os.path.basename(path)],
                         os.listdir(os.path.dirname(path)))


class ConvertTest(_BookTest):

    def _contents(self, path):
        with zipfile.ZipFile(path) as book:
            return {name: book.read(name) for name in book.namelist()}

    def test_png_pages_become_webp_and_everything_else_stays(self):
        page = line_art_png()
        with open(sample_pages()[0], 'rb') as jpeg:
            photo = jpeg.read()
        path = self.zip_book({'art/01.png': page, '02.jpg': photo,
                              'notes.txt': b'notes', '._01.png': b'finder'})
        converted = self.convert(path)

        contents = self._contents(path)
        self.assertEqual({'art/01.webp', '02.jpg', 'notes.txt', '._01.png'},
                         set(contents))
        self.assertEqual(pixels(page), pixels(contents['art/01.webp']))
        self.assertEqual(photo, contents['02.jpg'])
        self.assertEqual(b'notes', contents['notes.txt'])
        self.assertEqual(b'finder', contents['._01.png'])
        # With "/" on Windows too, as the bookmarks hold a page's name.
        self.assertEqual({'art/01.png': 'art/01.webp', '02.jpg': '02.jpg'},
                         converted.renamed)
        self.assertEqual(os.path.getsize(path), converted.after)
        self.assertLess(converted.after, converted.before)
        # Nothing is left beside the book.
        self.assertEqual(['book.cbz'], os.listdir(self.directory))

    def test_the_pages_are_worked_on_away_from_the_book(self):
        """Only the new archive is written beside the book, under a name
        the library passes over: the pages unpacked and their WebPs
        made there were read and written again on the book's disk, and
        a watched folder saw each of them come and go."""
        beside = []
        made = archive_packer.webp_instead

        def looking(*args):
            beside.extend(os.listdir(self.directory))
            return made(*args)

        path = self.zip_book({'01.png': line_art_png()})
        with unittest.mock.patch.object(archive_packer, 'webp_instead',
                                        looking):
            self.convert(path)
        self.assertIn('book.cbz', beside)
        self.assertEqual([], [name for name in beside if name != 'book.cbz'
                              and not archive_tools.is_working_file(name)])

    def test_no_comicinfo_is_added(self):
        path = self.zip_book({'01.png': line_art_png()})
        self.convert(path)
        self.assertEqual({'01.webp'}, set(self._contents(path)))

    def test_a_tar_stays_a_tar(self):
        page = line_art_png()
        path = os.path.join(self.directory, 'book.cbt')
        with tarfile.open(path, 'w') as book:
            info = tarfile.TarInfo('01.png')
            info.size = len(page)
            book.addfile(info, io.BytesIO(page))
        self.convert(path)
        with tarfile.open(path) as book:
            self.assertEqual(['01.webp'], book.getnames())

    @unittest.skipIf(sys.platform == 'win32',
                     'Windows keeps no mode but whether a file is read-only')
    def test_the_mode_of_the_file_is_kept(self):
        path = self.zip_book({'01.png': line_art_png()})
        os.chmod(path, 0o640)
        self.convert(path)
        self.assertEqual(0o640, os.stat(path).st_mode & 0o777)

    def test_progress_ends_at_the_whole_book(self):
        path = self.zip_book({'01.png': line_art_png(), '02.png': line_art_png()})
        done = []
        webp_books.convert(path, self.stop, done.append)
        self.assertEqual(sorted(done), done)
        self.assertAlmostEqual(1.0, done[-1])


class SkippedTest(_BookTest):

    def test_a_book_without_png_pages(self):
        path = self.zip_book({'01.jpg': open(sample_pages()[0], 'rb').read()})
        self.assertSkipped(path, 'no PNG pages')

    def test_a_book_whose_pngs_would_not_be_smaller(self):
        """A PNG of 16 bits a channel has no lossless WebP; the archive is
        not written again for nothing."""
        buffer = io.BytesIO()
        Image.new('I;16', (32, 32), 1000).save(buffer, 'PNG')
        path = self.zip_book({'01.png': buffer.getvalue()})
        self.assertSkipped(path, 'no page smaller as WebP')

    def test_a_book_with_archives_inside(self):
        path = self.zip_book({'01.png': line_art_png(), 'inner.cbz': b'PK'})
        self.assertSkipped(path, 'archives inside')

    def test_an_encrypted_book_is_skipped_without_asking(self):
        asked = refuse_passwords(self)
        path = os.path.join(self.directory, 'Encrypted.zip')
        shutil.copy(get_testfile_path('archives', 'Encrypted.zip'), path)
        self.assertSkipped(path, 'encrypted')
        self.assertEqual([], asked)

    def test_a_format_mcomix_cannot_write(self):
        path = os.path.join(self.directory, 'Flat.lha')
        shutil.copy(get_testfile_path('archives', 'Flat.lha'), path)
        self.assertSkipped(path, 'a format MComix cannot write here')

    def test_a_book_in_volumes(self):
        first = copy_rar_set(self.directory)[0]
        with self.assertRaises(webp_books.Skipped) as raised:
            self.convert(first)
        self.assertEqual('split into volumes', str(raised.exception))

    def test_a_stopped_conversion_leaves_the_book(self):
        path = self.zip_book({'01.png': line_art_png()})
        with open(path, 'rb') as book:
            before = book.read()
        self.stop.set()
        with self.assertRaises(archive_packer.Cancelled):
            self.convert(path)
        with open(path, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertEqual(['book.cbz'], os.listdir(self.directory))

# vim: expandtab:sw=4:ts=4
