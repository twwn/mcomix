import hashlib
import io
import locale
import os
import re
import shutil
import sys
import tarfile
import tempfile
import unittest
import unittest.mock
import zipfile

from . import MComixTest, get_testfile_path

try:
    import chardet
except ImportError:
    chardet = None

from mcomix import process
from mcomix.archive import (
    archive_recursive,
    lha_external,
    rar,
    rar_external,
    sevenzip_external,
    tar,
    zip,
    zip_external,
)
# Aliased: the plain name is used as a loop and parameter name below.
from mcomix.archive import password as archive_password

#: The real password prompt, which the tests below stand in for and put
#: back afterwards.
_REAL_ASK_FOR_PASSWORD = archive_password.ask_for_password


class UnsupportedFormat(Exception):

    def __init__(self, format):
        super().__init__('unsuported %s format' % format)


class UnsupportedOption(Exception):

    def __init__(self, format, option):
        super().__init__('unsuported option for %s format: %s' % (format, option))


def make_archive(outfile, contents, format='zip', solid=False, password=None, header_encryption=False):
    if os.path.exists(outfile):
        raise Exception('%s already exists' % outfile)
    cleanup = []
    try:
        outpath = os.path.abspath(outfile)
        tmp_dir = tempfile.mkdtemp(dir='test/tmp', prefix='make_archive.')
        cleanup.append(lambda: shutil.rmtree(tmp_dir))
        entry_list = []
        for name, filename in contents:
            entry_list.append(name)
            path = os.path.join(tmp_dir, name)
            if filename is None:
                os.makedirs(path)
                continue
            dir = os.path.dirname(path)
            if not os.path.exists(dir):
                os.makedirs(dir)
            shutil.copy(filename, path)
        if '7z' == format:
            cmd = ['7z', 'a']
            cmd.append('-ms=on' if solid else '-ms=off')
            if password is not None:
                cmd.append('-p' + password)
                if header_encryption:
                    cmd.append('-mhe=on')
            else:
                assert not header_encryption
            cmd.extend(('--', outpath))
            # To avoid @ being treated as a special character...
            tmp_file = tempfile.NamedTemporaryFile(dir='test/tmp',
                                                   prefix='make_archive.',
                                                   delete=False)
            cleanup.append(lambda: os.unlink(tmp_file.name))
            for entry in entry_list:
                tmp_file.write(entry.encode(locale.getpreferredencoding()) + '\n')
            tmp_file.close()
            entry_list = ['@' + tmp_file.name]
        elif 'lha' == format:
            assert password is None
            assert not header_encryption
            if solid:
                raise UnsupportedOption(format, 'solid')
            cmd = ['lha', 'a', outpath, '--']
        elif 'rar' == format:
            cmd = ['rar', 'a', '-r']
            cmd.append('-s' if solid else '-s-')
            if password is not None:
                if header_encryption:
                    cmd.append('-hp' + password)
                else:
                    cmd.append('-p' + password)
            else:
                assert not header_encryption
            cmd.extend(('--', outpath))
        elif format.startswith('tar'):
            assert password is None
            assert not header_encryption
            if not solid:
                raise UnsupportedOption(format, 'not solid')
            if 'tar' == format:
                compression = ''
            elif 'tar.bz2' == format:
                compression = 'j'
            elif 'tar.gz' == format:
                compression = 'z'
            elif 'tar.xz' == format:
                compression = 'J'
            else:
                raise UnsupportedFormat(format)
            cmd = ['tar', '-cv%sf' % compression, outpath, '--']
            # entry_list = [ name.replace('\\', '\\\\') for name in entry_list]
        elif 'zip' == format:
            assert not header_encryption
            if solid:
                raise UnsupportedOption(format, 'solid')
            cmd = ['zip', '-r']
            if password is not None:
                cmd.extend(['-P', password])
            cmd.extend([outpath, '--'])
        else:
            raise UnsupportedFormat(format)
        cmd.extend(entry_list)
        cwd = os.getcwd()
        cleanup.append(lambda: os.chdir(cwd))
        os.chdir(tmp_dir)
        proc = process.popen(cmd, stderr=process.PIPE)
        cleanup.append(proc.stdout.close)
        cleanup.append(proc.stderr.close)
        cleanup.append(proc.wait)
        stdout, stderr = proc.communicate()
    finally:
        for fn in reversed(cleanup):
            fn()
    if not os.path.exists(outfile):
        raise Exception('archive creation failed: %s\nstdout:\n%s\nstderr:\n%s\n' % (
            ' '.join(cmd), stdout, stderr
        ))


def md5(path):
    hash = hashlib.md5()
    hash.update(open(path, 'rb').read())
    return hash.hexdigest()


class ArchiveFormatTest:

    skip = None
    handler = None
    format = ''
    solid = False
    password = None
    header_encryption = False
    contents = ()
    archive = None

    @classmethod
    def _ask_password(cls, archive, on_password):
        # Stands in for the dialog, which hands the password to a callback
        # rather than returning it; the extracting thread waits either way.
        if not cls.password:
            raise Exception('asked for password on unprotected archive!')
        on_password(cls.password)

    @classmethod
    def tearDownClass(cls):
        archive_password.ask_for_password = _REAL_ASK_FOR_PASSWORD

    @classmethod
    def setUpClass(cls):
        if cls.skip is not None:
            raise unittest.SkipTest(cls.skip)
        cls.archive_path = '%s.%s' % (get_testfile_path('archives', cls.archive), cls.format)
        cls.archive_contents = {
            archive_name: filename
            for name, archive_name, filename in cls.contents
        }
        # Put back by tearDownClass: this is a module level function, so
        # leaving it replaced would follow every later test.
        archive_password.ask_for_password = cls._ask_password
        if os.path.exists(cls.archive_path):
            return
        if 'win32' == sys.platform:
            raise Exception('archive creation unsupported on Windows!')
        make_archive(cls.archive_path,
                     [(name, get_testfile_path(filename))
                      for name, archive_name, filename
                      in cls.contents],
                     format=cls.format,
                     solid=cls.solid,
                     password=cls.password,
                     header_encryption=cls.header_encryption)

    def setUp(self):
        super().setUp()
        self.dest_dir = tempfile.mkdtemp(prefix='extract.')
        self.archive = None

    def tearDown(self):
        if self.archive is not None:
            self.archive.close()
        super().tearDown()

    def test_init_not_unicode(self):
        self.assertRaises(AssertionError, self.handler, b'test')

    def test_archive(self):
        self.archive = self.handler(self.archive_path)
        self.assertEqual(self.archive.archive, self.archive_path)

    def test_list_contents(self):
        self.archive = self.handler(self.archive_path)
        contents = self.archive.list_contents()
        self.assertCountEqual(contents, list(self.archive_contents.keys()))

    def test_iter_contents(self):
        self.archive = self.handler(self.archive_path)
        contents = []
        for name in self.archive.iter_contents():
            contents.append(name)
        self.assertCountEqual(contents, list(self.archive_contents.keys()))

    def test_is_solid(self):
        self.archive = self.handler(self.archive_path)
        self.archive.list_contents()
        self.assertEqual(self.solid, self.archive.is_solid())

    def test_iter_is_solid(self):
        self.archive = self.handler(self.archive_path)
        list(self.archive.iter_contents())
        self.assertEqual(self.solid, self.archive.is_solid())

    def test_extract(self):
        self.archive = self.handler(self.archive_path)
        contents = self.archive.list_contents()
        self.assertCountEqual(contents, list(self.archive_contents.keys()))
        # Use out-of-order extraction to try to trip implementation.
        for name in reversed(contents):
            self.archive.extract(name, self.dest_dir)
            path = os.path.join(self.dest_dir, name)
            self.assertTrue(os.path.isfile(path))
            extracted_md5 = md5(path)
            original_md5 = md5(get_testfile_path(self.archive_contents[name]))
            self.assertEqual((name, extracted_md5), (name, original_md5))

    def test_iter_extract(self):
        self.archive = self.handler(self.archive_path)
        contents = self.archive.list_contents()
        self.assertCountEqual(contents, list(self.archive_contents.keys()))
        extracted = []
        for name in self.archive.iter_extract(reversed(contents), self.dest_dir):
            extracted.append(name)
            path = os.path.join(self.dest_dir, name)
            self.assertTrue(os.path.isfile(path))
            extracted_md5 = md5(path)
            original_md5 = md5(get_testfile_path(self.archive_contents[name]))
            self.assertEqual((name, extracted_md5), (name, original_md5))
        # Entries must have been extracted in the order they are listed in the archive.
        # (necessary to prevent bad performances on solid archives)
        self.assertEqual(extracted, contents)


class RecursiveArchiveCloseTest(MComixTest):

    def test_closes_an_archive_that_was_never_listed(self) -> None:
        # RecursiveArchive only learns about the main archive once listing
        # starts, so closing before that used to leave its handle open.
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        recursive = archive_recursive.RecursiveArchive(
            zip.ZipArchive(path), tempfile.mkdtemp())
        main_archive = recursive._main_archive
        recursive.close()
        self.assertIsNone(main_archive.zip.fp)

    def test_closes_every_archive_after_listing(self) -> None:
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        recursive = archive_recursive.RecursiveArchive(
            zip.ZipArchive(path), tempfile.mkdtemp())
        recursive.list_contents()
        recursive.close()
        self.assertIsNone(recursive._main_archive.zip.fp)


class TarCompressionTest(MComixTest):

    #: What every SolidFlat archive holds, whatever it is compressed with.
    CONTENTS = ['arg.jpeg', 'bar.jpg', 'foo.JPG', 'meh.png']

    def test_lists_a_tarball_of_each_compression(self):

        # The handler names the decompressor the magic asks for rather than
        # letting tarfile try each in turn, so each of these is read by a
        # different branch of that choice.
        for extension in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
            path = get_testfile_path('archives', 'SolidFlat.%s' % extension)
            archive = tar.TarArchive(path)
            try:
                self.assertEqual(sorted(archive.list_contents()),
                                 self.CONTENTS, extension)
            finally:
                archive.close()

    def test_a_listing_begun_again_lets_go_of_the_first_tarball(self):
        """A listing left partway, then another begun on the same
        handler, opened the tarball a second time and left the first
        open for good: close() only knows the latest.  The extractor
        closes a handler whose listing it stopped, so nothing does this
        today; the handler no longer depends on that."""
        path = get_testfile_path('archives', 'SolidFlat.tar')
        archive = tar.TarArchive(path)
        try:
            first = archive.iter_contents()
            next(first)
            abandoned = archive.tar
            self.assertEqual(sorted(archive.list_contents()), self.CONTENTS)
            self.assertIsNot(abandoned, archive.tar)
            self.assertTrue(abandoned.closed, 'the first tarball stayed open')
        finally:
            archive.close()


class ZipLegacyNameTest(MComixTest):

    """Names a zip stores without its UTF-8 flag.

    zipfile reads those as code page 437, which is what the format
    once said, so a zip made by an older Linux or Mac tool - UTF-8
    names, no flag - or by Windows in another language listed its pages
    under names like "\u2229\u00ba\u00ba".
    """

    def _legacy_zip(self, names, encoding):
        """A zip holding one tiny file per name in <names>, the names
        written in <encoding> with the UTF-8 flag left off."""
        path = os.path.join(self.tmp_dir, 'legacy.zip')
        placeholders = []
        with zipfile.ZipFile(path, 'w') as archive:
            for number, name in enumerate(names):
                length = len(name.encode(encoding))
                # One letter repeated, so that no placeholder is found
                # inside another.
                placeholder = chr(ord('A') + number) * length
                placeholders.append(placeholder)
                archive.writestr(placeholder, b'x')
        with open(path, 'rb') as fp:
            data = fp.read()
        # Not zip(): the handler module has that name here.
        for number, name in enumerate(names):
            data = data.replace(placeholders[number].encode('ascii'),
                                name.encode(encoding))
        with open(path, 'wb') as fp:
            fp.write(data)
        return path

    def _listed(self, path):
        archive = zip.ZipArchive(path)
        try:
            return archive.list_contents()
        finally:
            archive.close()

    def test_utf_8_names_without_the_flag_are_read_as_utf_8(self):
        names = ['Übersicht.jpg', 'Café/01.jpg']
        self.assertEqual(names, self._listed(self._legacy_zip(names, 'utf-8')))

    @unittest.skipUnless(chardet, 'chardet is optional')
    def test_names_in_a_windows_code_page_are_read_in_it(self):
        names = ['表紙.jpg', '第01話/001.jpg', '第01話/002.jpg', 'あとがき.png']
        self.assertEqual(names,
                         self._listed(self._legacy_zip(names, 'shift_jis')))

    def test_a_page_listed_under_its_decoded_name_is_extracted(self):
        names = ['Übersicht.jpg']
        archive = zip.ZipArchive(self._legacy_zip(names, 'utf-8'))
        try:
            archive.list_contents()
            archive.extract('Übersicht.jpg', self.tmp_dir)
        finally:
            archive.close()
        with open(os.path.join(self.tmp_dir, 'Übersicht.jpg'), 'rb') as fp:
            self.assertEqual(b'x', fp.read())


@unittest.skipUnless(sevenzip_external.SevenZipArchive._find_7z_executable(),
                     '7z is not installed')
class SevenZipLegacyNameTest(ZipLegacyNameTest):

    """The same zips, compressed in a way zipfile does not read, which
    sends them to 7z.

    7z was asked for UTF-8 but passes such a name through as the bytes
    it was stored as, and the listing, decoded strictly, raised
    UnicodeDecodeError: a zip of Shift-JIS or Windows-1252 names could
    not be opened at all.
    """

    def _legacy_zip(self, names, encoding):
        path = os.path.join(self.tmp_dir, 'legacy.zip')
        placeholders = []
        with zipfile.ZipFile(path, 'w',
                             compression=zipfile.ZIP_BZIP2) as archive:
            for number, name in enumerate(names):
                placeholder = chr(ord('A') + number) * len(
                    name.encode(encoding))
                placeholders.append(placeholder)
                archive.writestr(placeholder, b'x')
        with open(path, 'rb') as fp:
            data = fp.read()
        for number, name in enumerate(names):
            data = data.replace(placeholders[number].encode('ascii'),
                                name.encode(encoding))
        with open(path, 'wb') as fp:
            fp.write(data)
        return path

    def _handler(self, path):
        return sevenzip_external.SevenZipArchive(path)

    def _listed(self, path):
        archive = self._handler(path)
        try:
            return archive.list_contents()
        finally:
            archive.close()

    def test_names_in_a_western_code_page_are_listed(self):
        names = ['Übersicht.jpg', 'Café.jpg']
        listed = self._listed(self._legacy_zip(names, 'cp1252'))
        self.assertEqual(2, len(listed))
        for name in listed:
            name.encode('utf-8')

    def test_a_page_listed_under_its_decoded_name_is_extracted(self):
        archive = self._handler(self._legacy_zip(['Übersicht.jpg'], 'utf-8'))
        try:
            archive.list_contents()
            archive.extract('Übersicht.jpg', self.tmp_dir)
        finally:
            archive.close()
        with open(os.path.join(self.tmp_dir, 'Übersicht.jpg'), 'rb') as fp:
            self.assertEqual(b'x', fp.read())

    def test_every_page_comes_out_of_the_stream(self):
        names = ['表紙.jpg', '第01話.jpg', 'あとがき.png', '第02話.jpg']
        archive = self._handler(self._legacy_zip(names, 'shift_jis'))
        try:
            listed = archive.list_contents()
            extracted = list(archive.iter_extract(listed, self.tmp_dir))
        finally:
            archive.close()
        self.assertEqual(sorted(listed), sorted(extracted))
        for name in listed:
            with open(os.path.join(self.tmp_dir, name), 'rb') as fp:
                self.assertEqual(b'x', fp.read())


class TarLegacyNameTest(MComixTest):

    """Names a tarball stores in something other than UTF-8.

    tarfile reads them as UTF-8 with the undecodable bytes kept as lone
    surrogates, which GTK refuses outright: a label or a title given
    one raised UnicodeEncodeError, and so did every log line naming the
    page.
    """

    def _tar(self, names, encoding):
        path = os.path.join(self.tmp_dir, 'legacy.tar')
        with tarfile.open(path, 'w', format=tarfile.GNU_FORMAT,
                          encoding=encoding) as archive:
            for name in names:
                info = tarfile.TarInfo(name)
                info.size = 1
                archive.addfile(info, io.BytesIO(b'x'))
        return path

    def _listed(self, path):
        archive = tar.TarArchive(path)
        try:
            return archive.list_contents()
        finally:
            archive.close()

    def test_latin_1_names_are_read_as_latin_1(self):
        names = ['Übersicht.png', 'Zwölf.png']
        self.assertEqual(names, self._listed(self._tar(names, 'latin-1')))

    @unittest.skipUnless(chardet, 'chardet is optional')
    def test_names_in_a_windows_code_page_are_read_in_it(self):
        names = ['表紙.jpg', '第01話/001.jpg', '第01話/002.jpg', 'あとがき.png']
        self.assertEqual(names, self._listed(self._tar(names, 'shift_jis')))

    def test_every_name_listed_can_be_shown(self):
        """Whatever the names were written in, what is listed is text
        GTK takes: UTF-8 without lone surrogates."""
        for encoding, names in (
                ('latin-1', ['Übersicht.png', 'Zwölf.png']),
                ('shift_jis', ['表紙.jpg', 'あとがき.png']),
                ('cp1251', ['Обзор.png', 'Страница.png'])):
            with self.subTest(encoding):
                for name in self._listed(self._tar(names, encoding)):
                    name.encode('utf-8')

    def test_a_page_listed_under_its_decoded_name_is_extracted(self):
        archive = tar.TarArchive(self._tar(['Übersicht.png'], 'latin-1'))
        try:
            archive.list_contents()
            archive.extract('Übersicht.png', self.tmp_dir)
        finally:
            archive.close()
        with open(os.path.join(self.tmp_dir, 'Übersicht.png'), 'rb') as fp:
            self.assertEqual(b'x', fp.read())


class RecursiveArchiveNestingTest(MComixTest):

    def _nested_zip(self, depth):
        """Return a zip holding one image, wrapped in <depth> more zips."""

        path = os.path.join(self.tmp_dir, 'nested-000.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.write(get_testfile_path('images', 'blue.png'), 'blue.png')
        for level in range(1, depth + 1):
            outer = os.path.join(self.tmp_dir, 'nested-%03u.zip' % level)
            with zipfile.ZipFile(outer, 'w') as archive:
                archive.write(path, 'inner.zip')
            path = outer
        return path

    def _list_nested(self, depth):
        destination_dir = os.path.join(self.tmp_dir, 'dest')
        os.mkdir(destination_dir)
        recursive = archive_recursive.RecursiveArchive(
            zip.ZipArchive(self._nested_zip(depth)), destination_dir)
        try:
            return recursive.list_contents(), len(recursive._archive_list)
        finally:
            recursive.close()

    def test_follows_an_archive_within_an_archive(self):

        contents, opened = self._list_nested(1)
        self.assertEqual(contents, [os.path.join('inner.zip', 'blue.png')])
        self.assertEqual(opened, 2)

    def test_stops_following_at_the_nesting_limit(self):

        # An archive that holds a copy of itself would be followed for as
        # long as there is disk to extract it to.
        depth = archive_recursive.MAX_NESTING_DEPTH + 2
        contents, opened = self._list_nested(depth)
        self.assertEqual(opened, archive_recursive.MAX_NESTING_DEPTH + 1)
        # The archive the listing stopped at is named like any other entry
        # that holds no image, and nothing below it was extracted.
        self.assertEqual(len(contents), 1)
        self.assertTrue(contents[0].endswith('inner.zip'), contents)


class RecursiveArchiveFormatTest(ArchiveFormatTest):

    base_handler = None

    def handler(self, archive):
        main_archive = self.base_handler(archive)
        return archive_recursive.RecursiveArchive(main_archive, self.dest_dir)


for name, handler, is_available, format, not_solid, solid, password, header_encryption in (
    ('7z (external)', sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), '7z', True, True, True, True),
    ('7z (external) lha', sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), 'lha', True, False, False, False),
    ('7z (external) rar', sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), 'rar', True, True, True, True),
    ('7z (external) zip', sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), 'zip', True, False, True, False),
    ('tar', tar.TarArchive, True, 'tar', False, True, False, False),
    ('tar (gzip)', tar.TarArchive, True, 'tar.gz', False, True, False, False),
    ('tar (bzip2)', tar.TarArchive, True, 'tar.bz2', False, True, False, False),
    ('rar (external)', rar_external.RarArchive, rar_external.RarArchive.is_available(), 'rar', True, True, True, True),
    ('rar (dll)', rar.RarArchive, rar.RarArchive.is_available(), 'rar', True, True, True, True),
    ('zip', zip.ZipArchive, True, 'zip', True, False, True, False),
    ('zip (external)', zip_external.ZipArchive, zip_external.ZipArchive.is_available(), 'zip', True, False, True, False),
    ('lha (external)', lha_external.LhaArchive, lha_external.LhaArchive.is_available(), 'lha', True, False, False, False),
):
    base_class_name = 'ArchiveFormat'
    base_class_name += ''.join([part.capitalize() for part in re.sub(r'[^\w]+', ' ', name).split()])
    base_class_name += '%sTest'
    base_class_dict = {
        'name': name,
        'handler': handler,
        'format': format,
    }

    skip = None
    if not is_available:
        skip = 'support for %s format with %s not available' % (format, name)
    base_class_dict['skip'] = skip

    base_class_list = []
    if not_solid:
        base_class_list.append(('', {}))
    if solid:
        base_class_list.append(('Solid', {'solid': True}))

    class_list = []

    if password:
        for variant, params in base_class_list:
            variant = variant + 'Encrypted'
            params = dict(params)
            params['password'] = 'password'
            params['contents'] = (
                ('arg.jpeg', 'arg.jpeg', 'images/01-JPG-Indexed.jpg'),
                ('foo.JPG', 'foo.JPG', 'images/04-PNG-Indexed.png'),
                ('bar.jpg', 'bar.jpg', 'images/02-JPG-RGB.jpg'),
                ('meh.png', 'meh.png', 'images/03-PNG-RGB.png'),
            )
            class_list.append((variant, params))
            if header_encryption:
                variant = variant + 'Header'
                params = dict(params)
                params['header_encryption'] = True
                class_list.append((variant, params))
    else:
        assert not header_encryption

    for sub_variant, is_supported, contents in (
        ('Flat', True, (
            ('arg.jpeg', 'arg.jpeg', 'images/01-JPG-Indexed.jpg'),
            ('foo.JPG', 'foo.JPG', 'images/04-PNG-Indexed.png'),
            ('bar.jpg', 'bar.jpg', 'images/02-JPG-RGB.jpg'),
            ('meh.png', 'meh.png', 'images/03-PNG-RGB.png'),
        )),
        ('Tree', True, (
            ('dir1/arg.jpeg', 'dir1/arg.jpeg', 'images/01-JPG-Indexed.jpg'),
            ('dir1/subdir1/foo.JPG', 'dir1/subdir1/foo.JPG', 'images/04-PNG-Indexed.png'),
            ('dir2/subdir1/bar.jpg', 'dir2/subdir1/bar.jpg', 'images/02-JPG-RGB.jpg'),
            ('meh.png', 'meh.png', 'images/03-PNG-RGB.png'),
        )),
        ('Unicode', True, (
            ('1-قفهسا.jpg', '1-قفهسا.jpg', 'images/01-JPG-Indexed.jpg'),
            ('2-רדןקמא.png', '2-רדןקמא.png', 'images/04-PNG-Indexed.png'),
            ('3-りえsち.jpg', '3-りえsち.jpg', 'images/02-JPG-RGB.jpg'),
            ('4-щжвщджл.png', '4-щжвщджл.png', 'images/03-PNG-RGB.png'),
        )),
        # Check we don't treat an entry name as an option or command line switch.
        ('OptEntry', True, (
            ('-rg.jpeg', '-rg.jpeg', 'images/01-JPG-Indexed.jpg'),
            ('--o.JPG', '--o.JPG', 'images/04-PNG-Indexed.png'),
            ('+ar.jpg', '+ar.jpg', 'images/02-JPG-RGB.jpg'),
            ('@eh.png', '@eh.png', 'images/03-PNG-RGB.png'),
        )),
        # Check an entry name is not used as glob pattern.
        ('GlobEntries', 'win32' != sys.platform, (
            ('[rg.jpeg', '[rg.jpeg', 'images/01-JPG-Indexed.jpg'),
            ('[]rg.jpeg', '[]rg.jpeg', 'images/02-JPG-RGB.jpg'),
            ('*oo.JPG', '*oo.JPG', 'images/04-PNG-Indexed.png'),
            ('?eh.png', '?eh.png', 'images/03-PNG-RGB.png'),
            # ('\\r.jpg'             , '\\r.jpg'             , 'images/blue.png'          ),
            # ('ba\\.jpg'            , 'ba\\.jpg'            , 'images/red.png'           ),
        )),
        # Same, Windows version.
        ('GlobEntries', 'win32' == sys.platform, (
            ('[rg.jpeg', '[rg.jpeg', 'images/01-JPG-Indexed.jpg'),
            ('[]rg.jpeg', '[]rg.jpeg', 'images/02-JPG-RGB.jpg'),
            ('*oo.JPG', '_oo.JPG', 'images/04-PNG-Indexed.png'),
            ('?eh.png', '_eh.png', 'images/03-PNG-RGB.png'),
            # ('\\r.jpg'             , '\\r.jpg'             , 'images/blue.png'          ),
            # ('ba\\.jpg'            , 'ba\\.jpg'            , 'images/red.png'           ),
        )),
        # Check how invalid filesystem characters are handled.
        # ('InvalidFileSystemChars', 'win32' == sys.platform, (
        #     ('a<g.jpeg'            , 'a_g.jpeg'            ,'images/01-JPG-Indexed.jpg'),
        #     ('f*o.JPG'             , 'f_o.JPG'             ,'images/04-PNG-Indexed.png'),
        #     ('b:r.jpg'             , 'b_r.jpg'             ,'images/02-JPG-RGB.jpg'    ),
        #     ('m?h.png'             , 'm_h.png'             ,'images/03-PNG-RGB.png'    ),
        # )),
    ):
        if not is_supported:
            continue
        contents = [
            [s.replace('/', os.sep) for s in names]
            for names in contents
        ]
        for variant, params in base_class_list:
            variant = variant + sub_variant
            params = dict(params)
            params['contents'] = contents
            class_list.append((variant, params))

    for variant, params in class_list:
        class_name = base_class_name % variant
        class_dict = dict(base_class_dict)
        class_dict.update(params)
        class_dict['archive'] = variant
        globals()[class_name] = type(class_name, (ArchiveFormatTest, MComixTest), class_dict)
        class_name = 'Recursive' + class_name
        class_dict = dict(class_dict)
        class_dict['base_handler'] = class_dict['handler']
        del class_dict['handler']
        globals()[class_name] = type(class_name, (RecursiveArchiveFormatTest, MComixTest), class_dict)


# Custom tests for recursive archives support.

class RecursiveArchiveFormatRedAndBluesTest(RecursiveArchiveFormatTest):

    @classmethod
    def setUpClass(cls):
        skip = None
        if not cls.is_available:
            raise unittest.SkipTest('support for archive format not available')
        if not os.path.exists(cls.archive_path):
            skip = 'archive is missing: %s' % cls.archive_path
        if skip is not None:
            raise unittest.SkipTest(skip)
        cls.archive_contents = {
            archive_name.replace('/', os.sep): get_testfile_path(filename)
            for archive_name, filename in cls.contents}


class RecursiveArchiveFormatTarRedAndBluesTest(RecursiveArchiveFormatRedAndBluesTest, MComixTest):

    base_handler = tar.TarArchive
    is_available = True
    archive_path = get_testfile_path('archives', 'red_and_blues.tar')
    contents = (
        ('red_and_blues.7z/blues.rar/blue0.png', 'images/blue.png'),
        ('red_and_blues.7z/blues.rar/blue1.png', 'images/blue.png'),
        ('red_and_blues.7z/blues.rar/blue2.png', 'images/blue.png'),
        ('red_and_blues.7z/red.png', 'images/red.png'),
        ('red_and_blues.rar/blues.7z/blue0.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue1.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue2.png', 'images/blue.png'),
        ('red_and_blues.rar/red.png', 'images/red.png'),
    )
    solid = True


class RecursiveArchiveFormat7zRedAndBluesTest(RecursiveArchiveFormatRedAndBluesTest, MComixTest):

    base_handler = sevenzip_external.SevenZipArchive
    is_available = rar.RarArchive.is_available()
    archive_path = get_testfile_path('archives', 'red_and_blues.7z')
    contents = (
        ('blues.rar/blue0.png', 'images/blue.png'),
        ('blues.rar/blue1.png', 'images/blue.png'),
        ('blues.rar/blue2.png', 'images/blue.png'),
        ('red.png', 'images/red.png'),
    )
    solid = True


class RecursiveArchiveFormatExternalRarRedAndBluesTest(RecursiveArchiveFormatRedAndBluesTest, MComixTest):

    base_handler = rar_external.RarArchive
    is_available = rar_external.RarArchive.is_available()
    archive_path = get_testfile_path('archives', 'red_and_blues.rar')
    contents = (
        ('blues.7z/blue0.png', 'images/blue.png'),
        ('blues.7z/blue1.png', 'images/blue.png'),
        ('blues.7z/blue2.png', 'images/blue.png'),
        ('red.png', 'images/red.png'),
    )
    solid = True


class RecursiveArchiveFormatExternalRarEmbeddedRedAndBluesRarTest(RecursiveArchiveFormatExternalRarRedAndBluesTest):

    archive_path = get_testfile_path('archives', 'embedded_red_and_blues_rar.rar')
    contents = (
        ('red_and_blues.rar/blues.7z/blue0.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue1.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue2.png', 'images/blue.png'),
        ('red_and_blues.rar/red.png', 'images/red.png'),
    )


class RecursiveArchiveFormatRarRedAndBluesTest(RecursiveArchiveFormatExternalRarRedAndBluesTest):

    base_handler = rar.RarArchive
    is_available = rar.RarArchive.is_available()


class RecursiveArchiveFormatRarEmbeddedRedAndBluesRarTest(RecursiveArchiveFormatExternalRarEmbeddedRedAndBluesRarTest):

    base_handler = rar.RarArchive
    is_available = rar.RarArchive.is_available()


class RecursiveArchiveFormat7zExternalTarXzTest(RecursiveArchiveFormatTest, MComixTest):

    base_handler = sevenzip_external.TarArchive
    is_available = sevenzip_external.TarArchive.is_available()
    solid = True
    format = 'tar.xz'
    archive = 'SolidFlat'
    contents = (
        ('arg.jpeg', os.path.join('archive.tar', 'arg.jpeg'), 'images/01-JPG-Indexed.jpg'),
        ('foo.JPG', os.path.join('archive.tar', 'foo.JPG'), 'images/04-PNG-Indexed.png'),
        ('bar.jpg', os.path.join('archive.tar', 'bar.jpg'), 'images/02-JPG-RGB.jpg'),
        ('meh.png', os.path.join('archive.tar', 'meh.png'), 'images/03-PNG-RGB.png'),
    )


xfail_list = [
    # No password support when using some external tools.
    ('ZipExternalEncrypted', 'test_extract'),
    ('ZipExternalEncrypted', 'test_iter_extract'),
    # Lhasa, which is what 'lha' is on current distributions, prints a
    # question mark for every byte of a member name it cannot represent,
    # so non-ASCII names cannot be listed, let alone extracted.
    ('LhaExternalUnicode', 'test_extract'),
    ('LhaExternalUnicode', 'test_iter_extract'),
    ('LhaExternalUnicode', 'test_iter_contents'),
    ('LhaExternalUnicode', 'test_list_contents'),
]

if 'win32' == sys.platform:
    xfail_list.extend([
        # Bug...
        ('RarDllGlobEntries', 'test_iter_contents'),
        ('RarDllGlobEntries', 'test_list_contents'),
        ('RarDllGlobEntries', 'test_iter_extract'),
        ('RarDllGlobEntries', 'test_extract'),
        ('RarDllSolidGlobEntries', 'test_iter_contents'),
        ('RarDllSolidGlobEntries', 'test_list_contents'),
        ('RarDllSolidGlobEntries', 'test_iter_extract'),
        ('RarDllSolidGlobEntries', 'test_extract'),
        # Not supported by 7z executable...
        ('7zExternalLhaUnicode', 'test_iter_contents'),
        ('7zExternalLhaUnicode', 'test_list_contents'),
        ('7zExternalLhaUnicode', 'test_iter_extract'),
        ('7zExternalLhaUnicode', 'test_extract'),
        # Unicode not supported by the tar executable we used.
        ('TarBzip2SolidUnicode', 'test_iter_contents'),
        ('TarBzip2SolidUnicode', 'test_list_contents'),
        ('TarBzip2SolidUnicode', 'test_iter_extract'),
        ('TarBzip2SolidUnicode', 'test_extract'),
        ('TarGzipSolidUnicode', 'test_iter_contents'),
        ('TarGzipSolidUnicode', 'test_list_contents'),
        ('TarGzipSolidUnicode', 'test_iter_extract'),
        ('TarGzipSolidUnicode', 'test_extract'),
        ('TarSolidUnicode', 'test_iter_contents'),
        ('TarSolidUnicode', 'test_list_contents'),
        ('TarSolidUnicode', 'test_iter_extract'),
        ('TarSolidUnicode', 'test_extract'),
        # Idem with unzip...
        ('ZipExternalUnicode', 'test_iter_contents'),
        ('ZipExternalUnicode', 'test_list_contents'),
        ('ZipExternalUnicode', 'test_iter_extract'),
        ('ZipExternalUnicode', 'test_extract'),
        # ...and unrar!
        ('RarExternalUnicode', 'test_iter_contents'),
        ('RarExternalUnicode', 'test_list_contents'),
        ('RarExternalUnicode', 'test_iter_extract'),
        ('RarExternalUnicode', 'test_extract'),
        ('RarExternalSolidUnicode', 'test_iter_contents'),
        ('RarExternalSolidUnicode', 'test_list_contents'),
        ('RarExternalSolidUnicode', 'test_iter_extract'),
        ('RarExternalSolidUnicode', 'test_extract'),
    ])


class ExternalExecutableContractTest(MComixTest):

    """The base class builds a command line out of what these return.

    iter_contents() and extract() spell it as
    [executable] + arguments + [archive], so the arguments have to
    arrive as a list: a bare string would be concatenated character by
    character, and anything else raises TypeError. The base class
    declared all three of the methods that produce them as returning
    None, which said neither.
    """

    HANDLERS = (lha_external.LhaArchive, rar_external.RarArchive,
                sevenzip_external.SevenZipArchive, zip_external.ZipArchive)

    def _handler(self, klass):
        # Nothing here reads the archive; it only has to be a path.
        return klass(get_testfile_path('archives', '01-ZIP-Normal.zip'))

    def test_an_executable_is_named_or_reported_missing(self):
        for klass in self.HANDLERS:
            executable = self._handler(klass)._get_executable()
            self.assertTrue(executable is None or isinstance(executable, str),
                            '%s named %r as its executable'
                            % (klass.__name__, executable))

    def test_the_arguments_are_lists_a_command_can_be_built_from(self):
        for klass in self.HANDLERS:
            handler = self._handler(klass)
            for name in ('_get_list_arguments', '_get_extract_arguments'):
                arguments = getattr(handler, name)()
                self.assertIsInstance(
                    arguments, list,
                    '%s.%s() returned %r' % (klass.__name__, name, arguments))


def _expect_failure(klass, attr):
    """Mark the <attr> test of <klass> as an expected failure.

    unittest.expectedFailure() flags the function object handed to it and
    returns it unchanged, so marking a method inherited from
    ArchiveFormatTest would mark it for every other archive format class
    as well. Wrap it in a fresh function first. """

    method = getattr(klass, attr)

    def expected_to_fail(self, *args, **kwargs):
        return method(self, *args, **kwargs)

    expected_to_fail.__name__ = attr
    expected_to_fail.__doc__ = method.__doc__
    setattr(klass, attr, unittest.expectedFailure(expected_to_fail))


# Expected failures.
for test, attr in xfail_list:
    for name in (
        'ArchiveFormat%sTest' % test,
        'RecursiveArchiveFormat%sTest' % test,
    ):
        if name in globals():
            _expect_failure(globals()[name], attr)


class DirectoryEntryTest(MComixTest):

    """A directory an archive records is not a member anything extracts.

    Every archive format keeps an entry for each directory its files are
    in, and the four fixtures below were packed from a folder, so each
    holds one for "images" beside the five files under it.  Offering
    that entry in the listing had the extractor try to write it: opening
    a directory for writing raises IsADirectoryError, which was caught
    and logged with a traceback on every archive packed that way, which
    is most of them.  The generated fixtures the tests above build are
    all flat, which is why none of them saw it.
    """

    #: The five members each fixture really holds.
    MEMBERS = ['images/01-JPG-Indexed.jpg', 'images/02-JPG-RGB.jpg',
               'images/03-PNG-RGB.png', 'images/04-PNG-Indexed.png',
               'images/Comment.txt']

    #: Which handler to read which fixture with.  The externally driven
    #: handlers read more than the format they are named after, and each
    #: works the listing out differently, so each pairing is its own case.
    CASES = (
        ('zip', zip.ZipArchive, '01-ZIP-Normal.zip'),
        ('tar', tar.TarArchive, '02-TAR-Normal.tar'),
        ('rar (dll)', rar.RarArchive, '03-RAR-Normal.rar'),
        ('rar (external)', rar_external.RarArchive, '03-RAR-Normal.rar'),
        ('7z (external)', sevenzip_external.SevenZipArchive, '04-7Z-Normal.7z'),
        ('7z (external) zip', sevenzip_external.SevenZipArchive,
         '01-ZIP-Normal.zip'),
        ('7z (external) rar', sevenzip_external.SevenZipArchive,
         '03-RAR-Normal.rar'),
    )

    def test_the_directory_the_pages_are_in_is_not_a_member(self):
        for name, handler, fixture in self.CASES:
            with self.subTest(handler=name, archive=fixture):
                if not handler.is_available():
                    self.skipTest('%s is not available' % name)
                archive = handler(get_testfile_path('archives', fixture))
                try:
                    self.assertCountEqual(archive.list_contents(),
                                          self.MEMBERS)
                finally:
                    archive.close()


class ListingParserTest(MComixTest):

    """The line parsers of the handlers that drive an outside program.

    Each of these listings names an entry on one line and says what it
    is on a later one, so the parser holds a name back until the next
    entry begins.  They are exercised here line by line rather than
    through an archive, because the one format with no fixture holding a
    directory - lha - cannot be packed on this machine: the lha in
    Debian and Arch is Lhasa, which only unpacks.
    """

    def _parse(self, archive, lines):
        """Every name <archive>'s parser returns for <lines>."""
        names = []
        for line in lines:
            name = archive._parse_list_output_line(line)
            if name is not None:
                names.append(name)
        pending = archive._flush_pending_entry()
        if pending is not None:
            names.append(pending)
        return names

    def test_7z_keeps_the_directory_out_and_the_last_file_in(self):
        archive = sevenzip_external.SevenZipArchive('unused.7z')
        self.assertEqual(self._parse(archive, [
            'Listing archive: unused.7z',
            '----------',
            'Path = images',
            'Size = 0',
            'Attributes = D_ drwxr-xr-x',
            '',
            'Path = images/page.png',
            'Size = 140',
            'Attributes = A_ -rw-r--r--',
        ]), ['images/page.png'])

    def test_7z_takes_an_entry_with_no_attributes_for_a_file(self):
        """Not every format 7z reads records any."""
        archive = sevenzip_external.SevenZipArchive('unused.7z')
        self.assertEqual(self._parse(archive, [
            '----------',
            'Path = page.png',
            'Size = 140',
        ]), ['page.png'])

    def test_rar_keeps_the_directory_out_and_the_last_file_in(self):
        archive = rar_external.RarArchive('unused.rar')
        self.assertEqual(self._parse(archive, [
            'Details: RAR 5',
            '        Name: images',
            '        Type: Directory',
            '  Attributes: ...D...',
            '        Name: images/page.png',
            '        Type: File',
            '        Size: 140',
        ]), ['images/page.png'])

    def test_rar_keeps_a_file_of_no_size(self):
        """A comment file in the fixtures is empty, and is still a member."""
        archive = rar_external.RarArchive('unused.rar')
        self.assertEqual(self._parse(archive, [
            'Details: RAR 5',
            '        Name: images/Comment.txt',
            '        Type: File',
            '        Size: 0',
        ]), ['images/Comment.txt'])

    def test_lha_keeps_the_directory_out(self):
        archive = lha_external.LhaArchive('unused.lha')
        self.assertEqual(self._parse(archive, [
            'drwxr-xr-x  1000/1000       0 100.0% Apr 12  2015 images/',
            '-rw-------  1000/1000     332 100.0% Apr 12  2015 images/page.png',
        ]), ['images/page.png'])


class ExternalRarLocaleTest(MComixTest):

    """The names unrar lists, whatever locale MComix was started in.

    unrar writes names in the character set of the locale it runs in:
    under C every letter outside ASCII came out as '?', and under a
    Latin-1 locale the listing could not be read as UTF-8 at all."""

    @unittest.skipUnless(rar_external.RarArchive.is_available(),
                         'unrar is not installed')
    def test_names_are_listed_right_under_the_c_locale(self):
        with unittest.mock.patch.dict(os.environ,
                                      {'LANG': 'C', 'LC_ALL': 'C'}):
            archive = rar_external.RarArchive(
                get_testfile_path('archives', 'Unicode.rar'))
            names = list(archive.iter_contents())
        self.assertIn('1-قفهسا.jpg', names)
        self.assertFalse([name for name in names if '?' in name], names)

    @unittest.skipUnless(zip_external.ZipArchive.is_available(),
                         'unzip is not installed')
    def test_unzip_names_are_listed_and_extracted_under_the_c_locale(self):
        """unzip is locale-bound the same way: under C it wrote each
        letter outside ASCII as #U followed by its code."""
        with unittest.mock.patch.dict(os.environ,
                                      {'LANG': 'C', 'LC_ALL': 'C'}):
            archive = zip_external.ZipArchive(
                get_testfile_path('archives', 'Unicode.zip'))
            names = list(archive.iter_contents())
            archive.extract('1-قفهسا.jpg', self.tmp_dir)
        self.assertIn('1-قفهسا.jpg', names)
        self.assertTrue(os.path.getsize(
            os.path.join(self.tmp_dir, '1-قفهسا.jpg')) > 0)

    @unittest.skipUnless(rar_external.RarArchive.is_available(),
                         'unrar is not installed')
    def test_a_file_is_extracted_by_its_name_under_the_c_locale(self):
        with unittest.mock.patch.dict(os.environ,
                                      {'LANG': 'C', 'LC_ALL': 'C'}):
            archive = rar_external.RarArchive(
                get_testfile_path('archives', 'Unicode.rar'))
            archive.list_contents()
            archive.extract('1-قفهسا.jpg', self.tmp_dir)
        extracted = os.path.join(self.tmp_dir, '1-قفهسا.jpg')
        self.assertTrue(os.path.getsize(extracted) > 0)
