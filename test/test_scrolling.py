# -*- coding: utf-8 -*-

"""Moving the viewport over the page."""

from . import MComixTest

from mcomix import constants
from mcomix.box import Box
from mcomix.scrolling import Scrolling


class ScrollingTest(MComixTest):

    def setUp(self):
        super(ScrollingTest, self).setUp()
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

# vim: expandtab:sw=4:ts=4
