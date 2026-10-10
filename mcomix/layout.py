"""layout.py - Where the pages of a book are put on screen.

A layout holds one Box per page, laid out in a row along the
*distribution axis* and centred on the other, the *alignment axis*, and
the viewport Box that is the window looking at them.  Each page also has
a *wrapper* Box: the page grown to at least the size of the viewport, so
that a page smaller than the window still has somewhere to scroll to.
The union of the wrappers is the whole scrollable area.

An orientation is a vector of 1 and -1 saying which way each axis runs,
which is what turns the layout round for manga.
"""

import operator

from collections.abc import Callable, Sequence

from mcomix import constants
from mcomix import scrolling
from mcomix import tools
from mcomix import box


class FiniteLayout:  # 2D only

    """The pages of the open book, as Boxes, and the viewport on them."""

    @staticmethod
    def create_finite_layout(
            box_count: int, orientation: Sequence[int], spacing: int,
            distribution_axis: int, alignment_axis: int,
            scrollbar_update: Callable[[list[bool]], None],
            visible_area_update: Callable[[], Sequence[int]],
            sizes_update: Callable[
                [list[int]], tuple[Sequence[Sequence[int]], Sequence[bool]]]
            ) -> 'FiniteLayout':
        """Build the layout for a viewport size that settles.

        How large the pages are drawn depends on how large the viewport
        is, and how large the viewport is depends on which scrollbars
        are shown, which depends in turn on whether the pages fit.  So
        this asks for the sizes, lays them out, tells the window which
        scrollbars that needs and asks again, until the answer stops
        changing.

        A scrollbar that has been asked for is never taken back within
        one run - the requests are or-ed together - so the loop cannot
        oscillate between two answers.  The one thing that starts it
        over is needing both scrollbars, which is when the window is
        asked to expand its area instead.
        """
        viewport_size: Sequence[int] | None = None
        expand_area = False
        scrollbar_requests = [False] * 2  # 2D only
        while True:
            scrollbar_update(scrollbar_requests)
            new_viewport_size = visible_area_update()
            if new_viewport_size == viewport_size:
                break
            viewport_size = new_viewport_size
            # The pages are scaled to the viewport with the spacing
            # between them taken out of it first, since that is room
            # they cannot have.
            zoom_dummy_size: list[int] = list(viewport_size)
            dasize = zoom_dummy_size[distribution_axis] - \
                spacing * (box_count - 1)
            if dasize <= 0:
                dasize = 1
            zoom_dummy_size[distribution_axis] = dasize
            scaled_sizes_distorted = sizes_update(zoom_dummy_size)
            result = FiniteLayout(scaled_sizes_distorted[0], scaled_sizes_distorted[1],
                                  viewport_size, orientation, spacing, expand_area,
                                  distribution_axis=distribution_axis,
                                  alignment_axis=alignment_axis)
            union_scaled_size = result.get_union_box().get_size()
            scrollbar_requests = list(map(operator.or_, scrollbar_requests,
                                          tools.smaller(viewport_size, union_scaled_size)))
            if sum(scrollbar_requests) > 1 and not expand_area:
                expand_area = True
                viewport_size = None  # start anew
        return result

    def __init__(self, content_sizes: Sequence[Sequence[int]],
                 content_distorted: Sequence[bool],
                 viewport_size: Sequence[int], orientation: Sequence[int],
                 spacing: int, wrap_individually: bool,
                 distribution_axis: int, alignment_axis: int) -> None:
        """Lay out Boxes of <content_sizes> along the distribution axis.

        <content_distorted> says, for each of them, whether it was
        scaled without keeping its aspect ratio; the layout only carries
        that on to whoever draws the page.  <spacing> is the gap left
        between one Box and the next.  <wrap_individually> gives each
        Box a wrapper Box of its own, which is what lets a scroll step
        run off the end of one page and on to the next; without it the
        only wrapper is the union of them all.
        """
        self.scroller = scrolling.Scrolling()
        self.current_index = -1
        # Filled in by _reset() below, which is also how a layout is
        # given a new set of pages later on.
        self.content_boxes: list[box.Box]
        self.content_distorted: Sequence[bool]
        self.wrapper_boxes: list[box.Box]
        self.union_box: box.Box
        self.viewport_box: box.Box
        self.orientation: Sequence[int]
        self.dirty_current_index: bool
        self.wrap_individually = wrap_individually
        self._distribution_axis = distribution_axis
        #: Which of the pages standing side by side is being read, where
        #: scrolling cannot tell: see pages_abreast().
        self.reading_pass = 0
        #: How many pages the content stands for, where that is more
        #: than its Boxes: a single scan of two facing pages is two.
        self.spread_pages: int | None = None
        self._reset(content_sizes, content_distorted, viewport_size, orientation,
                    spacing, wrap_individually, distribution_axis, alignment_axis)

    def set_viewport_position(self, viewport_position: Sequence[int]) -> None:
        """Move the viewport to <viewport_position>."""
        self.viewport_box = self.viewport_box.set_position(viewport_position)
        self.dirty_current_index = True

    def scroll_smartly(self, max_scroll: Sequence[float], backwards: bool,
                       axis_map: Sequence[int] | None,
                       index: int | None = None) -> int:
        """Take one "smart scrolling" step, at most <max_scroll> pixels.

        <axis_map> is the order the axes are stepped through in, and
        <index> the Box the step is measured against, the current one by
        default.  Scrolling backwards runs the orientation the other
        way.

        The answer is the index of the current Box afterwards, and the
        viewport has been moved to match.  Where there was nothing left
        to scroll to it is an index outside the layout instead, and the
        viewport has not moved: -1 for running off the start and the
        number of Boxes for running off the end, which is what tells the
        caller to turn the page rather than to redraw.
        """
        if (index is None) or (not self.wrap_individually):
            index = self.get_current_index()
        if not self.wrap_individually:
            wrapper_index = 0
        else:
            wrapper_index = index
        direction = tools.vector_opposite(self.orientation) if backwards \
            else self.orientation
        new_pos = self.scroller.scroll_smartly(self.wrapper_boxes[wrapper_index],
                                               self.viewport_box, direction,
                                               max_scroll, axis_map)
        if new_pos == []:
            if self.wrap_individually:
                index += -1 if backwards else 1
                # The Box moved to is scrolled to the edge the reader
                # is arriving from, so that a step off the end of one
                # page lands at the start of the next rather than
                # somewhere in the middle of it.
                if 0 <= index < len(self.get_content_boxes()):
                    self.scroll_to_predefined(
                        tools.vector_opposite(direction), index)
                return index
            else:
                return -1 if backwards else len(self.get_content_boxes())
        self.set_viewport_position(new_pos)
        # Asked again: a spread is one wrapper Box, and the step may have
        # crossed from one of its pages into the other.
        return self.get_current_index()

    def scroll_to_predefined(self, destination: Sequence[int],
                             index: int | None = None) -> None:
        """Scroll the viewport to <destination>, a vector of one code
        per axis.

        Each is 1 (towards the greatest values in this dimension), -1
        (towards the smallest), 0 (keep the position), or one of
        SCROLL_TO_CENTER, SCROLL_TO_START and SCROLL_TO_END, which are
        relative to the content rather than to the axis.

        <index> is the Box to scroll within, the current one by default,
        or UNION_INDEX for the union box.  A layout that does not wrap
        its pages individually has only the union box, and uses it
        whatever the index says.
        """
        if index == constants.FIRST_INDEX:
            self.reading_pass = 0
        elif index == constants.LAST_INDEX:
            # Arrived at from the page after it, so the last of the
            # pages side by side is the one being read.
            self.reading_pass = self._pages() - 1
        if index is None:
            index = self.get_current_index()
        if not self.wrap_individually:
            index = constants.UNION_INDEX
        if index == constants.UNION_INDEX:
            current_box = self.union_box
        else:
            if index == constants.LAST_INDEX:
                index = len(self.content_boxes) - 1
            current_box = self.wrapper_boxes[index]
        self.set_viewport_position(self.scroller.scroll_to_predefined(
            current_box, self.viewport_box, self.orientation, destination))

    def pages_abreast(self) -> int:
        """How many pages have to be read one after the other although
        the viewport shows them all at once.

        Two pages side by side that fit the window's width and not its
        height scroll as one: down, and that is the end of them.  They
        are read as two all the same, the first to its bottom and then
        the second from its top (upstream feature request 124).  So is
        one picture holding both pages, which the window says through
        <spread_pages>.  One wherever scrolling already tells the pages
        apart, or there is nothing to scroll.
        """
        if self.wrap_individually or self._pages() < 2:
            return 1
        across = self._distribution_axis
        along = 1 - across  # 2D only
        viewport = self.viewport_box.get_size()
        union = self.union_box.get_size()
        if union[across] > viewport[across] or union[along] <= viewport[along]:
            return 1
        return self._pages()

    def _pages(self) -> int:
        return self.spread_pages or len(self.content_boxes)

    def _page_abreast_after(self, backwards: bool) -> "int | None":
        abreast = self.pages_abreast()
        after = min(self.reading_pass, abreast - 1) + (-1 if backwards else 1)
        return after if 0 <= after < abreast else None

    def has_page_abreast_left(self, backwards: bool) -> bool:
        """Whether another of the pages side by side is still to be
        read once scroll_smartly() has run off the end of them."""
        return self._page_abreast_after(backwards) is not None

    def read_next_page_abreast(self, backwards: bool) -> None:
        """Go on to the next of the pages side by side: back to the
        edge the reader starts a page from."""
        after = self._page_abreast_after(backwards)
        if after is None:
            return
        self.reading_pass = after
        direction = tools.vector_opposite(self.orientation) if backwards \
            else self.orientation
        self.scroll_to_predefined(tools.vector_opposite(direction))

    def get_content_boxes(self) -> list[box.Box]:
        """The Boxes the pages are drawn in, in the order laid out."""
        return self.content_boxes

    def get_content_distorted(self) -> Sequence[bool]:
        """Whether each content Box was scaled without keeping its
        aspect ratio."""
        return self.content_distorted

    def get_union_box(self) -> box.Box:
        """The Box covering every wrapper Box: the whole scrollable
        area."""
        return self.union_box

    def get_current_index(self) -> int:
        """The index of the Box the viewport is looking at.

        Worked out from the viewport's position when it has moved since
        the last answer, and remembered until it moves again.
        """
        if self.dirty_current_index:
            self.current_index = self.viewport_box.current_box_index(
                self.orientation, self.content_boxes)
            self.dirty_current_index = False
        return self.current_index

    def get_viewport_box(self) -> box.Box:
        """The Box the window is looking through."""
        return self.viewport_box

    def get_orientation(self) -> Sequence[int]:
        """Which way each axis of this layout runs."""
        return self.orientation

    def set_orientation(self, orientation: Sequence[int]) -> None:
        """Set which way each axis runs, 1 forwards and -1 backwards.

        Manga mode is the reason there is one: it runs the distribution
        axis backwards, so that the first page is the rightmost.  Nothing
        is laid out again here - the caller does that.
        """
        self.orientation = orientation

    def _reset(self, content_sizes: Sequence[Sequence[int]],
               content_distorted: Sequence[bool],
               viewport_size: Sequence[int], orientation: Sequence[int],
               spacing: int, wrap_individually: bool,
               distribution_axis: int, alignment_axis: int) -> None:
        """Lay the pages out afresh and work out what can be scrolled.

        One Box per page, of the sizes in <content_sizes>, centred against
        each other along <alignment_axis> and set side by side along
        <distribution_axis> with <spacing> between them.  Each then gets a
        wrapper Box saying how far the viewport may move over it: one
        wrapper per page where <wrap_individually> holds, so that scrolling
        stops at each page in turn, and otherwise a single wrapper round
        the lot.  <content_distorted> says which pages were scaled without
        keeping their ratio, which is what decides whether a page is
        allowed to be scrolled at all.

        Everything here is in the layout's own coordinates, with the union
        of the pages at the origin; set_viewport_position() is what moves
        the window's view over them afterwards.
        """
        # The Boxes are laid out left to right and reversed afterwards
        # for an axis that runs the other way, rather than the
        # distribution being taught to run backwards.
        if orientation[distribution_axis] == -1:
            content_sizes = tuple(reversed(content_sizes))
        content_boxes = list(map(box.Box, content_sizes))
        content_boxes = box.Box.align_center(content_boxes, alignment_axis, 0,
                                             orientation[alignment_axis])
        content_boxes = box.Box.distribute(content_boxes, distribution_axis, 0,
                                           spacing)
        if wrap_individually:
            wrapper_boxes, union_box = FiniteLayout._wrap_individually(
                content_boxes, viewport_size, orientation)
        else:
            wrapper_boxes, union_box = FiniteLayout._wrap_union(
                content_boxes, viewport_size, orientation)
        # Everything is placed relative to the union Box, so moving that
        # to the origin puts the whole layout into the coordinates the
        # viewport is in.
        origin = union_box.get_position()
        content_boxes = [each.translate_opposite(origin)
                         for each in content_boxes]
        wrapper_boxes = [each.translate_opposite(origin)
                         for each in wrapper_boxes]
        union_box = union_box.translate_opposite(origin)
        if orientation[distribution_axis] == -1:
            content_boxes = list(reversed(content_boxes))
            wrapper_boxes = list(reversed(wrapper_boxes))
        self.content_boxes = content_boxes
        self.content_distorted = content_distorted
        self.wrapper_boxes = wrapper_boxes
        self.union_box = union_box
        self.viewport_box = box.Box(viewport_size)
        self.orientation = orientation
        self.dirty_current_index = True

    @staticmethod
    def _wrap_individually(
            content_boxes: list[box.Box], viewport_size: Sequence[int],
            orientation: Sequence[int]) -> tuple[list[box.Box], box.Box]:
        """A wrapper Box per content Box, and the Box bounding them all.

        A wrapper is at least as large as the viewport, so it may well
        reach past the neighbouring pages; the bounding Box is what the
        viewport is allowed to move within.
        """
        wrapper_boxes = [content_box.wrapper_box(viewport_size, orientation)
                         for content_box in content_boxes]
        return (wrapper_boxes, box.Box.bounding_box(wrapper_boxes))

    @staticmethod
    def _wrap_union(
            content_boxes: list[box.Box], viewport_size: Sequence[int],
            orientation: Sequence[int]) -> tuple[list[box.Box], box.Box]:
        """One wrapper Box around every content Box, which is also the
        bounding Box."""
        wrapper_boxes = [box.Box.bounding_box(content_boxes).wrapper_box(
            viewport_size, orientation)]
        return (wrapper_boxes, wrapper_boxes[0])


def create_dummy_layout() -> FiniteLayout:
    """A one-page layout of a single pixel, for a window with no book
    open in it."""
    # One Box, so one flag saying whether it was distorted:
    # get_content_distorted() answers one flag per Box.
    return FiniteLayout(((1, 1),), (False,), (1, 1), (1, 1), 0, False, 0, 0)


# vim: expandtab:sw=4:ts=4
