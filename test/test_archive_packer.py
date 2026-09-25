"""Packing the pages of an edited archive into a new one.

The pages are renamed so that their names sort the way the editor put
them, and the files that came with them keep the names they had unless
one of the pages has taken it.
"""

import os
import sys
import tarfile
import unittest
import unittest.mock
import zipfile
import xml.etree.ElementTree as ElementTree

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

    def test_a_comment_file_is_written_under_the_name_it_was_given(self):
        """A comment renamed in the archive editor is written under that
        name, as a page renamed there is."""
        packer = archive_packer.Packer(
            self.pages, [self.comment], self.archive, 'Comic',
            comment_names={self.comment: 'Notes.txt'})
        packer.pack()
        self.assertTrue(packer.wait())
        self.assertIn('Notes.txt', self._names())
        self.assertNotIn('comment.txt', self._names())

    def test_a_file_whose_name_a_page_has_taken_is_moved_aside(self):
        taken = os.path.join(self.tmp_dir, '1 - Comic.jpg')
        with open(taken, 'w') as clash:
            clash.write('not a page')
        self.assertTrue(self._pack('Comic', [taken]))
        self.assertIn('_1 - Comic.jpg', self._names())

    def test_two_pages_renamed_alike_are_both_written(self):
        """A name the reader gave one page can be the number another is
        written under; the second to claim it is moved aside rather than
        the archive holding two entries of one name."""
        packer = archive_packer.Packer(
            self.pages, [], self.archive, 'Comic',
            page_names={self.pages[1]: '1 - Comic.jpg'})
        packer.pack()
        self.assertTrue(packer.wait())
        self.assertEqual(['1 - Comic.jpg', '_1 - Comic.jpg', '3 - Comic.png'],
                         self._names())

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

    def test_a_clean_up_that_fails_as_well_stays_in_the_thread(self):
        """A write that fails for want of room leaves a writer whose
        closing fails the same way, and the exception from the finally
        clause went to threading.excepthook as a bare traceback."""
        writer = unittest.mock.Mock()
        writer.add.side_effect = OSError('no space left on device')
        writer.clean_up.side_effect = OSError('no space left on device')
        packer = archive_packer.Packer(self.pages, [], self.archive, 'Comic')
        with unittest.mock.patch.object(archive_packer, 'make_writer',
                                        return_value=writer), \
                unittest.mock.patch('threading.excepthook') as excepthook:
            packer.pack()
            self.assertFalse(packer.wait())
        writer.clean_up.assert_called_once_with()
        excepthook.assert_not_called()


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

    @unittest.skipIf(archive_packer.szip_executable() is None,
                     '7-Zip is not installed')
    def test_pages_that_cannot_be_linked_are_copied_to_7z(self):
        """The pages are laid out for 7z by linking them, which fails
        across file systems; they are copied then."""
        def refuse(*args):
            raise OSError(18, 'Invalid cross-device link')

        with unittest.mock.patch('os.link', side_effect=refuse):
            path, packed = self._pack('Comic.cb7', constants.SEVENZIP)
        self.assertTrue(packed)
        self.assertIn('Path = 2 - Comic.jpg',
                      os.popen('7z l -ba -slt %s' % path).read())

    def _staging_left(self):
        return [name for name in os.listdir(self.tmp_dir)
                if name.startswith('mcomix-pack.')]

    def test_7z_that_is_not_installed_packs_nothing(self):
        with unittest.mock.patch.object(archive_packer._SevenZipWriter,
                                        '_executable', return_value=None):
            _path, packed = self._pack('Comic.cb7', constants.SEVENZIP)
        self.assertFalse(packed)
        self.assertEqual([], self._staging_left())

    def test_an_archiver_that_refuses_packs_nothing(self):
        with unittest.mock.patch.object(archive_packer._SevenZipWriter,
                                        '_executable',
                                        return_value='/bin/false'), \
                unittest.mock.patch.object(archive_packer.process, 'call',
                                           return_value=False):
            _path, packed = self._pack('Comic.cb7', constants.SEVENZIP)
        self.assertFalse(packed)
        self.assertEqual([], self._staging_left())

    def test_an_archive_that_cannot_be_created_packs_nothing(self):
        refused = OSError(13, 'Permission denied')
        with unittest.mock.patch.object(archive_packer, 'make_writer',
                                        side_effect=refused):
            _path, packed = self._pack('Comic.cbz', constants.ZIP)
        self.assertFalse(packed)

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


class WriteArchiveTest(MComixTest):

    """write_archive(), and the ComicInfo.xml it puts in every archive.

    A book saved without one is a ZIP of pictures to every other reader,
    so one goes in; one the archive already carried is kept as it is
    unless a page added or removed has made its count wrong.
    """

    def setUp(self):
        super().setUp()
        self.pages = [get_testfile_path('images', name)
                      for name in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg',
                                   '03-PNG-RGB.png')]
        self.directory = os.path.join(self.tmp_dir, 'books')
        os.makedirs(self.directory)
        self.archive = os.path.join(self.directory, 'packed.cbz')

    def _write(self, pages=None, carried_files=None):
        archive_packer.write_archive(
            self.archive, self.pages if pages is None else pages, [],
            carried_files=carried_files)

    def _carried(self, body, name='ComicInfo.xml'):
        """An existing ComicInfo.xml, as the file handler hands one over."""
        path = os.path.join(self.tmp_dir, 'carried.xml')
        with open(path, 'wb') as fp:
            fp.write(body)
        return {path: name}

    def _read(self, name='ComicInfo.xml'):
        with zipfile.ZipFile(self.archive) as packed:
            return packed.read(name)

    def _names(self):
        with zipfile.ZipFile(self.archive) as packed:
            return packed.namelist()

    @unittest.skipIf(sys.platform == 'win32', 'symbolic links need privileges')
    def test_a_book_saved_through_a_link_is_saved_where_the_link_points(self):
        """A book reached through a symbolic link - a reading list of
        links into the collection - was written back over the link: the
        book in the collection kept its old pages, and a copy with the
        new ones stood where the link had been."""
        shelf = os.path.join(self.tmp_dir, 'shelf')
        os.makedirs(shelf)
        book = os.path.join(shelf, 'book.cbz')
        archive_packer.write_archive(book, self.pages[:1], [])
        os.symlink(book, self.archive)

        self._write()

        self.assertTrue(os.path.islink(self.archive))
        with zipfile.ZipFile(book) as packed:
            self.assertEqual(4, len(packed.namelist()))
        self.assertEqual(['book.cbz'], os.listdir(shelf))

    def test_an_archive_written_from_nothing_carries_a_comicinfo(self):
        self._write()
        self.assertIn('ComicInfo.xml', self._names())
        root = ElementTree.fromstring(self._read())
        self.assertEqual('3', root.findtext('PageCount'))

    def test_a_tar_carries_one_as_well_as_a_zip_does(self):
        """ComicInfo.xml is what a comic archive carries, whatever the
        container is: a CBT and a CB7 are read by the same programs a
        CBZ is, and the file goes in before the format is chosen."""
        self.archive = os.path.join(self.directory, 'packed.cbt')
        archive_packer.write_archive(self.archive, self.pages, [],
                                     archive_type=constants.TAR)
        with tarfile.open(self.archive) as written:
            self.assertIn('ComicInfo.xml', written.getnames())
            body = written.extractfile('ComicInfo.xml').read()
        self.assertEqual('3',
                         ElementTree.fromstring(body).findtext('PageCount'))

    def test_the_comicinfo_counts_the_pages_that_were_written(self):
        self._write(pages=self.pages[:2])
        root = ElementTree.fromstring(self._read())
        self.assertEqual('2', root.findtext('PageCount'))
        self.assertEqual(2, len(root.find('Pages').findall('Page')))

    def test_one_that_still_counts_the_pages_is_carried_untouched(self):
        body = (b'<ComicInfo><Series>S</Series>'
                b'<PageCount>3</PageCount></ComicInfo>')
        self._write(carried_files=self._carried(body))
        self.assertEqual(body, self._read())

    def test_one_a_deletion_has_invalidated_is_written_again(self):
        self._write(pages=self.pages[:2], carried_files=self._carried(
            b'<ComicInfo><Series>S</Series>'
            b'<PageCount>3</PageCount></ComicInfo>'))
        root = ElementTree.fromstring(self._read())
        self.assertEqual('2', root.findtext('PageCount'))
        self.assertEqual('S', root.findtext('Series'),
                         'the rewrite dropped what it does not describe')

    def test_a_rewritten_one_stays_where_the_archive_kept_it(self):
        """Carrying a file means carrying it where it was; a copy at the
        root would be a second ComicInfo.xml rather than the same one."""
        self._write(pages=self.pages[:1], carried_files=self._carried(
            b'<ComicInfo><PageCount>3</PageCount></ComicInfo>',
            name='meta/ComicInfo.xml'))
        self.assertEqual(['meta/ComicInfo.xml'],
                         [name for name in self._names()
                          if name.endswith('ComicInfo.xml')])
        root = ElementTree.fromstring(self._read('meta/ComicInfo.xml'))
        self.assertEqual('1', root.findtext('PageCount'))

    def test_one_that_cannot_be_read_is_written_again(self):
        """Carried but unreadable is not the same as absent."""
        self._write(carried_files={'/no/such/ComicInfo.xml': 'ComicInfo.xml'})
        root = ElementTree.fromstring(self._read())
        self.assertEqual('3', root.findtext('PageCount'))

    def test_one_handed_over_as_a_comment_is_written_again_too(self):
        """The default comment extensions take in .xml, so a book's
        ComicInfo.xml usually comes as a comment rather than as a carried
        file.  The comment was packed under that name and the rewrite
        skipped as a name already taken, so a book that had lost a page
        kept a count that still named it."""
        comment = os.path.join(self.tmp_dir, 'ComicInfo.xml')
        with open(comment, 'wb') as fp:
            fp.write(b'<ComicInfo><Series>S</Series>'
                     b'<PageCount>3</PageCount></ComicInfo>')
        archive_packer.write_archive(self.archive, self.pages[:2], [comment])
        self.assertEqual(['ComicInfo.xml'],
                         [name for name in self._names()
                          if name.lower().endswith('comicinfo.xml')])
        root = ElementTree.fromstring(self._read())
        self.assertEqual('2', root.findtext('PageCount'))
        self.assertEqual('S', root.findtext('Series'),
                         'the rewrite dropped what it does not describe')

    def test_nothing_is_left_beside_the_archive_that_was_written(self):
        self._write()
        self.assertEqual(['packed.cbz'], os.listdir(self.directory))

    def test_a_packer_that_fails_fails_the_write(self):
        """The packer runs on a thread of its own and answers whether it
        managed; a failure there has to come out of write_archive() as
        the error it raises, with nothing left behind."""
        with unittest.mock.patch.object(
                archive_packer._ZipWriter, 'add',
                side_effect=OSError(5, 'Input/output error')), \
                self.assertRaisesRegex(OSError, 'could not be packed'):
            self._write()
        self.assertEqual([], os.listdir(self.directory))

    def test_nothing_is_left_beside_an_archive_that_failed(self):
        with self.assertRaises(OSError):
            self._write(pages=self.pages + ['/no/such/page.jpg'])
        self.assertEqual([], os.listdir(self.directory))

    def test_the_old_archive_stays_when_the_new_one_cannot_take_its_place(self):
        """The old archive was deleted before the new one was renamed
        over it, and the new one was deleted as a leftover when the
        rename failed, so the book was gone from the disk."""
        self._write()
        with open(self.archive, 'rb') as fp:
            before = fp.read()
        rename, replace = os.rename, os.replace

        def _refused(real):
            def move(source, target, *args, **kwargs):
                if target == self.archive:
                    raise PermissionError(13, 'Permission denied', target)
                return real(source, target, *args, **kwargs)
            return move

        with unittest.mock.patch('os.rename', _refused(rename)), \
                unittest.mock.patch('os.replace', _refused(replace)), \
                self.assertRaises(OSError):
            self._write(pages=self.pages[:1])
        with open(self.archive, 'rb') as fp:
            self.assertEqual(before, fp.read())
        self.assertEqual(['packed.cbz'], os.listdir(self.directory))

    def test_the_old_archive_stays_when_the_permissions_cannot_be_set(self):
        """The mode was set once the new archive had replaced the old
        one, so a failure there reported a save that had not happened
        over an archive that had already been written over."""
        self._write()
        with open(self.archive, 'rb') as fp:
            before = fp.read()

        def refuse(*args, **kwargs):
            raise PermissionError(1, 'Operation not permitted')

        with unittest.mock.patch('os.chmod', refuse), \
                self.assertRaises(OSError):
            self._write(pages=self.pages[:1])
        with open(self.archive, 'rb') as fp:
            self.assertEqual(before, fp.read())
        self.assertEqual(['packed.cbz'], os.listdir(self.directory))


# vim: expandtab:sw=4:ts=4
