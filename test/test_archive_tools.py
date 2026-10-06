
import lzma
import os
import tarfile

from . import MComixTest, get_testfile_path

from mcomix import archive_tools
from mcomix import constants


_EXTENSION_TO_MIME_TYPES = {
    'cbz': constants.ZIP,
    'zip': constants.ZIP,
    'zip.bz2': constants.ZIP_EXTERNAL,
    'rar': constants.RAR,
    # The volumes of Multivolume.rar: each starts with the RAR signature.
    'part1.rar': constants.RAR,
    'part2.rar': constants.RAR,
    'part3.rar': constants.RAR,
    'tar': constants.TAR,
    'tar.gz': constants.GZIP,
    'tar.bz2': constants.BZIP2,
    # Python's tarfile module reads xz compressed tarballs itself, so these
    # are handled as plain tar rather than handed to the 7z executable.
    'tar.xz': constants.TAR,
    'pdf': constants.PDF,
    '7z': constants.SEVENZIP,
    'lha': constants.LHA,
}

_ARCHIVE_TYPE_NAMES = {
    constants.ZIP: 'zip',
    constants.RAR: 'rar',
    constants.TAR: 'tar',
    constants.GZIP: 'gzip',
    constants.BZIP2: 'bzip2',
    constants.XZ: 'xz',
    constants.PDF: 'pdf',
    constants.SEVENZIP: '7z',
    constants.LHA: 'lha',
    constants.ZIP_EXTERNAL: 'zip (external)',
}


class ArchiveToolsTest(MComixTest):

    def test_archive_mime_type(self):

        dir = get_testfile_path('archives')
        for filename in os.listdir(dir):
            ext = '.'.join(filename.split('.')[1:])
            path = os.path.join(dir, filename)
            archive_type = archive_tools.archive_mime_type(path)
            expected_type = _EXTENSION_TO_MIME_TYPES.get(ext, '???')
            msg = (
                'archive_mime_type("%s") failed; '
                'result differs: %s [%s] instead of %s [%s]'
                % (path,
                   archive_type, _ARCHIVE_TYPE_NAMES.get(archive_type, '???'),
                   expected_type, _ARCHIVE_TYPE_NAMES.get(expected_type, '???'))
            )
            self.assertEqual(archive_type, expected_type, msg=msg)

    def test_only_the_first_volume_of_a_rar_set_is_a_book(self):
        for part, later in ((1, False), (2, True), (3, True)):
            with self.subTest(part=part):
                self.assertEqual(later, archive_tools.is_later_volume(
                    get_testfile_path('archives',
                                      'Multivolume.part%d.rar' % part)))
        for name in ('RAR4.rar', 'RAR5.rar', '01-ZIP-Normal.zip'):
            with self.subTest(name=name):
                self.assertFalse(archive_tools.is_later_volume(
                    get_testfile_path('archives', name)))

    def test_a_later_volume_leads_to_the_first_one_beside_it(self):
        import shutil
        for width in (1, 2):
            with self.subTest(width=width):
                directory = os.path.join(self.tmp_dir, 'width%d' % width)
                os.makedirs(directory)
                names = []
                for part in (1, 2, 3):
                    name = 'Set.part%s.rar' % str(part).zfill(width)
                    shutil.copy(get_testfile_path(
                        'archives', 'Multivolume.part%d.rar' % part),
                        os.path.join(directory, name))
                    names.append(os.path.join(directory, name))
                first, second, third = names
                self.assertEqual(first, archive_tools.first_volume(second))
                self.assertEqual(first, archive_tools.first_volume(third))
                self.assertIsNone(archive_tools.first_volume(first))
                os.remove(first)
                self.assertIsNone(archive_tools.first_volume(second))

    def test_a_book_that_is_no_later_volume_leads_nowhere(self):
        self.assertIsNone(archive_tools.first_volume(
            get_testfile_path('archives', '03-RAR-Normal.rar')))

    def test_a_later_rar_4_volume_is_told_by_its_flags(self):
        """The rar here writes only RAR 5, so the main header of a RAR 4
        volume is written by hand: CRC16, type 0x73, the flags, size."""
        def header(flags):
            return (b'Rar!\x1a\x07\x00' + b'\x00\x00\x73'
                    + flags.to_bytes(2, 'little') + b'\x0d\x00' + bytes(6))
        volume, new_numbering, first_volume = 0x0001, 0x0010, 0x0100
        for flags, later in (
                (volume | new_numbering, True),
                (volume | new_numbering | first_volume, False),
                # Before RAR 3, which named the others name.r00 and so on.
                (volume, False),
                (0, False)):
            with self.subTest(flags=hex(flags)):
                path = os.path.join(self.tmp_dir, 'set.part2.rar')
                with open(path, 'wb') as volume_file:
                    volume_file.write(header(flags))
                self.assertEqual(later, archive_tools.is_later_volume(path))

    def test_a_rar_that_ends_inside_its_header_is_not_a_later_volume(self):
        path = os.path.join(self.tmp_dir, 'short.rar')
        with open(path, 'wb') as short:
            short.write(b'Rar!\x1a\x07\x01\x00\x00\x00\x00\x00\x8c')
        self.assertFalse(archive_tools.is_later_volume(path))

    def test_empty_tar_is_a_tar(self):

        path = os.path.join(self.tmp_dir, 'empty.tar')
        tarfile.open(path, 'w:').close()
        self.assertEqual(archive_tools.archive_mime_type(path), constants.TAR)

    def test_the_formats_with_no_fixture_are_told_by_their_first_bytes(self):
        """PDF, MOBI, and a single file compressed with xz or lzma that
        is not a tarball: test/files/archives holds none of them."""
        page = b'not a tarball, only what was compressed'
        for name, content, expected in (
                ('book.pdf', b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n', constants.PDF),
                ('book.mobi', bytes(60) + b'BOOKMOBI' + bytes(8),
                 constants.MOBI),
                ('page.xz', lzma.compress(page), constants.XZ),
                ('page.lzma', lzma.compress(page, format=lzma.FORMAT_ALONE),
                 constants.XZ)):
            with self.subTest(name=name):
                path = os.path.join(self.tmp_dir, name)
                with open(path, 'wb') as archive:
                    archive.write(content)
                self.assertEqual(expected,
                                 archive_tools.archive_mime_type(path))

    def test_zero_filled_file_is_not_an_archive(self):

        # A run of zero bytes is a well-formed empty archive as far as
        # tarfile is concerned, and reading one as a tar used to hand the
        # whole file to every decompressor tarfile knows before saying so.
        path = os.path.join(self.tmp_dir, 'broken.zip')
        with open(path, 'wb') as broken:
            broken.write(b'\0' * (tarfile.RECORDSIZE * 8))
        self.assertIsNone(archive_tools.archive_mime_type(path))


class UnrarLibraryTest(MComixTest):

    def test_libunrar_is_not_loaded_from_the_current_directory(self):
        """Where the system had no libunrar, the one in whatever
        directory MComix was started from was loaded: a library planted
        in a folder of downloads ran as MComix."""
        import ctypes
        import sys
        import unittest.mock
        from mcomix.archive import rar
        if sys.platform == 'win32':
            self.skipTest('Windows searches for DLLs by its own rules')
        tried = []

        def load(path):
            tried.append(path)
            raise OSError('not loaded')

        # Cached for the process: cleared on both sides, so that neither
        # this answer nor an earlier one outlives the patch.
        rar._get_unrar_dll.cache_clear()
        self.addCleanup(rar._get_unrar_dll.cache_clear)
        with unittest.mock.patch('ctypes.util.find_library',
                                 return_value=None), \
                unittest.mock.patch.object(ctypes.cdll, 'LoadLibrary', load):
            self.assertIsNone(rar._get_unrar_dll())
        self.assertTrue(tried, 'nothing was tried, so this proves nothing')
        cwd = os.getcwd()
        self.assertEqual([path for path in tried
                          if os.path.dirname(os.path.abspath(path)) == cwd],
                         [])


class DescribeTest(MComixTest):

    def test_a_tarball_is_described_by_its_compression(self):
        """An xz compressed tarball is of type TAR, since tarfile reads
        it like a plain one, and was described as a plain one although
        a gzip or bzip2 compressed one was not."""
        for name, described in (('SolidFlat.tar', 'Tar archive'),
                                ('SolidFlat.tar.gz',
                                 'Gzip compressed tar archive'),
                                ('SolidFlat.tar.bz2',
                                 'Bzip2 compressed tar archive'),
                                ('SolidFlat.tar.xz',
                                 'XZ compressed tar archive')):
            with self.subTest(name):
                path = get_testfile_path('archives', name)
                self.assertEqual(described, archive_tools.describe(
                    path, archive_tools.archive_mime_type(path)))


class CannotOpenTest(MComixTest):
    """What a reader is told about an archive that no installed handler
    opens.  It said "Non-supported archive format" of a RAR on a system
    with no unrar, which left them to guess what to install (upstream
    forum topic d6af396b68)."""

    def test_the_message_names_what_the_format_needs(self):
        for name, said in (
                ('04-7Z-Normal.7z',
                 'Could not open 04-7Z-Normal.7z: it needs 7z.'),
                ('03-RAR-Normal.rar',
                 'Could not open 03-RAR-Normal.rar: it needs unrar or 7z.'),
                ('Flat.lha', 'Could not open Flat.lha: it needs 7z or lha.')):
            with self.subTest(name):
                self.assertEqual(said, archive_tools.cannot_open(
                    get_testfile_path('archives', name)))

    def test_a_pdf_needs_pymupdf_or_mutool(self):
        self.assertEqual(
            'Could not open book.pdf: it needs PyMuPDF or mutool.',
            archive_tools.cannot_open(os.path.join('nowhere', 'book.pdf'),
                                      constants.PDF))

    def test_a_file_of_no_known_format_is_said_to_be_unsupported(self):
        path = os.path.join(self.tmp_dir, 'notes.txt')
        with open(path, 'w') as fp:
            fp.write('nothing an archive handler reads')
        self.assertEqual('Non-supported archive format: notes.txt',
                         archive_tools.cannot_open(path))

    def test_every_format_without_a_handler_of_its_own_names_one(self):
        """A handler added without a helper would leave its format with
        the message that names nothing."""
        for archive_type in archive_tools._HANDLERS:
            with self.subTest(archive_type):
                if archive_type in (constants.ZIP, constants.TAR,
                                    constants.GZIP, constants.BZIP2,
                                    constants.MOBI):
                    self.assertEqual([], archive_tools.helpers(archive_type))
                else:
                    self.assertTrue(archive_tools.helpers(archive_type))
