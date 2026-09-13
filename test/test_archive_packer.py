"""Packing the pages of an edited archive into a new one.

The pages are renamed so that their names sort the way the editor put
them, and the files that came with them keep the names they had unless
one of the pages has taken it.
"""

import os
import tarfile
import unittest
import unittest.mock
import zipfile

from . import MComixTest, get_testfile_path

from mcomix import archive_packer
from mcomix import constants


class PackerTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.pages = [get_testfile_path('images', name)
                      for name in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg',
                                   '03-PNG-RGB.png')]
        self.comment = os.path.join(self.tmp_dir, 'comment.txt')
        with open(self.comment, 'w') as comment:
            comment.write('a comment')
        self.archive = os.path.join(self.tmp_dir, 'packed.zip')

    def _pack(self, base_name, other_files=()):
        packer = archive_packer.Packer(self.pages, list(other_files),
                                       self.archive, base_name)
        packer.pack()
        return packer.wait()

    def _names(self):
        with zipfile.ZipFile(self.archive) as packed:
            return packed.namelist()

    def test_the_pages_are_numbered_in_the_order_they_were_given(self):
        self.assertTrue(self._pack('Comic'))
        self.assertEqual(['1 - Comic.jpg', '2 - Comic.jpg', '3 - Comic.png'],
                         self._names())

    def test_a_name_with_a_per_cent_sign_in_it_is_a_name_like_any_other(self):
        # The number and the extension used to be spliced into a format
        # string that the name itself had already been spliced into, so
        # a per cent sign in the name was read as a format of its own:
        # "My%20Comic", which is what a download names a file, raised
        # ValueError out of the packer thread and left the archive open.
        self.assertTrue(self._pack('My%20Comic'))
        self.assertEqual(['1 - My%20Comic.jpg', '2 - My%20Comic.jpg',
                          '3 - My%20Comic.png'], self._names())

    def test_the_numbers_are_padded_to_sort_lexically(self):
        packer = archive_packer.Packer(self.pages * 4, [], self.archive, 'C')
        packer.pack()
        self.assertTrue(packer.wait())
        self.assertTrue(self._names()[0].startswith('01 - '))

    def test_the_other_files_keep_their_names(self):
        self.assertTrue(self._pack('Comic', [self.comment]))
        self.assertIn('comment.txt', self._names())

    def test_a_file_whose_name_a_page_has_taken_is_moved_aside(self):
        taken = os.path.join(self.tmp_dir, '1 - Comic.jpg')
        with open(taken, 'w') as clash:
            clash.write('not a page')
        self.assertTrue(self._pack('Comic', [taken]))
        self.assertIn('_1 - Comic.jpg', self._names())

    def test_every_entry_is_deflated(self):
        """The pages were stored rather than deflated, so an archive
        rewritten with a page or two removed could still come out larger
        than the one it was made from."""
        self.assertTrue(self._pack('Comic', [self.comment]))
        with zipfile.ZipFile(self.archive) as packed:
            self.assertEqual({info.compress_type
                              for info in packed.infolist()},
                             {zipfile.ZIP_DEFLATED})

    def test_a_page_whose_bytes_compress_is_written_compressed(self):
        """Not every image is a compressed one: a BMP or an
        uncompressed TIFF page took its whole size in the archive."""
        page = os.path.join(self.tmp_dir, 'page.bmp')
        with open(page, 'wb') as uncompressed:
            uncompressed.write(b'\0' * 100000)
        packer = archive_packer.Packer([page], [], self.archive, 'Comic')
        packer.pack()
        self.assertTrue(packer.wait())
        self.assertLess(os.path.getsize(self.archive), 10000,
                        'the page was written at its full size')

    def test_a_carried_file_keeps_the_name_it_had_in_the_archive(self):
        """The pages are renamed and the imported files are flattened,
        but a file carried over from the archive being edited is only
        there so that the new archive still holds it."""
        carried = os.path.join(self.tmp_dir, 'ComicInfo.xml')
        with open(carried, 'w') as written:
            written.write('<ComicInfo/>')
        packer = archive_packer.Packer(
            self.pages, [], self.archive, 'Comic',
            carried_files={carried: 'meta/ComicInfo.xml'})
        packer.pack()
        self.assertTrue(packer.wait())
        self.assertIn('meta/ComicInfo.xml', self._names())

    def test_a_carried_file_under_a_name_already_written_is_left_out(self):
        """The editor shows the comment files itself, so one of those is
        written from its list and must not be written again."""
        packer = archive_packer.Packer(
            self.pages, [self.comment], self.archive, 'Comic',
            carried_files={self.comment: 'comment.txt'})
        packer.pack()
        self.assertTrue(packer.wait())
        self.assertEqual(self._names().count('comment.txt'), 1)

    def test_a_page_that_is_not_there_leaves_no_half_written_archive(self):
        packer = archive_packer.Packer(self.pages + ['/no/such/page.jpg'], [],
                                       self.archive, 'Comic')
        packer.pack()
        self.assertFalse(packer.wait())
        self.assertFalse(os.path.exists(self.archive),
                         'the half-written archive was left behind')


class WriterTest(MComixTest):

    """The three formats a book can be written back into.

    MComix reads a dozen and writes what the standard library and 7-Zip
    can make: a ZIP, a tar, and a 7z where 7-Zip is installed.
    """

    def setUp(self):
        super().setUp()
        self.pages = [get_testfile_path('images', name)
                      for name in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg')]

    def _pack(self, name, archive_type):
        path = os.path.join(self.tmp_dir, name)
        packer = archive_packer.Packer(self.pages, [], path, 'Comic',
                                       archive_type=archive_type)
        packer.pack()
        return path, packer.wait()

    def test_a_zip_is_what_a_book_is_written_as_by_default(self):
        path, packed = self._pack('Comic.cbz', constants.ZIP)
        self.assertTrue(packed)
        with zipfile.ZipFile(path) as written:
            self.assertEqual(written.namelist(),
                             ['1 - Comic.jpg', '2 - Comic.jpg'])

    def test_a_tar_holds_the_same_entries(self):
        path, packed = self._pack('Comic.cbt', constants.TAR)
        self.assertTrue(packed)
        with tarfile.open(path) as written:
            self.assertEqual(written.getnames(),
                             ['1 - Comic.jpg', '2 - Comic.jpg'])

    def test_a_tar_is_compressed_the_way_its_name_says_it_is(self):
        """tarfile reads an xz tar as any other, so the archive type
        says only "a tar": a .tar.gz written back uncompressed would be
        a file that is not what it says it is."""
        path, packed = self._pack('Comic.tar.gz', constants.GZIP)
        self.assertTrue(packed)
        with open(path, 'rb') as written:
            self.assertEqual(written.read(2), b'\x1f\x8b', 'not gzipped')
        with tarfile.open(path, 'r:gz') as written:
            self.assertEqual(len(written.getnames()), 2)

    def test_a_tar_that_says_nothing_about_compression_has_none(self):
        path, packed = self._pack('Comic.cbt', constants.TAR)
        self.assertTrue(packed)
        with tarfile.open(path, 'r:') as written:
            self.assertEqual(len(written.getnames()), 2)

    @unittest.skipIf(archive_packer.szip_executable() is None,
                     '7-Zip is not installed')
    def test_a_7z_holds_the_same_entries(self):
        """7z names an entry after the file it is given, so the entries
        are laid out under a directory of their own and that is what it
        is pointed at."""
        path, packed = self._pack('Comic.cb7', constants.SEVENZIP)
        self.assertTrue(packed)
        listing = os.popen('7z l -ba -slt %s' % path).read()
        self.assertIn('Path = 1 - Comic.jpg', listing)
        self.assertIn('Path = 2 - Comic.jpg', listing)
        self.assertEqual([name for name in os.listdir(self.tmp_dir)
                          if name.startswith('mcomix-pack.')], [],
                         'the staging directory was left behind')

    @unittest.skipIf(archive_packer.szip_executable() is None,
                     '7-Zip is not installed')
    def test_a_7z_is_written_over_the_empty_file_holding_its_name(self):
        """The editor writes under a temporary name it takes with
        mkstemp, which leaves an empty file there; 7z adds to an archive
        that is already there and refuses a file that is not one."""
        path = os.path.join(self.tmp_dir, 'Comic.cb7')
        open(path, 'wb').close()
        packer = archive_packer.Packer(self.pages, [], path, 'Comic',
                                       archive_type=constants.SEVENZIP)
        packer.pack()
        self.assertTrue(packer.wait(), '7z would not write the archive')
        self.assertIn('Path = 1 - Comic.jpg',
                      os.popen('7z l -ba -slt %s' % path).read())

    @unittest.skipIf(archive_packer.rar_executable() is None,
                     'the rar program is not installed')
    def test_a_rar_holds_the_same_entries(self):
        """unrar, which is what a RAR is read with, only ever reads; the
        rar program itself makes one, and is installed by hand where it
        is installed at all."""
        path, packed = self._pack('Comic.cbr', constants.RAR)
        self.assertTrue(packed, 'rar would not write the archive')
        listing = os.popen('unrar lb %s' % path).read().split('\n')
        self.assertIn('1 - Comic.jpg', listing)
        self.assertIn('2 - Comic.jpg', listing)

    def test_a_format_that_cannot_be_written_is_written_as_a_zip(self):
        """Nothing makes an LHA, a PDF or a MOBI out of a book."""
        path, packed = self._pack('Comic.cbz', constants.LHA)
        self.assertTrue(packed)
        self.assertTrue(zipfile.is_zipfile(path))

    def test_which_formats_can_be_written(self):
        for archive_type in (constants.ZIP, constants.ZIP_EXTERNAL,
                             constants.TAR, constants.GZIP, constants.BZIP2):
            self.assertTrue(archive_packer.can_write(archive_type))
        for archive_type in (constants.LHA, constants.PDF,
                             constants.MOBI, None):
            self.assertFalse(archive_packer.can_write(archive_type))
        self.assertEqual(archive_packer.can_write(constants.SEVENZIP),
                         archive_packer.szip_executable() is not None)
        self.assertEqual(archive_packer.can_write(constants.RAR),
                         archive_packer.rar_executable() is not None)

    def test_a_program_that_is_not_installed_is_not_offered(self):
        with unittest.mock.patch.object(archive_packer, 'szip_executable',
                                        lambda: None):
            self.assertFalse(archive_packer.can_write(constants.SEVENZIP))
        with unittest.mock.patch.object(archive_packer, 'rar_executable',
                                        lambda: None):
            self.assertFalse(archive_packer.can_write(constants.RAR))


# vim: expandtab:sw=4:ts=4
