"""Moving the viewport over the page."""

import math
import random

from . import MComixTest

from mcomix import constants
from mcomix.box import Box
from mcomix.scrolling import Scrolling


class ScrollingTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.scrolling = Scrolling()

    def test_an_invalid_destination_is_reported_as_one(self):
        """The complaint was built by adding the destination and the
        index straight to a string, so an invalid destination raised a
        TypeError about concatenating an int rather than a ValueError
        saying which destination was wrong."""
        with self.assertRaises(ValueError) as caught:
            self.scrolling.scroll_to_predefined(
                Box((100, 100)), Box((50, 50)), [1, 1], [99, 0])
        self.assertIn('99', str(caught.exception))

    def test_a_destination_below_the_last_one_is_invalid_too(self):
        with self.assertRaises(ValueError):
            self.scrolling.scroll_to_predefined(
                Box((100, 100)), Box((50, 50)), [1, 1],
                [constants.SCROLL_TO_END - 1, 0])

    def test_scrolling_to_the_start_goes_to_where_the_content_starts(self):
        position = self.scrolling.scroll_to_predefined(
            Box((100, 100), (10, 20)), Box((50, 50)), [1, 1],
            [constants.SCROLL_TO_START, constants.SCROLL_TO_START])
        self.assertEqual(position, [10, 20])

    def test_scrolling_to_the_end_goes_to_where_the_content_ends(self):
        position = self.scrolling.scroll_to_predefined(
            Box((100, 100), (10, 20)), Box((50, 50)), [1, 1],
            [constants.SCROLL_TO_END, constants.SCROLL_TO_END])
        self.assertEqual(position, [60, 70])

    def test_a_destination_of_zero_keeps_the_viewport_where_it_was(self):
        position = self.scrolling.scroll_to_predefined(
            Box((100, 100)), Box((50, 50), (7, 9)), [1, 1], [0, 0])
        self.assertEqual(position, [7, 9])


class SmartScrollingTest(MComixTest):

    """scroll_smartly(), which is what the space bar does.

    The pages are two dimensional, the first axis the one along a row
    and the second the one down the page.  A page that is only as wide
    as the viewport leaves the first axis nothing to do, which keeps the
    grid on the second easy to read off.
    """

    def setUp(self):
        super().setUp()
        self.scrolling = Scrolling()

    def _read(self, content, viewport, max_scroll, orientation,
              axis_map=None, start=None):
        """Every position the viewport takes reading <content> through,
        from <start> or from where <orientation> begins."""
        if start is None:
            start = [0 if direction == 1 else size - seen
                     for size, seen, direction
                     in zip(content, viewport, orientation)]
        positions = [list(start)]
        for _step in range(10000):
            step = self.scrolling.scroll_smartly(
                Box(content), Box(viewport, positions[-1]), orientation,
                max_scroll, axis_map)
            if step == []:
                return positions
            positions.append(step)
        self.fail('reading %s through %s never came to an end'
                  % (content, viewport))

    def test_a_page_is_read_along_each_row_before_going_down(self):
        self.assertEqual(
            self._read((300, 500), (200, 200), (200, 200), (1, 1)),
            [[0, 0], [100, 0], [0, 150], [100, 150], [0, 300], [100, 300]])

    def test_manga_reads_each_row_from_the_right(self):
        self.assertEqual(
            self._read((300, 500), (200, 200), (200, 200), (-1, 1)),
            [[100, 0], [0, 0], [100, 150], [0, 150], [100, 300], [0, 300]])

    def test_inverted_smart_scroll_goes_down_before_along(self):
        self.assertEqual(
            self._read((300, 500), (200, 200), (200, 200), (1, 1),
                       axis_map=(1, 0)),
            [[0, 0], [0, 150], [0, 300], [100, 0], [100, 150], [100, 300]])

    def test_the_pixels_left_over_are_spread_over_the_steps(self):
        """701 pixels to go in steps of at most 200 are four steps, and
        the one pixel that does not divide goes into one of them rather
        than into a fifth step or off the end of the page."""
        self.assertEqual(
            [position[1] for position in
             self._read((300, 1001), (300, 300), (300, 200), (1, 1))],
            [0, 175, 350, 526, 701])

    def test_a_step_from_between_two_stops_goes_to_the_next_one(self):
        """A step back can leave the viewport off the grid the next step
        on is taken along: 51 pixels down, where 101 pixels in two steps
        stop at 50 going down.  The step on goes to the stop after it,
        not past that one and off the end of a page not yet read, and a
        step back from 50 goes to the top."""
        content, viewport, max_scroll = (100, 201), (100, 100), (100, 60)
        self.assertEqual(
            self.scrolling.scroll_smartly(Box(content), Box(viewport, (0, 51)),
                                          (1, 1), max_scroll),
            [0, 101])
        self.assertEqual(
            self.scrolling.scroll_smartly(Box(content), Box(viewport, (0, 50)),
                                          (-1, -1), max_scroll),
            [0, 0])

    def test_no_part_of_a_page_is_left_unread(self):
        for content, viewport, max_scroll in (
                ((640, 2400), (500, 700), (450, 630)),
                ((1300, 1900), (800, 600), (720.5, 540.5)),
                ((333, 1000), (333, 97), (333, 13)),
                ((900, 901), (450, 900), (405, 810))):
            for orientation in ((1, 1), (-1, 1)):
                positions = self._read(content, viewport, max_scroll,
                                       orientation)
                for axis in (0, 1):
                    seen = sorted({position[axis] for position in positions})
                    self.assertEqual(
                        [seen[0], seen[-1]],
                        [0, content[axis] - viewport[axis]],
                        'the viewport did not reach both edges of %s'
                        % (content,))
                    for before, after in zip(seen, seen[1:]):
                        self.assertLessEqual(
                            after - before,
                            min(viewport[axis], math.ceil(max_scroll[axis])),
                            'a step along axis %d of %s skipped part of the '
                            'page or went further than it may'
                            % (axis, content))

    def test_reading_back_from_the_end_mirrors_reading_on_from_the_start(self):
        """Not the same stops: 101 pixels in two steps stop at 50 going
        down and at 51 coming back up."""
        content, viewport, max_scroll = (100, 201), (100, 100), (100, 60)
        down = self._read(content, viewport, max_scroll, (1, 1))
        up = self._read(content, viewport, max_scroll, (-1, -1),
                        start=down[-1])
        self.assertEqual([position[1] for position in down], [0, 50, 101])
        self.assertEqual([position[1] for position in up], [101, 51, 0])

        for content, viewport, max_scroll in (
                ((640, 2400), (500, 700), (450, 630)),
                ((1300, 1900), (800, 600), (720.5, 540.5)),
                ((333, 1000), (333, 97), (333, 13))):
            ends = [size - seen for size, seen in zip(content, viewport)]
            forwards = self._read(content, viewport, max_scroll, (1, 1))
            backwards = self._read(content, viewport, max_scroll, (-1, -1))
            self.assertEqual(
                backwards,
                [[end - value for end, value in zip(ends, position)]
                 for position in forwards])
    def test_a_viewport_just_past_the_content_starts_it_over_either_way(self):
        """A viewport wholly outside the content - just touching its edge
        - begins the content afresh on every axis.  Reading forwards
        that was so for one that ended where the content starts; reading
        backwards, one that started where the content ends kept its
        place on the other axes instead."""
        content, viewport = (100, 100), (50, 50)
        forwards = self.scrolling.scroll_smartly(
            Box(content), Box(viewport, (-50, 30)), (1, 1), (50, 50))
        backwards = self.scrolling.scroll_smartly(
            Box(content), Box(viewport, (100, 20)), (-1, -1), (50, 50))
        self.assertEqual([0, 0], forwards)
        self.assertEqual([50, 50], backwards)

    def test_every_destination_is_mirrored_by_reading_the_other_way(self):
        """Scrolling to a named place answers the mirror of itself when
        the reading direction and the destination are both turned round:
        1 and -1 name an end of the axis and change places, while the
        ones read along the direction - the two ends of the reading, and
        the middle - stay as they are.  Random pages, viewports and
        positions, from a fixed seed."""
        destinations = (0, 1, -1, constants.SCROLL_TO_CENTER,
                        constants.SCROLL_TO_START, constants.SCROLL_TO_END)
        random.seed(5)
        for _case in range(2000):
            content = [random.randint(1, 400) for _ in range(2)]
            view = [random.randint(1, 300) for _ in range(2)]
            start = [random.randint(-100, 100) for _ in range(2)]
            position = [random.randint(-450, 450) for _ in range(2)]
            destination = [random.choice(destinations) for _ in range(2)]
            content_box = Box(content, start)
            forwards = self.scrolling.scroll_to_predefined(
                content_box, Box(view, position), (1, 1), destination)
            mirrored = [2 * s + c - v - p for s, c, v, p
                        in zip(start, content, view, position)]
            backwards = self.scrolling.scroll_to_predefined(
                content_box, Box(view, mirrored), (-1, -1),
                [-d if d in (1, -1) else d for d in destination])
            self.assertEqual([2 * s + c - v - f for s, c, v, f
                              in zip(start, content, view, forwards)],
                             backwards,
                             'content %s viewport %s at %s to %s'
                             % (content, view, position, destination))


# vim: expandtab:sw=4:ts=4
