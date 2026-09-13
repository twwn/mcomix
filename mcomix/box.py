"""box.py - Hyperrectangles.

A Box is an axis-aligned rectangle in as many dimensions as it is given
coordinates for, and it is immutable: every method that would change one
returns a new Box instead.  Two dimensions is what MComix uses it in -
layout.py lays the pages of a spread out with it, and zoom.py and
scrolling.py read the result - but nothing here is written for two.

Several methods take an orientation, which is one number per dimension
saying which way "forward" reads in it: 1 towards larger coordinates,
-1 towards smaller ones, and 0 for a dimension that is not to be
considered at all.  It is what makes the same code lay out a
left-to-right and a right-to-left book.
"""

from mcomix import tools

from collections.abc import Sequence


class Box:

    def __init__(self, size: Sequence[int],
                 position: Sequence[int] | None = None) -> None:
        """A Box of <size>, at <position> or at the origin.

        Each component of size should be positive (i.e. non-zero), and
        position and size must have the same number of dimensions.
        """
        if position is None:
            self.position = (0,) * len(size)
        else:
            self.position = tuple(position)
        self.size = tuple(size)
        if len(self.position) != len(self.size):
            raise ValueError('different number of dimensions: %d != %d'
                             % (len(self.position), len(self.size)))

    def __str__(self) -> str:
        """ Returns a string representation of this Box. """
        return '{%s:%s}' % (self.get_position(), self.get_size())

    def __eq__(self, other: object) -> bool:
        """ Two Boxes are said to be equal if and only if the number of
        dimensions, the positions and the sizes of the two Boxes are equal,
        respectively. Anything that is not a Box is left to answer for
        itself, which is what makes a Box comparable to one: reading a
        position off whatever was passed raised instead. """
        if not isinstance(other, Box):
            return NotImplemented
        return (self.get_position() == other.get_position()) and \
            (self.get_size() == other.get_size())

    def __len__(self) -> int:
        """ Returns the number of dimensions of this Box. """
        return len(self.position)

    def get_size(self) -> tuple[int, ...]:
        """ Returns the size of this Box. """
        return self.size

    def get_position(self) -> tuple[int, ...]:
        """ Returns the position of this Box. """
        return self.position

    def set_position(self, position: Sequence[int]) -> 'Box':
        """ Returns a new Box of this size at <position>. """
        return Box(self.get_size(), position)

    def set_size(self, size: Sequence[int]) -> 'Box':
        """ Returns a new Box of <size> at this position. """
        return Box(size, self.get_position())

    def distance_point_squared(self, point: Sequence[int]) -> int:
        """Return the square of the Euclidean distance to <point>.

        A point inside the Box is at distance zero; otherwise the
        distance is to the closest point of the Box.  The square is what
        is wanted, because the only thing this is used for is comparing
        one distance against another and a square root would not change
        the order.
        """
        result = 0
        for p, start, length in zip(point, self.position, self.size):
            end = start + length
            if p < start:
                edge = start - p
            elif p >= end:
                edge = p - end + 1
            else:
                continue
            result += edge * edge
        return result

    def translate(self, delta: Sequence[int]) -> 'Box':
        """ Returns a new Box of this size, moved by <delta>. """
        return Box(self.get_size(),
                   tools.vector_add(self.get_position(), delta))

    def translate_opposite(self, delta: Sequence[int]) -> 'Box':
        """ Returns a new Box of this size, moved by -<delta>. """
        return Box(self.get_size(),
                   tools.vector_sub(self.get_position(), delta))

    def _distance_to_origin(self,
                            orientation: Sequence[int]) -> tuple[int, ...]:
        """How far this Box is from the origin <orientation> implies.

        One number per dimension the orientation does not ignore, in
        dimension order, so that comparing two of these tuples compares
        the Boxes: the first dimension they differ in decides, which is
        what "closer to the origin" means when the origin is a corner
        rather than a point.
        """
        return tuple(position if o > 0 else size - position
                     for o, position, size
                     in zip(orientation, self.position, self.size,
                            strict=True)
                     if o != 0)

    @staticmethod
    def closest_boxes(point: Sequence[int], boxes: Sequence['Box'],
                      orientation: Sequence[int] | None = None) -> list[int]:
        """Return the indexes of the Boxes in <boxes> closest to <point>.

        Distance is measured to the closest point of each Box, so a Box
        containing the point wins outright.  Several Boxes can be equally
        close, and all of them are returned; <orientation>, if it is
        given, breaks that tie in favour of the Box closer to the origin
        it implies, and can leave a tie of its own.
        """
        if not boxes:
            return []
        ranks = [(b.distance_point_squared(point),
                  () if orientation is None
                  else b._distance_to_origin(orientation))
                 for b in boxes]
        closest = min(ranks)
        return [index for index, rank in enumerate(ranks) if rank == closest]

    def get_center(self, orientation: Sequence[int]) -> list[int]:
        """Return the center of this Box.

        A Box of even size has no exact center, and the coordinate
        closer to the origin <orientation> implies is chosen.
        """
        return [Box._box_to_center_offset_1d(size - 1, o) + position
                for o, size, position
                in zip(orientation, self.size, self.position, strict=True)]

    @staticmethod
    def _box_to_center_offset_1d(box_size_delta: int, orientation: int) -> int:
        """Half of <box_size_delta>, rounded towards the origin.

        An odd delta cannot be halved exactly, and which way it is
        rounded is what decides where the extra pixel of an even-sized
        Box goes.
        """
        if orientation == -1:
            box_size_delta += 1
        return box_size_delta >> 1

    def current_box_index(self, orientation: Sequence[int],
                          boxes: Sequence['Box']) -> int:
        """ Returns the index of the Box in <boxes> closest to this Box's
        center, with <orientation> deciding any tie. """
        return Box.closest_boxes(self.get_center(orientation), boxes,
                                 orientation)[0]

    @staticmethod
    def align_center(boxes: Sequence['Box'], axis: int, fix: int,
                     orientation: int) -> list['Box']:
        """Return new Boxes with their centers on one line along <axis>.

        <fix> is the index of the Box that does not move, and
        <orientation> decides which way a Box of even size along that
        axis is nudged.
        """
        if not boxes:
            return []
        center_box = boxes[fix]
        center_size = center_box.get_size()[axis]
        if center_size % 2 != 0:
            center_size += 1
        center_position = center_box.get_position()[axis]
        result: list[Box] = []
        for b in boxes:
            size = b.get_size()
            position = list(b.get_position())
            position[axis] = center_position + Box._box_to_center_offset_1d(
                center_size - size[axis], orientation)
            result.append(Box(size, position))
        return result

    @staticmethod
    def distribute(boxes: Sequence['Box'], axis: int, fix: int,
                   spacing: int = 0) -> list['Box']:
        """Return new Boxes laid end to end along <axis>, in their own order.

        <fix> is the index of the Box that does not move; the ones after
        it follow it and the ones before it lead up to it, with <spacing>
        pixels of gap.
        """
        if not boxes:
            return []
        # Every index is written by one of the two loops below, which
        # between them cover the whole range; the boxes handed in stand
        # in until then so that the list holds Boxes throughout.
        result = list(boxes)
        start = boxes[fix].get_position()[axis]

        partial_sum = start
        for index in range(fix, len(boxes)):
            size = boxes[index].get_size()
            position = list(boxes[index].get_position())
            position[axis] = partial_sum
            result[index] = Box(size, position)
            partial_sum += size[axis] + spacing

        partial_sum = start
        for index in range(fix - 1, -1, -1):
            size = boxes[index].get_size()
            position = list(boxes[index].get_position())
            partial_sum -= size[axis] + spacing
            position[axis] = partial_sum
            result[index] = Box(size, position)
        return result

    def wrapper_box(self, viewport_size: Sequence[int],
                    orientation: Sequence[int]) -> 'Box':
        """Return the area a scrollable viewport showing this Box covers.

        That is this Box in any dimension it fills the viewport in, and
        the viewport itself in any dimension it does not, centered on
        this Box with <orientation> deciding the odd pixel.
        """
        size = self.get_size()
        position = self.get_position()
        result_size = [max(c, v) for c, v
                       in zip(size, viewport_size, strict=True)]
        result_position = [
            Box._box_to_center_offset_1d(c - r, o) + p
            for c, r, o, p
            in zip(size, result_size, orientation, position, strict=True)]
        return Box(result_size, result_position)

    @staticmethod
    def bounding_box(boxes: Sequence['Box']) -> 'Box':
        """ Returns the union of <boxes>: the smallest Box containing
        all of them. """
        if not boxes:
            return Box((), ())
        # The first Box is the starting extent rather than a None to
        # compare against, which is the same answer without a sentinel.
        first = boxes[0]
        mins = list(first.get_position())
        maxes = [p + s for p, s in zip(first.get_position(), first.get_size())]
        for b in boxes:
            for i, (p, s) in enumerate(zip(b.get_position(), b.get_size())):
                mins[i] = min(mins[i], p)
                maxes[i] = max(maxes[i], p + s)
        return Box(tools.vector_sub(maxes, mins), mins)

    @staticmethod
    def intersect(box_a: 'Box', box_b: 'Box') -> 'Box':
        """Return the largest Box contained by both <box_a> and <box_b>.

        Boxes that do not overlap in some dimension give a negative size
        in it, since the two edges cross over.  Nothing here rejects
        that: the callers - the lens, and the "fit to size" zoom over a
        spread - intersect Boxes that are known to overlap, and a Box is
        not asked to be valid.
        """
        a_position = box_a.get_position()
        b_position = box_b.get_position()
        result_position = []
        result_size = []
        for a_start, a_length, b_start, b_length in zip(
                a_position, box_a.get_size(),
                b_position, box_b.get_size(), strict=True):
            start = max(a_start, b_start)
            end = min(a_start + a_length, b_start + b_length)
            result_position.append(start)
            result_size.append(end - start)
        return Box(result_size, result_position)


# vim: expandtab:sw=4:ts=4
