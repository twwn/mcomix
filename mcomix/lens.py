"""lens.py - Magnifying lens."""


from collections.abc import Sequence
from typing import Any, TYPE_CHECKING

from gi.repository import GdkPixbuf, Graphene, Gtk

from mcomix.preferences import prefs
from mcomix import image_tools
from mcomix import constants
from mcomix import box
from mcomix import tools

if TYPE_CHECKING:
    from mcomix import main
    from mcomix import ui


class MagnifyingLens:

    """The MagnifyingLens creates cursors from the raw pixbufs containing
    the unscaled data for the currently displayed images. It does this by
    looking at the cursor position and calculating what image data to put
    in the "lens" cursor.

    Note: The mapping is highly dependent on the exact layout of the main
    window images, thus this module isn't really independent from the main
    module as it uses implementation details not in the interface.
    """

    #: What the lens is called among the canvas' overlays.
    _OVERLAY = 'lens'

    def __init__(self, window: 'main.MainWindow') -> None:
        self._window = window
        self._area = self._window._main_layout
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._motion_event)
        self._area.add_controller(motion)

        #: Stores lens state
        self._enabled = False
        #: Stores a tuple of the last mouse coordinates
        self._point: tuple[int, int] | None = None
        #: Stores the last rectangle that was used to render the lens
        self._last_lens_rect: tuple[int, int, int, int] | None = None

    def get_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

        if enabled:
            self._window.osd.clear()

        self._follow_state()

    enabled = property(get_enabled, set_enabled)

    def file_changed(self) -> None:
        """Follow a file being opened or closed.

        The lens can be switched on with no file open, and was left on
        when one was closed; either way it hides the cursor over pages
        that are not there.
        """
        if self._enabled:
            self._follow_state()

    def _follow_state(self) -> None:
        """Take the cursor and the lens to where the state says.

        The cursor goes only while the lens has something to draw over:
        hiding it over an empty window leaves the pointer invisible with
        nothing to show for it.
        """
        if self._enabled and self._window.filehandler.file_loaded:
            self._window.cursor_handler.set_cursor_type(constants.NO_CURSOR)

            if self._point:
                self._draw_lens(*self._point)
        else:
            self._window.cursor_handler.set_cursor_type(constants.NORMAL_CURSOR)
            self._clear_lens()
            self._last_lens_rect = None

    def _draw_lens(self, x: int, y: int) -> None:
        """Calculate what image data to put in the lens and update the cursor
        with it; <x> and <y> are the positions of the cursor within the
        main window layout area.
        """
        # A Gtk.Picture with nothing in it has nothing to magnify.
        if self._window.images[0].get_paintable() is None:
            return

        lens_size = (prefs['lens size'],) * 2 # 2D only
        border_size = 1
        rectangle = self._calculate_lens_rect(x, y, *lens_size, border_size)

        pixbuf = self._get_lens_pixbuf(x, y, lens_size, border_size,
            (x - rectangle[0], y - rectangle[1]))

        # There is no window to paint into any more: the canvas draws the
        # lens over the pages, and works out for itself what that damages.
        texture = image_tools.pixbuf_to_texture(pixbuf)
        bounds = Graphene.Rect()
        bounds.init(*rectangle)
        self._area.set_overlay(
            self._OVERLAY,
            lambda snapshot: snapshot.append_texture(texture, bounds))

        self._last_lens_rect = rectangle

    def _calculate_lens_rect(self, x: int, y: int, width: int, height: int,
                             border_size: int) -> tuple[int, int, int, int]:
        """ Calculates the area where the lens will be drawn on screen. This method takes
        screen space into calculation and moves the rectangle accordingly when the the rectangle
        would otherwise flow over the allocated area. """

        lens_x = max(x - width // 2, 0)
        lens_y = max(y - height // 2, 0)

        max_width, max_height = self._window.get_visible_area_size()
        max_width += int(self._window._hadjust.get_value())
        max_height += int(self._window._vadjust.get_value())
        lens_x = min(lens_x, max_width - width)
        lens_y = min(lens_y, max_height - height)

        return lens_x, lens_y, width + 2 * border_size, height + 2 * border_size

    def _clear_lens(self, current_lens_region: Any = None) -> None:
        """ Takes the lens off the pages again. """

        if not self._last_lens_rect:
            return

        self._area.set_overlay(self._OVERLAY, None)
        self._last_lens_rect = None

    def toggle(self, action: "ui._Action") -> None:
        """Toggle on or off the lens depending on the state of <action>."""
        self.enabled = action.get_active()

    def _motion_event(self, controller: Any, x: float, y: float) -> None:
        """ Called whenever the mouse moves over the image area. """
        # The lens works in canvas coordinates, which is what the events
        # on Gtk.Layout's scrolling window carried; a controller reports
        # where the pointer is in the widget instead.
        self._point = (int(x + self._window._hadjust.get_value()),
                       int(y + self._window._vadjust.get_value()))
        if self.enabled:
            self._draw_lens(*self._point)

    def _get_lens_pixbuf(self, x: int, y: int, lens_size: Sequence[int],
                         border_size: int,
                         check_offset: Sequence[int]) -> GdkPixbuf.Pixbuf:
        """Get a pixbuf containing the appropiate image data for the lens
        where <x> and <y> are the positions of the cursor.
        """
        cb = self._window.layout.get_content_boxes()
        source_pixbufs = self._window.imagehandler.get_pixbufs(len(cb))
        transforms = self._window.transforms
        lens_scale = (prefs['lens magnification'],) * 2 # 2D only
        opaque = prefs['checkered bg for transparent images'] or not any(
            map(GdkPixbuf.Pixbuf.get_has_alpha, source_pixbufs))
        canvas = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
            has_alpha=not opaque, bits_per_sample=8, width=lens_size[0],
            height=lens_size[1]) # 2D only
        assert canvas is not None, 'the lens could not be allocated'
        canvas.fill(image_tools.convert_rgba_to_rgba8int(self._window.get_bg_colour()))
        for b, source_pixbuf, tf in zip(cb, source_pixbufs, transforms):
            if image_tools.is_animation(source_pixbuf):
                continue
            cpos = b.get_position()
            # The scale is decomposed too, and dropped: the transform
            # carries the turn and the flips a page was drawn with, not
            # the size it was fitted to.  That is the content box's, and
            # _draw_lens_pixbuf() works it out from there.
            _scale, rotation, flips = tf.to_image_transforms()
            composite_color_args = image_tools.get_composite_color_args(0) if \
                source_pixbuf.get_has_alpha() and opaque else None
            self._draw_lens_pixbuf((x - cpos[0], y - cpos[1]), b.get_size(),
                source_pixbuf, rotation, flips,
                lens_size, lens_scale, canvas, prefs['scaling quality'],
                composite_color_args, (x - border_size - check_offset[0],
                y - border_size - check_offset[1])) # 2D only

        canvas = self._window.enhancer.enhance(canvas)

        return image_tools.add_border(canvas, border_size)

    def _draw_lens_pixbuf(self, ref_pos: Sequence[int], csize: Sequence[int],
                          srcbuf: GdkPixbuf.Pixbuf, rotation: int,
                          flips: Sequence[bool], lens_size: Sequence[int],
                          lens_scale: Sequence[float],
                          dstbuf: GdkPixbuf.Pixbuf,
                          interpolation: GdkPixbuf.InterpType,
                          composite_color_args: tuple[int, int, int] | None,
                          check_offset: Sequence[int]) -> None:
        if tools.volume(csize) == 0:
            return

        # Some computations are the same for each axis.
        def calc_1d(ref_pos: int, csize: int, src_pixbuf_size: int,
                    lens_size: int, lens_scale: float) -> tuple[Any, ...]:
            # compute initial scales, sizes and positions
            page_scale = csize / src_pixbuf_size
            source_ref_pos = ref_pos / page_scale
            combined_source_scale = page_scale * lens_scale
            mapped_ref_pos = source_ref_pos * combined_source_scale
            mapped_ref_pos_int = int(round(mapped_ref_pos * 2)) // 2
            mapped_size = int(round(src_pixbuf_size * combined_source_scale))
            # take rounding errors into account
            applied_source_scale = mapped_size / src_pixbuf_size
            # calculate data for clamping
            lens_size_2q, lens_size_2r = divmod(lens_size, 2)
            neg_mapped_lens_pos = lens_size_2q - mapped_ref_pos_int
            dest_lens_offset = neg_mapped_lens_pos
            dest_lens_end = dest_lens_offset + mapped_size
            # clamp to lens
            dest_lens_end = min(dest_lens_end, lens_size)
            dest_lens_offset = max(0, dest_lens_offset)
            dest_lens_size = dest_lens_end - dest_lens_offset
            return applied_source_scale, neg_mapped_lens_pos, dest_lens_offset, \
                dest_lens_size, mapped_size, mapped_ref_pos_int, lens_size_2q, lens_size_2r

        # prepare actual computation
        src_pixbuf_size = [srcbuf.get_width(), srcbuf.get_height()] # 2D only
        transpose = (1, 0) if tools.rotation_swaps_axes(rotation) else (0, 1) # 2D only
        def tp[T](vector: Sequence[T]) -> list[T]:
            """<vector> with its two axes the way round the rotation put them."""
            return tools.remap_axes(vector, transpose)

        axis_flip = tuple(map(lambda r, f: (rotation in r) ^ f, ((270, 180), (90, 180)), tp(flips))) # 2D only

        # calculate size and position data
        applied_source_scale, neg_mapped_lens_pos, dest_lens_offset, dest_lens_size, \
            mapped_size, mapped_ref_pos_int, lens_size_2q, lens_size_2r = \
            [list(x) for x in zip(*(map(calc_1d, tp(ref_pos), tp(csize),
            src_pixbuf_size, tp(lens_size), tp(lens_scale))))]

        if min(dest_lens_size) > 0:
            # Using GdkPixbuf.Pixbuf.scale here so we do not need to worry about
            # interpolation issues when close to the edges. Also, one can exploit it
            # later to only recompute the parts of the lens where the content might
            # have changed.
            if any(flips) or any(axis_flip):
                # Unfortuantely, GdkPixbuf does not seem to provide an API for applying
                # arbitrary matrix transforms the same way, which is why we need to
                # apply inefficient workarounds.

                # keep track of (mirrored) reference point
                refpos_tracking = list(mapped_ref_pos_int)
                for i, s in enumerate(axis_flip):
                    if s:
                        # Subtracting the remainder keeps a lens with an odd number
                        # of pixels centered at the (mirrored) reference point.
                        refpos_tracking[i] = mapped_size[i] - refpos_tracking[i] - lens_size_2r[i]
                refpos_tracking = tools.vector_sub(refpos_tracking, lens_size_2q)

                # write to temporary buffer
                tempbuf = GdkPixbuf.Pixbuf.new(srcbuf.get_colorspace(),
                    srcbuf.get_has_alpha(), srcbuf.get_bits_per_sample(), *dest_lens_size)
                assert tempbuf is not None, 'the lens buffer could not be allocated'
                temp_lens_box = box.Box.intersect(box.Box(lens_size, position=refpos_tracking),
                    box.Box(mapped_size))
                temp_x, temp_y = tools.vector_opposite(
                    temp_lens_box.get_position())
                srcbuf.scale(tempbuf, 0, 0, dest_lens_size[0], dest_lens_size[1],
                    temp_x, temp_y,
                    applied_source_scale[0], applied_source_scale[1],
                    interpolation) # 2D only

                # apply all necessary transforms to temporary buffer
                tempbuf = image_tools.rotate_pixbuf(tempbuf, rotation)
                for i, f in enumerate(flips):
                    if f:
                        tempbuf = image_tools.flip_pixbuf(tempbuf, i)

                # Not sure whether it should be inverse axis remapping instead of
                # forward, but in 2D, there is no difference anyway.
                # 2D only, and spelled out rather than starred: the
                # destination arguments of both calls below are followed
                # by more of them, which a starred vector cannot express.
                dest_x, dest_y = tp(dest_lens_offset)
                dest_width, dest_height = tp(dest_lens_size)

                # copy result from temporary buffer to actual lens buffer
                if composite_color_args is None:
                    tempbuf.copy_area(0, 0, dest_width, dest_height, dstbuf,
                        dest_x, dest_y)
                else:
                    check_x, check_y = tools.vector_add(tp(dest_lens_offset),
                                                        check_offset)
                    tempbuf.composite_color(dstbuf, dest_x, dest_y,
                        dest_width, dest_height, dest_x, dest_y, 1, 1,
                        GdkPixbuf.InterpType.NEAREST, 255, check_x, check_y,
                        *composite_color_args)
                # unref temporary buffer
                tempbuf = None
            else:
                # no workaround needed
                # 2D only, and spelled out rather than starred: the
                # destination arguments are followed by more of them,
                # which a starred vector cannot express.
                if composite_color_args is None:
                    srcbuf.scale(dstbuf, dest_lens_offset[0], dest_lens_offset[1],
                        dest_lens_size[0], dest_lens_size[1],
                        neg_mapped_lens_pos[0], neg_mapped_lens_pos[1],
                        applied_source_scale[0], applied_source_scale[1],
                        interpolation)
                else:
                    check_x, check_y = tools.vector_add(dest_lens_offset,
                                                        check_offset)
                    srcbuf.composite_color(dstbuf,
                        dest_lens_offset[0], dest_lens_offset[1],
                        dest_lens_size[0], dest_lens_size[1],
                        neg_mapped_lens_pos[0], neg_mapped_lens_pos[1],
                        applied_source_scale[0], applied_source_scale[1],
                        interpolation, 255, check_x, check_y,
                        *composite_color_args)
        else:
            # If we are here, there is either no image to be drawn at all, or it is
            # out of range.
            pass


# vim: expandtab:sw=4:ts=4
