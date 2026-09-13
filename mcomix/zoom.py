"""zoom.py - How large the pages of the current view are drawn.

Two things decide that, and they multiply.  The fit mode turns the room
on screen into a limit on one axis, both, or neither, and the pages are
scaled to respect whichever limits it names; the reader's own zoom then
scales that result again.  A page marked do_not_transform - an animation,
which is drawn frame by frame at whatever size the layout hands it -
takes neither and is left at its own size.

Pages are laid out side by side along one axis, the distribution axis,
which is the one they share the room on: their sizes add up along it
where they are compared along every other.  That is what makes the
distribution axis a case of its own throughout this module.
"""

import operator
from mcomix import constants
from mcomix.preferences import prefs
from mcomix import tools
from mcomix import box
from functools import reduce
from collections.abc import Sequence
from dataclasses import dataclass

#: The scale that leaves a page at the size it came in at.
IDENTITY_ZOOM = 1.0
#: The reader's zoom level standing at that scale.
IDENTITY_ZOOM_LOG = 0
#: How many steps of the reader's zoom double the size of a page.  The
#: level is kept as a count of steps rather than as a scale so that
#: zooming out and back in again lands exactly where it started.
USER_ZOOM_LOG_SCALE1 = 4.0
#: How far the reader may zoom: down to a thirty-second of the fitted
#: size, up to eight times it.
MIN_USER_ZOOM_LOG = -20
MAX_USER_ZOOM_LOG = 12


@dataclass
class _ScalingData:

    """What is known about one box while the scales are worked out.

    This was a five-element list indexed by number throughout, which
    said nothing about what any of the five meant.
    """

    #: The scale this box is to be given.
    local_scale: float
    #: The size it would have at the scale every box started with, or
    #: None for a box that is not being scaled at all.
    ideal: Sequence[float] | None
    #: Whether it can still be made one pixel smaller along the axis.
    can_be_downscaled: bool
    #: The scale that would make it that much smaller, and what taking
    #: that step would cost as a relative volume error.  Both are only
    #: read while can_be_downscaled holds; otherwise they stand at the
    #: values a box that is never touched carries.
    forced_scale: float
    forced_vol_err: float


class ZoomModel:
    """ Handles zoom and fit modes. """

    def __init__(self) -> None:
        #: User zoom level.
        self._user_zoom_log = IDENTITY_ZOOM_LOG
        #: Image fit mode. Determines the base zoom level for an image by
        #: calculating its maximum size.
        self._fitmode = constants.ZoomMode.MANUAL
        #: Whether a page smaller than the room it has is enlarged to
        #: fill it, or left at the size it came in at.
        self._scale_up = False

    def set_fit_mode(self, fitmode: int) -> None:
        """Fit pages the way <fitmode>, one of the ZoomMode values, says.

        A plain number rather than the member itself: the preference it
        comes from holds one, because that is what survives a trip
        through the preferences file.  Converting it here is also what
        rejects a number that names no mode.
        """
        self._fitmode = constants.ZoomMode(fitmode)

    def get_scale_up(self) -> bool:
        """Whether a page smaller than the room it has is enlarged."""
        return self._scale_up

    def set_scale_up(self, scale_up: bool) -> None:
        """Enlarge a page to fill the room it has, or leave it be."""
        self._scale_up = scale_up

    def _set_user_zoom_log(self, zoom_log: int) -> None:
        """Put the reader's zoom at <zoom_log>, as far as it will go."""
        self._user_zoom_log = min(max(zoom_log, MIN_USER_ZOOM_LOG), MAX_USER_ZOOM_LOG)

    def zoom_in(self) -> None:
        """Take the pages one step larger."""
        self._set_user_zoom_log(self._user_zoom_log + 1)

    def zoom_out(self) -> None:
        """Take the pages one step smaller."""
        self._set_user_zoom_log(self._user_zoom_log - 1)

    def reset_user_zoom(self) -> None:
        """Draw the pages at the size the fit mode alone asks for."""
        self._set_user_zoom_log(IDENTITY_ZOOM_LOG)

    def get_zoomed_size(self, image_sizes: Sequence[Sequence[int]],
                        screen_size: Sequence[int],
                        distribution_axis: constants.PageAxis, do_not_transform: list[bool], prefer_same_size: bool,
                        fit_same_size: bool) -> tuple[list[list[int]], list[bool]]:
        """How large to draw each of <image_sizes>, and which came out distorted.

        <screen_size> is the room the pages have between them, and
        <distribution_axis> is the axis they are laid out along, so that
        their sizes add up along it and are compared along every other.
        An entry of <do_not_transform> marks a page that must be handed
        back at the size it came in at, whatever the rest of this works
        out.

        The work goes in this order.  Where <prefer_same_size> is asked
        for, the pages are first scaled to one another - up to the box
        that holds them all if enlarging is allowed, down to the box
        they all cover if it is not - and everything after that is done
        on those sizes rather than the ones that came in.  The fit mode
        then names a limit on each axis, or none, and the pages are
        scaled by as much as the limits away from the distribution axis
        allow.  Where the distribution axis has a limit of its own, and
        the pages either overflow the screen along it or have no other
        limit to answer to, the scales that make their total along it
        come out as close to that limit as it can be are worked out per
        page and taken instead, or taken as the smaller of the two where
        another axis also has a say.  What is left is multiplied by the
        reader's own zoom and rounded to whole pixels.

        Keeping every page's aspect ratio and making them all the same
        size are not always both possible, and <fit_same_size> says
        which of the two to give up: with it, each axis but the
        distribution one is forced to the largest size any page came out
        at when enlarging is allowed and the smallest when it is not.
        The second list returned marks the pages that were stretched to
        get there; without <fit_same_size> nothing is, and it is all
        False.
        """
        scale_up = self._scale_up
        # The sizes worked with from here on.  Scaling every page to the
        # same size first hands back fractional sizes, so these are not
        # the integer sizes that came in.
        working_sizes: Sequence[Sequence[float]] = image_sizes
        if prefer_same_size:
            # Preprocessing step: scale all images to the same size
            image_boxes = [box.Box(s) for s in image_sizes]
            # Scale up to the same size if this is allowed, otherwise scale down.
            if scale_up:
                # Scale up to union.
                pre_limits = box.Box.bounding_box(image_boxes).get_size()
            else:
                # Scale down to intersection.
                pre_limits = reduce(box.Box.intersect, image_boxes, image_boxes[0]).get_size()
            new_image_sizes = [tuple(tools.scale(s, ZoomModel._preferred_scale(
                s, pre_limits, distribution_axis))) for s in image_sizes]
            new_image_sizes2 = [new_image_sizes[i] if not do_not_transform[i] else image_sizes[i]
                                for i in range(len(new_image_sizes))]
            working_sizes = new_image_sizes2
        union_size = _union_size(working_sizes, distribution_axis)
        limits = ZoomModel._calc_limits(union_size, screen_size, self._fitmode,
                                        scale_up)
        prefscale = ZoomModel._preferred_scale(union_size, limits, distribution_axis)
        preferred_scales: list[float] = [
            prefscale if not dnt else IDENTITY_ZOOM for dnt in do_not_transform]
        prescaled = list(map(lambda size, scale, dnt: tuple(_scale_image_size(size, scale)),
                         working_sizes, preferred_scales, do_not_transform))
        prescaled_union_size = _union_size(prescaled, distribution_axis)

        def _other_preferences(limits: Sequence[int | None],
                               distribution_axis: constants.PageAxis) -> bool:
            """Whether any axis but the distribution one has a limit."""
            for i in range(len(limits)):
                if i == distribution_axis:
                    continue
                if limits[i] is not None:
                    return True
            return False
        other_preferences = _other_preferences(limits, distribution_axis)
        distribution_limit = limits[distribution_axis]
        if distribution_limit is not None and \
            (prescaled_union_size[distribution_axis] > screen_size[distribution_axis]
            or not other_preferences):
            distributed_scales = ZoomModel._scale_distributed(working_sizes,
                distribution_axis, distribution_limit, scale_up, do_not_transform)
            if other_preferences:
                preferred_scales = list(map(min, preferred_scales, distributed_scales))
            else:
                preferred_scales = distributed_scales
        if not scale_up:
            preferred_scales = [min(x, IDENTITY_ZOOM) for x in preferred_scales]
        user_scale = 2 ** (self._user_zoom_log / USER_ZOOM_LOG_SCALE1)
        res_scales = [preferred_scales[i] * (user_scale if not do_not_transform[i] else IDENTITY_ZOOM)
            for i in range(len(preferred_scales))]
        res = list(map(lambda size, scale: list(_scale_image_size(size, scale)),
            working_sizes, res_scales))
        distorted = [False] * len(res)
        if prefer_same_size and fit_same_size:
            # While the algorithm so far tries hard to keep the aspect ratios of the
            # original images, in extreme cases, it is not possible to both keep aspect
            # ratios as well as make the images fit to the same size, especially after
            # applying user_scale. In those cases, we will make them fit.
            # Simple approach: For each dimension, we fit each image to either the
            # minimum size (if scale_up is false) or maximum size (if scale_up is true)
            # of all images, given the scaled sizes computed so far.
            op = operator.gt if scale_up else operator.lt
            exs: list[int | None] = [None] * len(limits)
            for d in range(len(limits)):
                if d == distribution_axis:
                    continue
                for row in res:
                    extreme = exs[d]
                    if extreme is None or op(row[d], extreme):
                        exs[d] = row[d]
            for d in range(len(limits)):
                if d == distribution_axis:
                    continue
                extreme = exs[d]
                if extreme is None:
                    # Nothing was measured along this axis, which is
                    # only so when there is nothing to measure.
                    continue
                for i in range(len(res)):
                    if (res[i][d] != extreme) and not do_not_transform[i]:
                        res[i][d] = extreme
                        distorted[i] = True
        return (res, distorted)

    @staticmethod
    def _preferred_scale(image_size: Sequence[float],
                         limits: Sequence[int | None],
                         distribution_axis: int) -> float:
        """ Returns scale that makes an image of size image_size respect the
        limits imposed by limits. If no proper value can be determined,
        IDENTITY_ZOOM is returned. """
        min_scale = None
        for i in range(len(limits)):
            if i == distribution_axis:
                continue
            l = limits[i]
            if l is None:
                continue
            s = tools.div(l, image_size[i])
            if min_scale is None or s < min_scale:
                min_scale = s
        if min_scale is None:
            min_scale = IDENTITY_ZOOM
        return min_scale

    @staticmethod
    def _calc_limits(union_size: Sequence[float], screen_size: Sequence[int],
                     fitmode: constants.ZoomMode,
                     allow_upscaling: bool) -> Sequence[int | None]:
        """ Returns a list or a tuple with the i-th element set to int x if
        fitmode limits the size at the i-th axis to x, or None if fitmode has no
        preference for this axis. """
        manual = fitmode == constants.ZoomMode.MANUAL
        if fitmode == constants.ZoomMode.BEST or \
            (manual and allow_upscaling and all(tools.smaller(union_size, screen_size))):
            return screen_size
        if fitmode == constants.ZoomMode.SIZE:
            if union_size[constants.PageAxis.WIDTH] > union_size[constants.PageAxis.HEIGHT]:
                return [int(prefs['fit to size width wide']),
                    int(prefs['fit to size height wide'])]
            else:
                return [int(prefs['fit to size width other']),
                    int(prefs['fit to size height other'])]
        result: list[int | None] = [None] * len(screen_size)
        if not manual:
            if fitmode == constants.ZoomMode.WIDTH:
                axis = constants.PageAxis.WIDTH
            elif fitmode == constants.ZoomMode.HEIGHT:
                axis = constants.PageAxis.HEIGHT
            else:
                assert False, 'Cannot map fitmode to axis'
            result[axis] = screen_size[axis]
        return result

    @staticmethod
    def _scale_distributed(sizes: Sequence[Sequence[float]], axis: int,
                           max_size: int, allow_upscaling: bool,
                           do_not_transform: Sequence[bool]) -> list[float]:
        """ Calculates scales for a list of boxes that are distributed along a
        given axis (without any gaps). If the resulting scales are applied to
        their respective boxes, their new total size along axis will be as close
        as possible to max_size. The current implementation ensures that equal
        box sizes are mapped to equal scales.
        @param sizes: A list of box sizes.
        @param axis: The axis along which those boxes are distributed.
        @param max_size: The maximum size the scaled boxes may have along axis.
        @param allow_upscaling: True if upscaling is allowed, False otherwise.
        @param do_not_transform: True if the resulting scale must be 1, False
        otherwise.
        @return: A list of scales where the i-th scale belongs to the i-th box
        size. If sizes is empty, the empty list is returned. If there are more
        boxes than max_size, an approximation is returned where all resulting
        scales will shrink their respective boxes to 1 along axis. In this case,
        the scaled total size might be greater than max_size. """
        n = len(sizes)
        # trivial cases first
        if n == 0:
            return []
        if n >= max_size:
            # In this case, only one solution or only an approximation is available.
            # if n > max_size, the result won't fit into max_size.
            return [IDENTITY_ZOOM if dnt else tools.div(1, s[axis]) for s, dnt in zip(sizes, do_not_transform)]
        total_axis_size = sum([s[axis] for s in sizes])
        total_dnt_axis_size = sum([s[axis] for s, dnt in zip(sizes, do_not_transform) if dnt])
        if ((total_axis_size <= max_size) and not allow_upscaling) or \
            (total_axis_size == total_dnt_axis_size):
            # identity
            return [IDENTITY_ZOOM] * n

        # non-trival case
        # initial guess
        scale = tools.div(max_size - total_dnt_axis_size, total_axis_size - total_dnt_axis_size)
        scaling_data: list[_ScalingData] = []
        total_axis_size = 0
        # This loop collects some data we need for the actual computations later.
        for i in range(n):
            this_size = sizes[i]
            # Shortcut: If the size cannot be changed, accept the original size.
            if do_not_transform[i]:
                total_axis_size += this_size[axis]
                scaling_data.append(_ScalingData(
                    IDENTITY_ZOOM, None, False, IDENTITY_ZOOM, 0.0))
                continue
            # Initial guess: The current scale works for all tuples.
            ideal = tools.scale(this_size, scale)
            ideal_vol = tools.volume(ideal)
            # Let's use a dummy to compute the actual (rounded) size along axis
            # so we can rescale the rounded tuple with a better local_scale
            # later. This rescaling is necessary to ensure that the sizes in ALL
            # dimensions are monotonically scaled (with respect to local_scale).
            # A nice side effect of this is that it keeps the aspect ratio better.
            dummy_approx = _round_nonempty((ideal[axis],))[0]
            local_scale = tools.div(dummy_approx, this_size[axis])
            total_axis_size += dummy_approx
            can_be_downscaled = dummy_approx > 1
            if can_be_downscaled:
                forced_size = dummy_approx - 1
                forced_scale = tools.div(forced_size, this_size[axis])
                forced_approx = _scale_image_size(this_size, forced_scale)
                forced_vol_err = tools.relerr(tools.volume(forced_approx), ideal_vol)
            else:
                # Never read while can_be_downscaled is False; the same
                # standing values a box that is not scaled at all takes.
                forced_scale = IDENTITY_ZOOM
                forced_vol_err = 0.0
            scaling_data.append(_ScalingData(
                local_scale, ideal, can_be_downscaled,
                forced_scale, forced_vol_err))
        # Now we need to find at most total_axis_size - max_size occasions to
        # scale down some tuples so the whole thing would fit into max_size. If
        # we are lucky, there will be no gaps at the end (or at least fewer gaps
        # than we would have if we always rounded down).
        dirty=True # This flag prevents infinite loops if nothing can be made any smaller.
        while dirty and (total_axis_size > max_size):
            # This algorithm needs O(n*n) time. Let's hope that n is small enough.
            dirty=False
            current_index = 0
            current_min: _ScalingData | None = None
            for i in range(n):
                d = scaling_data[i]
                if not d.can_be_downscaled:
                    # Ignore elements that cannot be made any smaller.
                    continue
                if (current_min is None) or (d.forced_vol_err
                                             < current_min.forced_vol_err):
                    # We are searching for the tuple where downscaling results
                    # in the smallest relative volume error (compared to the
                    # respective ideal volume).
                    current_min = d
                    current_index = i
            if current_min is None:
                # Nothing left that can be made smaller, so the loop
                # below would step over every element and change none.
                break
            for i in range(current_index, n):
                # We must scale down ALL equal tuples. Otherwise, images that
                # are of equal size might appear to be of different size
                # afterwards. The downside of this approach is that it might
                # introduce more gaps than necessary.
                d = scaling_data[i]
                if (not d.can_be_downscaled) or (d.ideal != current_min.ideal):
                    continue
                d.local_scale = d.forced_scale
                d.can_be_downscaled = False  # only once per tuple
                total_axis_size -= 1
                dirty=True
        # Where the loop leaves total_axis_size below max_size, the tuples
        # could be upscaled the same way (smallest relative volume error
        # first, equal boxes in conjunction with each other). That is less
        # useful than shrinking them, slightly more complicated, and it would
        # do nothing at all when every tuple is the same size.
        return [d.local_scale for d in scaling_data]

def _scale_image_size(size: Sequence[float], scale: float) -> list[int]:
    """The whole-pixel size <size> comes to at <scale>."""
    return _round_nonempty(tools.scale(size, scale))

def _round_nonempty(t: Sequence[float]) -> list[int]:
    """<t> rounded to whole numbers, none of them below one.

    A page scaled far enough down rounds to nothing on one axis or
    both, and a page of no width is a page that cannot be seen at all.
    """
    result = [0] * len(t)
    for i in range(len(t)):
        x = int(round(t[i]))
        result[i] = x if x > 0 else 1
    return result

def _union_size(image_sizes: Sequence[Sequence[float]],
                distribution_axis: int) -> list[float]:
    """The size <image_sizes> come to standing side by side.

    They are laid out along <distribution_axis> without gaps, so their
    sizes add up along it; along every other axis the room they need is
    the largest of them.
    """
    if len(image_sizes) == 0:
        return []
    n = len(image_sizes[0])
    union_size = [reduce(max, [x[i] for x in image_sizes]) for i in range(n)]
    union_size[distribution_axis] = sum([x[distribution_axis] for x in image_sizes])
    return union_size

# vim: expandtab:sw=4:ts=4
