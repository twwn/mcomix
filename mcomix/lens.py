"""lens.py - Magnifying lens."""


from gi.repository import Gdk, GdkPixbuf, Gtk

from mcomix.preferences import prefs
from mcomix import image_tools
from mcomix import constants
from mcomix import box
from mcomix import tools


class MagnifyingLens(object):

    """The MagnifyingLens creates cursors from the raw pixbufs containing
    the unscaled data for the currently displayed images. It does this by
    looking at the cursor position and calculating what image data to put
    in the "lens" cursor.

    Note: The mapping is highly dependent on the exact layout of the main
    window images, thus this module isn't really independent from the main
    module as it uses implementation details not in the interface.
    """

    def __init__(self, window):
        self._window = window
        self._area = self._window._main_layout
        self._area.connect('motion-notify-event', self._motion_event)

        #: Stores lens state
        self._enabled = False
        #: Stores a tuple of the last mouse coordinates
        self._point = None
        #: Stores the last rectangle that was used to render the lens
        self._last_lens_rect = None

    def get_enabled(self):
        return self._enabled

    def set_enabled(self, enabled):
        self._enabled = enabled

        if enabled:
            # FIXME: If no file is currently loaded, the cursor will still be hidden.
            self._window.cursor_handler.set_cursor_type(constants.NO_CURSOR)
            self._window.osd.clear()

            if self._point:
                self._draw_lens(*self._point)
        else:
            self._window.cursor_handler.set_cursor_type(constants.NORMAL_CURSOR)
            self._clear_lens()
            self._last_lens_rect = None

    enabled = property(get_enabled, set_enabled)

    def _draw_lens(self, x, y):
        """Calculate what image data to put in the lens and update the cursor
        with it; <x> and <y> are the positions of the cursor within the
        main window layout area.
        """
        if self._window.images[0].get_storage_type() not in (Gtk.ImageType.PIXBUF,
            Gtk.ImageType.ANIMATION):
            return

        lens_size = (prefs['lens size'],) * 2 # 2D only
        border_size = 1
        rectangle = self._calculate_lens_rect(x, y, *lens_size, border_size)

        draw_region = Gdk.Rectangle()
        draw_region.x, draw_region.y, draw_region.width, draw_region.height = rectangle
        if self._last_lens_rect:
            last_region = Gdk.Rectangle()
            last_region.x, last_region.y, last_region.width, last_region.height = self._last_lens_rect
            draw_region = Gdk.rectangle_union(draw_region, last_region)

        pixbuf = self._get_lens_pixbuf(x, y, lens_size, border_size,
            (x - rectangle[0], y - rectangle[1]))
        window = self._window._main_layout.get_bin_window()
        window.begin_paint_rect(draw_region)

        self._clear_lens()

        cr = window.cairo_create()
        surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, 0, window)
        cr.set_source_surface(surface, rectangle[0], rectangle[1])
        cr.paint()

        window.end_paint()

        self._last_lens_rect = rectangle

    def _calculate_lens_rect(self, x, y, width, height, border_size):
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

    def _clear_lens(self, current_lens_region=None):
        """ Invalidates the area that was damaged by the last call to draw_lens. """

        if not self._last_lens_rect:
            return

        window = self._window._main_layout.get_bin_window()
        crect = Gdk.Rectangle()
        crect.x, crect.y, crect.width, crect.height = self._last_lens_rect
        window.invalidate_rect(crect, True)
        window.process_updates(True)
        self._last_lens_rect = None

    def toggle(self, action):
        """Toggle on or off the lens depending on the state of <action>."""
        self.enabled = action.get_active()

    def _motion_event(self, widget, event):
        """ Called whenever the mouse moves over the image area. """
        self._point = (int(event.x), int(event.y))
        if self.enabled:
            self._draw_lens(*self._point)

    def _get_lens_pixbuf(self, x, y, lens_size, border_size, check_offset):
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
        canvas.fill(image_tools.convert_rgba_to_rgba8int(self._window.get_bg_colour()))
        for b, source_pixbuf, tf in zip(cb, source_pixbufs, transforms):
            if image_tools.is_animation(source_pixbuf):
                continue
            cpos = b.get_position()
            _scale, rotation, flips = tf.to_image_transforms() # FIXME use scale as soon as it is correctly included
            composite_color_args = image_tools.get_composite_color_args(0) if \
                source_pixbuf.get_has_alpha() and opaque else None
            self._draw_lens_pixbuf((x - cpos[0], y - cpos[1]), b.get_size(),
                source_pixbuf, rotation, flips,
                lens_size, lens_scale, canvas, prefs['scaling quality'],
                composite_color_args, (x - border_size - check_offset[0],
                y - border_size - check_offset[1])) # 2D only

        canvas = self._window.enhancer.enhance(canvas)

        return image_tools.add_border(canvas, border_size)

    def _draw_lens_pixbuf(self, ref_pos, csize, srcbuf, rotation, flips,
        lens_size, lens_scale, dstbuf, interpolation, composite_color_args,
        check_offset):
        if tools.volume(csize) == 0:
            return

        # Some computations are the same for each axis.
        def calc_1d(ref_pos, csize, src_pixbuf_size, lens_size, lens_scale):
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
        tp = lambda x: tools.remap_axes(x, transpose)
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
                temp_lens_box = box.Box.intersect(box.Box(lens_size, position=refpos_tracking),
                    box.Box(mapped_size))
                srcbuf.scale(tempbuf, 0, 0, *dest_lens_size,
                    *tools.vector_opposite(temp_lens_box.get_position()),
                    *applied_source_scale, interpolation) # 2D only

                # apply all necessary transforms to temporary buffer
                tempbuf = image_tools.rotate_pixbuf(tempbuf, rotation)
                for i, f in enumerate(flips):
                    if f:
                        tempbuf = image_tools.flip_pixbuf(tempbuf, i)

                # Not sure whether it should be inverse axis remapping instead of
                # forward, but in 2D, there is no difference anyway.
                remapped_dest_lens_offset = tp(dest_lens_offset)
                remapped_dest_lens_size = tp(dest_lens_size)

                # copy result from temporary buffer to actual lens buffer
                if composite_color_args is None:
                    tempbuf.copy_area(0, 0, *remapped_dest_lens_size, dstbuf,
                        *remapped_dest_lens_offset) # 2D only
                else:
                    tempbuf.composite_color(dstbuf, *remapped_dest_lens_offset,
                        *remapped_dest_lens_size, *remapped_dest_lens_offset, 1, 1,
                        GdkPixbuf.InterpType.NEAREST, 255,
                        *tools.vector_add(tp(dest_lens_offset), check_offset),
                        *composite_color_args) # 2D only
                # unref temporary buffer
                tempbuf = None
            else:
                # no workaround needed
                if composite_color_args is None:
                    srcbuf.scale(dstbuf, *dest_lens_offset, *dest_lens_size,
                        *neg_mapped_lens_pos, *applied_source_scale, interpolation) # 2D only
                else:
                    srcbuf.composite_color(dstbuf, *dest_lens_offset, *dest_lens_size,
                        *neg_mapped_lens_pos, *applied_source_scale, interpolation,
                        255, *tools.vector_add(dest_lens_offset, check_offset),
                        *composite_color_args) # 2D only
        else:
            # If we are here, there is either no image to be drawn at all, or it is
            # out of range.
            pass
        return dstbuf


# vim: expandtab:sw=4:ts=4
