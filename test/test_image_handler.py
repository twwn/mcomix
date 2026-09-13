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

class CacheWindowTest(MComixTest):

    """The set of pages C{_ask_for_pages} picks must always contain the page
    that is on screen: it doubles as the list of pixbufs worth keeping, so a
    window that misses the current page throws it away as soon as it is
    shown."""

    def setUp(self):
        super(CacheWindowTest, self).setUp()
        self.handler = image_handler.ImageHandler(_StubWindow())
        self.handler.set_image_files(['%02d.png' % n for n in range(1, 11)])
        for page in range(1, 11):
            self.handler.page_available(page)

    def tearDown(self):
        self.handler.cleanup()
        super(CacheWindowTest, self).tearDown()

    def _wanted(self, cache_pages, double_page, page):
        prefs['default double page'] = double_page
        self.handler._cache_pages = cache_pages
        return self.handler._ask_for_pages(page)

    def test_no_cacheing_asks_for_the_current_page(self):
        self.assertEqual(self._wanted(0, False, 5), [4])

    def test_no_cacheing_asks_for_both_pages_of_a_spread(self):
        self.assertEqual(sorted(self._wanted(0, True, 5)), [4, 5])

    def test_a_budget_too_small_to_look_back_spends_it_on_the_current_page(self):
        for cache_pages in (1, 2, 3):
            self.assertIn(4, self._wanted(cache_pages, False, 5))
        for cache_pages in (1, 2, 3, 4):
            self.assertIn(4, self._wanted(cache_pages, True, 5))
            self.assertIn(5, self._wanted(cache_pages, True, 5))

    def test_the_default_budget_still_spans_the_page_before_and_after(self):
        self.assertEqual(self._wanted(7, False, 5), [4, 5, 3, 6, 7, 8, 9])

    def test_a_book_shorter_than_a_spread_still_asks_for_its_one_page(self):
        self.handler.set_image_files(['01.png'])
        self.assertEqual(self._wanted(-1, True, 1), [0])

    def test_the_window_is_clipped_to_the_book(self):
        self.assertEqual(self._wanted(7, False, 1), [0, 1, 2, 3, 4, 5])
        self.assertEqual(self._wanted(7, False, 10), [9, 8])


# vim: expandtab:sw=4:ts=4
