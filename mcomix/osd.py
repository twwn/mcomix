""" osd.py - Onscreen display showing currently opened file. """
# -*- coding: utf-8 -*-

import textwrap

from gi.repository import GLib, Graphene
from gi.repository import Pango, PangoCairo

from mcomix import image_tools


class OnScreenDisplay(object):

    """ The OSD shows information such as currently opened file, archive and
    page in a black box drawn on the bottom end of the screen.

    The OSD will automatically be erased after TIMEOUT seconds.
    """

    TIMEOUT = 3

    #: What the OSD is called among the canvas' overlays.
    _OVERLAY = 'osd'

    def __init__(self, window):
        #: MainWindow
        self._window = window
        #: Stores the last rectangle that was used to render the OSD
        self._last_osd_rect = None
        #: Timeout event ID registered while waiting to hide the OSD
        self._timeout_event = None

    def show(self, text):
        """ Shows the OSD on the lower portion of the image window. """

        # Determine text to draw
        text = self._wrap_text(text)
        layout = self._window._main_layout.create_pango_layout(text)

        # Set up font information
        font = layout.get_context().get_font_description()
        font.set_weight(Pango.Weight.BOLD)
        layout.set_alignment(Pango.Alignment.CENTER)

        # Scale font to fit within the screen size
        max_width, max_height = self._window.get_visible_area_size()
        self._scale_font(font, layout, max_width, max_height)

        # Calculate surrounding box
        layout_width, layout_height = layout.get_pixel_size()
        pos_x = max(int(max_width // 2) - int(layout_width // 2) +
                    int(self._window._hadjust.get_value()), 0)
        pos_y = max(int(max_height) - int(layout_height * 1.1) +
                    int(self._window._vadjust.get_value()), 0)

        rect = (pos_x - 10, pos_y - 20,
                layout_width + 20, layout_height + 20)

        self._draw_osd(layout, rect)

        self._last_osd_rect = rect
        if self._timeout_event:
            GLib.source_remove(self._timeout_event)
        self._timeout_event = GLib.timeout_add_seconds(
            OnScreenDisplay.TIMEOUT, self.clear)

    def clear(self) -> int:
        """ Removes the OSD. """
        if self._timeout_event:
            GLib.source_remove(self._timeout_event)
        self._timeout_event = None
        self._clear_osd()
        return 0 # To unregister gobject timer event

    def _wrap_text(self, text, width=70):
        """ Wraps the text to be C{width} characters at most. """
        parts = text.split('\n')
        result = []

        for part in parts:
            if part:
                result.extend(textwrap.wrap(part, width))
            else:
                result.append(part)

        return "\n".join(result)

    def _clear_osd(self) -> None:
        """ Take the OSD off the pages again. """

        if not self._last_osd_rect:
            return

        self._window._main_layout.set_overlay(self._OVERLAY, None)
        self._last_osd_rect = None

    def _scale_font(self, font, layout, max_width, max_height):
        """ Scales the font used by C{layout} until max_width/max_height is reached. """

        SIZE_MIN, SIZE_MAX = 10, 60
        for font_size in range(SIZE_MIN, SIZE_MAX, 5):
            old_size = font.get_size()
            font.set_size(font_size * Pango.SCALE)
            layout.set_font_description(font)

            if layout.get_pixel_size()[0] > max_width:
                font.set_size(old_size)
                layout.set_font_description(font)
                break

    def _draw_osd(self, layout, rect):
        """ Draws the text specified in C{layout} into a box at C{rect}. """

        # There is no window to paint into any more, and no damage to
        # work out: the canvas draws the OSD over the pages, and cairo
        # is still what draws it - a snapshot hands one out.
        def draw(snapshot) -> None:
            bounds = Graphene.Rect()
            bounds.init(*rect)
            cr = snapshot.append_cairo(bounds)
            black = image_tools.RGBA_BLACK
            cr.set_source_rgb(black.red, black.green, black.blue)
            cr.rectangle(*rect)
            cr.fill()
            extents = layout.get_extents()[0]
            white = image_tools.RGBA_WHITE
            cr.set_source_rgb(white.red, white.green, white.blue)
            cr.translate(rect[0] + extents.x / Pango.SCALE,
                         rect[1] + extents.y / Pango.SCALE)
            PangoCairo.update_layout(cr, layout)
            PangoCairo.show_layout(cr, layout)

        self._window._main_layout.set_overlay(self._OVERLAY, draw)

# vim: expandtab:sw=4:ts=4
