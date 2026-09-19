"""FiniteLayout, which places the pages being shown and scales them."""

import unittest

from mcomix import constants
from mcomix import layout


class GapTest(unittest.TestCase):

    """The space between two pages is taken out of the window before the
    pages are scaled to it, and left between them where they are placed."""

    VIEWPORT = (745, 384)

    def _layout(self, gap):
        """A two-page spread laid out with <gap>, and every size the pages
        were asked to fit."""
        asked = []

        def sizes_update(zoom_dummy_size):
            asked.append(list(zoom_dummy_size))
            return [[200, 300], [200, 300]], [False, False]

        result = layout.FiniteLayout.create_finite_layout(
            2, constants.WESTERN_ORIENTATION, gap,
            constants.DISTRIBUTION_AXIS, constants.ALIGNMENT_AXIS,
            lambda requests: None, lambda: self.VIEWPORT, sizes_update)
        return result, asked

    def test_the_gap_is_taken_out_of_the_width_the_pages_fit(self):
        for gap in (0, 2, 100):
            with self.subTest(gap=gap):
                _result, asked = self._layout(gap)
                self.assertEqual([self.VIEWPORT[0] - gap, self.VIEWPORT[1]],
                                 asked[-1])

    def test_the_pages_are_placed_the_gap_apart(self):
        for gap in (0, 2, 100):
            with self.subTest(gap=gap):
                result, _asked = self._layout(gap)
                first, second = result.get_content_boxes()
                self.assertEqual(
                    first.get_position()[0] + first.get_size()[0] + gap,
                    second.get_position()[0])

    def test_a_gap_as_wide_as_the_window_leaves_the_pages_no_room(self):
        """Why the preferences dialog bounds the gap."""
        _result, asked = self._layout(self.VIEWPORT[0])
        self.assertEqual(1, asked[-1][0])

# vim: expandtab:sw=4:ts=4


class SmartScrollTest(unittest.TestCase):

    """The space bar's step through two tall pages side by side, in a
    window a third of a page high and one page wide."""

    def _layout(self, wrap_individually):
        result = layout.FiniteLayout(
            [[100, 300], [100, 300]], [False, False], (100, 100),
            constants.WESTERN_ORIENTATION, 0, wrap_individually,
            constants.DISTRIBUTION_AXIS, constants.ALIGNMENT_AXIS)
        result.scroll_to_predefined((-1, -1), 0)
        return result

    def _steps(self, result, count, backwards=False):
        steps = []
        for _ in range(count):
            index = result.scroll_smartly([100, 100], backwards,
                                          constants.NORMAL_AXES)
            steps.append((index,
                          tuple(result.get_viewport_box().get_position())))
        return steps

    def test_each_page_is_read_down_then_the_next_from_its_top(self):
        result = self._layout(True)
        self.assertEqual([(0, (0, 100)), (0, (0, 200)),
                          (1, (100, 0)), (1, (100, 100)), (1, (100, 200)),
                          (2, (100, 200))],
                         self._steps(result, 6))

    def test_backwards_a_page_is_arrived_at_from_its_bottom(self):
        result = self._layout(True)
        self._steps(result, 5)
        self.assertEqual([(1, (100, 100)), (1, (100, 0)),
                          (0, (0, 200)), (0, (0, 100)), (0, (0, 0)),
                          (-1, (0, 0))],
                         self._steps(result, 6, backwards=True))

    def test_a_spread_is_read_across_both_pages_a_row_at_a_time(self):
        """The answer is the page the window has reached, which for a
        spread was the one it had left."""
        result = self._layout(False)
        self.assertEqual([(1, (100, 0)), (0, (0, 100)), (1, (100, 100)),
                          (0, (0, 200)), (1, (100, 200)), (2, (100, 200))],
                         self._steps(result, 6))
