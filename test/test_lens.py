""" The magnifying lens, which draws a scaled patch of the page.

The lens was the last part of the viewer with no tests at all, and its
arithmetic is where a rotated or flipped page goes wrong quietly: what
it draws is a cursor, so nothing raises when it draws the wrong thing.
"""

import hashlib
import os

from gi.repository import GdkPixbuf

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import image_tools
from mcomix import main
from mcomix.lens import MagnifyingLens


def _source(has_alpha):
    """A small page to magnify, asymmetric in both axes so that a flip
    or a rotation shows up in what is drawn."""
    name = 'pattern-transparent-rgba.png' if has_alpha else 'pattern.jpg'
    page = GdkPixbuf.Pixbuf.new_from_file(get_testfile_path('images', name))
    return page.scale_simple(40, 30, GdkPixbuf.InterpType.NEAREST)


class LensDrawingTest(MComixTest):

    """What _draw_lens_pixbuf() puts in the lens.

    It reads nothing off the window, so it can be exercised without one.
    """

    LENS_SIZE = (64, 64)

    def setUp(self):
        super().setUp()
        self.lens = MagnifyingLens.__new__(MagnifyingLens)

    def _drawn(self, rotation, flips, has_alpha):
        """The lens over a page turned by <rotation> and flipped by
        <flips>, as its pixels."""
        target = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                      *self.LENS_SIZE)
        target.fill(0x00000000)
        self.lens._draw_lens_pixbuf(
            (20, 15), (200, 150), _source(has_alpha), rotation, flips,
            self.LENS_SIZE, (2, 2), target, GdkPixbuf.InterpType.NEAREST,
            image_tools.get_composite_color_args(0) if has_alpha else None,
            (0, 0))
        return target.get_pixels()

    def test_every_rotation_and_flip_draws_something(self):
        for rotation in (0, 90, 180, 270):
            for flips in ((False, False), (True, False),
                          (False, True), (True, True)):
                for has_alpha in (False, True):
                    with self.subTest(rotation=rotation, flips=flips,
                                      has_alpha=has_alpha):
                        drawn = self._drawn(rotation, flips, has_alpha)
                        self.assertNotEqual(
                            b'\x00' * len(drawn), drawn,
                            'the lens was left empty')

    def test_a_flip_changes_what_is_drawn(self):
        # The horizontal flip is the one the rotated branch reaches
        # through its own axis remapping.
        plain = self._drawn(0, (False, False), False)
        self.assertNotEqual(plain, self._drawn(0, (True, False), False))
        self.assertNotEqual(plain, self._drawn(0, (False, True), False))

    def test_a_rotation_changes_what_is_drawn(self):
        plain = self._drawn(0, (False, False), False)
        for rotation in (90, 180, 270):
            self.assertNotEqual(plain, self._drawn(rotation, (False, False), False),
                                'rotating by %d changed nothing' % rotation)

    def test_a_page_of_no_size_is_not_drawn(self):
        target = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                      *self.LENS_SIZE)
        target.fill(0x00000000)
        self.lens._draw_lens_pixbuf(
            (0, 0), (0, 0), _source(False), 0, (False, False),
            self.LENS_SIZE, (2, 2), target, GdkPixbuf.InterpType.NEAREST,
            None, (0, 0))
        self.assertEqual(b'\x00' * len(target.get_pixels()), target.get_pixels())

    def test_the_pixels_drawn_are_the_ones_that_were_drawn_before(self):
        """A fingerprint of all thirty-two combinations.

        The calls into GdkPixbuf take their destination rectangle as
        loose arguments, so an argument counted wrong lands the patch in
        the wrong place rather than raising.
        """
        digest = hashlib.sha256()
        for rotation in (0, 90, 180, 270):
            for flips in ((False, False), (True, False),
                          (False, True), (True, True)):
                for has_alpha in (False, True):
                    digest.update(self._drawn(rotation, flips, has_alpha))
        self.assertEqual('322586bbb8b2ef4fec95b6c694f4765c'
                         '85eff384d89e0c05e862d13d9e4dadcf',
                         digest.hexdigest())

class LensCursorTest(MComixTest):

    """Whether the pointer is hidden while the lens is on.

    The lens draws a cursor, so it hides the real one; with no file
    open it draws nothing, and hiding the pointer over an empty window
    leaves it invisible with nothing to show for it.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _open_a_file(self):
        self.window.filehandler.open_file(
            get_testfile_path('archives', '01-ZIP-Normal.zip'))
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)
        pump()

    @property
    def _cursor(self):
        return self.window.cursor_handler._current_cursor

    def test_switching_the_lens_on_with_no_file_leaves_the_cursor(self):
        self.window.lens.enabled = True
        self.assertEqual(constants.NORMAL_CURSOR, self._cursor)

    def test_opening_a_file_with_the_lens_on_hides_the_cursor(self):
        self.window.lens.enabled = True
        self._open_a_file()
        self.assertEqual(constants.NO_CURSOR, self._cursor)

    def test_switching_it_on_over_a_file_hides_the_cursor(self):
        self._open_a_file()
        self.window.lens.enabled = True
        self.assertEqual(constants.NO_CURSOR, self._cursor)

    def test_closing_the_file_under_the_lens_puts_the_cursor_back(self):
        self._open_a_file()
        self.window.lens.enabled = True
        self.window.filehandler.close_file()
        pump()
        self.assertEqual(constants.NORMAL_CURSOR, self._cursor)

    def test_switching_it_off_puts_the_cursor_back(self):
        self._open_a_file()
        self.window.lens.enabled = True
        self.window.lens.enabled = False
        self.assertEqual(constants.NORMAL_CURSOR, self._cursor)


# vim: expandtab:sw=4:ts=4
