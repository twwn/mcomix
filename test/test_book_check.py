"""Whether every file of a book can be read (mcomix.library.book_check)."""

import errno
import os
import shutil
import threading
import unittest.mock
import zipfile

from . import (MComixTest, NORMAL_ZIP, copy_rar_set, damage_member,
               get_testfile_path, line_art_png, refuse_passwords,
               skip_unless_rar_reads)
from mcomix.archive import zip as zip_archive
from mcomix.library import book_check
from mcomix.library.book_check import Fault


class CheckTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.stop = threading.Event()

    def check(self, path):
        return book_check.check(path, self.stop)

    def copied(self, *components):
        path = os.path.join(self.tmp_dir, components[-1])
        shutil.copy(get_testfile_path(*components), path)
        return path

    def zip_book(self, files):
        path = os.path.join(self.tmp_dir, 'book.cbz')
        with zipfile.ZipFile(path, 'w') as book:
            for name, data in files.items():
                book.writestr(name, data)
        return path

    def test_a_sound_book(self):
        self.assertIsNone(self.check(NORMAL_ZIP))

    def test_nothing_is_left_behind(self):
        """Each file is deleted as it comes out, and the folder after."""
        work = os.path.join(self.tmp_dir, 'work')
        os.mkdir(work)
        self.enterContext(unittest.mock.patch.object(
            book_check.archive_packer, 'working_folder', return_value=work))
        removed = []
        remove = book_check.tools.remove_file
        self.enterContext(unittest.mock.patch.object(
            book_check.tools, 'remove_file',
            lambda path: (removed.append(path), remove(path))))
        self.assertIsNone(self.check(NORMAL_ZIP))
        self.assertEqual([], os.listdir(work))
        self.assertTrue(removed)

    def test_a_damaged_file_is_named(self):
        path = self.zip_book({'01.png': line_art_png(),
                              '02.png': line_art_png(),
                              'notes.txt': b'notes'})
        damage_member(path, '02.png')
        checked = self.check(path)
        self.assertEqual(Fault.DAMAGED, checked.fault)
        self.assertEqual(['02.png'], list(checked.unreadable))

    def test_damage_past_the_pages_counts_too(self):
        """A file that is no page is a file the book cannot give back."""
        path = self.zip_book({'01.png': line_art_png(),
                              'notes.txt': b'notes' * 20})
        damage_member(path, 'notes.txt')
        self.assertEqual(['notes.txt'],
                         list(self.check(path).unreadable))

    def test_an_encrypted_book_asks_nothing(self):
        asked = refuse_passwords(self)
        checked = self.check(self.copied('archives', 'Encrypted.zip'))
        self.assertEqual(Fault.ENCRYPTED, checked.fault)
        self.assertEqual([], asked)

    def test_a_file_that_is_no_archive(self):
        path = os.path.join(self.tmp_dir, 'book.cbz')
        with open(path, 'wb') as book:
            book.write(b'\x00\x00\x00\x18ftypmp42' + bytes(64))
        self.assertEqual(Fault.NOT_AN_ARCHIVE, self.check(path).fault)

    def test_a_zip_whose_listing_is_cut_off(self):
        path = os.path.join(self.tmp_dir, 'cut.cbz')
        with open(NORMAL_ZIP, 'rb') as whole:
            data = whole.read()
        with open(path, 'wb') as book:
            book.write(data[:len(data) // 2])
        self.assertIn(self.check(path).fault,
                      (Fault.NOT_AN_ARCHIVE, Fault.DAMAGED))

    def test_a_format_nothing_here_reads(self):
        path = self.copied('archives', 'Flat.lha')
        with unittest.mock.patch.object(book_check.archive_tools,
                                        'get_archive_handler',
                                        return_value=None):
            self.assertEqual(Fault.NO_READER, self.check(path).fault)

    def test_a_later_volume_is_read_with_its_first(self):
        skip_unless_rar_reads(self)
        first, second, third = copy_rar_set(self.tmp_dir)
        self.assertIsNone(self.check(second))
        self.assertIsNone(self.check(first))

    def test_a_full_disk_is_not_the_book(self):
        def full(archive, names, directory):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), names[0])
            yield

        with unittest.mock.patch.object(
                zip_archive.ZipArchive, 'iter_extract', full), \
                self.assertRaises(OSError) as raised:
            self.check(NORMAL_ZIP)
        self.assertEqual(errno.ENOSPC, raised.exception.errno)

    def test_stopped(self):
        self.stop.set()
        with self.assertRaises(book_check.Stopped):
            self.check(NORMAL_ZIP)

    def test_the_faults_are_named(self):
        for fault, name in ((Fault.NOT_AN_ARCHIVE,
                             'damaged, or not an archive'),
                            (Fault.NO_READER,
                             'nothing installed here reads the format'),
                            (Fault.ENCRYPTED, 'encrypted'),
                            (Fault.DAMAGED, 'damaged')):
            with self.subTest(fault=fault):
                self.assertEqual(name, fault.describe())
