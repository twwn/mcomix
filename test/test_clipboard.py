""" Copying the open page to the system clipboard.

What the clipboard gets is the page as the view draws it, so the tests
here are about the transformations the view applies: a turned page is
copied turned, a flipped one flipped, and a two-page spread is joined
along the axis the view lays it out on, in the order it shows it.
"""

from types import SimpleNamespace

from gi.repository import GdkPixbuf

from . import MComixTest

from mcomix import box
from mcomix import constants
from mcomix.clipboard import Clipboard
from mcomix.transform import Transform


def _solid(width, height, colour):
    """A page of one colour, as Pixbuf.fill() takes it."""
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8,
                                  width, height)
    pixbuf.fill(colour)
    return pixbuf


def _corners(width, height):
    """A page with a different colour in each quadrant.

    Turning or flipping it moves the colours about, which is what makes
    either of them visible in a single pixel.
    """
    pixbuf = _solid(width, height, 0x000000FF)
    for x, y, colour in ((0, 0, 0xFF0000FF), (width // 2, 0, 0x00FF00FF),
                         (0, height // 2, 0x0000FFFF),
                         (width // 2, height // 2, 0xFFFF00FF)):
        quadrant = _solid(width // 2, height // 2, colour)
        quadrant.copy_area(0, 0, width // 2, height // 2, pixbuf, x, y)
    return pixbuf


def _pixel(pixbuf, x, y):
    channels = pixbuf.get_n_channels()
    offset = y * pixbuf.get_rowstride() + x * channels
    return tuple(pixbuf.get_pixels()[offset:offset + channels])


class ClipboardTest(MComixTest):

    """copy_page() over a stubbed window.

    Everything it reads off the window is a plain attribute or a one-line
    call, so a stub is enough and spares the tests a real book.
    """

    RED, GREEN = 0xFF0000FF, 0x00FF00FF

    def setUp(self):
        super().setUp()
        self.clipboard = Clipboard.__new__(Clipboard)
        self.copied = None
        self.clipboard.copy = self._capture

    def _capture(self, text, pixbuf):
        self.copied = (text, pixbuf)

    def _window(self, pixbufs, transforms=None, boxes=None,
                is_manga_mode=False, path='/books/page.png',
                file_loaded=True):
        """A stub window showing <pixbufs>.

        <boxes> defaults to the pages side by side at their own sizes,
        which is what an untransformed view lays out.
        """
        if boxes is None:
            boxes = []
            offset = 0
            for pixbuf in pixbufs:
                size = (pixbuf.get_width(), pixbuf.get_height())
                boxes.append(box.Box(size, (offset, 0)))
                offset += size[0]
        return SimpleNamespace(
            filehandler=SimpleNamespace(file_loaded=file_loaded),
            imagehandler=SimpleNamespace(
                get_pixbufs=lambda count: list(pixbufs[:count]),
                get_path_to_page=lambda: path),
            displayed_page_count=lambda: len(pixbufs),
            transforms=[] if transforms is None else list(transforms),
            layout=SimpleNamespace(get_content_boxes=lambda: boxes),
            is_manga_mode=is_manga_mode)

    def _copied(self, *args, **kwargs):
        self.clipboard._window = self._window(*args, **kwargs)
        self.clipboard.copy_page()
        return self.copied

    def test_a_page_with_nothing_done_to_it_is_copied_as_it_is(self):
        page = _corners(8, 6)
        text, pixbuf = self._copied([page], [Transform.ID])
        self.assertEqual('/books/page.png', text)
        self.assertEqual((8, 6), (pixbuf.get_width(), pixbuf.get_height()))
        self.assertEqual((255, 0, 0), _pixel(pixbuf, 1, 1))

    def test_a_turned_page_is_copied_turned(self):
        """The view turns a page for the Exif orientation, for the page's
        own proportions and for the reader asking; all three arrive here
        as one rotation in the transform."""
        page = _corners(8, 6)
        _text, pixbuf = self._copied(
            [page], [Transform.from_rotation(90)])
        self.assertEqual((6, 8), (pixbuf.get_width(), pixbuf.get_height()),
                         'a quarter turn did not swap the axes')
        # The top left quadrant is red before the turn and blue after it.
        self.assertEqual((0, 0, 255), _pixel(pixbuf, 1, 1))

    def test_a_flipped_page_is_copied_flipped(self):
        page = _corners(8, 6)
        for flips, expected in (((True, False), (0, 255, 0)),
                                ((False, True), (0, 0, 255))):
            with self.subTest(flips=flips):
                _text, pixbuf = self._copied(
                    [page], [Transform.from_flips(*flips)])
                self.assertEqual((8, 6),
                                 (pixbuf.get_width(), pixbuf.get_height()))
                self.assertEqual(expected, _pixel(pixbuf, 1, 1))

    def test_a_page_the_view_has_not_drawn_yet_is_copied_untouched(self):
        """Nothing has been drawn before the first draw, so the window
        carries no transform to read; the page is what it is."""
        page = _corners(8, 6)
        _text, pixbuf = self._copied([page])
        self.assertEqual((8, 6), (pixbuf.get_width(), pixbuf.get_height()))
        self.assertEqual((255, 0, 0), _pixel(pixbuf, 1, 1))

    def test_a_spread_is_copied_in_the_order_it_is_laid_out(self):
        pages = [_solid(4, 6, self.RED), _solid(4, 6, self.GREEN)]
        _text, pixbuf = self._copied(pages, [Transform.ID] * 2)
        self.assertEqual((8, 6), (pixbuf.get_width(), pixbuf.get_height()))
        self.assertEqual((255, 0, 0), _pixel(pixbuf, 1, 1))
        self.assertEqual((0, 255, 0), _pixel(pixbuf, 5, 1))

    def test_a_manga_spread_puts_the_first_page_on_the_right(self):
        """The layout says so: it has already put the second page at the
        left edge."""
        pages = [_solid(4, 6, self.RED), _solid(4, 6, self.GREEN)]
        _text, pixbuf = self._copied(
            pages, [Transform.ID] * 2,
            boxes=[box.Box((4, 6), (4, 0)), box.Box((4, 6), (0, 0))],
            is_manga_mode=True)
        self.assertEqual((0, 255, 0), _pixel(pixbuf, 1, 1))
        self.assertEqual((255, 0, 0), _pixel(pixbuf, 5, 1))

    def test_a_turned_spread_is_copied_stacked(self):
        """A quarter turn distributes the pages on the height instead, so
        the copy stacks them rather than setting them side by side."""
        pages = [_corners(8, 6), _corners(8, 6)]
        _text, pixbuf = self._copied(
            pages, [Transform.from_rotation(90)] * 2,
            boxes=[box.Box((6, 8), (0, 0)), box.Box((6, 8), (0, 8))])
        self.assertEqual((6, 16), (pixbuf.get_width(), pixbuf.get_height()))
        self.assertEqual((0, 0, 255), _pixel(pixbuf, 1, 1))
        self.assertEqual((0, 0, 255), _pixel(pixbuf, 1, 9))

    def test_a_spread_with_no_layout_yet_falls_back_on_reading_order(self):
        """The window starts on a one-page dummy layout, which says
        nothing about where two pages would go."""
        pages = [_solid(4, 6, self.RED), _solid(4, 6, self.GREEN)]
        dummy = [box.Box((1, 1), (0, 0))]
        for manga, left in ((False, (255, 0, 0)), (True, (0, 255, 0))):
            with self.subTest(is_manga_mode=manga):
                _text, pixbuf = self._copied(pages, boxes=dummy,
                                             is_manga_mode=manga)
                self.assertEqual(left, _pixel(pixbuf, 1, 1))

    def test_two_pages_drawn_at_the_same_place_go_side_by_side(self):
        """A window with no size in it lays both boxes out at the origin,
        and neither axis is then the one they are distributed on."""
        pages = [_solid(4, 6, self.RED), _solid(4, 6, self.GREEN)]
        _text, pixbuf = self._copied(
            pages, [Transform.ID] * 2,
            boxes=[box.Box((0, 0), (0, 0)), box.Box((0, 0), (0, 0))])
        self.assertEqual((8, 6), (pixbuf.get_width(), pixbuf.get_height()))

    def test_a_page_with_no_file_behind_it_copies_an_empty_path(self):
        _text, _pixbuf = self._copied([_solid(4, 6, self.RED)],
                                      [Transform.ID], path=None)
        self.assertEqual('', self.copied[0])

    def test_nothing_is_copied_with_no_file_open(self):
        self.clipboard._window = self._window(
            [_solid(4, 6, self.RED)], file_loaded=False)
        self.clipboard.copy_page()
        self.assertIsNone(self.copied)

    def test_the_distribution_axis_is_the_one_the_boxes_differ_on(self):
        self.assertEqual(
            constants.PageAxis.WIDTH,
            Clipboard._distribution_axis(
                [box.Box((4, 6), (0, 0)), box.Box((4, 6), (4, 0))]))
        self.assertEqual(
            constants.PageAxis.HEIGHT,
            Clipboard._distribution_axis(
                [box.Box((4, 6), (0, 0)), box.Box((4, 6), (0, 6))]))

# vim: expandtab:sw=4:ts=4
