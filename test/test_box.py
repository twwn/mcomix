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

    def test_the_distance_to_a_point_is_to_the_nearest_pixel_of_the_box(self):
        """Squared, and none from inside; the box at (2, 2) covers 2 to
        11 on each axis, its end not included."""
        box = Box((10, 10), (2, 2))
        for point, distance in (((5, 5), 0), ((-1, 5), 9), ((12, 5), 1),
                                ((14, 5), 9), ((5, 20), 81), ((-1, 20), 90)):
            with self.subTest(point=point):
                self.assertEqual(distance, box.distance_point_squared(point))

    def test_the_page_shown_is_the_one_under_the_middle_of_the_window(self):
        """A window ten wide over two pages ten wide, half over each, has
        no middle pixel: it is the one towards where reading starts."""
        pages = [Box((10, 10), (0, 0)), Box((10, 10), (10, 0))]
        window = Box((10, 10), (5, 0))
        self.assertEqual(0, window.current_box_index((1, 1), pages))
        self.assertEqual(1, window.current_box_index((-1, 1), pages))

    def test_a_point_as_near_two_boxes_goes_to_the_one_reading_starts_at(self):
        pages = [Box((4, 4), (0, 0)), Box((4, 4), (5, 0))]
        self.assertEqual([0, 1], Box.closest_boxes((4, 0), pages))
        self.assertEqual([0], Box.closest_boxes((4, 0), pages, (1, 1)))
        self.assertEqual([1], Box.closest_boxes((4, 0), pages, (-1, 1)))
        window = Box((1, 1), (4, 0))
        self.assertEqual(1, window.current_box_index((-1, 1), pages))

    def test_a_page_narrower_than_the_window_is_centred_in_it(self):
        """Five pixels to share, the odd one goes to the side reading
        starts from."""
        page = Box((5, 20), (0, 0))
        for orientation, left in (((1, 1), -3), ((-1, 1), -2)):
            with self.subTest(orientation=orientation):
                self.assertEqual(Box((10, 20), (left, 0)),
                                 page.wrapper_box((10, 10), orientation))

# vim: expandtab:sw=4:ts=4
