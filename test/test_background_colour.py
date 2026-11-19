"""The background colour read off the pages on screen."""

import os
import threading
import unittest.mock

from PIL import Image

from . import MainWindowLaterTest, pump, wait_for

from mcomix import image_tools
from mcomix.preferences import prefs


RED = (200, 0, 0)
BLUE = (0, 0, 200)


class DynamicBackgroundTest(MainWindowLaterTest):

    """A page with red sides and a blue top and bottom, read with the
    dynamic background colour on."""

    def setUp(self):
        super().setUp()
        prefs['smart bg'] = True
        book = os.path.join(self.tmp_dir, 'book')
        os.makedirs(book)
        page = Image.new('RGB', (60, 90), (255, 255, 255))
        for x in range(60):
            for y in range(90):
                if y < 4 or y >= 86:
                    page.putpixel((x, y), BLUE)
                elif x < 4 or x >= 56:
                    page.putpixel((x, y), RED)
        for name in ('1.png', '2.png'):
            page.save(os.path.join(book, name))
        self.open_main_window()
        self.window.filehandler.open_file(os.path.join(book, '1.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.page_is_available()))
        pump()

    def _colour(self):
        self.window.draw_image()
        pump()
        return tuple(round(component * 255)
                     for component in self.window.get_bg_colour()[:3])

    def test_the_colour_is_that_of_the_sides_of_the_page(self):
        self.assertEqual(RED, self._colour())

    def test_a_page_turned_on_its_side_is_read_at_its_sides_on_screen(self):
        """The colour was read down the left and right of the page as
        it is in the file, which a quarter turn puts at the top and the
        bottom of the screen."""
        prefs['rotation'] = 90
        self.assertEqual(BLUE, self._colour())

    def test_an_enhanced_page_is_enhanced_once_for_the_colour_too(self):
        """The colour was read off a second enhancement of the whole
        page at the size it is in the file, made for nothing else: 20
        to 70 ms a page turn for a 2000 by 3000 scan."""
        self.window.enhancer.brightness = 1.1
        pump()
        enhance = image_tools.enhance
        # The thumbnail sidebar enhances its thumbnails too, on worker
        # threads that may be at it while the page is drawn: only the
        # redraw's own calls, on this thread, are counted.
        here = threading.get_ident()
        calls = []

        def counted(*args, **kwargs):
            if threading.get_ident() == here:
                calls.append(args)
            return enhance(*args, **kwargs)

        with unittest.mock.patch.object(image_tools, 'enhance', counted):
            # The redraw itself rather than the main loop, which would
            # also run the sidebar's idle callbacks.
            self.window._draw_image()
        self.assertEqual(1, len(calls))


class DoublePageBackgroundTest(MainWindowLaterTest):

    """Two pages side by side: the colour is read down the outer sides,
    the left of the left page and the right of the right one, which
    are what meets the background."""

    GREEN = (0, 200, 0)
    MANGA = False

    def setUp(self):
        super().setUp()
        prefs['smart bg'] = True
        prefs['default double page'] = True
        prefs['default manga mode'] = self.MANGA
        book = os.path.join(self.tmp_dir, 'book')
        os.makedirs(book)
        # The first page green on its left and red on its right, the
        # second the other way round: green outside, red in the middle.
        for name, left, right in (('1.png', self.GREEN, RED),
                                  ('2.png', RED, self.GREEN)):
            page = Image.new('RGB', (60, 90), (255, 255, 255))
            for x in range(60):
                for y in range(90):
                    if x < 4:
                        page.putpixel((x, y), left)
                    elif x >= 56:
                        page.putpixel((x, y), right)
            page.save(os.path.join(book, name))
        self.open_main_window()
        self.window.filehandler.open_file(os.path.join(book, '1.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.page_is_available(1)
            and self.window.imagehandler.page_is_available(2)))
        pump()

    def test_the_colour_is_that_of_the_outer_sides(self):
        self.window.draw_image()
        pump()
        self.assertTrue(self.window.displayed_double())
        self.assertEqual(self.GREEN, tuple(
            round(component * 255)
            for component in self.window.get_bg_colour()[:3]))


class MangaDoublePageBackgroundTest(DoublePageBackgroundTest):

    """In manga mode the first page is on the right: the outer sides
    are then the second page's left and the first page's right, both
    red, and the sides read are those on screen, not those of the
    first and the second page."""

    MANGA = True

    def test_the_colour_is_that_of_the_outer_sides(self):
        self.window.draw_image()
        pump()
        self.assertTrue(self.window.is_manga_mode)
        self.assertEqual(RED, tuple(
            round(component * 255)
            for component in self.window.get_bg_colour()[:3]))
