"""Hyperrectangles, which the page layout is worked out in."""

from . import MComixTest

from mcomix.box import Box


class BoxTest(MComixTest):

    def test_two_boxes_of_the_same_shape_are_equal(self):
        self.assertEqual(Box((2, 3), (4, 5)), Box((2, 3), (4, 5)))
        self.assertNotEqual(Box((2, 3), (4, 5)), Box((2, 3), (4, 6)))
        self.assertNotEqual(Box((2, 3), (4, 5)), Box((2, 9), (4, 5)))

    def test_a_box_is_unequal_to_what_is_not_a_box_rather_than_raising(self):
        """Comparing a Box to anything else read a position off whatever
        it was handed, so a Box could not be compared to an int, to None
        or to the tuple of its own size without raising."""
        box = Box((2, 3), (4, 5))
        self.assertNotEqual(box, 5)
        self.assertNotEqual(box, None)
        self.assertNotEqual(box, 'a box')
        self.assertNotEqual(box, (2, 3))
        self.assertNotIn(box, [1, 'two', None])

    def test_the_bounding_box_covers_every_box_it_was_given(self):
        boxes = [Box((2, 2), (0, 0)), Box((3, 1), (5, 4)), Box((1, 1), (-2, 7))]
        bounds = Box.bounding_box(boxes)
        self.assertEqual(bounds.get_position(), (-2, 0))
        self.assertEqual(bounds.get_size(), (10, 8))

    def test_the_bounding_box_of_nothing_has_no_dimensions(self):
        self.assertEqual(Box.bounding_box([]).get_size(), ())

    def test_distributing_boxes_leaves_the_fixed_one_where_it_was(self):
        boxes = [Box((2, 5), (0, 0)), Box((3, 5), (0, 0)), Box((4, 5), (0, 0))]
        spread = Box.distribute(boxes, 0, 1, spacing=1)
        self.assertEqual([box.get_position()[0] for box in spread],
                         [-3, 0, 4])
        # The other axis is left alone, and the sizes with it.
        self.assertEqual([box.get_position()[1] for box in spread], [0, 0, 0])
        self.assertEqual([box.get_size() for box in spread],
                         [(2, 5), (3, 5), (4, 5)])

    def test_distributing_nothing_gives_nothing(self):
        self.assertEqual(Box.distribute([], 0, 0), [])

# vim: expandtab:sw=4:ts=4
