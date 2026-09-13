""" Tests for the external (mutool/mudraw) PDF handler. """

import os
import unittest

from mcomix.archive import pdf_external

from . import MComixTest

try:
    import fitz
except ImportError:
    fitz = None


def _write_pdf(path, pages):
    """Write a PDF of <pages> pages, each holding one image."""
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page()
        page.insert_image(fitz.Rect(0, 0, 200, 300),
                          pixmap=fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 300)))
    document.save(path)
    document.close()


@unittest.skipUnless(pdf_external.PdfArchive.is_available(), 'MuPDF not installed')
@unittest.skipIf(fitz is None, 'PyMuPDF is needed to write the test document')
class PdfExternalTest(MComixTest):

    """The handler shells out to mutool, so the version it found decides
    which executable draws a page and how a page is traced for its size."""

    def setUp(self):
        super().setUp()
        self._pdf = os.path.join(self.tmp_dir, 'test.pdf')
        _write_pdf(self._pdf, 3)

    def test_a_page_is_listed_for_every_page_of_the_document(self):
        archive = pdf_external.PdfArchive(self._pdf)
        self.assertEqual(['1.png', '2.png', '3.png'], archive.list_contents())

    def test_a_listed_page_extracts_to_an_image(self):
        archive = pdf_external.PdfArchive(self._pdf)
        destination = os.path.join(self.tmp_dir, 'out')
        archive.extract('2.png', destination)
        self.assertEqual(['2.png'], os.listdir(destination))
        with open(os.path.join(destination, '2.png'), 'rb') as page:
            self.assertEqual(b'\x89PNG\r\n\x1a\n', page.read(8))

    def test_the_resolved_commands_name_the_installed_mutool(self):
        mupdf = pdf_external._find_mupdf()
        self.assertIsNotNone(mupdf)
        self.assertTrue(os.path.isfile(mupdf.mutool[0]))
        self.assertTrue(os.path.isfile(mupdf.mudraw[0]))
        self.assertTrue(mupdf.trace_args)

# vim: expandtab:sw=4:ts=4
