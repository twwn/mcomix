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

    def test_the_pixel_too_many_comes_off_the_page_it_costs_least(self):
        """87.5 and 17.5 pixels round to 88 and 18, one more than the
        105 there are. Taken from the wide page, the pixel is a
        hundredth of it; taken from the narrow one, a seventeenth."""
        _scales, widths = self._widths([[100, 500], [20, 500]], 105)
        self.assertEqual([87, 18], widths)

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

class ZoomedSizeTest(MComixTest):

    """get_zoomed_size() on pages worked out by hand, where the random
    cases above promise only bounds."""

    def _zoomed(self, sizes, screen, mode, scale_up=False, steps=0,
                same=False, fit_same=False):
        model = ZoomModel()
        model.set_fit_mode(int(mode))
        model.set_scale_up(scale_up)
        for _step in range(abs(steps)):
            if steps > 0:
                model.zoom_in()
            else:
                model.zoom_out()
        return model.get_zoomed_size(sizes, screen, PageAxis.WIDTH,
                                     [False] * len(sizes), same, fit_same)

    def test_four_steps_in_double_the_page_and_one_out_takes_a_fourth_root(self):
        self.assertEqual(([[800, 600]], [False]),
                         self._zoomed([[400, 300]], (1024, 768), ZoomMode.MANUAL,
                                      steps=4))
        # 400 and 300 times 2 ** -0.25, 0.8409.
        self.assertEqual(([[336, 252]], [False]),
                         self._zoomed([[400, 300]], (1024, 768), ZoomMode.MANUAL,
                                      steps=-1))

    def test_a_small_page_is_enlarged_to_fit_only_where_that_is_allowed(self):
        for scale_up, size in ((False, [200, 100]), (True, [1000, 500])):
            with self.subTest(scale_up=scale_up):
                self.assertEqual(
                    ([size], [False]),
                    self._zoomed([[200, 100]], (1000, 1000), ZoomMode.BEST,
                                 scale_up))

    def test_pages_fit_to_the_width_share_it_and_to_the_screen_its_height(self):
        """Fit to width, no other axis has a say, so the pages fill the
        width between them, however high that makes them; best fit, the
        height has its say as well."""
        for mode, drawn in ((ZoomMode.WIDTH, [[200, 600], [400, 600]]),
                            (ZoomMode.BEST, [[33, 100], [67, 100]])):
            with self.subTest(mode=mode):
                self.assertEqual(
                    (drawn, [False, False]),
                    self._zoomed([[100, 300], [200, 300]], (600, 100), mode,
                                 True))

    def test_pages_made_one_size_are_stretched_only_where_asked(self):
        """Two pages scaled to one height round to 307 and 308 pixels
        high; forced to one size, the one that came out lower is
        stretched, and said to be.  Forcing alone, without scaling them
        to one another first, does nothing."""
        sizes, screen = [[302, 147], [62, 126]], (931, 450)
        for same, fit_same, distorted in ((True, False, [False, False]),
                                          (False, True, [False, False]),
                                          (True, True, [True, False])):
            with self.subTest(same=same, fit_same=fit_same):
                drawn, stretched = self._zoomed(
                    sizes, screen, ZoomMode.BEST, True, -1, same, fit_same)
                self.assertEqual(distorted, stretched)
        self.assertEqual([[632, 308], [151, 308]], drawn)


# vim: expandtab:sw=4:ts=4
