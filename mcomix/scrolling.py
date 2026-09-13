""" Smart scrolling. """

from mcomix import tools
from mcomix import constants
from mcomix import box
import math

from collections.abc import Sequence


class Scrolling:

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
        """ Returns a new viewport position when reading forwards using
        the given orientation. If there is no space left to go, the empty
        list is returned. Note that all params are lists of ints (except
        max_scroll which might also contain floats) where each index
        corresponds to one dimension. The lower the index, the faster the
        corresponding position changes when reading. If you need to override
        this behavior, use the optional axis_map.
        @param content_box: The Box of the content to display.
        @param viewport_box: The viewport Box we are looking through.
        @param orientation: The orientation which shows where "forward"
        points to. Either 1 (towards larger values in this dimension when
        reading) or -1 (towards smaller values in this dimension when reading).
        Note that you can emulate "reading backwards" by flipping the sign
        of this argument.
        @param max_scroll: The maximum number of pixels to scroll in one step.
        (Floats allowed.)
        @param axis_map: The index of the dimension to modify.
        @return: A new viewport_position if you can read further or the
        empty list if there is nothing left to read. """
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
        for i, (content, viewport, position, o) in enumerate(
                zip(content_size, viewport_size, viewport_position,
                    orientation)):
            invisible_size = content - viewport
            # Find a nice starting point
            if o == 1:
                if position < 0:
                    result[i] = 0
                    carry = False
                    if position <= -viewport:
                        reset_all_axes = True
                        break
            else:  # o == -1
                if position > invisible_size:
                    result[i] = invisible_size
                    carry = False
                    if position > content:
                        reset_all_axes = True
                        break
        if reset_all_axes:
            # We don't see anything at all because we are somewhere way before
            # the content box. Let's go to it.
            for i, (content, viewport, o) in enumerate(
                    zip(content_size, viewport_size, orientation)):
                result[i] = 0 if o == 1 else content - viewport

        # This code is somewhat similar to a simple ripple-carry adder.
        if carry:
            for i, (content, viewport, position, o, axis_max_scroll) in \
                    enumerate(zip(content_size, viewport_size,
                                  viewport_position, orientation, max_scroll)):
                invisible_size = content - viewport
                ms = min(axis_max_scroll, invisible_size)
                # Let's calculate the grid we want to snap to.
                if ms != 0:
                    steps_to_take = int(math.ceil(float(invisible_size) / ms))
                if ms == 0 or steps_to_take >= invisible_size:
                    # special case: We MUST go forward by at least 1 pixel.
                    if o >= 0:
                        result[i] += 1
                        carry = result[i] > invisible_size
                        if carry:
                            result[i] = 0
                            continue
                    else:
                        result[i] -= 1
                        carry = result[i] < 0
                        if carry:
                            result[i] = invisible_size
                            continue
                    break
                # If orientation is -1, we need to round half up instead of
                # half down.
                positions = self._cached_bs(invisible_size, steps_to_take, o == -1)

                # Where are we now (according to the grid)?
                index = tools.bin_search(positions, position)

                if index < 0:
                    # We're somewhere between two valid grid points, so
                    # let's go to the next one.
                    index = ~index
                    if o >= 0:
                        # index tends to be greater, so we need to go back
                        # manually, if needed.
                        index -= 1
                # Let's go to where we're headed for.
                index += o

                carry = index < 0 or index >= len(positions)
                if carry:
                    # There is no space left in this dimension, so let's go
                    # back in this one and one step forward in the next one.
                    result[i] = 0 if o > 0 else invisible_size
                else:
                    # We found a valid grid point in this dimension, so let's
                    # stop here.
                    result[i] = positions[index]
                    break
        if carry:
            # No space left.
            return []

        # Undo axis remapping, if any
        if axis_map is not None:
            result = tools.remap_axes(result, tools.inverse_axis_map(axis_map))

        return tools.vector_add(result, offset)

    def scroll_to_predefined(self, content_box: box.Box,
                             viewport_box: box.Box,
                             orientation: Sequence[int],
                             destination: Sequence[int]) -> list[int]:
        """ Returns a new viewport position when scrolling towards a
        predefined destination. Note that all params are lists of integers
        where each index corresponds to one dimension.
        @param content_box: The Box of the content to display.
        @param viewport_box: The viewport Box we are looking through.
        @param orientation: The orientation which shows where "forward"
        points to. Either 1 (towards larger values in this dimension when
        reading) or -1 (towards smaller values in this dimension when reading).
        @param destination: An integer representing a predefined destination.
        Either 1 (towards the greatest possible values in this dimension),
        -1 (towards the smallest value in this dimension), 0 (keep position),
        SCROLL_TO_CENTER (scroll to the center of the content in this
        dimension), SCROLL_TO_START (scroll to where the content starts in this
        dimension) or SCROLL_TO_END (scroll to where the content ends in this
        dimension).
        @return: A new viewport position as specified above. """
        content_position = content_box.get_position()
        content_size = content_box.get_size()
        viewport_size = viewport_box.get_size()
        result = list(viewport_box.get_position())
        for i, (content, viewport, start, o, d) in enumerate(
                zip(content_size, viewport_size, content_position,
                    orientation, destination)):
            if d == 0:
                continue
            if d < constants.SCROLL_TO_END or d > 1:
                raise ValueError('invalid destination %d at index %d' % (d, i))
            if d == constants.SCROLL_TO_END:
                d = o
            if d == constants.SCROLL_TO_START:
                d = -o
            invisible_size = content - viewport
            result[i] = start + (box.Box._box_to_center_offset_1d(
                invisible_size, o) if d == constants.SCROLL_TO_CENTER
                else invisible_size if d == 1
                else 0)  # if d == -1
        return result

    def _cached_bs(self, num: int, denom: int, half_up: bool) -> list[int]:
        """ A simple (and ugly) caching mechanism used to avoid
        recomputations. The current implementation offers a cache with
        only two entries so it's only useful for the two "fastest"
        dimensions. """
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
        """ Clears all caches that are used internally. """
        self._cache0 = (0, 0, False, [])
        self._cache1 = (0, 0, False, [])

    @staticmethod
    def _bresenham_sums(num: int, denom: int, half_up: bool) -> list[int]:
        """ This algorithm is derived from Bresenham's line algorithm in
        order to distribute the remainder of num/denom equally. See
        https://en.wikipedia.org/wiki/Bresenham%27s_line_algorithm for details.
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
