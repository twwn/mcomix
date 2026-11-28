"""Storing the PNG pages of books as lossless WebP (mcomix.webp_books)."""

import errno
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
from mcomix import constants
from mcomix import webp_books
from mcomix.archive import sevenzip_external
from mcomix.archive import zip as zip_archive
from mcomix.preferences import prefs

from . import (MComixTest, copy_rar_set, damage_member, get_testfile_path,
               line_art_png, refuse_passwords, sample_pages,
               skip_unless_rar_reads)


def pixels(data):
    with Image.open(io.BytesIO(data)) as picture:
        return picture.convert('RGBA').tobytes()


class _Packer:

    """Stands in for archive_packer.Packer: each wait on it writes one
    more of <files> files, and the waits and the first stop are kept."""

    def __init__(self, files):
        self.files = files
        self.written = 0
        self.waits = []
        self.stopped_at = None

    def finished(self, timeout=0):
        self.waits.append(timeout)
        if self.written == self.files:
            return True
        self.written += 1
        return False

    def progress(self):
        return self.written, self.files

    def stop(self):
        if self.stopped_at is None:
            self.stopped_at = self.written


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

    def assertSkipped(self, path, reason, damaged=False):
        """Converting <path> skips it, saying <reason>, as a book whose
        file could not be read where <damaged>, and leaves its bytes as
        they were."""
        with open(path, 'rb') as book:
            before = book.read()
        with self.assertRaises(webp_books.Skipped) as raised:
            self.convert(path)
        self.assertEqual(reason, str(raised.exception))
        self.assertEqual(damaged, raised.exception.damaged)
        with open(path, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertEqual([os.path.basename(path)],
                         os.listdir(os.path.dirname(path)))


class ConvertTest(_BookTest):

    def _contents(self, path):
        with zipfile.ZipFile(path) as book:
            return {name: book.read(name) for name in book.namelist()}

    def test_png_pages_become_webp_and_everything_else_stays(self):
        """The JPEG is one jpegtran makes no smaller."""
        page = line_art_png()
        with open(sample_pages()[1], 'rb') as jpeg:
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

    def test_the_pages_are_worked_on_in_the_unpack_folder(self):
        """The folder the preference names, as for a book opened."""
        folder = os.path.join(self.tmp_dir, 'unpack')
        os.makedirs(folder)
        self.enterContext(unittest.mock.patch.dict(
            prefs, {'unpack folder': folder}))
        there = []
        made = archive_packer.webp_instead

        def looking(*args):
            there.extend(os.listdir(folder))
            return made(*args)

        path = self.zip_book({'01.png': line_art_png()})
        with unittest.mock.patch.object(archive_packer, 'webp_instead',
                                        looking):
            self.convert(path)
        # The book unpacked, and the WebPs made of its pages.
        self.assertEqual(2, len(there), msg=there)
        self.assertTrue(all(name.startswith('mcomix-') for name in there),
                        msg=there)
        self.assertEqual([], os.listdir(folder))

    def test_a_folder_the_archive_lists_is_no_file_left_out(self):
        path = self.zip_book({'art/': b'', 'art/01.png': line_art_png()})
        converted = self.convert(path)
        self.assertEqual({}, converted.left_out)
        self.assertEqual({'art/01.png': 'art/01.webp'}, converted.renamed)

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
        # Unpacking is the first fifth, a share for each file out.
        self.assertEqual([0.1, 0.2], [round(value, 6) for value in done[:2]])
        self.assertAlmostEqual(1.0, done[-1])

    def test_the_writing_is_the_rest_of_the_progress_and_can_be_stopped(self):
        """Read off the packer at each wait: a stand-in here, which
        writes one of four files each time it is waited on."""
        packer = _Packer(4)
        done = []

        def write(*args, waiting, **kwargs):
            waiting(packer)
            return {}

        def progress(value):
            done.append(round(value, 6))
            if value >= 0.6:
                self.stop.set()

        path = self.zip_book({'01.png': line_art_png()})
        with unittest.mock.patch.object(archive_packer, 'write_archive',
                                        write):
            webp_books.convert(path, self.stop, progress)
        self.assertEqual([0.2, 0.4, 0.6, 0.8, 1.0, 1.0], done)
        self.assertEqual({webp_books._TICK}, set(packer.waits))
        # Told at the next wait after Stop, and not before.
        self.assertEqual(3, packer.stopped_at)

    def test_a_jpeg_page_is_optimised_under_its_own_name(self):
        """sample_pages()[0] was written without optimised tables."""
        if not archive_packer._optimises_jpegs():
            self.skipTest('jpegtran is not installed')
        with open(sample_pages()[0], 'rb') as jpeg:
            photo = jpeg.read()
        path = self.zip_book({'01.JPEG': photo})
        converted = self.convert(path)
        self.assertEqual({'01.JPEG': '01.JPEG'}, converted.renamed)
        with zipfile.ZipFile(path) as book:
            optimised = book.read('01.JPEG')
        self.assertLess(len(optimised), len(photo))
        self.assertEqual(pixels(photo), pixels(optimised))

    def test_gif_pages_become_webp_as_well(self):
        from PIL import Image
        with Image.open(io.BytesIO(line_art_png())) as art:
            gif = io.BytesIO()
            art.convert('P').save(gif, 'GIF')
        path = self.zip_book({'01.gif': gif.getvalue()})
        converted = self.convert(path)
        self.assertEqual({'01.gif': '01.webp'}, converted.renamed)
        with zipfile.ZipFile(path) as book:
            self.assertEqual(pixels(gif.getvalue()),
                             pixels(book.read('01.webp')))


class DamagedTest(_BookTest):

    """A file in the archive that cannot be read is left out of it,
    rather than costing the whole book: every other page was lost with
    it before, the book reported as not written."""

    def damaged_book(self, damaged='02.png'):
        """A ZIP of three PNG pages and a text, the bytes of <damaged>
        changed so that its checksum fails."""
        path = self.zip_book({name: line_art_png() for name in
                              ('01.png', '02.png', '03.png')}
                             | {'notes.txt': b'notes'})
        damage_member(path, damaged)
        return path

    def test_a_damaged_page_is_left_out(self):
        path = self.damaged_book()
        converted = self.convert(path)
        with zipfile.ZipFile(path) as book:
            self.assertEqual(['01.webp', '03.webp', 'notes.txt'],
                             sorted(book.namelist()))
            self.assertEqual(b'notes', book.read('notes.txt'))
        self.assertEqual(['02.png'], list(converted.left_out))
        self.assertIn('CRC', converted.left_out['02.png'])
        self.assertEqual({'01.png': '01.webp', '03.png': '03.webp'},
                         converted.renamed)
        self.assertEqual(['book.cbz'], os.listdir(self.directory))

    def test_a_file_that_comes_out_as_nothing_is_left_out(self):
        """The reader's book failed with "[Errno 2] No such file or
        directory" over its damaged page."""
        path = self.damaged_book()
        extract = zip_archive.ZipArchive.extract

        def missing(archive, name, directory):
            if name == '01.png':
                raise FileNotFoundError(2, 'No such file or directory',
                                        os.path.join(directory, name))
            return extract(archive, name, directory)

        with unittest.mock.patch.object(zip_archive.ZipArchive, 'extract',
                                        missing):
            converted = self.convert(path)
        self.assertEqual(['01.png', '02.png'], sorted(converted.left_out))
        with zipfile.ZipFile(path) as book:
            self.assertEqual(['03.webp', 'notes.txt'],
                             sorted(book.namelist()))

    def test_a_file_said_to_be_out_that_is_not_is_left_out(self):
        path = self.zip_book({'01.png': line_art_png(),
                              '02.png': line_art_png()})
        iter_extract = zip_archive.ZipArchive.iter_extract

        def losing(archive, names, directory):
            for name in iter_extract(archive, names, directory):
                if name == '01.png':
                    os.remove(os.path.join(directory, name))
                yield name

        with unittest.mock.patch.object(zip_archive.ZipArchive,
                                        'iter_extract', losing):
            converted = self.convert(path)
        self.assertEqual({'01.png': 'nothing came out of it'},
                         converted.left_out)
        self.assertEqual({'02.png': '02.webp'}, converted.renamed)

    def test_a_failure_that_is_no_os_error_is_told_as_one(self):
        path = self.damaged_book()
        with unittest.mock.patch.object(
                zip_archive.ZipArchive, 'list_contents',
                side_effect=RuntimeError('the listing failed')), \
                self.assertRaises(OSError) as raised:
            self.convert(path)
        self.assertEqual('the listing failed', str(raised.exception))

    def test_a_full_disk_is_no_damaged_file(self):
        path = self.damaged_book()
        with open(path, 'rb') as book:
            before = book.read()

        def full(archive, name, directory):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), name)

        with unittest.mock.patch.object(zip_archive.ZipArchive, 'extract',
                                        full), \
                self.assertRaises(OSError) as raised:
            self.convert(path)
        self.assertEqual(errno.ENOSPC, raised.exception.errno)
        with open(path, 'rb') as book:
            self.assertEqual(before, book.read())


class SkippedTest(_BookTest):

    def test_a_book_without_png_pages(self):
        """Nor GIF or JPEG pages: only pictures stored as they are."""
        webp = io.BytesIO()
        Image.new('RGB', (32, 32), 'white').save(webp, 'WEBP')
        path = self.zip_book({'01.webp': webp.getvalue()})
        self.assertSkipped(path, 'no PNG, GIF or JPEG pages')

    def test_a_book_whose_pngs_would_not_be_smaller(self):
        """A PNG of 16 bits a channel has no lossless WebP; the archive is
        not written again for nothing."""
        buffer = io.BytesIO()
        Image.new('I;16', (32, 32), 1000).save(buffer, 'PNG')
        path = self.zip_book({'01.png': buffer.getvalue()})
        self.assertSkipped(path, 'no page made smaller')

    def test_a_book_with_archives_inside(self):
        path = self.zip_book({'01.png': line_art_png(), 'inner.cbz': b'PK'})
        self.assertSkipped(path, 'archives inside')

    def test_an_encrypted_book_is_skipped_without_asking(self):
        asked = refuse_passwords(self)
        path = os.path.join(self.directory, 'Encrypted.zip')
        shutil.copy(get_testfile_path('archives', 'Encrypted.zip'), path)
        self.assertSkipped(path, 'encrypted')
        self.assertEqual([], asked)

    def test_every_kind_of_encrypted_book_is_skipped(self):
        """Their names encrypted too or not, solid or not: some fail
        their listing, some each file, some come out empty.  Whether
        MComix could write them back does not come into it."""
        asked = refuse_passwords(self)
        self.enterContext(unittest.mock.patch.object(
            archive_packer, 'can_write', return_value=True))
        for name in ('Encrypted.7z', 'EncryptedHeader.7z', 'Encrypted.rar',
                     'EncryptedHeader.rar', 'SolidEncrypted.7z',
                     'SolidEncryptedHeader.7z', 'SolidEncrypted.rar',
                     'SolidEncryptedHeader.rar'):
            with self.subTest(name=name):
                if name.endswith('.rar'):
                    skip_unless_rar_reads(self)
                elif not sevenzip_external.SevenZipArchive.is_available():
                    self.skipTest('7z is not installed')
                folder = os.path.join(self.directory, name)
                os.makedirs(folder)
                path = os.path.join(folder, name)
                shutil.copy(get_testfile_path('archives', name), path)
                self.assertSkipped(path, 'encrypted')
        self.assertEqual([], asked)

    def test_a_format_mcomix_cannot_write(self):
        path = os.path.join(self.directory, 'Flat.lha')
        shutil.copy(get_testfile_path('archives', 'Flat.lha'), path)
        self.assertSkipped(path, 'a format MComix does not write: '
                           'LHA archive')

    def test_a_file_that_is_no_archive(self):
        """A damaged book, or a video saved as one, is told as such and
        not as a format MComix cannot write."""
        path = os.path.join(self.directory, 'book.cbz')
        with open(path, 'wb') as book:
            book.write(b'\x00\x00\x00\x18ftypmp42' + bytes(64))
        self.assertSkipped(path, 'damaged, or not an archive', damaged=True)

    def test_a_rar_without_the_rar_program(self):
        path = os.path.join(self.directory, 'Flat.rar')
        shutil.copy(get_testfile_path('archives', 'Flat.rar'), path)
        with unittest.mock.patch.object(archive_packer, 'rar_executable',
                                        return_value=None):
            self.assertSkipped(path, 'the rar program that writes the '
                               'format is not installed')

    def test_no_png_pages_is_told_before_the_missing_program(self):
        """A book done before, in a format written only with a program
        that is not installed, has nothing to write either way: it is
        told as having no PNG, GIF or JPEG pages.  The ZIP stands in for that format
        here, since every RAR the tests carry holds a PNG."""
        path = self.zip_book({'01.webp': b'RIFF'})
        with unittest.mock.patch.object(archive_packer, 'can_write',
                                        return_value=False), \
                unittest.mock.patch.dict(webp_books._WRITTEN_BY_PROGRAM,
                                         {constants.ZIP: 'zip'}):
            self.assertSkipped(path, 'no PNG, GIF or JPEG pages')

    def test_a_book_in_volumes(self):
        for parts in ((1, 2, 3), (1, 2)):
            with self.subTest(parts=parts):
                first = copy_rar_set(os.path.join(self.directory,
                                                  str(len(parts))),
                                     parts=parts)[0]
                with self.assertRaises(webp_books.Skipped) as raised:
                    self.convert(first)
                self.assertEqual('split into volumes', str(raised.exception))

    def test_a_format_nothing_installed_here_reads(self):
        path = self.zip_book({'01.png': line_art_png()})
        with unittest.mock.patch.object(archive_tools, 'get_archive_handler',
                                        return_value=None):
            self.assertSkipped(path, 'nothing installed here reads the format')

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
