""" Tests for the DjVu handler, which shells out to DjVuLibre. """

import os
import shutil
import subprocess
import unittest

from PIL import Image

from . import MComixTest, wait_for
from .test_file_handler import _WindowTest

from mcomix import archive_tools
from mcomix import constants
from mcomix.archive import djvu_external

#: The colour of each page of the document _write_djvu() makes.
_PAGES = ((200, 30, 30), (30, 30, 200))


def _write_djvu(directory, pages=_PAGES):
    """Write a DjVu document of one page per colour in <pages>, bundled
    when there is more than one, as c44 and djvm make them; return its
    path."""
    singles = []
    for number, colour in enumerate(pages, 1):
        picture = os.path.join(directory, 'page%d.ppm' % number)
        Image.new('RGB', (40, 60), colour).save(picture)
        single = os.path.join(directory, 'page%d.djvu' % number)
        subprocess.run(['c44', picture, single], check=True,
                       stdout=subprocess.DEVNULL)
        singles.append(single)
    if len(singles) == 1:
        return singles[0]
    bundled = os.path.join(directory, 'book.djvu')
    subprocess.run(['djvm', '-c', bundled] + singles, check=True)
    return bundled


_CAN_WRITE = shutil.which('c44') is not None and shutil.which('djvm') is not None

_needs_djvulibre = (
    unittest.skipUnless(djvu_external.DjvuArchive.is_available(),
                        'DjVuLibre not installed'),
    unittest.skipUnless(_CAN_WRITE, 'c44 and djvm are needed to write the '
                        'test document'))


def _with_djvulibre(cls):
    for decorator in _needs_djvulibre:
        cls = decorator(cls)
    return cls


@_with_djvulibre
class DjvuExternalTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.djvu = _write_djvu(self.tmp_dir)

    def test_a_djvu_document_is_known_by_its_content(self):
        single = _write_djvu(self.tmp_dir, _PAGES[:1])
        for path in (self.djvu, single):
            self.assertEqual(constants.DJVU,
                             archive_tools.archive_mime_type(path), path)
        self.assertTrue(archive_tools.is_archive_file(self.djvu))

    def test_a_page_is_listed_for_every_page_of_the_document(self):
        archive = djvu_external.DjvuArchive(self.djvu)
        self.assertEqual(['1.tif', '2.tif'], list(archive.iter_contents()))

    def test_a_listed_page_extracts_to_its_picture(self):
        archive = djvu_external.DjvuArchive(self.djvu)
        destination = os.path.join(self.tmp_dir, 'out')
        archive.extract('2.tif', destination)
        with Image.open(os.path.join(destination, '2.tif')) as page:
            red, green, blue = page.convert('RGB').getpixel((20, 30))[:3]
        self.assertGreater(blue, 150)
        self.assertLess(red, 80)


@_with_djvulibre
class DjvuBookTest(_WindowTest):

    def test_it_opens_as_a_book_of_its_pages(self):
        path = _write_djvu(self.tmp_dir)
        self.assertTrue(self.handler.open_file(path))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 2,
            seconds=20))
        self.assertEqual(constants.DJVU, self.handler.archive_type)


class NoDjVuLibreTest(MComixTest):

    """Without the programs, the format is not offered, and a document
    that is opened anyway names what it needs."""

    def setUp(self):
        super().setUp()
        saved_path = os.environ.get('PATH')
        os.environ['PATH'] = os.path.join(self.tmp_dir, 'empty')
        self.addCleanup(os.environ.__setitem__, 'PATH', saved_path or '')
        djvu_external._find_djvulibre.cache_clear()
        self.addCleanup(djvu_external._find_djvulibre.cache_clear)

    def test_nothing_reads_it(self):
        self.assertFalse(djvu_external.DjvuArchive.is_available())
        self.assertIn('ddjvu', archive_tools.cannot_open(
            os.path.join('nowhere', 'book.djvu'), constants.DJVU))

# vim: expandtab:sw=4:ts=4
