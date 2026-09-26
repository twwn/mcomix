""" Tests for the external (mutool/mudraw) PDF handler. """

import os
import sys
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

@unittest.skipIf(sys.platform == 'win32',
                 'the stand-in tools are shell scripts')
class MuPdfVersionTest(MComixTest):

    """Which commands the handler settles on for each MuPDF there is.

    From 1.8 mutool draws pages itself; before that a separate mudraw
    did, 1.7 traced a page with "-F trace" and 1.6 - which does not
    answer to "-v" at all - with "-x".  The tools are stood in for by
    scripts on a PATH of their own, since only the newest is installed.
    """

    def setUp(self):
        super().setUp()
        self._bin = os.path.join(self.tmp_dir, 'bin')
        os.makedirs(self._bin)
        saved_path = os.environ.get('PATH')
        os.environ['PATH'] = self._bin
        self.addCleanup(os.environ.__setitem__, 'PATH', saved_path or '')
        pdf_external._find_mupdf.cache_clear()
        self.addCleanup(pdf_external._find_mupdf.cache_clear)

    def _tool(self, name, says_version=None):
        path = os.path.join(self._bin, name)
        with open(path, 'w') as script:
            script.write('#!/bin/sh\n')
            if says_version is not None:
                script.write('echo "mutool version %s" >&2\n' % says_version)
        os.chmod(path, 0o755)
        return path

    def test_mutool_from_1_8_draws_the_pages_itself(self):
        mutool = self._tool('mutool', '1.18.0')
        mupdf = pdf_external._find_mupdf()
        self.assertEqual(([mutool], [mutool, 'draw'], ['-F', 'trace']),
                         (mupdf.mutool, mupdf.mudraw, mupdf.trace_args))

    def test_1_7_draws_with_mudraw_and_traces_with_f(self):
        mutool = self._tool('mutool', '1.7')
        mudraw = self._tool('mudraw')
        mupdf = pdf_external._find_mupdf()
        self.assertEqual(([mutool], [mudraw], ['-F', 'trace']),
                         (mupdf.mutool, mupdf.mudraw, mupdf.trace_args))

    def test_a_mutool_that_says_no_version_is_1_6_and_traces_with_x(self):
        self._tool('mutool')
        mudraw = self._tool('mudraw')
        mupdf = pdf_external._find_mupdf()
        self.assertEqual(([mudraw], ['-x']), (mupdf.mudraw, mupdf.trace_args))

    def test_an_old_mutool_without_mudraw_is_no_mupdf(self):
        self._tool('mutool', '1.7')
        self.assertIsNone(pdf_external._find_mupdf())

    def test_no_mutool_is_no_mupdf(self):
        self.assertIsNone(pdf_external._find_mupdf())
        self.assertFalse(pdf_external.PdfArchive.is_available())


# vim: expandtab:sw=4:ts=4
