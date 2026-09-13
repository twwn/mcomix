"""scrolling.py - Reading a page one screenful at a time.

"Smart scrolling" is what a single press of the space bar does: it
moves the viewport to the next part of the page that has not been read
yet, going along the fastest axis first and carrying into the next one
when that axis runs out, the way a ripple-carry adder does.  The axes
are ordered by how quickly they change while reading, fastest first,
which an axis map can override.

Each axis is stepped along a grid of positions rather than by a fixed
number of pixels, so that the last step of an axis lands exactly on the
end of the content instead of overshooting it or leaving a sliver
unread.  The grid is Bresenham's line algorithm spreading the remainder
of the division evenly over the steps.
"""

from mcomix import tools
from mcomix import constants
from mcomix import box
import math

from collections.abc import Sequence


class Scrolling:

    """Where a scrolling step lands, given the content and the viewport.

    It holds nothing about the page but the last two step grids it
    worked out, which is what makes it worth having an instance of
    rather than a set of functions.
    """

    def __init__(self) -> None:
        #: The last two answers of _bresenham_sums(), each kept beside
        #: the arguments that produced it.  Declared here and filled in
        #: by clear_cache(), which is also how they are emptied again.
        self._cache0: tuple[int, int, bool, list[int]]
        self._cache1: tuple[int, int, bool, list[int]]
        self.clear_cache()

    def scroll_smartly(self, content_box: box.Box, viewport_box: box.Box,
                       orientation: Sequence[int],
                       max_scroll: Sequence[float],
                       axis_map: Sequence[int] | None = None) -> list[int]:
        """Where the viewport goes next, reading <content_box> forwards.

        The answer is a new position for <viewport_box>, or the empty
        list when there is nothing left to read.

        Every argument holds one value per dimension.  <orientation>
        says which way "forwards" is on each axis, 1 towards the larger
        values and -1 towards the smaller, so reading backwards is the
        same call with the signs flipped.  <max_scroll> is how far one
        step may move, in pixels, and may hold floats.

        The axes are taken in order, the lowest index changing fastest,
        and <axis_map> reorders them where that is not what is wanted -
        which is the "invert smart scroll" preference.
        """
        # Translate content and viewport so that content position equals origin
        offset = content_box.get_position()
        content_size = content_box.get_size()
        viewport_position = tools.vector_sub(viewport_box.get_position(), offset)
        viewport_size = viewport_box.get_size()
        # Remap axes
        if axis_map is not None:
            content_size = tuple(tools.remap_axes(content_size, axis_map))
            viewport_size = tuple(tools.remap_axes(viewport_size, axis_map))
            viewport_position = tools.remap_axes(viewport_position, axis_map)
            orientation = tools.remap_axes(orientation, axis_map)
            max_scroll = tools.remap_axes(max_scroll, axis_map)

        result = list(viewport_position)
        carry = True
        reset_all_axes = False
        # The viewport may be sitting before the content rather than in
        # it - a page smaller than the last one, or one just opened - in
        # which case the step is to the start of the content and not
        # one grid point further on.
        for axis, (content, viewport, position, direction) in enumerate(
                zip(content_size, viewport_size, viewport_position,
                    orientation)):
            invisible_size = content - viewport
            if direction == 1:
                if position < 0:
                    result[axis] = 0
                    carry = False
                    if position <= -viewport:
                        reset_all_axes = True
                        break
            else:  # direction == -1
                if position > invisible_size:
                    result[axis] = invisible_size
                    carry = False
                    if position > content:
                        reset_all_axes = True
                        break
        if reset_all_axes:
            # Not even an edge of the content is in view, so there is no
            # part-read axis to preserve: go to the start of all of them.
            for axis, (content, viewport, direction) in enumerate(
                    zip(content_size, viewport_size, orientation)):
                result[axis] = 0 if direction == 1 else content - viewport

        # A ripple-carry adder: each axis is stepped on, and an axis
        # with no room left goes back to its start and carries into the
        # next one.
        if carry:
            for axis, (content, viewport, position, direction,
                       axis_max_scroll) in \
                    enumerate(zip(content_size, viewport_size,
                                  viewport_position, orientation, max_scroll)):
                invisible_size = content - viewport
                step = min(axis_max_scroll, invisible_size)
                # A step of no pixels, or a grid finer than the pixels
                # it is drawn on, is no grid at all.
                by_one_pixel = step == 0
                if not by_one_pixel:
                    steps_to_take = math.ceil(invisible_size / step)
                    by_one_pixel = steps_to_take >= invisible_size
                if by_one_pixel:
                    # Whatever else happens, the step has to move.
                    if direction >= 0:
                        result[axis] += 1
                        carry = result[axis] > invisible_size
                        if carry:
                            result[axis] = 0
                            continue
                    else:
                        result[axis] -= 1
                        carry = result[axis] < 0
                        if carry:
                            result[axis] = invisible_size
                            continue
                    break
                # Reading towards the smaller values rounds the other
                # way, which makes its grid the mirror image of the one
                # read towards the larger values: back from the far end
                # takes the steps that forwards from the start does.
                positions = self._cached_bresenham_sums(
                    invisible_size, steps_to_take, direction == -1)

                index = tools.bin_search(positions, position)
                if index < 0:
                    # Between two grid points: ~index is the one after,
                    # which is where reading backwards is headed and one
                    # too far for reading forwards.
                    index = ~index
                    if direction >= 0:
                        index -= 1
                index += direction

                carry = index < 0 or index >= len(positions)
                if carry:
                    result[axis] = 0 if direction > 0 else invisible_size
                else:
                    result[axis] = positions[index]
                    break
        if carry:
            # Every axis carried, so the whole content has been read.
            return []

        # Undo axis remapping, if any
        if axis_map is not None:
            result = tools.remap_axes(result, tools.inverse_axis_map(axis_map))

        return tools.vector_add(result, offset)

    def scroll_to_predefined(self, content_box: box.Box,
                             viewport_box: box.Box,
                             orientation: Sequence[int],
                             destination: Sequence[int]) -> list[int]:
        """Where the viewport goes to reach <destination>.

        Every argument holds one value per dimension.  <orientation>
        says which way "forwards" is on each axis, 1 towards the larger
        values and -1 towards the smaller.

        Each value of <destination> is 1 (towards the greatest values
        in this dimension), -1 (towards the smallest), 0 (keep the
        position), or one of SCROLL_TO_CENTER, SCROLL_TO_START and
        SCROLL_TO_END.  The last two are relative to the reading
        direction rather than to the axis, so they are the orientation
        and its opposite.
        """
        content_position = content_box.get_position()
        content_size = content_box.get_size()
        viewport_size = viewport_box.get_size()
        result = list(viewport_box.get_position())
        for axis, (content, viewport, start, direction, target) in enumerate(
                zip(content_size, viewport_size, content_position,
                    orientation, destination)):
            if target == 0:
                continue
            if target < constants.SCROLL_TO_END or target > 1:
                raise ValueError('invalid destination %d at index %d'
                                 % (target, axis))
            if target == constants.SCROLL_TO_END:
                target = direction
            if target == constants.SCROLL_TO_START:
                target = -direction
            invisible_size = content - viewport
            result[axis] = start + (box.Box._box_to_center_offset_1d(
                invisible_size, direction) if target == constants.SCROLL_TO_CENTER
                else invisible_size if target == 1
                else 0)  # if target == -1
        return result

    def _cached_bresenham_sums(self, num: int, denom: int,
                               half_up: bool) -> list[int]:
        """_bresenham_sums(), remembering its last two answers.

        Two entries because a scrolling step asks for the same grid on
        the same two axes over and over, and the axes are asked about in
        turn: a one-entry cache would be overwritten by the second axis
        before the first asked again.  The matching entry is moved to
        the front, so what is thrown away is the one asked for longer
        ago.
        """
        if (self._cache0[0] != num or
                self._cache0[1] != denom or
                self._cache0[2] != half_up):
            self._cache0, self._cache1 = self._cache1, self._cache0
        if (self._cache0[0] != num or
                self._cache0[1] != denom or
                self._cache0[2] != half_up):
            self._cache0 = (num, denom, half_up,
                            Scrolling._bresenham_sums(num, denom, half_up))
        return self._cache0[3]

    def clear_cache(self) -> None:
        """Forget the remembered step grids."""
        self._cache0 = (0, 0, False, [])
        self._cache1 = (0, 0, False, [])

    @staticmethod
    def _bresenham_sums(num: int, denom: int, half_up: bool) -> list[int]:
        """The <denom> + 1 grid points from 0 to <num>, evenly spread.

        <num> rarely divides by <denom>, and the remainder has to go
        somewhere: this spreads it over the steps rather than letting it
        pile up at one end, by Bresenham's line algorithm.  See
        https://en.wikipedia.org/wiki/Bresenham%27s_line_algorithm.

        <half_up> rounds a step that falls exactly between two pixels
        upwards instead of downwards, which makes the grid the mirror
        image of the one without it: reading towards the smaller values
        from the far end steps the way reading towards the larger values
        does from the start.  The two are not the same points - 101
        pixels in two steps are [0, 50, 101] one way and [0, 51, 101]
        the other - so a step back after a step on can stop a pixel
        short of where the step on began.
        """
        if num < 0:
            raise ValueError("num < 0")
        if denom < 1:
            raise ValueError("denom < 1")
        quotient = num // denom
        remainder = num % denom
        needs_up = half_up and (remainder != 0) and ((denom & 1) == 0)
        up_flag = False
        error = denom >> 1
        result = [0]
        partial_sum = 0
        for i in range(denom):
            error -= remainder
            if error < 0:
                error += denom
                partial_sum += quotient + 1
            else:
                partial_sum += quotient

            # round half up, if necessary
            if up_flag:
                partial_sum -= 1
                up_flag = False
            elif needs_up and error == 0:
                partial_sum += 1
                up_flag = True

            result.append(partial_sum)
        return result


# vim: expandtab:sw=4:ts=4
