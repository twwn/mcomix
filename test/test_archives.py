import hashlib
import locale
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

from . import MComixTest, get_testfile_path

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
        cls.archive_contents = dict([
            (archive_name, filename)
            for name, archive_name, filename
            in cls.contents
        ])
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
    ('7z (external)'    , sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), '7z'     , True , True , True , True  ),
    ('7z (external) lha', sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), 'lha'    , True , False, False, False ),
    ('7z (external) rar', sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), 'rar'    , True , True , True , True  ),
    ('7z (external) zip', sevenzip_external.SevenZipArchive, sevenzip_external.SevenZipArchive.is_available(), 'zip'    , True , False, True , False ),
    ('tar'              , tar.TarArchive                   , True                                            , 'tar'    , False, True , False, False ),
    ('tar (gzip)'       , tar.TarArchive                   , True                                            , 'tar.gz' , False, True , False, False ),
    ('tar (bzip2)'      , tar.TarArchive                   , True                                            , 'tar.bz2', False, True , False, False ),
    ('rar (external)'   , rar_external.RarArchive          , rar_external.RarArchive.is_available()          , 'rar'    , True , True , True , True  ),
    ('rar (dll)'        , rar.RarArchive                   , rar.RarArchive.is_available()                   , 'rar'    , True , True , True , True  ),
    ('zip'              , zip.ZipArchive                   , True                                            , 'zip'    , True , False, True , False ),
    ('zip (external)'   , zip_external.ZipArchive          , zip_external.ZipArchive.is_available()          , 'zip'    , True , False, True , False ),
    ('lha (external)'   , lha_external.LhaArchive          , lha_external.LhaArchive.is_available()          , 'lha'    , True , False, False, False ),
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
                ('foo.JPG' , 'foo.JPG' , 'images/04-PNG-Indexed.png'),
                ('bar.jpg' , 'bar.jpg' , 'images/02-JPG-RGB.jpg'    ),
                ('meh.png' , 'meh.png' , 'images/03-PNG-RGB.png'    ),
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
            ('arg.jpeg'            , 'arg.jpeg'            , 'images/01-JPG-Indexed.jpg'),
            ('foo.JPG'             , 'foo.JPG'             , 'images/04-PNG-Indexed.png'),
            ('bar.jpg'             , 'bar.jpg'             , 'images/02-JPG-RGB.jpg'    ),
            ('meh.png'             , 'meh.png'             , 'images/03-PNG-RGB.png'    ),
        )),
        ('Tree', True, (
            ('dir1/arg.jpeg'       , 'dir1/arg.jpeg'       , 'images/01-JPG-Indexed.jpg'),
            ('dir1/subdir1/foo.JPG', 'dir1/subdir1/foo.JPG', 'images/04-PNG-Indexed.png'),
            ('dir2/subdir1/bar.jpg', 'dir2/subdir1/bar.jpg', 'images/02-JPG-RGB.jpg'    ),
            ('meh.png'             , 'meh.png'             , 'images/03-PNG-RGB.png'    ),
        )),
        ('Unicode', True, (
            ('1-قفهسا.jpg'        , '1-قفهسا.jpg'        , 'images/01-JPG-Indexed.jpg'),
            ('2-רדןקמא.png'       , '2-רדןקמא.png'       , 'images/04-PNG-Indexed.png'),
            ('3-りえsち.jpg'      , '3-りえsち.jpg'      , 'images/02-JPG-RGB.jpg'    ),
            ('4-щжвщджл.png'      , '4-щжвщджл.png'      , 'images/03-PNG-RGB.png'    ),
        )),
        # Check we don't treat an entry name as an option or command line switch.
        ('OptEntry', True, (
            ('-rg.jpeg'            , '-rg.jpeg'            , 'images/01-JPG-Indexed.jpg'),
            ('--o.JPG'             , '--o.JPG'             , 'images/04-PNG-Indexed.png'),
            ('+ar.jpg'             , '+ar.jpg'             , 'images/02-JPG-RGB.jpg'    ),
            ('@eh.png'             , '@eh.png'             , 'images/03-PNG-RGB.png'    ),
        )),
        # Check an entry name is not used as glob pattern.
        ('GlobEntries', 'win32' != sys.platform, (
            ('[rg.jpeg'            , '[rg.jpeg'            , 'images/01-JPG-Indexed.jpg'),
            ('[]rg.jpeg'           , '[]rg.jpeg'           , 'images/02-JPG-RGB.jpg'    ),
            ('*oo.JPG'             , '*oo.JPG'             , 'images/04-PNG-Indexed.png'),
            ('?eh.png'             , '?eh.png'             , 'images/03-PNG-RGB.png'    ),
            # ('\\r.jpg'             , '\\r.jpg'             , 'images/blue.png'          ),
            # ('ba\\.jpg'            , 'ba\\.jpg'            , 'images/red.png'           ),
        )),
        # Same, Windows version.
        ('GlobEntries', 'win32' == sys.platform, (
            ('[rg.jpeg'            , '[rg.jpeg'            , 'images/01-JPG-Indexed.jpg'),
            ('[]rg.jpeg'           , '[]rg.jpeg'           , 'images/02-JPG-RGB.jpg'    ),
            ('*oo.JPG'             , '_oo.JPG'             , 'images/04-PNG-Indexed.png'),
            ('?eh.png'             , '_eh.png'             , 'images/03-PNG-RGB.png'    ),
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
        cls.archive_contents = dict([
            (archive_name.replace('/', os.sep),
             get_testfile_path(filename))
            for archive_name, filename in
            cls.contents])

class RecursiveArchiveFormatTarRedAndBluesTest(RecursiveArchiveFormatRedAndBluesTest, MComixTest):

    base_handler = tar.TarArchive
    is_available = True
    archive_path = get_testfile_path('archives', 'red_and_blues.tar')
    contents = (
        ('red_and_blues.7z/blues.rar/blue0.png', 'images/blue.png'),
        ('red_and_blues.7z/blues.rar/blue1.png', 'images/blue.png'),
        ('red_and_blues.7z/blues.rar/blue2.png', 'images/blue.png'),
        ('red_and_blues.7z/red.png'            , 'images/red.png' ),
        ('red_and_blues.rar/blues.7z/blue0.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue1.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue2.png', 'images/blue.png'),
        ('red_and_blues.rar/red.png'           , 'images/red.png' ),
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
        ('red.png'            , 'images/red.png' ),
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
        ('red.png'           , 'images/red.png' ),
    )
    solid = True

class RecursiveArchiveFormatExternalRarEmbeddedRedAndBluesRarTest(RecursiveArchiveFormatExternalRarRedAndBluesTest):

    archive_path = get_testfile_path('archives', 'embedded_red_and_blues_rar.rar')
    contents = (
        ('red_and_blues.rar/blues.7z/blue0.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue1.png', 'images/blue.png'),
        ('red_and_blues.rar/blues.7z/blue2.png', 'images/blue.png'),
        ('red_and_blues.rar/red.png'           , 'images/red.png' ),
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
        ('foo.JPG' , os.path.join('archive.tar', 'foo.JPG' ), 'images/04-PNG-Indexed.png'),
        ('bar.jpg' , os.path.join('archive.tar', 'bar.jpg' ), 'images/02-JPG-RGB.jpg'    ),
        ('meh.png' , os.path.join('archive.tar', 'meh.png' ), 'images/03-PNG-RGB.png'    ),
    )

xfail_list = [
    # No password support when using some external tools.
    ('ZipExternalEncrypted'             , 'test_extract'      ),
    ('ZipExternalEncrypted'             , 'test_iter_extract' ),
    # Lhasa, which is what 'lha' is on current distributions, prints a
    # question mark for every byte of a member name it cannot represent,
    # so non-ASCII names cannot be listed, let alone extracted.
    ('LhaExternalUnicode'               , 'test_extract'      ),
    ('LhaExternalUnicode'               , 'test_iter_extract' ),
    ('LhaExternalUnicode'               , 'test_iter_contents'),
    ('LhaExternalUnicode'               , 'test_list_contents'),
]

if 'win32' == sys.platform:
    xfail_list.extend([
        # Bug...
        ('RarDllGlobEntries'      , 'test_iter_contents'),
        ('RarDllGlobEntries'      , 'test_list_contents'),
        ('RarDllGlobEntries'      , 'test_iter_extract' ),
        ('RarDllGlobEntries'      , 'test_extract'      ),
        ('RarDllSolidGlobEntries' , 'test_iter_contents'),
        ('RarDllSolidGlobEntries' , 'test_list_contents'),
        ('RarDllSolidGlobEntries' , 'test_iter_extract' ),
        ('RarDllSolidGlobEntries' , 'test_extract'      ),
        # Not supported by 7z executable...
        ('7zExternalLhaUnicode'   , 'test_iter_contents'),
        ('7zExternalLhaUnicode'   , 'test_list_contents'),
        ('7zExternalLhaUnicode'   , 'test_iter_extract' ),
        ('7zExternalLhaUnicode'   , 'test_extract'      ),
        # Unicode not supported by the tar executable we used.
        ('TarBzip2SolidUnicode'   , 'test_iter_contents'),
        ('TarBzip2SolidUnicode'   , 'test_list_contents'),
        ('TarBzip2SolidUnicode'   , 'test_iter_extract' ),
        ('TarBzip2SolidUnicode'   , 'test_extract'      ),
        ('TarGzipSolidUnicode'    , 'test_iter_contents'),
        ('TarGzipSolidUnicode'    , 'test_list_contents'),
        ('TarGzipSolidUnicode'    , 'test_iter_extract' ),
        ('TarGzipSolidUnicode'    , 'test_extract'      ),
        ('TarSolidUnicode'        , 'test_iter_contents'),
        ('TarSolidUnicode'        , 'test_list_contents'),
        ('TarSolidUnicode'        , 'test_iter_extract' ),
        ('TarSolidUnicode'        , 'test_extract'      ),
        # Idem with unzip...
        ('ZipExternalUnicode'     , 'test_iter_contents'),
        ('ZipExternalUnicode'     , 'test_list_contents'),
        ('ZipExternalUnicode'     , 'test_iter_extract' ),
        ('ZipExternalUnicode'     , 'test_extract'      ),
        # ...and unrar!
        ('RarExternalUnicode'     , 'test_iter_contents'),
        ('RarExternalUnicode'     , 'test_list_contents'),
        ('RarExternalUnicode'     , 'test_iter_extract' ),
        ('RarExternalUnicode'     , 'test_extract'      ),
        ('RarExternalSolidUnicode', 'test_iter_contents'),
        ('RarExternalSolidUnicode', 'test_list_contents'),
        ('RarExternalSolidUnicode', 'test_iter_extract' ),
        ('RarExternalSolidUnicode', 'test_extract'      ),
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
    """ Mark the C{attr} test of C{klass} as an expected failure.

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

