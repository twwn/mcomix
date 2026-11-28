"""The histogram the enhance dialog draws beside its sliders."""

import math

import PIL.Image as Image

from . import MComixTest, pixel

from mcomix import histogram
from mcomix import image_tools


#: What the graph shows where no bar is.
BACKGROUND = (30, 30, 30)


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
            image_tools.pil_to_pixbuf(page), height=self.HEIGHT)
        self.tall = int(90 * (self.HEIGHT - 6) / 90)
        self.short = int(10 * (self.HEIGHT - 6) / 90)

    def _at(self, column, y):
        """The pixel <y> up graph column <column>."""
        return pixel(self.drawn, column + 2, self.HEIGHT - 5 - y + 2)

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

    def _column(self, column, drawn=None):
        """Graph column <column>, from the bottom up to the top."""
        drawn = drawn or self.drawn
        return [pixel(drawn, column + 2, self.HEIGHT - 3 - y)
                for y in range(self.HEIGHT - 4)]

    def _runs(self, *runs):
        """A column of <runs>, each a colour and how many pixels high,
        the background above them."""
        column = [colour for colour, count in runs for _ in range(count)]
        return column + [BACKGROUND] * (self.HEIGHT - 4 - len(column))

    def test_each_column_from_the_bottom_up(self):
        """The bottom row stays background; a bar fills from the row
        above it, and its outline covers the filling where it runs."""
        grey, white = (170, 170, 170), (255, 255, 255)
        # Nothing at 8; 9 rises to the full height, 10 holds it and
        # falls at 11, which falls to nothing at 12.
        expected = {
            9: self._runs((BACKGROUND, 1)),
            10: self._runs((BACKGROUND, 1), (white, self.tall)),
            11: self._runs((BACKGROUND, 1), (grey, self.short),
                           (white, self.tall - self.short)),
            12: self._runs((BACKGROUND, 1), (white, self.short)),
            13: self._runs((BACKGROUND, 1)),
        }
        self.assertEqual(expected, {column: self._column(column)
                                    for column in expected})

    def test_the_frame_is_grey_inside_black(self):
        width = self.drawn.get_width()
        for x, y in ((0, 0), (width - 1, self.HEIGHT - 1), (5, 0)):
            self.assertEqual((0, 0, 0), pixel(self.drawn, x, y))
        for x, y in ((1, 1), (width - 2, self.HEIGHT - 2), (1, 5)):
            self.assertEqual((80, 80, 80), pixel(self.drawn, x, y))

    def test_the_defaults_are_170_high_and_linear(self):
        page = image_tools.pil_to_pixbuf(self._page({9: 90, 11: 10}))
        self.assertEqual(
            histogram.draw_histogram(page, height=170,
                                     logarithmic=False).get_pixels(),
            histogram.draw_histogram(page).get_pixels())

    def _page(self, counts):
        """A grey page of <counts> pixels by their value."""
        page = Image.new('RGB', (sum(counts.values()), 1))
        page.putdata([(value,) * 3 for value, count in counts.items()
                      for _ in range(count)])
        return page

    def test_a_page_of_one_pixel_fills_the_height(self):
        page = image_tools.pil_to_pixbuf(self._page({0: 1}))
        drawn = histogram.draw_histogram(page, height=self.HEIGHT)
        self.assertEqual(self._runs((BACKGROUND, 1),
                                    ((255, 255, 255), self.tall)),
                         self._column(1, drawn))

    def test_logarithmic_counts_raise_the_short_bars(self):
        page = image_tools.pil_to_pixbuf(self._page({9: 90, 11: 10}))
        drawn = histogram.draw_histogram(page, height=self.HEIGHT,
                                         logarithmic=True)
        short = int(math.log1p(10) * (self.HEIGHT - 6) / math.log1p(90))
        self.assertEqual(self._runs((BACKGROUND, 1),
                                    ((255, 255, 255), short)),
                         self._column(12, drawn))


class ChannelsTest(MComixTest):

    """At 5, 6 and 7, 90 pixels of red, 60 of green and 30 of blue;
    the rest of the 90 pixels of green and blue lie far off."""

    HEIGHT = 170

    def test_each_channel_fills_up_to_its_own_height(self):
        page = Image.new('RGB', (270, 1))
        page.putdata([(v, v, v) for v in (5, 6, 7) for _ in range(30)]
                     + [(v, v, 200) for v in (5, 6, 7) for _ in range(30)]
                     + [(v, 201, 202) for v in (5, 6, 7) for _ in range(30)])
        drawn = histogram.draw_histogram(image_tools.pil_to_pixbuf(page),
                                         height=self.HEIGHT)
        red, green, blue = (int(count * (self.HEIGHT - 6) / 90)
                            for count in (90, 60, 30))
        # Value 6, between a rise and a fall: its filling, and the one
        # pixel at the top of each channel's bar its outline.
        column = [pixel(drawn, 6 + 1 + 2, self.HEIGHT - 3 - y)
                  for y in range(1, red + 2)]
        expected = ([(170, 170, 170)] * (blue - 1) + [(170, 170, 255)]
                    + [(170, 170, 0)] * (green - blue - 1) + [(170, 255, 0)]
                    + [(170, 0, 0)] * (red - green - 1) + [(255, 0, 0)]
                    + [BACKGROUND])
        self.assertEqual(expected, column)

    def test_a_channel_with_none_and_one_a_pixel_high(self):
        """At 19, 20 and 21, no red, 90 pixels of green and 1 of blue,
        whose bar is one pixel high; the red and the rest of the blue
        lie far off."""
        page = Image.new('RGB', (270, 1))
        page.putdata([(100 + v, v, 50 + v) for v in (19, 20, 21)
                      for _ in range(89)]
                     + [(100 + v, v, v) for v in (19, 20, 21)])
        drawn = histogram.draw_histogram(image_tools.pil_to_pixbuf(page),
                                         height=self.HEIGHT)
        green = self.HEIGHT - 6
        column = [pixel(drawn, 20 + 1 + 2, self.HEIGHT - 3 - y)
                  for y in range(1, green + 2)]
        expected = ([(0, 170, 255)] + [(0, 170, 0)] * (green - 2)
                    + [(0, 255, 0)] + [BACKGROUND])
        self.assertEqual(expected, column)

    def test_the_last_value_does_not_wrap_round_to_the_first(self):
        """The column left of the bar for 0 stays empty, though 255 is
        all the page holds."""
        page = Image.new('RGB', (1, 1), (255, 255, 255))
        drawn = histogram.draw_histogram(image_tools.pil_to_pixbuf(page),
                                         height=self.HEIGHT)
        self.assertEqual({BACKGROUND},
                         {pixel(drawn, 2, y)
                          for y in range(2, self.HEIGHT - 2)})
