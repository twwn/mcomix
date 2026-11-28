""" Tests for the external (mutool/mudraw) PDF handler. """

import os
import subprocess
import sys
import unittest
import unittest.mock

from mcomix import process
from mcomix.archive import archive_base
from mcomix.archive import pdf_external
from mcomix.constants import PDF_RENDER_DPI_DEF, PDF_RENDER_DPI_MAX
from mcomix.version_tools import Version

from . import MComixTest

try:
    import pymupdf
except ImportError:
    pymupdf = None


def _write_pdf(path, pages):
    """Write a PDF of <pages> pages, each holding one image."""
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page()
        page.insert_image(pymupdf.Rect(0, 0, 200, 300),
                          pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 300)))
    document.save(path)
    document.close()


@unittest.skipUnless(pdf_external.PdfArchive.is_available(), 'MuPDF not installed')
@unittest.skipIf(pymupdf is None, 'PyMuPDF is needed to write the test document')
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


def _image(width, height, matrix):
    """A line of a page's trace: an image of <width> by <height> pixels
    drawn under <matrix>."""
    return ('<fill_image alpha="1" transform="%s" width="%d" height="%d"/>'
            % (matrix, width, height))


class ResolutionTest(MComixTest):

    """A page is rendered at the resolution that draws the largest side
    of its largest image at that image's own size in pixels.

    The tools are stood in for: the trace is given, and the render is
    read off the command that would draw it.
    """

    MUPDF = pdf_external._MuPdf(Version('1.24'), ['mutool'],
                                ['mutool', 'draw'], ['-F', 'trace'])

    def setUp(self):
        super().setUp()
        self.enterContext(unittest.mock.patch.object(
            pdf_external, '_find_mupdf', return_value=self.MUPDF))
        self.pdf = os.path.join(self.tmp_dir, 'book.pdf')
        self.destination = os.path.join(self.tmp_dir, 'out')
        self.rendered = True

    def _render(self, *trace):
        """The resolution page 3 is rendered at, after <trace>."""
        traced = subprocess.CompletedProcess([], 0, '\n'.join(
            ('<page number="3">',) + trace + ('</page>',)))
        with unittest.mock.patch('subprocess.run',
                                 return_value=traced) as tracing, \
                unittest.mock.patch.object(
                    process, 'call', return_value=self.rendered) as drawing:
            pdf_external.PdfArchive(self.pdf).extract('3.png',
                                                      self.destination)
        # Decoded, whatever the bytes, and without a console on Windows.
        tracing.assert_called_once_with(
            ['mutool', 'draw', '-F', 'trace', '--', self.pdf, '3'],
            stdout=subprocess.PIPE, encoding='utf-8', errors='replace',
            creationflags=process.CREATIONFLAGS)
        (command,), _ = drawing.call_args
        resolution = command[3]
        self.assertEqual(['mutool', 'draw', '-r', resolution, '-o',
                          os.path.join(self.destination, '3.png'),
                          '--', self.pdf, '3'], command)
        return int(resolution)

    def test_a_page_without_images_takes_the_default(self):
        self.assertEqual(PDF_RENDER_DPI_DEF, self._render())

    def test_an_image_drawn_at_half_its_size_takes_144(self):
        # 1000 by 1500 pixels on 500 by 750 points.
        self.assertEqual(144, self._render(
            '<fill_path/>', _image(1000, 1500, '500 0 0 750 0 0')))

    def test_a_turned_image_is_measured_along_its_sides(self):
        """Each side is as long as its pair of the matrix says: the
        first two numbers for the pixels across, the next two for the
        pixels down.  1500 pixels across on sqrt(300² + 400²) = 500
        points are 216 per inch; 1500 down on sqrt(750² + 600²) = 960.5
        points are 112."""
        self.assertEqual(216, self._render(
            _image(1500, 1000, '300 400 -750 0 0 0')))
        self.assertEqual(112, self._render(
            _image(1000, 1500, '0 500 -750 600 0 0')))

    def test_the_largest_side_of_the_images_decides(self):
        """The first image is 1000 pixels each way on 1000 points; the
        second, narrower, is 2000 high on 1000 points; the third is
        smaller."""
        self.assertEqual(144, self._render(
            _image(1000, 1000, '1000 0 0 1000 0 0'),
            _image(100, 2000, '100 0 0 1000 0 0'),
            _image(50, 50, '1 0 0 1 0 0')))

    def test_the_resolution_is_bounded(self):
        self.assertEqual(PDF_RENDER_DPI_MAX, self._render(
            _image(10000, 10000, '72 0 0 72 0 0')))

    def test_a_render_that_fails_asks_whether_the_disk_is_full(self):
        for rendered in (False, True):
            self.rendered = rendered
            with self.subTest(rendered=rendered), \
                    unittest.mock.patch.object(
                        archive_base, 'raise_if_no_room') as asked:
                self._render()
            if rendered:
                asked.assert_not_called()
            else:
                asked.assert_called_once_with(
                    os.path.join(self.destination, '3.png'))


# vim: expandtab:sw=4:ts=4
