"""The background colour read off the pages on screen."""

import os
import unittest.mock

from PIL import Image

from . import MComixTest, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import image_tools
from mcomix import main
from mcomix.preferences import prefs


RED = (200, 0, 0)
BLUE = (0, 0, 200)


class DynamicBackgroundTest(MComixTest):

    """A page with red sides and a blue top and bottom, read with the
    dynamic background colour on."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['smart bg'] = True
        icons.load_icons()
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
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.window.filehandler.open_file(os.path.join(book, '1.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.page_is_available()))
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

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
        with unittest.mock.patch.object(
                image_tools, 'enhance',
                side_effect=image_tools.enhance) as enhance:
            # The redraw itself rather than the main loop, which would
            # also run the thumbnail sidebar enhancing its thumbnails.
            self.window._draw_image()
        self.assertEqual(1, enhance.call_count)
