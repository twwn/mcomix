""" Tests for the parts of the image handler that decide how a page is
shown, which every page stepped over is asked about. """

import os
import shutil
import threading
import unittest.mock

from . import MComixTest, get_testfile_path

from mcomix import callback
from mcomix import constants
from mcomix import image_handler
from mcomix import image_tools
from mcomix.preferences import prefs


class _StubFileHandler:

    archive_type = None
    file_loaded = False

    @callback.Callback
    def file_available(self, filepaths):
        pass


class _StubWindow:

    def __init__(self):
        self.filehandler = _StubFileHandler()

    def displayed_double(self):
        return False


class VirtualDoublePageTest(MComixTest):

    def setUp(self):
        super().setUp()
        prefs['max pages to cache'] = 4
        prefs['default double page'] = True
        prefs['virtual double page for fitting images'] = constants.SHOW_DOUBLE_AS_ONE_WIDE
        self.handler = image_handler.ImageHandler(_StubWindow())

    def tearDown(self):
        self.handler.cleanup()
        super().tearDown()

    def _make_book(self, *names):
        """Make a book out of the named test images, with none of them
        extracted yet, and return its list of paths."""
        paths = []
        for number, name in enumerate(names, 1):
            path = os.path.join(self.tmp_dir, '%02d-%s' % (number, name))
            shutil.copyfile(get_testfile_path('images', name), path)
            paths.append(path)
        self.handler.set_image_files(paths)
        return paths

    def _open(self, *names):
        """Make a book out of the named test images, and go to its first page."""
        paths = self._make_book(*names)
        for page in range(1, len(paths) + 1):
            self.handler.page_available(page)
        self.handler.set_page(1)
        return paths

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

    def test_a_page_that_will_not_load_answers_with_the_missing_icon(self):
        """A book holds whatever files it was pointed at, and one of them
        may be truncated, or not an image at all.  Nothing above this
        expects an exception, so the page shows the missing-image icon."""
        self._open('portrait-no-exif.png')
        broken = self.handler.get_path_to_page(1)
        with open(broken, 'wb') as damaged:
            damaged.write(b'not an image')
        self.handler._raw_pixbufs.clear()
        self.assertIs(self.handler._get_pixbuf(0),
                      image_tools.missing_page())

    def test_a_page_that_would_not_load_is_not_read_again(self):
        """Its answer is cached like any other, so a page turn back and
        forth over a broken page does not retry the decode each time."""
        self._open('portrait-no-exif.png')
        broken = self.handler.get_path_to_page(1)
        with open(broken, 'wb') as damaged:
            damaged.write(b'not an image')
        self.handler._raw_pixbufs.clear()
        self.handler._get_pixbuf(0)
        self.assertEqual(list(self.handler._raw_pixbufs), [0])

        reads = []
        real_load = image_tools.load_pixbuf
        image_tools.load_pixbuf = lambda path: reads.append(path) or real_load(path)
        try:
            self.handler._get_pixbuf(0)
        finally:
            image_tools.load_pixbuf = real_load
        self.assertEqual(reads, [], 'the broken page was read a second time')

    def test_the_thumbnail_of_a_page_that_will_not_load_is_the_missing_icon(self):
        """The thumbnail bar and the page selector draw what this
        answers, and both take None for a page not extracted yet, to be
        asked for again once it has been."""
        self._open('portrait-no-exif.png')
        broken = self.handler.get_path_to_page(1)
        with open(broken, 'wb') as damaged:
            damaged.write(b'not an image')
        self.assertIs(self.handler.get_thumbnail(1, 64, 64),
                      image_tools.missing_image_icon(64, 64))

    def test_a_page_that_loads_is_the_pixbuf_the_cache_keeps(self):
        self._open('portrait-no-exif.png')
        self.handler._raw_pixbufs.clear()
        pixbuf = self.handler._get_pixbuf(0)
        self.assertIsNot(pixbuf, image_tools.missing_page())
        self.assertIs(self.handler._raw_pixbufs[0], pixbuf)
        self.assertIs(self.handler._get_pixbuf(0), pixbuf)

    def test_a_page_dropped_from_the_cache_mid_read_is_still_read(self):
        """_get_pixbuf() runs on the caching thread as well as on the
        main one, and WorkerThread._run() calls it outside its lock, so
        do_cacheing() can delete the entry the caching thread is in the
        middle of reading.  The page it is looking at is a good one; it
        has to come back, not come back as the missing-image icon."""
        self._open('portrait-no-exif.png')

        class _VanishingCache(dict):
            """The entry is gone by the time it is read for.

            What a concurrent do_cacheing() does, made to happen every
            time rather than once in a long while.
            """

            def __contains__(self, key):
                return True

            def __getitem__(self, key):
                raise KeyError(key)

            def get(self, key, default=None):
                return default

        self.handler._raw_pixbufs = _VanishingCache()
        pixbuf = self.handler._get_pixbuf(0)
        self.assertIsNot(pixbuf, image_tools.missing_page(),
                         'a good page came back as the missing-image icon')
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height()),
                         (210, 297))

    def test_a_page_that_moved_does_not_show_what_was_read_for_its_old_number(self):
        """A pixbuf is held by position in the list of image files, so
        the moment that list is rewritten it would otherwise stand
        against whatever page now sits at that number."""
        listing = self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        self.handler._get_pixbuf(0)
        self.assertEqual(list(self.handler._raw_pixbufs), [0])

        self.handler.replace_pages(list(reversed(listing)))
        self.assertEqual(self.handler._image_files, list(reversed(listing)))
        # What page 1 shows is the file that is page 1 now.
        self.assertEqual(
            (self.handler._get_pixbuf(0).get_width(),
             self.handler._get_pixbuf(0).get_height()),
            (297, 210))

    def test_a_page_that_moved_keeps_the_pixbuf_that_was_read_for_it(self):
        """The pixbuf belongs to the file, not to the number, so the
        page that changed places is not decoded a second time."""
        listing = self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        portrait = self.handler._get_pixbuf(0)

        self.handler.replace_pages(list(reversed(listing)))
        self.assertIs(self.handler._raw_pixbufs.get(1), portrait)

    def test_replacing_the_pages_with_the_same_listing_changes_nothing(self):
        """do_cacheing() reads the set of extracted pages to know which
        ones it may fetch ahead: emptying it would stop the reading-ahead
        for the rest of the session."""
        self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        available = set(self.handler._available_images)
        self.assertTrue(available)
        self.handler.replace_pages(list(self.handler._image_files))
        self.assertEqual(self.handler._available_images, available)

    def test_reordering_the_pages_carries_over_what_has_been_extracted(self):
        """An archive is still being unpacked while the editor is open,
        so which pages are out of it is a partial answer that has to
        follow its files to their new numbers."""
        listing = self._make_book('portrait-no-exif.png', 'landscape-no-exif.png')
        self.handler.page_available(1)

        self.handler.replace_pages(list(reversed(listing)))
        self.assertFalse(self.handler.page_is_available(1),
                         'a page nothing had extracted was called available')
        self.assertTrue(self.handler.page_is_available(2),
                        'a page that had been extracted was called missing')

    def test_dropping_a_page_drops_what_had_been_extracted_of_it(self):
        """Availability left behind by a deleted page names a number the
        book no longer has, and marks its successor ready to read."""
        listing = self._make_book('portrait-no-exif.png', 'landscape-no-exif.png')
        self.handler.page_available(1)

        self.handler.replace_pages(listing[1:])
        self.assertEqual(self.handler._available_images, set())

    def test_a_number_the_book_no_longer_has_is_dropped(self):
        """The caching thread reads a page while the main one removes it.

        _get_pixbuf() stores what it read - the missing-page icon, where
        the file has gone with the page - under the number it was asked
        for, and page_available() records that number as extracted.
        Either can land after the listing has been shortened, and
        rewriting the pages then looked the stale number up in a listing
        that is now too short for it.
        """
        listing = self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        self.handler.replace_pages(listing[:1])
        # As the caching thread leaves them behind.
        self.handler._raw_pixbufs[1] = image_tools.missing_page()
        self.handler._available_images.add(1)

        self.handler.replace_pages(listing[:1])

        self.assertEqual(self.handler._image_files, listing[:1])
        self.assertEqual(set(self.handler._raw_pixbufs), set())
        self.assertEqual(self.handler._available_images, {0})

    def test_a_number_the_book_no_longer_has_is_not_a_page_that_failed(self):
        """The caching thread takes an order and then waits for the page;
        deleting a page meanwhile leaves it asking for a number past the
        end of the book.  That was logged as an error, "Could not load
        pixbuf for page 2: IndexError", for a page nobody had asked to
        see, after every deletion in the main window's tests."""
        listing = self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        self.handler._raw_pixbufs.clear()
        self.handler.replace_pages(listing[:1])
        # As page_available() leaves it when it lands after the change.
        self.handler._available_images.add(1)

        with self.assertNoLogs('mcomix', level='ERROR'):
            pixbuf = self.handler._get_pixbuf(1)

        self.assertIs(pixbuf, image_tools.missing_page())
        self.assertNotIn(1, self.handler._raw_pixbufs)

    def test_a_page_read_while_the_pages_are_rewritten_keeps_to_its_file(self):
        """The caching thread reads a page while the editor deletes one
        in front of it.

        _get_pixbuf() filed what it read under the number it had been
        asked for, in whichever cache the handler held by the time the
        read finished.  After a deletion that number belongs to the page
        behind, which then showed the page it had replaced.
        """
        listing = self._open('portrait-no-exif.png', 'landscape-no-exif.png',
                             'portrait-no-exif.png')
        load_pixbuf = image_tools.load_pixbuf
        reading = threading.Event()
        rewritten = threading.Event()

        def slow_load(path):
            reading.set()
            rewritten.wait(10)
            return load_pixbuf(path)

        with unittest.mock.patch.object(image_tools, 'load_pixbuf', slow_load):
            reader = threading.Thread(target=self.handler._get_pixbuf,
                                      args=(1,))
            reader.start()
            self.assertTrue(reading.wait(10))
            self.handler.replace_pages(listing[1:])
            rewritten.set()
            reader.join(10)
        self.assertFalse(reader.is_alive())
        # Page 2 is the third file now, which is a portrait.
        pixbuf = self.handler._get_pixbuf(1)
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height()),
                         (210, 297))

    def test_a_thumbnail_is_turned_as_its_page_is_shown(self):
        """The page is shown turned by its Exif orientation, and its
        thumbnail stood the other way round beside it."""
        self._open('landscape-exif-270-rotation.jpg')
        thumbnail = self.handler.get_thumbnail(1, 64, 64)
        self.assertGreater(thumbnail.get_width(), thumbnail.get_height())

    def test_a_thumbnail_is_left_as_stored_when_pages_are_not_turned(self):
        prefs['auto rotate from exif'] = False
        self._open('landscape-exif-270-rotation.jpg')
        thumbnail = self.handler.get_thumbnail(1, 64, 64)
        self.assertLess(thumbnail.get_width(), thumbnail.get_height())

    def test_a_cached_page_is_measured_from_the_pixbuf(self):
        self._open('portrait-no-exif.png', 'landscape-no-exif.png')
        # Whichever way round the answer is arrived at, it is the same.
        uncached = self.handler._get_displayed_size(2)
        self.handler._get_pixbuf(1)
        self.assertEqual(self.handler._get_displayed_size(2), uncached)


class CacheWindowTest(MComixTest):

    """The set of pages _ask_for_pages() picks must always contain the page
    that is on screen: it doubles as the list of pixbufs worth keeping, so a
    window that misses the current page throws it away as soon as it is
    shown."""

    def setUp(self):
        super().setUp()
        self.handler = image_handler.ImageHandler(_StubWindow())
        self.handler.set_image_files(['%02d.png' % n for n in range(1, 11)])
        for page in range(1, 11):
            self.handler.page_available(page)

    def tearDown(self):
        self.handler.cleanup()
        super().tearDown()

    def _wanted(self, cache_pages, double_page, page):
        prefs['default double page'] = double_page
        prefs['max pages to cache'] = cache_pages
        return self.handler._ask_for_pages(page)

    def test_the_budget_follows_the_preference_while_a_book_is_open(self):
        """The preferences dialog writes the new value and asks the
        handler to cache again in the same breath, so the handler has to
        read the preference then rather than when it was built."""
        prefs['default double page'] = False
        prefs['max pages to cache'] = 0
        self.assertEqual(self.handler._ask_for_pages(5), [4])
        prefs['max pages to cache'] = 7
        self.assertEqual(self.handler._ask_for_pages(5),
                         [4, 5, 3, 6, 7, 8, 9])

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


class NoPageYetTest(MComixTest):

    """What the handler answers before a page has been set.

    Nothing asks it that early on the way through the program, so this
    is about the answers being answers rather than exceptions.
    """

    def setUp(self):
        super().setUp()
        self.handler = image_handler.ImageHandler(_StubWindow())

    def tearDown(self):
        self.handler.cleanup()
        super().tearDown()

    def test_there_are_no_pages_to_show(self):
        self.assertEqual(self.handler.get_pixbufs(1), [])
        self.assertEqual(self.handler.get_pixbufs(2), [])


class BeforeAPageIsChosenTest(MComixTest):

    """What the handler answers between being given a book and being
    told which page of it is showing.

    set_image_files() and set_page() are two separate calls, so there is
    a moment where the handler knows the files but not the page.
    """

    def setUp(self):
        super().setUp()
        self.handler = image_handler.ImageHandler(_StubWindow())
        self.handler.set_image_files(['/nowhere/one.jpg', '/nowhere/two.jpg'])

    def test_there_is_no_path_to_a_page_that_was_never_chosen(self):
        """The index of the current page is None until set_page() runs,
        and it was compared against the length of the file list, which
        raised rather than answering that there is no page."""
        self.assertIsNone(self.handler.get_path_to_page())

    def test_the_page_asked_for_by_number_is_still_answered(self):
        self.assertEqual(self.handler.get_path_to_page(1), '/nowhere/one.jpg')
        self.assertEqual(self.handler.get_path_to_page(2), '/nowhere/two.jpg')
        self.assertIsNone(self.handler.get_path_to_page(3))

    def test_the_book_still_knows_how_long_it_is(self):
        self.assertEqual(self.handler.get_number_of_pages(), 2)
        self.assertEqual(self.handler.get_current_page(), 0)

    def test_nothing_is_waited_on_for_a_page_that_was_never_chosen(self):
        self.assertFalse(self.handler._wait_on_page(None, check_only=True))

# vim: expandtab:sw=4:ts=4
