"""Where the two pages of a spread go when the spread is turned or flipped.

draw_image() turns a spread of two pages as one: a quarter turn stacks
them, and which one goes on top depends on the direction of the turn,
on the reading direction, and on the flips.  None of the quarter-turn
branch ran in a test.  What must hold is that the pages are arranged
the way the transform each of them is drawn with would carry the whole
spread: the step from the first page to the second, turned by that
same transform, is the step they are laid out along.
"""

import itertools
import os

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.preferences import prefs


class SpreadRotationTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        prefs['default double page'] = True
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        # A portrait page, followed by one that is not wide either, so
        # the two are shown together.
        self.window.filehandler.open_file(
            get_testfile_path('images', 'portrait-no-exif.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 1))
        self.window.actiongroup.get_action('double_page').set_active(True)
        pump()
        self.assertEqual(2, self.window.displayed_page_count())

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    @staticmethod
    def _sign(value):
        return (value > 0) - (value < 0)

    def _step(self):
        """Which way the second page lies from the first, per axis."""
        first, second = (
            [position + size / 2 for position, size in
             zip(content.get_position(), content.get_size())]
            for content in self.window.layout.get_content_boxes())
        return tuple(self._sign(b - a) for a, b in zip(first, second))

    def test_the_pages_go_where_the_transform_carries_the_spread(self):
        for manga, rotation, horizontal, vertical in itertools.product(
                (False, True), (0, 90, 180, 270), (False, True),
                (False, True)):
            with self.subTest(manga=manga, rotation=rotation,
                              horizontal_flip=horizontal,
                              vertical_flip=vertical):
                self.window.actiongroup.get_action('manga_mode').set_active(
                    manga)
                prefs['rotation'] = rotation
                prefs['horizontal flip'] = horizontal
                prefs['vertical flip'] = vertical
                self.window.draw_image()
                pump()
                transforms = self.window.transforms[:2]
                self.assertEqual(transforms[0], transforms[1])
                # Unturned, the second page is to the right of the first,
                # or to its left in manga mode.
                x, y = (-1 if manga else 1), 0
                m1, m2, m3, m4 = transforms[0].m
                self.assertEqual((self._sign(m1 * x + m2 * y),
                                  self._sign(m3 * x + m4 * y)),
                                 self._step())
