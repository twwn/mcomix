""" Tests for the native (PyMuPDF) PDF handler. """

import builtins
import io
import os
import re
import sys
import tempfile
import tomllib
import types
import unittest
from importlib import metadata
from unittest import mock

import mcomix
from PIL import features

from mcomix.archive import pdf_multi
from mcomix.preferences import prefs

from . import MComixTest, posix_byte_names


PYPROJECT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(mcomix.__file__))),
                         'pyproject.toml')


class RequiredVersionTest(unittest.TestCase):

    """The minimum PyMuPDF version is written down in two places that have
    to agree, and used to be compared against the wrong version number."""

    def _declared_requirement(self):
        with open(PYPROJECT, 'rb') as pyproject:
            extras = tomllib.load(pyproject)['project']['optional-dependencies']
        for requirement in extras['fileformats']:
            match = re.fullmatch(r'PyMuPDF\s*>=\s*(\S+)', requirement)
            if match is not None:
                return match.group(1)
        self.fail('pyproject.toml declares no minimum PyMuPDF version')

    @unittest.skipUnless(os.path.isfile(PYPROJECT), 'not running from a source tree')
    def test_pyproject_declares_the_same_minimum(self):
        self.assertEqual(self._declared_requirement(),
                         pdf_multi.PYMUPDF_VERSION_REQUIRED)

    def test_the_declared_minimum_is_accepted(self):
        # It was not: the check compared the required PyMuPDF version
        # against the version of the MuPDF library PyMuPDF is built on,
        # which is numbered separately and is regularly lower.
        self.assertTrue(pdf_multi.is_supported_version(
            pdf_multi.PYMUPDF_VERSION_REQUIRED))

    def test_newer_versions_are_accepted(self):
        self.assertTrue(pdf_multi.is_supported_version('1.99.0'))

    def test_older_versions_are_rejected(self):
        self.assertFalse(pdf_multi.is_supported_version('1.19.2'))
        self.assertFalse(pdf_multi.is_supported_version('0.9'))

    def test_the_releases_that_crash_after_gtk_are_rejected(self):
        # PyMuPDF 1.23.5, 1.24.0 and 1.24.5 took the process down when
        # their extension was loaded after GTK 4; 1.24.7 was the first
        # that did not.
        self.assertFalse(pdf_multi.is_supported_version('1.23.5'))
        self.assertFalse(pdf_multi.is_supported_version('1.24.5'))
        self.assertTrue(pdf_multi.is_supported_version('1.24.7'))

    def test_installed_version_reports_the_binding_version(self):
        module = types.SimpleNamespace(__version__='1.23.26',
                                       VersionBind='1.23.26',
                                       VersionFitz='1.23.10')
        self.assertEqual(pdf_multi.module_version(module), '1.23.26')

    def test_installed_version_falls_back_to_VersionBind(self):
        # __version__ only exists from PyMuPDF 1.23 onward.
        module = types.SimpleNamespace(VersionBind='1.19.2', VersionFitz='1.19.0')
        self.assertEqual(pdf_multi.module_version(module), '1.19.2')

    def test_installed_version_of_an_unrecognizable_module(self):
        self.assertFalse(pdf_multi.is_supported_version(
            pdf_multi.module_version(types.SimpleNamespace())))

    def _imports_during(self, call):
        """The names imported while <call> runs, and what it returned."""
        imported = []
        real_import = builtins.__import__

        def recording_import(name, *args, **kwargs):
            imported.append(name)
            return real_import(name, *args, **kwargs)

        with mock.patch('builtins.__import__', recording_import):
            result = call()
        return imported, result

    def test_the_version_is_read_without_loading_pymupdf(self):
        """PyMuPDF up to 1.24.5 crashes the process when its extension is
        loaded after GTK 4, which MComix always has loaded by then: the
        version has to be known before anything is imported."""
        with mock.patch('importlib.metadata.version', return_value='1.24.10'):
            imported, version = self._imports_during(pdf_multi.installed_version)
        self.assertEqual('1.24.10', version)
        self.assertFalse({'pymupdf', 'fitz'} & set(imported), imported)

    def test_a_release_too_old_is_never_loaded(self):
        with mock.patch('importlib.metadata.version', return_value='1.23.5'):
            imported, handler = self._imports_during(pdf_multi.load_handler)
        self.assertIs(pdf_multi.DisabledFitzArchive, handler)
        self.assertFalse({'pymupdf', 'fitz'} & set(imported), imported)

    def test_a_pymupdf_without_metadata_is_asked_for_its_version(self):
        module = types.SimpleNamespace(__version__='1.24.10')
        with mock.patch('importlib.metadata.version',
                        side_effect=metadata.PackageNotFoundError('PyMuPDF')), \
                mock.patch.dict(sys.modules, {'pymupdf': module}):
            self.assertEqual('1.24.10', pdf_multi.installed_version())

    def test_loading_the_handler_keeps_pymupdf_out_of_the_process(self):
        """PyMuPDF runs in the worker process, and nowhere else: loaded
        into MComix' own process it costs a fifth of a second of every
        start, and a release that crashes beside GTK takes the window
        down with it."""
        import subprocess
        probe = ("import sys; from mcomix.archive import pdf_multi; "
                 "print(pdf_multi.PdfMultiArchive.__name__, sorted("
                 "{'pymupdf', 'fitz', 'mcomix.archive.native_pdf.child'}"
                 " & set(sys.modules)))")
        root = os.path.dirname(os.path.dirname(os.path.abspath(mcomix.__file__)))
        answer = subprocess.run([sys.executable, '-c', probe], cwd=root,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, answer.returncode, answer.stderr)
        name, _separator, loaded = answer.stdout.strip().partition(' ')
        self.assertEqual('[]', loaded, answer.stdout)
        if pdf_multi.PdfMultiArchive is not pdf_multi.DisabledFitzArchive:
            self.assertEqual('FitzArchive', name)

    def test_the_worker_is_never_forked_from_the_window(self):
        """A worker forked from MComix starts with GTK already loaded."""
        from mcomix.archive.native_pdf import manager
        self.assertIn(manager.worker_context().get_start_method(),
                      ('forkserver', 'spawn'))

    def test_no_pymupdf_at_all_has_no_version(self):
        with mock.patch('importlib.metadata.version',
                        side_effect=metadata.PackageNotFoundError('PyMuPDF')), \
                mock.patch.dict(sys.modules, {'pymupdf': None, 'fitz': None}):
            self.assertIsNone(pdf_multi.installed_version())
            self.assertIs(pdf_multi.DisabledFitzArchive, pdf_multi.load_handler())


def _make_pdf(path, text_page=False, rotation=0, image_format='JPEG'):
    """Write a two page PDF: a page holding nothing but a full page image
    in <image_format>, turned by <rotation> degrees, and, if <text_page> is
    set, a page of text.  The image is noise, and a JPEG is saved at a
    quality no default picks, so that compressing it again changes it."""
    import pymupdf
    from PIL import Image

    image = io.BytesIO()
    options = {'quality': 95} if image_format == 'JPEG' else {}
    Image.effect_noise((200, 300), 64).convert('RGB').save(
        image, format=image_format, **options)
    document = pymupdf.open()
    page = document.new_page(width=200, height=300)
    page.insert_image(page.rect, stream=image.getvalue())
    if rotation:
        page.set_rotation(rotation)
    if text_page:
        document.new_page(width=200, height=300).insert_text((20, 20), 'text')
    document.save(path)
    document.close()


@unittest.skipUnless(pdf_multi.PdfMultiArchive is not pdf_multi.DisabledFitzArchive,
                     'native PDF handler is not available')
class FitzWorkerTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.directory = tempfile.mkdtemp(dir=os.environ['TMPDIR'])
        self.pdf = os.path.join(self.directory, 'test.pdf')

    def _worker(self, **kwargs):
        from mcomix.archive.native_pdf.child import FitzWorker
        _make_pdf(self.pdf, **kwargs)
        return FitzWorker(self.pdf)

    def test_a_scanned_page_is_listed_for_extraction(self):
        names = list(self._worker().iter_contents())
        self.assertEqual(len(names), 1)
        self.assertIn('_mcmxref', names[0])

    def test_the_listed_extension_matches_the_extracted_data(self):
        # The extension used to come from image_profile(), which raises
        # TypeError in PyMuPDF 1.28, leaving every page named ".png"
        # whatever its content turned out to be.
        worker = self._worker()
        name = next(iter(worker.iter_contents()))
        self.assertTrue(name.endswith('.jpeg'), name)
        worker.extract_file(name, self.directory)
        from PIL import Image
        with Image.open(os.path.join(self.directory, name)) as extracted:
            self.assertEqual(extracted.format, 'JPEG')

    def test_a_page_with_text_is_rendered_instead(self):
        names = list(self._worker(text_page=True).iter_contents())
        self.assertEqual(len(names), 2)
        self.assertIn('_mcmxref', names[0])
        self.assertEqual(names[1], 'page0002.png')

    def test_a_rendered_page_is_extracted_as_a_png(self):
        worker = self._worker(text_page=True)
        names = list(worker.iter_contents())
        worker.extract_file(names[1], self.directory)
        from PIL import Image
        with Image.open(os.path.join(self.directory, names[1])) as extracted:
            self.assertEqual(extracted.format, 'PNG')

    def test_page_count(self):
        self.assertEqual(self._worker(text_page=True).page_count(), 2)

    def _extract_first(self, **kwargs):
        """The first page's name, the file extracted for it, and the image
        the PDF holds for it."""
        worker = self._worker(**kwargs)
        name = next(iter(worker.iter_contents()))
        worker.extract_file(name, self.directory)
        xref = int(os.path.splitext(name)[0].split('_mcmxref')[1])
        embedded = worker.doc.extract_image(xref)['image']
        return name, os.path.join(self.directory, name), embedded

    def test_a_turned_jpeg_page_keeps_its_compressed_picture(self):
        """Saving the page again through Pillow to add its orientation
        compressed the picture again, at Pillow's default quality; only
        the Exif segment changes now."""
        from mcomix import image_tools
        name, path, embedded = self._extract_first(rotation=90)
        self.assertTrue(name.endswith('.jpeg'), name)
        with open(path, 'rb') as fp:
            extracted = fp.read()
        self.assertEqual(embedded[embedded.index(b'\xff\xda'):],
                         extracted[extracted.index(b'\xff\xda'):])
        self.assertEqual(90, image_tools.get_implied_rotation_from_file(path))

    @unittest.skipUnless(features.check('jpg_2000'), 'Pillow reads no JPEG 2000')
    def test_a_turned_jpeg_2000_page_becomes_a_png_that_keeps_its_turn(self):
        """Pillow writes no Exif into JPEG 2000, so the orientation saved
        into such a page was lost and the page was shown unturned."""
        from PIL import Image
        from mcomix import image_tools
        name, path, _embedded = self._extract_first(
            rotation=90, image_format='JPEG2000')
        self.assertTrue(name.endswith('.png'), name)
        with Image.open(path) as page:
            self.assertEqual(('PNG', (200, 300)), (page.format, page.size))
        self.assertEqual(90, image_tools.get_implied_rotation_from_file(path))

    @unittest.skipUnless(features.check('jpg_2000'), 'Pillow reads no JPEG 2000')
    def test_an_unturned_jpeg_2000_page_is_handed_over_as_it_is(self):
        name, path, embedded = self._extract_first(image_format='JPEG2000')
        self.assertTrue(name.endswith('.jpx'), name)
        with open(path, 'rb') as fp:
            self.assertEqual(embedded, fp.read())

    @unittest.skipUnless(features.check('jpg_2000'), 'Pillow reads no JPEG 2000')
    def test_a_turned_page_pillow_cannot_read_is_rendered_turned(self):
        """As a JBIG2 image cannot be: the page is drawn as the PDF
        shows it, turned, with no orientation left for the display."""
        from PIL import Image, UnidentifiedImageError
        from mcomix import image_tools
        from mcomix.archive.native_pdf import child
        worker = self._worker(rotation=90, image_format='JPEG2000')
        name = next(iter(worker.iter_contents()))
        with mock.patch.object(child.Image, 'open',
                               side_effect=UnidentifiedImageError('JBIG2')):
            worker.extract_file(name, self.directory)
        path = os.path.join(self.directory, name)
        with Image.open(path) as page:
            width, height = page.size
        self.assertGreater(width, height)
        self.assertEqual(0, image_tools.get_implied_rotation_from_file(path))


@unittest.skipUnless(pdf_multi.PdfMultiArchive is not pdf_multi.DisabledFitzArchive,
                     'native PDF handler is not available')
class JpegOrientationTest(unittest.TestCase):

    """An orientation written into a JPEG without compressing it again."""

    def _jpeg(self, **options):
        from PIL import Image
        data = io.BytesIO()
        Image.effect_noise((40, 30), 64).convert('RGB').save(
            data, format='JPEG', **options)
        return data.getvalue()

    def test_the_picture_is_copied_and_the_orientation_set(self):
        from PIL import Image, ExifTags
        from mcomix.archive.native_pdf.child import jpeg_with_orientation
        source = self._jpeg()
        turned = jpeg_with_orientation(source, 6)
        self.assertEqual(source[source.index(b'\xff\xda'):],
                         turned[turned.index(b'\xff\xda'):])
        with Image.open(io.BytesIO(turned)) as image:
            self.assertEqual(6, image.getexif()[ExifTags.Base.Orientation])
        # The JFIF segment Pillow writes has to stay the first.
        self.assertEqual(b'\xff\xe0', turned[2:4])

    def test_an_existing_exif_is_kept_and_its_orientation_replaced(self):
        from PIL import Image, ExifTags
        from mcomix.archive.native_pdf.child import jpeg_with_orientation
        exif = Image.Exif()
        exif[ExifTags.Base.Software] = 'scanner'
        exif[ExifTags.Base.Orientation] = 1
        turned = jpeg_with_orientation(self._jpeg(exif=exif.tobytes()), 8)
        self.assertEqual(1, turned.count(b'Exif\x00\x00'))
        with Image.open(io.BytesIO(turned)) as image:
            written = image.getexif()
        self.assertEqual((8, 'scanner'), (written[ExifTags.Base.Orientation],
                                          written[ExifTags.Base.Software]))

    def test_other_data_is_refused(self):
        from mcomix.archive.native_pdf.child import jpeg_with_orientation
        for data in (b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff\xe0\x00'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                jpeg_with_orientation(data, 6)


    def test_a_file_broken_off_is_refused(self):
        """A file that ended on a marker's first byte raised IndexError,
        which nothing caught: the turned page of a damaged PDF failed
        where it would otherwise have been saved again or rendered."""
        from mcomix.archive.native_pdf.child import jpeg_with_orientation
        source = self._jpeg()
        for end in range(2, source.index(b'\xff\xda') + 1):
            for data in (source[:end], source[:end] + b'\xff'):
                with self.subTest(end=end, data=data[-2:]), \
                        self.assertRaises(ValueError):
                    jpeg_with_orientation(data, 6)

@unittest.skipUnless(pdf_multi.PdfMultiArchive is not pdf_multi.DisabledFitzArchive,
                     'native PDF handler is not available')
class FitzArchiveTest(MComixTest):

    """The handler as MComix uses it: the document open in a worker
    process of its own, reached through a multiprocessing manager."""

    def setUp(self):
        super().setUp()
        self.pdf = os.path.join(self.tmp_dir, 'turned.pdf')
        _make_pdf(self.pdf, rotation=90)
        self.destination = os.path.join(self.tmp_dir, 'pages')

    def _extracted(self):
        """The size of the first page as the worker extracts it, and the
        rotation its metadata asks the display for."""
        from PIL import Image
        from mcomix import image_tools
        archive = pdf_multi.PdfMultiArchive(self.pdf)
        try:
            name = next(iter(archive.iter_contents()))
            archive.extract(name, self.destination)
        finally:
            # Left running, the manager's process outlives the test.
            archive._mgr.mgr.shutdown()
            archive.close()
        path = os.path.join(self.destination, name)
        with Image.open(path) as page:
            return page.size, image_tools.get_implied_rotation_from_file(path)

    def test_the_page_count_is_a_number(self):
        """A call through the manager answers with a proxy for the result,
        not the result: FitzArchive logged "PDF contains %d pages" with
        the proxy, which raised as soon as debug logging was on."""
        archive = pdf_multi.PdfMultiArchive(self.pdf)
        try:
            count = archive.mgr.page_count()
        finally:
            archive._mgr.mgr.shutdown()
            archive.close()
        self.assertIsInstance(count, int)
        self.assertEqual(1, count)

    @posix_byte_names
    def test_a_pdf_whose_path_is_not_utf_8_opens(self):
        """PyMuPDF takes a file name only as UTF-8 text, and a name on
        disk need not be: a PDF in a folder named in Latin-1 raised
        FileDataError in the worker, and could not be opened at all."""
        latin = os.fsdecode(os.path.join(os.fsencode(self.tmp_dir),
                                         'B\xfccher.pdf'.encode('latin-1')))
        os.rename(self.pdf, latin)
        archive = pdf_multi.PdfMultiArchive(latin)
        try:
            names = list(archive.iter_contents())
            archive.extract(names[0], self.destination)
        finally:
            archive._mgr.mgr.shutdown()
            archive.close()
        self.assertEqual(1, len(names))
        self.assertTrue(os.path.isfile(os.path.join(self.destination,
                                                    names[0])))

    def test_a_turned_page_keeps_its_pixels_and_names_its_turn(self):
        """The worker records the page's rotation as Exif orientation
        rather than turning its pixels, and the display turns it as it
        does any image, while "auto rotate from exif" is set."""
        self.assertEqual(((200, 300), 90), self._extracted())

    def test_the_page_comes_out_the_same_whatever_the_preference(self):
        """A worker started by forkserver or spawn - the defaults on Python
        3.14 and on Windows - reads the preferences afresh and would see
        their defaults, so nothing it writes may depend on them."""
        prefs['auto rotate from exif'] = False
        self.assertEqual(((200, 300), 90), self._extracted())

# vim: expandtab:sw=4:ts=4
