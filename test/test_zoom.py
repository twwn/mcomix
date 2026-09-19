"""What the zoom model computes, which nothing else in the suite reaches."""

import random

from . import MComixTest

from mcomix.constants import PageAxis, ZoomMode
from mcomix.preferences import prefs
from mcomix.zoom import IDENTITY_ZOOM, ZoomModel


class ZoomLimitsTest(MComixTest):

    """The size each fit mode allows a page along each axis.

    A limit of None means the mode has no preference for that axis, and
    _preferred_scale() then leaves the axis alone.
    """

    SCREEN = (1024, 768)

    def _limits(self, fitmode, union=(400, 300), upscaling=False):
        return list(ZoomModel._calc_limits(union, self.SCREEN, fitmode,
                                           upscaling))

    def test_best_fit_is_limited_by_both_axes(self):
        self.assertEqual(self._limits(ZoomMode.BEST), list(self.SCREEN))

    def test_fit_to_width_is_limited_by_the_screen_width_alone(self):
        self.assertEqual(self._limits(ZoomMode.WIDTH),
                         [self.SCREEN[PageAxis.WIDTH], None])

    def test_fit_to_height_is_limited_by_the_screen_height_alone(self):
        self.assertEqual(self._limits(ZoomMode.HEIGHT),
                         [None, self.SCREEN[PageAxis.HEIGHT]])

    def test_manual_zoom_is_limited_by_neither_axis(self):
        self.assertEqual(self._limits(ZoomMode.MANUAL), [None, None])

    def test_manual_zoom_that_may_upscale_fills_a_screen_the_page_fits_in(self):
        self.assertEqual(self._limits(ZoomMode.MANUAL, upscaling=True),
                         list(self.SCREEN))

    def test_manual_zoom_that_may_upscale_leaves_a_larger_page_alone(self):
        self.assertEqual(self._limits(ZoomMode.MANUAL, union=(4000, 3000),
                                      upscaling=True), [None, None])

    def test_fit_to_size_takes_the_wide_preferences_for_a_wide_page(self):
        prefs['fit to size width wide'] = 1200
        prefs['fit to size height wide'] = 900
        self.assertEqual(self._limits(ZoomMode.SIZE, union=(2000, 1000)),
                         [1200, 900])

    def test_fit_to_size_takes_the_other_preferences_for_a_tall_page(self):
        prefs['fit to size width other'] = 600
        prefs['fit to size height other'] = 800
        self.assertEqual(self._limits(ZoomMode.SIZE, union=(1000, 2000)),
                         [600, 800])


class ZoomDistributionTest(MComixTest):

    """_scale_distributed() shares one axis out between the pages on it."""

    def _widths(self, sizes, max_size, upscaling=False, do_not_transform=None):
        if do_not_transform is None:
            do_not_transform = [False] * len(sizes)
        scales = ZoomModel._scale_distributed(sizes, PageAxis.WIDTH, max_size,
                                              upscaling, do_not_transform)
        return scales, [round(size[PageAxis.WIDTH] * scale)
                        for size, scale in zip(sizes, scales)]

    def test_pages_side_by_side_fit_the_width_they_are_given(self):
        sizes = [[400, 300], [400, 300], [400, 300]]
        scales, widths = self._widths(sizes, 600)
        self.assertLessEqual(sum(widths), 600)
        self.assertEqual(len(set(scales)), 1,
                         'equal pages were given unequal scales: %r' % (scales,))

    def test_pages_that_already_fit_are_left_alone(self):
        sizes = [[100, 300], [100, 300]]
        scales, _ = self._widths(sizes, 600)
        self.assertEqual(scales, [IDENTITY_ZOOM] * 2)

    def test_a_page_that_may_not_be_transformed_keeps_its_scale(self):
        sizes = [[400, 300], [400, 300]]
        scales, _ = self._widths(sizes, 300, do_not_transform=[True, False])
        self.assertEqual(scales[0], IDENTITY_ZOOM)
        self.assertLess(scales[1], IDENTITY_ZOOM)

    def test_a_wide_page_beside_narrow_ones_still_fits(self):
        """A page that rounds to a single pixel cannot be made smaller,
        so the wide one beside it has to give up more than the one pixel
        each box used to be allowed: 15 + 1 + 1 + 1 came to 17 in 16."""
        sizes = [[1042, 443]] + [[26, 926]] * 3
        _scales, widths = self._widths(sizes, 16, upscaling=True)
        self.assertLessEqual(sum(widths), 16, widths)

    def test_the_pages_fit_whatever_sizes_they_come_in(self):
        """Random pages, some of them alike, from a fixed seed: the
        widths add up to no more than the room there is, and pages that
        came in alike are scaled alike."""
        random.seed(7)
        for _case in range(2000):
            count = random.randint(1, 4)
            sizes = []
            for index in range(count):
                if index and random.random() < 0.5:
                    sizes.append(list(sizes[-1]))
                else:
                    sizes.append([random.randint(1, 2000),
                                  random.randint(1, 2000)])
            max_size = random.randint(count + 1, 3000)
            scales, widths = self._widths(
                sizes, max_size, upscaling=random.random() < 0.5)
            self.assertLessEqual(sum(widths), max_size,
                                 '%r in %d came to %r' % (sizes, max_size,
                                                          widths))
            for first in range(count):
                for second in range(first + 1, count):
                    if sizes[first] == sizes[second]:
                        self.assertEqual(scales[first], scales[second],
                                         '%r got %r' % (sizes, scales))

    def test_what_holds_for_any_pages_on_any_screen(self):
        """Three promises of get_zoomed_size(), over random pages and
        screens from a fixed seed: a page that may not be transformed
        comes back at the size it went in at, fitting by width or to the
        screen leaves the pages no wider than the screen between them,
        and making them the same size does make them the same size."""
        random.seed(11)
        model = ZoomModel()
        for _case in range(2000):
            count = random.randint(1, 2)
            sizes = [[random.randint(1, 3000), random.randint(1, 3000)]
                     for _ in range(count)]
            if count == 2 and random.random() < 0.4:
                sizes[1] = list(sizes[0])
            screen = [random.randint(10, 2000), random.randint(10, 2000)]
            fixed = [random.random() < 0.2 for _ in range(count)]
            same = random.random() < 0.5
            fit_same = same and random.random() < 0.5
            mode = random.choice(list(ZoomMode))
            model.set_fit_mode(int(mode))
            model.set_scale_up(random.random() < 0.5)
            model.reset_user_zoom()
            zoomed = random.random() < 0.5
            if zoomed:
                for _step in range(random.randint(1, 3)):
                    if random.random() < 0.5:
                        model.zoom_in()
                    else:
                        model.zoom_out()
            drawn, _distorted = model.get_zoomed_size(
                sizes, screen, PageAxis.WIDTH, fixed, same, fit_same)
            case = '%r on %r, %s' % (sizes, screen, mode)
            for size, keep, came_out in zip(sizes, fixed, drawn):
                if keep:
                    self.assertEqual(size, list(came_out), case)
            if (mode in (ZoomMode.WIDTH, ZoomMode.BEST) and not any(fixed)
                    and not zoomed):
                self.assertLessEqual(
                    sum(page[PageAxis.WIDTH] for page in drawn),
                    screen[PageAxis.WIDTH], case)
            if fit_same and count == 2 and not any(fixed):
                self.assertEqual(drawn[0][PageAxis.HEIGHT],
                                 drawn[1][PageAxis.HEIGHT], case)

    def test_no_pages_at_all_need_no_room(self):
        self.assertEqual(ZoomModel._scale_distributed([], PageAxis.WIDTH, 100,
                                                      False, []), [])

# vim: expandtab:sw=4:ts=4
