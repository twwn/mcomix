# -*- coding: utf-8 -*-

"""The 2x2 matrices the viewer turns and flips pages with.

Nothing covered transform.py at all, and the one thing it is for -
decomposing a matrix back into the scale, rotation and flip an image
library takes - answered wrong for every transform that swaps the axes.
"""

from . import MComixTest

from mcomix.transform import Matrix, Transform


#: Every decomposition from_image_transforms() accepts.
SCALES = ((1, 1), (2, 3), (3, 2), (0.5, 4), (1, 2), (2, 1))
ROTATIONS = (0, 90, 180, 270)
FLIPS = ((False, False), (True, False), (False, True), (True, True))


class DecompositionTest(MComixTest):

    def test_a_transform_survives_being_taken_apart_and_put_together(self):
        for scales in SCALES:
            for rotation in ROTATIONS:
                for flips in FLIPS:
                    with self.subTest(scales=scales, rotation=rotation,
                                      flips=flips):
                        matrix = Transform.from_image_transforms(
                            (scales, rotation, flips))
                        self.assertEqual(
                            matrix,
                            Transform.from_image_transforms(
                                matrix.to_image_transforms()))

    def test_a_rotation_reports_the_scales_of_the_axes_it_started_from(self):
        # Read straight off the rows, a matrix that swaps the axes
        # reported (3, 2) here: the scales as the rotation left them,
        # where the sequence puts them before it.
        matrix = Transform.from_scales(2, 3) + Transform.ROT90
        scales, rotation, flips = matrix.to_image_transforms()
        self.assertEqual((2, 3), scales)
        self.assertEqual(90, rotation)
        self.assertEqual((False, False), flips)

    def test_the_scales_are_positive_whichever_way_the_page_is_flipped(self):
        for flips in FLIPS:
            with self.subTest(flips=flips):
                matrix = Transform.from_image_transforms(((2, 3), 0, flips))
                scales, _rotation, _flips = matrix.to_image_transforms()
                self.assertEqual((2, 3), scales)

    def test_a_horizontal_flip_of_a_quarter_turn_is_reported_as_the_other(self):
        # Horizontal flips are slow on some hardware, so one that comes
        # with a quarter turn is answered as three quarters and a
        # vertical flip instead.  Same transform, cheaper to draw.
        matrix = Transform.from_image_transforms(
            ((1, 1), 90, (True, False)))
        self.assertEqual(((1, 1), 270, (False, True)),
                         matrix.to_image_transforms())

    def test_a_flip_of_both_axes_is_reported_as_a_half_turn(self):
        matrix = Transform.from_image_transforms(((1, 1), 0, (True, True)))
        self.assertEqual(((1, 1), 180, (False, False)),
                         matrix.to_image_transforms())


class MatrixTest(MComixTest):

    def test_the_identity_is_the_only_matrix_that_is_false(self):
        self.assertFalse(Transform.ID)
        for matrix in (Transform.ROT90, Transform.ROT180, Transform.ROT270,
                       Transform.INVX, Transform.INVY, Transform.TRP,
                       Transform.TRPINV):
            self.assertTrue(matrix)

    def test_adding_is_applying_one_transform_after_the_other(self):
        self.assertEqual(Transform.ROT180, Transform.ROT90 + Transform.ROT90)
        self.assertEqual(Transform.ID, Transform.ROT90 + Transform.ROT270)
        self.assertEqual(Transform.ROT180, Transform.INVX + Transform.INVY)

    def test_a_matrix_answers_nothing_useful_about_anything_else(self):
        self.assertIs(NotImplemented, Matrix(1, 0, 0, 1).__add__(90))
        self.assertIs(NotImplemented, Matrix(1, 0, 0, 1).__eq__('ID'))

    def test_the_helpers_say_the_same_as_adding_by_hand(self):
        matrix = Matrix(1, 0, 0, 1)
        self.assertEqual(matrix + Transform.ROT90, matrix.rotated(90))
        self.assertEqual(matrix + Transform.INVX, matrix.flipped_x())
        self.assertEqual(matrix + Transform.INVY, matrix.flipped_y())
        self.assertEqual(matrix + Transform.from_scales(2, 2),
                         matrix.scaled(2))
        self.assertEqual(matrix.rotated(90).flipped_y(),
                         matrix.and_then_all(Transform.ROT90, Transform.INVY))

    def test_only_a_quarter_turn_swaps_the_axes(self):
        self.assertFalse(Transform.ID.swaps_axes())
        self.assertFalse(Transform.ROT180.swaps_axes())
        self.assertTrue(Transform.ROT90.swaps_axes())
        self.assertTrue(Transform.ROT270.swaps_axes())

    def test_a_transform_that_cannot_be_built_says_so(self):
        self.assertRaises(ValueError, Transform.from_rotation, 45)
        self.assertRaises(ValueError, Transform.from_scales, 0, 1)
        self.assertRaises(ValueError, Transform.from_scales, 1, 0)

    def test_a_negative_rotation_is_the_positive_one_that_matches(self):
        self.assertEqual(Transform.ROT270, Transform.from_rotation(-90))
        self.assertEqual(Transform.ROT180, Transform.from_rotation(-180))
        self.assertEqual(Transform.ROT90, Transform.from_rotation(-270))


# vim: expandtab:sw=4:ts=4
