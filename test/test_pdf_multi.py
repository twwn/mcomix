# -*- coding: utf-8 -*-

""" Tests for the native (PyMuPDF) PDF handler. """

import io
import os
import re
import tempfile
import tomllib
import types
import unittest

import mcomix
from mcomix.archive import pdf_multi

from . import MComixTest


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

    def test_installed_version_reports_the_binding_version(self):
        module = types.SimpleNamespace(__version__='1.23.26',
                                       VersionBind='1.23.26',
                                       VersionFitz='1.23.10')
        self.assertEqual(pdf_multi.installed_version(module), '1.23.26')

    def test_installed_version_falls_back_to_VersionBind(self):
        # __version__ only exists from PyMuPDF 1.23 onward.
        module = types.SimpleNamespace(VersionBind='1.19.2', VersionFitz='1.19.0')
        self.assertEqual(pdf_multi.installed_version(module), '1.19.2')

    def test_installed_version_of_an_unrecognizable_module(self):
        self.assertFalse(pdf_multi.is_supported_version(
            pdf_multi.installed_version(types.SimpleNamespace())))


def _make_pdf(path, text_page=False):
    """Write a two page PDF: a page holding nothing but a full page JPEG,
    and, if <text_page> is set, a page of text."""
    import pymupdf
    from PIL import Image

    image = io.BytesIO()
    Image.new('RGB', (200, 300), (16, 32, 64)).save(image, format='JPEG')
    document = pymupdf.open()
    page = document.new_page(width=200, height=300)
    page.insert_image(page.rect, stream=image.getvalue())
    if text_page:
        document.new_page(width=200, height=300).insert_text((20, 20), 'text')
    document.save(path)
    document.close()


@unittest.skipUnless(pdf_multi.PdfMultiArchive is not pdf_multi.DisabledFitzArchive,
                     'native PDF handler is not available')
class FitzWorkerTest(MComixTest):

    def setUp(self):
        super(FitzWorkerTest, self).setUp()
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

# vim: expandtab:sw=4:ts=4
