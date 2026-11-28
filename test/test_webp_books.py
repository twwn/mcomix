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

from gi.repository import GLib
from PIL import Image

from mcomix import archive_packer
from mcomix import archive_tools
from mcomix import constants
from mcomix import tools
from mcomix import webp_books
from mcomix.archive import sevenzip_external
from mcomix.archive import zip as zip_archive
from mcomix.page_shrink import Shrink
from mcomix.preferences import prefs

from . import (MComixTest, copy_rar_set, damage_member, drawn_page, encoded,
               get_testfile_path, line_art_png, refuse_passwords,
               sample_pages, skip_unless_rar_reads)


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

    """A file in the archive that cannot be read leaves the book as it
    was: written over, the archive would lose what can still be got out
    of the file.  A shrink, whose old archive goes to the trash, leaves
    the file out instead and writes the rest of the book, rather than
    costing all of it."""

    SHRINK = Shrink(limit=100, quality=80)

    def damaged_book(self, damaged='02.png'):
        """A ZIP of three PNG pages and a text, the bytes of <damaged>
        changed so that its checksum fails."""
        path = self.zip_book({name: line_art_png() for name in
                              ('01.png', '02.png', '03.png')}
                             | {'notes.txt': b'notes'})
        damage_member(path, damaged)
        return path

    def shrunk(self, path):
        return webp_books.convert(path, self.stop, shrink=self.SHRINK)

    def test_a_book_with_a_damaged_page_is_left_as_it_was(self):
        """Converted or repacked: the repack replaces a ZIP in place,
        or removes the old archive once the ZIP takes its place."""
        path = self.damaged_book()
        with open(path, 'rb') as book:
            before = book.read()
        for repack in (False, True):
            with self.subTest(repack=repack), \
                    self.assertRaises(webp_books.Skipped) as skipped:
                webp_books.convert(path, self.stop, repack=repack)
            self.assertTrue(skipped.exception.damaged)
        with open(path, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertEqual(['book.cbz'], os.listdir(self.directory))

    def test_asked_to_the_book_is_written_without_the_damaged_page(self):
        for repack in (False, True):
            with self.subTest(repack=repack):
                path = self.damaged_book()
                converted = webp_books.convert(path, self.stop,
                                               repack=repack,
                                               without_damaged=True)
                self.assertEqual(['02.png'], list(converted.left_out))
                with zipfile.ZipFile(path) as book:
                    self.assertNotIn('02.png', book.namelist())
                    self.assertEqual(b'notes', book.read('notes.txt'))

    def test_a_damaged_page_is_left_out_of_a_shrunk_book(self):
        path = self.damaged_book()
        converted = self.shrunk(path)
        with zipfile.ZipFile(path) as book:
            self.assertEqual(['01.webp', '03.webp', 'notes.txt'],
                             sorted(book.namelist()))
            self.assertEqual(b'notes', book.read('notes.txt'))
        self.assertEqual(['02.png'], list(converted.left_out))
        self.assertIn('CRC', converted.left_out['02.png'])
        self.assertEqual({'01.png': '01.webp', '03.png': '03.webp'},
                         converted.renamed)
        self.assertEqual(['book.cbz'], os.listdir(self.directory))
        self.assertEqual(1, len(os.listdir(self.trash_dir)))

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
            converted = self.shrunk(path)
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
            converted = self.shrunk(path)
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



class ShrinkTest(_BookTest):

    """A book of two pages over the limit, one under it and a text,
    surveyed and then shrunk."""

    SHRINK = Shrink(limit=600, quality=80)

    def setUp(self):
        super().setUp()
        self.members = {
            '01.jpg': encoded(drawn_page(1, (1000, 1500)), 'JPEG',
                              quality=95),
            '02.png': encoded(drawn_page(2, (400, 600)), 'PNG'),
            'sub/03.png': encoded(drawn_page(3, (1000, 1500)), 'PNG'),
            'notes.txt': b'kept as it was',
        }
        self.book = self.zip_book(self.members)

    def test_the_survey_counts_the_pages_over_the_limit_and_writes_nothing(
            self):
        with open(self.book, 'rb') as book:
            before = book.read()
        surveyed = webp_books.survey(self.book, self.SHRINK, self.stop)
        self.assertEqual(2, surveyed.pages)
        self.assertEqual(len(before), surveyed.size)
        over = len(self.members['01.jpg']) + len(self.members['sub/03.png'])
        self.assertGreater(surveyed.saved, over // 2)
        self.assertLess(surveyed.saved, over)
        with open(self.book, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertEqual(['book.cbz'], os.listdir(self.directory))

    def test_the_survey_of_a_book_with_no_page_over_the_limit(self):
        book = self.zip_book({'01.png': self.members['02.png']}, 'small.cbz')
        with self.assertRaises(webp_books.Skipped) as raised:
            webp_books.survey(book, self.SHRINK, self.stop)
        self.assertEqual('no page over the limit', str(raised.exception))

    def test_the_pages_over_the_limit_are_shrunk_and_the_book_trashed(self):
        with open(self.book, 'rb') as book:
            before = book.read()
        converted = webp_books.convert(self.book, self.stop,
                                       shrink=self.SHRINK)
        self.assertEqual({'01.jpg': '01.webp', '02.png': '02.png',
                          'sub/03.png': 'sub/03.webp'}, converted.renamed)
        self.assertEqual((len(before), os.path.getsize(self.book)),
                         (converted.before, converted.after))
        with zipfile.ZipFile(self.book) as book:
            self.assertEqual(
                ['01.webp', '02.png', 'notes.txt', 'sub/03.webp'],
                sorted(book.namelist()))
            self.assertEqual(self.members['02.png'], book.read('02.png'))
            with book.open('sub/03.webp') as member, \
                    Image.open(member) as page:
                self.assertEqual((400, 600), page.size)
        trashed, = os.listdir(self.trash_dir)
        with open(os.path.join(self.trash_dir, trashed), 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertEqual(['book.cbz'], os.listdir(self.directory))

    def test_a_book_not_trashed_is_replaced_in_place(self):
        """For a disk without room for both: a trash that would refuse
        it is never asked."""
        with unittest.mock.patch.object(tools, 'trash_refuses',
                                        return_value=True):
            converted = webp_books.convert(self.book, self.stop,
                                           shrink=self.SHRINK, trash=False)
        self.assertEqual(os.path.getsize(self.book), converted.after)
        with zipfile.ZipFile(self.book) as book:
            self.assertIn('sub/03.webp', book.namelist())
        self.assertFalse(os.path.exists(self.trash_dir), 'trashed')
        self.assertEqual(['book.cbz'], os.listdir(self.directory))

    def test_a_book_the_trash_refuses_is_left_as_it_was(self):
        with unittest.mock.patch.object(tools, 'move_to_trash',
                                        side_effect=GLib.Error('no trash')):
            self.assertSkipped(self.book, 'the trash refused it: no trash')
        with unittest.mock.patch.object(tools, 'trash_refuses',
                                        return_value=True):
            self.assertSkipped(self.book,
                               'the trash takes no files from its folder')

    def test_the_new_book_is_kept_where_the_old_one_could_not_be_replaced(
            self):
        """The book as it was is in the trash by then; the one written
        is all there is of it in its folder."""
        rename = webp_books.portability.rename_once_closed

        def refused(replace, source, target):
            # The packer's own rename, of its temporary file, goes on.
            if target == self.book:
                raise OSError(errno.EACCES, 'refused')
            rename(replace, source, target)
        with unittest.mock.patch.object(
                webp_books.portability, 'rename_once_closed', refused), \
                self.assertLogs('mcomix', level='WARNING') as logged, \
                self.assertRaises(OSError):
            webp_books.convert(self.book, self.stop, shrink=self.SHRINK)
        written, = os.listdir(self.directory)
        with zipfile.ZipFile(os.path.join(self.directory, written)) as book:
            self.assertIn('01.webp', book.namelist())
        self.assertEqual(1, len(os.listdir(self.trash_dir)))
        self.assertIn(written, '\n'.join(logged.output))

    def convert(self, path):
        return webp_books.convert(path, self.stop, shrink=self.SHRINK)


class ChainTest(_BookTest):

    """The steps ticked together in one pass: a page over the limit
    shrunk, the other PNG pages made smaller without loss, the book
    repacked as a ZIP last."""

    SHRINK = Shrink(limit=600, quality=80)

    def setUp(self):
        super().setUp()
        self.members = {'01.png': encoded(drawn_page(3, (1000, 1500)), 'PNG'),
                        '02.png': line_art_png(),
                        'notes.txt': b'kept as it was'}
        self.book = os.path.join(self.directory, 'book.cbt')
        with tarfile.open(self.book, 'w') as book:
            for member, data in self.members.items():
                info = tarfile.TarInfo(member)
                info.size = len(data)
                book.addfile(info, io.BytesIO(data))
        with open(self.book, 'rb') as book:
            self.before = book.read()
        self.zip_book_path = os.path.join(self.directory, 'book.cbz')

    def _contents(self):
        with zipfile.ZipFile(self.zip_book_path) as book:
            return {name: book.read(name) for name in book.namelist()}

    def test_all_three_steps_trash_the_book_and_leave_a_zip(self):
        converted = webp_books.convert(self.book, self.stop,
                                       shrink=self.SHRINK, repack=True,
                                       lossless=True)
        self.assertEqual(['book.cbz'], os.listdir(self.directory))
        self.assertEqual(self.zip_book_path, converted.moved_to)
        self.assertEqual({'01.png': '01.webp', '02.png': '02.webp'},
                         converted.renamed)
        contents = self._contents()
        self.assertEqual({'01.webp', '02.webp', 'notes.txt'}, set(contents))
        with Image.open(io.BytesIO(contents['01.webp'])) as page:
            self.assertEqual((400, 600), page.size)
        # Below the limit, made smaller without loss.
        self.assertEqual(pixels(self.members['02.png']),
                         pixels(contents['02.webp']))
        trashed, = os.listdir(self.trash_dir)
        with open(os.path.join(self.trash_dir, trashed), 'rb') as book:
            self.assertEqual(self.before, book.read())

    def test_a_shrink_without_lossless_leaves_the_other_pages(self):
        converted = webp_books.convert(self.book, self.stop,
                                       shrink=self.SHRINK, repack=True)
        self.assertEqual({'01.png': '01.webp', '02.png': '02.png'},
                         converted.renamed)
        self.assertEqual(self.members['02.png'], self._contents()['02.png'])

    def test_a_shrink_repacked_and_not_trashed_replaces_the_book(self):
        converted = webp_books.convert(self.book, self.stop,
                                       shrink=self.SHRINK, repack=True,
                                       trash=False)
        self.assertEqual(self.zip_book_path, converted.moved_to)
        self.assertEqual(['book.cbz'], os.listdir(self.directory))
        self.assertFalse(os.path.exists(self.trash_dir), 'trashed')

    def test_lossless_and_repack_replace_the_book_with_a_zip(self):
        converted = webp_books.convert(self.book, self.stop, repack=True,
                                       lossless=True)
        self.assertEqual(['book.cbz'], os.listdir(self.directory))
        self.assertEqual({'01.png': '01.webp', '02.png': '02.webp'},
                         converted.renamed)
        self.assertEqual(pixels(self.members['01.png']),
                         pixels(self._contents()['01.webp']))
        self.assertFalse(os.path.exists(self.trash_dir), 'trashed')

    def test_a_zip_made_meanwhile_leaves_the_shrunk_book(self):
        """The ZIP's name taken while the book was written: the book is
        not trashed for a ZIP that cannot take its place."""
        real = archive_packer.check_zip

        def taken(*args):
            real(*args)
            with open(self.zip_book_path, 'wb') as made:
                made.write(b'made meanwhile')
        with unittest.mock.patch.object(archive_packer, 'check_zip', taken), \
                self.assertRaises(webp_books.Skipped) as raised:
            webp_books.convert(self.book, self.stop, shrink=self.SHRINK,
                               repack=True)
        self.assertEqual('book.cbz is there already', str(raised.exception))
        self.assertEqual(['book.cbt', 'book.cbz'],
                         sorted(os.listdir(self.directory)))
        with open(self.book, 'rb') as book:
            self.assertEqual(self.before, book.read())


class RepackTest(_BookTest):

    """Books written again as ZIP, every file in them as it was."""

    TEXT = b'a text that deflates well ' * 200

    def convert(self, path):
        return webp_books.convert(path, self.stop, repack=True)

    def tar_book(self, members, name='book.cbt'):
        path = os.path.join(self.directory, name)
        with tarfile.open(path, 'w') as book:
            for member, data in members.items():
                info = tarfile.TarInfo(member)
                info.size = len(data)
                book.addfile(info, io.BytesIO(data))
        return path

    def assertPackedAsZip(self, path, members):
        """<path> is a ZIP of <members>, byte for byte, each picture
        stored and the text deflated."""
        with zipfile.ZipFile(path) as book:
            self.assertEqual(members, {name: book.read(name)
                                       for name in book.namelist()})
            self.assertEqual(
                {name: (zipfile.ZIP_DEFLATED if name.endswith('.txt')
                        else zipfile.ZIP_STORED) for name in members},
                {info.filename: info.compress_type
                 for info in book.infolist()})

    def test_a_tar_becomes_a_zip_of_its_name(self):
        members = {'01.png': line_art_png(),
                   'sub/02.png': line_art_png(size=(200, 300)),
                   'notes.txt': self.TEXT}
        path = self.tar_book(members)
        before = os.path.getsize(path)
        converted = self.convert(path)
        zip_book = os.path.join(self.directory, 'book.cbz')
        self.assertEqual(['book.cbz'], os.listdir(self.directory))
        self.assertPackedAsZip(zip_book, members)
        self.assertEqual(zip_book, converted.moved_to)
        self.assertEqual({'01.png': '01.png', 'sub/02.png': 'sub/02.png'},
                         converted.renamed)
        self.assertEqual((before, os.path.getsize(zip_book)),
                         (converted.before, converted.after))

    def test_a_zip_that_does_not_read_back_leaves_the_book(self):
        """The archive a repack replaces is removed for good: the ZIP is
        read back first."""
        path = self.tar_book({'01.png': line_art_png()})
        with open(path, 'rb') as file:
            before = file.read()
        failure = OSError(errno.EIO, 'the ZIP written does not read back')
        with unittest.mock.patch.object(webp_books.archive_packer,
                                        'check_zip', side_effect=failure):
            with self.assertRaises(OSError):
                self.convert(path)
        self.assertEqual(['book.cbt'], os.listdir(self.directory))
        with open(path, 'rb') as file:
            self.assertEqual(before, file.read())

    def test_a_rar_needs_no_rar_program(self):
        skip_unless_rar_reads(self)
        path = os.path.join(self.directory, 'Flat.rar')
        shutil.copy(get_testfile_path('archives', 'Flat.rar'), path)
        names = archive_tools.get_archive_handler(path).list_contents()
        with unittest.mock.patch.object(archive_packer, 'rar_executable',
                                        return_value=None):
            converted = self.convert(path)
        self.assertEqual(os.path.join(self.directory, 'Flat.zip'),
                         converted.moved_to)
        self.assertEqual(['Flat.zip'], os.listdir(self.directory))
        with zipfile.ZipFile(converted.moved_to) as book:
            self.assertEqual(sorted(names), sorted(book.namelist()))

    def test_a_zip_is_replaced_where_it_comes_out_smaller(self):
        members = {'01.png': line_art_png(), 'notes.txt': self.TEXT}
        path = os.path.join(self.directory, 'book.cbz')
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as book:
            for member, data in members.items():
                book.writestr(member, data)
        converted = self.convert(path)
        self.assertIsNone(converted.moved_to)
        self.assertLess(converted.after, converted.before)
        self.assertEqual(['book.cbz'], os.listdir(self.directory))
        self.assertPackedAsZip(path, members)

    def test_a_zip_no_smaller_packed_again_is_left(self):
        path = self.zip_book({'01.png': line_art_png()})
        self.assertSkipped(path, 'a ZIP already, no smaller packed again')

    def test_a_book_whose_zip_name_is_taken_is_left(self):
        path = self.tar_book({'01.png': line_art_png()})
        taken = self.zip_book({'01.png': b'another book'})
        with open(taken, 'rb') as book:
            before = book.read()
        with self.assertRaises(webp_books.Skipped) as raised:
            self.convert(path)
        self.assertEqual('book.cbz is there already', str(raised.exception))
        with open(taken, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertEqual(['book.cbt', 'book.cbz'],
                         sorted(os.listdir(self.directory)))

    @unittest.skipIf(sys.platform == 'win32',
                     'making a symbolic link needs rights on Windows')
    def test_a_link_to_a_book_of_another_format_is_left(self):
        path = self.tar_book({'01.png': line_art_png()})
        link = os.path.join(self.tmp_dir, 'link.cbt')
        os.symlink(path, link)
        with self.assertRaises(webp_books.Skipped) as raised:
            self.convert(link)
        self.assertEqual('a symbolic link, which would no longer lead to it',
                         str(raised.exception))
        self.assertEqual(['book.cbt'], os.listdir(self.directory))

    def test_a_pdf_is_not_repacked(self):
        path = os.path.join(self.directory, 'book.pdf')
        with open(path, 'wb') as book:
            book.write(b'%PDF-1.4\n')
        with unittest.mock.patch.object(archive_tools, 'archive_mime_type',
                                        return_value=constants.PDF):
            self.assertSkipped(path, 'not an archive of picture files: '
                               'PDF document')
        self.assertFalse(webp_books.can_repack(constants.PDF))
        self.assertTrue(webp_books.can_repack(constants.RAR))

    def test_the_old_book_kept_where_it_cannot_be_removed(self):
        """The ZIP holds all of it by then: the reader is told, and the
        book is counted as repacked."""
        path = self.tar_book({'01.png': line_art_png()})
        with unittest.mock.patch.object(
                tools, 'remove_file', side_effect=PermissionError(
                    errno.EACCES, 'refused')), \
                self.assertLogs('mcomix', level='WARNING') as logged:
            converted = self.convert(path)
        self.assertEqual(['book.cbt', 'book.cbz'],
                         sorted(os.listdir(self.directory)))
        self.assertEqual(os.path.join(self.directory, 'book.cbz'),
                         converted.moved_to)
        self.assertIn('could not be removed', '\n'.join(logged.output))

    def test_a_stop_leaves_the_book_and_writes_no_zip(self):
        path = self.tar_book({'01.png': line_art_png()})
        self.stop.set()
        with self.assertRaises(archive_packer.Cancelled):
            self.convert(path)
        self.assertEqual(['book.cbt'], os.listdir(self.directory))

    def test_the_zip_name(self):
        for path, becomes in (('a/b.cbr', 'a/b.cbz'), ('b.CB7', 'b.cbz'),
                              ('b.cbt', 'b.cbz'), ('b.rar', 'b.zip'),
                              ('b.7z', 'b.zip'), ('b.tar.gz', 'b.zip'),
                              ('b.TAR.XZ', 'b.zip'), ('b.lha', 'b.zip')):
            with self.subTest(path=path):
                self.assertEqual(becomes, webp_books.zip_name(path))

# vim: expandtab:sw=4:ts=4
