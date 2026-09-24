"""The histogram the enhance dialog draws beside its sliders."""

import PIL.Image as Image

from . import MComixTest

from mcomix import histogram
from mcomix import image_tools


class HistogramTest(MComixTest):

    """A grey page of 190 pixels: 90 at 9, 90 at 10 and 10 at 11, the
    same in red, green and blue.

    The tallest bars are those at 9 and 10, so each pixel counts
    (170 - 6) / 90 of the graph's height: they are 164 high and the
    bars at 11 are 18.  The graph sits inside a border two pixels wide;
    the bar for value x fills column x + 1 of the graph, and the outline
    of a fall from x - 1 to x is drawn in that same column.
    """

    HEIGHT = 170

    def setUp(self):
        super().setUp()
        page = Image.new('RGB', (190, 1))
        page.putdata([(9, 9, 9)] * 90 + [(10, 10, 10)] * 90
                     + [(11, 11, 11)] * 10)
        self.drawn = histogram.draw_histogram(
            image_tools.pil_to_pixbuf(page), height=self.HEIGHT, text=False)
        self.tall = int(90 * (self.HEIGHT - 6) / 90)
        self.short = int(10 * (self.HEIGHT - 6) / 90)

    def _at(self, column, y):
        """The pixel <y> up graph column <column>."""
        x, row = column + 2, self.HEIGHT - 5 - y + 2
        offset = row * self.drawn.get_rowstride() + x * 3
        return tuple(self.drawn.get_pixels()[offset:offset + 3])

    def test_it_is_262_wide_and_as_high_as_asked(self):
        self.assertEqual((262, self.HEIGHT),
                         (self.drawn.get_width(), self.drawn.get_height()))

    def test_a_bar_that_rises_is_outlined_up_the_rise(self):
        # Each rises from nothing at 8 to its full height at 9, in
        # column 10: the outline runs all the way up.
        self.assertEqual((255, 255, 255), self._at(10, self.tall // 2))
        self.assertEqual((255, 255, 255), self._at(10, self.tall))

    def test_a_bar_that_falls_is_outlined_down_the_fall(self):
        """Each holds from 9 to 10 and falls at 11: the fall is outlined
        down column 11, over the filling of 10's bar, between the two
        heights and not below."""
        middle = (self.tall + self.short) // 2
        self.assertEqual((255, 255, 255), self._at(11, middle))
        self.assertEqual((170, 170, 170), self._at(11, self.short // 2))
