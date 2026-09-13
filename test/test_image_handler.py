# -*- coding: utf-8 -*-

""" Tests for the parts of the image handler that decide how a page is
shown, which every page stepped over is asked about. """

import os
import shutil

from . import MComixTest, get_testfile_path

from mcomix import callback
from mcomix import constants
from mcomix import image_handler
from mcomix.preferences import prefs


class _StubFileHandler(object):

    archive_type = None
    file_loaded = False

    @callback.Callback
    def file_available(self, filepaths):
        pass


class _StubWindow(object):

    def __init__(self):
        self.filehandler = _StubFileHandler()

    def displayed_double(self):
        return False


class VirtualDoublePageTest(MComixTest):

    def setUp(self):
        super(VirtualDoublePageTest, self).setUp()
        prefs['max pages to cache'] = 4
        prefs['default double page'] = True
        prefs['virtual double page for fitting images'] = constants.SHOW_DOUBLE_AS_ONE_WIDE
        self.handler = image_handler.ImageHandler(_StubWindow())

    def tearDown(self):
        self.handler.cleanup()
        super(VirtualDoublePageTest, self).tearDown()

    def _open(self, *names):
        """Make a book out of the named test images, and go to its first page."""
        paths = []
        for number, name in enumerate(names, 1):
            path = os.path.join(self.tmp_dir, '%02d-%s' % (number, name))
            shutil.copyfile(get_testfile_path('images', name), path)
            paths.append(path)
        self.handler.set_image_files(paths)
        for page in range(1, len(paths) + 1):
            self.handler.page_available(page)
        self.handler.set_page(1)

    def test_a_wide_page_is_shown_on_its_own(self):
        self._open('portrait-no-exif.png', 'landscape-no-exif.png',
                   'portrait-no-exif.png')
        self.assertTrue(self.handler.get_virtual_double_page(2))

    def test_a_tall_page_is_shown_beside_its_neighbour(self):
        self._open('portrait-no-exif.png', 'portrait-no-exif.png',
                   'portrait-no-exif.png')
        self.assertFalse(self.handler.get_virtual_double_page(2))

    def test_the_last_page_is_shown_on_its_own(self):
        self._open('portrait-no-exif.png', 'portrait-no-exif.png')
        self.assertFalse(self.handler.get_virtual_double_page(2))

    def test_a_page_that_is_not_extracted_yet_is_not_waited_for(self):
        self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        self.handler._available_images.clear()
        self.assertFalse(self.handler.get_virtual_double_page(1))

    def test_exif_rotation_decides_which_way_round_a_page_is(self):
        # Stored 210x297, but its Exif data says to turn it a quarter
        # turn, so it is shown 297x210: a page to show on its own.
        self._open('portrait-no-exif.jpg', 'landscape-exif-270-rotation.jpg',
                   'portrait-no-exif.jpg')
        prefs['auto rotate from exif'] = True
        self.assertTrue(self.handler.get_virtual_double_page(2))
        prefs['auto rotate from exif'] = False
        self.assertFalse(self.handler.get_virtual_double_page(2))

    def test_the_pages_it_looks_at_are_not_decoded(self):
        # Deciding this used to load every page it was asked about, which
        # is what made holding a page key down step through a book one
        # slow decode at a time.
        self._open(*(('portrait-no-exif.png',) * 6))
        self.handler._raw_pixbufs.clear()
        for page in range(1, 6):
            self.handler.get_virtual_double_page(page)
        self.assertEqual(self.handler._raw_pixbufs, {})

    def test_a_cached_page_is_measured_from_the_pixbuf(self):
        self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        # Whichever way round the answer is arrived at, it is the same.
        uncached = self.handler._get_displayed_size(2)
        self.handler._get_pixbuf(1)
        self.assertEqual(self.handler._get_displayed_size(2), uncached)

# vim: expandtab:sw=4:ts=4
