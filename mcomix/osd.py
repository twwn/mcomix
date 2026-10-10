""" osd.py - Onscreen display showing currently opened file. """

import textwrap

from gi.repository import GLib, Graphene, Gtk
from gi.repository import Pango, PangoCairo

from mcomix import image_tools
from mcomix import status
from mcomix.preferences import prefs

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


class OnScreenDisplay:

    """ The OSD shows information such as currently opened file, archive and
    page in a black box drawn on the bottom end of the screen.

    The OSD will automatically be erased after TIMEOUT seconds.
    """

    TIMEOUT = 3

    #: What the OSD is called among the canvas' overlays.
    _OVERLAY = 'osd'

    def __init__(self, window: "main.MainWindow") -> None:
        #: MainWindow
        self._window = window
        #: Stores the last rectangle that was used to render the OSD
        self._last_osd_rect: tuple[int, int, int, int] | None = None
        #: Timeout event ID registered while waiting to hide the OSD
        self._timeout_event: int | None = None

    def show(self, text: str) -> None:
        """ Shows the OSD on the lower portion of the image window. """

        # Determine text to draw
        text = self._wrap_text(text)
        layout = self._window.page_area.create_pango_layout(text)

        # Set up font information
        font = layout.get_context().get_font_description()
        if font is None:
            # A context that describes no font of its own: there is
            # still one to scale, it is simply the default.
            font = Pango.FontDescription()
        font.set_weight(Pango.Weight.BOLD)
        layout.set_alignment(Pango.Alignment.CENTER)

        # Scale font to fit within the screen size
        max_width, max_height = self._window.get_visible_area_size()
        self._scale_font(font, layout, max_width)

        # Calculate surrounding box
        layout_width, layout_height = layout.get_pixel_size()
        offset_x, offset_y = self._window.scroll_offset()
        pos_x = max(int(max_width // 2) - int(layout_width // 2) +
                    int(offset_x), 0)
        pos_y = max(int(max_height) - int(layout_height * 1.1) +
                    int(offset_y), 0)

        rect = (pos_x - 10, pos_y - 20,
                layout_width + 20, layout_height + 20)

        self._draw_osd(layout, rect)

        self._last_osd_rect = rect
        if self._timeout_event:
            GLib.source_remove(self._timeout_event)
        self._timeout_event = GLib.timeout_add_seconds(
            OnScreenDisplay.TIMEOUT, self.clear)

    def clear(self) -> bool:
        """ Removes the OSD. """
        if self._timeout_event:
            GLib.source_remove(self._timeout_event)
        self._timeout_event = None
        self._clear_osd()
        return GLib.SOURCE_REMOVE  # The timer that called this is done.

    def _wrap_text(self, text: str, width: int = 70) -> str:
        """Break <text> into lines of at most <width> characters.

        Each line is wrapped on its own so that the blank lines between
        the fields of the OSD survive: textwrap.wrap() answers an empty
        list for an empty string, which would run the fields together.
        """
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

        self._window.page_area.set_overlay(self._OVERLAY, None)
        self._last_osd_rect = None

    def _scale_font(self, font: Pango.FontDescription, layout: Pango.Layout,
                    max_width: int) -> None:
        """Set the font of <layout> to the largest size the text fits at.

        Sizes are tried from 10 points to 60 inclusive in steps of five,
        and the first one wider than <max_width> ends the search with
        the size before it put back.  A size can only be tried by laying
        the text out at it, so <font> and <layout> are both left holding
        the answer.
        """

        SIZE_MIN, SIZE_MAX = 10, 60
        for font_size in range(SIZE_MIN, SIZE_MAX + 1, 5):
            old_size = font.get_size()
            font.set_size(font_size * Pango.SCALE)
            layout.set_font_description(font)

            if layout.get_pixel_size()[0] > max_width:
                font.set_size(old_size)
                layout.set_font_description(font)
                break

    def _draw_osd(self, layout: Pango.Layout,
                  rect: tuple[int, int, int, int]) -> None:
        """Draw the text of <layout> in white on a black box at <rect>."""

        # The canvas draws the OSD over the pages, with cairo from the
        # snapshot, and works out for itself what that damages.
        def draw(snapshot: Gtk.Snapshot) -> None:
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

        self._window.page_area.set_overlay(self._OVERLAY, draw)

class PageCounter:

    """The pages on screen and the book's length, in the corner of the
    view while the window fills the screen (upstream feature request
    81), where the status bar is hidden and the OSD only comes on Tab.

    Drawn as an overlay on the canvas, which draws overlays after
    moving them by how far the view is scrolled: the position is worked
    out at each draw, from the scroll offset then, so the counter stays
    in the corner as the page scrolls under it.
    """

    #: What the counter is called among the canvas' overlays.
    _OVERLAY = 'page counter'
    #: Pixels between the counter and the edges of the view.
    _MARGIN = 12
    #: Seconds the counter stays after a page turn, where it is set to go.
    TIMEOUT = 3
    #: What 'page counter' says: never, always, or after a page turn.
    NEVER, ALWAYS, AFTER_TURN = 0, 1, 2

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        self._text = ''
        self._shown = False
        self._timeout_event: int | None = None

    def update(self, again: bool = False) -> None:
        """Show the counter, or take it away, as the window now asks.

        Where 'page counter' is AFTER_TURN, it shows when the pages on
        screen change and goes again TIMEOUT seconds later, as CDisplayEx
        does it (the comment of 2026-10-09 on feature request 81); a
        redraw of the same pages does not bring it back.  <again> shows
        it whatever it said before, for the preferences that change.
        """
        window = self._window
        pages = window.displayed_pages() if window.filehandler.file_loaded \
            else []
        if not (prefs['page counter'] != self.NEVER and pages
                and window.is_fullscreen()):
            self._text = ''
            self._hide()
            return
        text = status.format_page_number(
            pages, window.imagehandler.get_number_of_pages())
        if text == self._text and not again:
            return
        self._text = text
        layout = window.page_area.create_pango_layout(text)
        window.page_area.set_overlay(
            self._OVERLAY, lambda snapshot: self._draw(snapshot, layout))
        self._shown = True
        self._stop_timer()
        if prefs['page counter'] == self.AFTER_TURN:
            self._timeout_event = GLib.timeout_add_seconds(
                self.TIMEOUT, self._time_up)

    def text(self) -> str:
        """What the counter says, or nothing while it is not shown."""
        return self._text if self._shown else ''

    def _time_up(self) -> bool:
        self._timeout_event = None
        self._hide()
        return GLib.SOURCE_REMOVE  # The timer that called this is done.

    def _hide(self) -> None:
        """Take the counter off the page, keeping what it said, so that
        the same pages drawn again do not put it back."""
        self._stop_timer()
        self._shown = False
        self._window.page_area.set_overlay(self._OVERLAY, None)

    def _stop_timer(self) -> None:
        if self._timeout_event is not None:
            GLib.source_remove(self._timeout_event)
            self._timeout_event = None

    def _draw(self, snapshot: Gtk.Snapshot, layout: Pango.Layout) -> None:
        """Draw <layout>, white on a dark box, in the lower right corner
        of what is on screen now."""
        width, height = layout.get_pixel_size()
        view_width, view_height = self._window.get_visible_area_size()
        offset_x, offset_y = self._window.scroll_offset()
        pad = 6
        rect = (int(offset_x) + view_width - width - 2 * pad - self._MARGIN,
                int(offset_y) + view_height - height - 2 * pad - self._MARGIN,
                width + 2 * pad, height + 2 * pad)
        bounds = Graphene.Rect()
        bounds.init(*rect)
        cr = snapshot.append_cairo(bounds)
        black = image_tools.RGBA_BLACK
        cr.set_source_rgba(black.red, black.green, black.blue, 0.6)
        cr.rectangle(*rect)
        cr.fill()
        white = image_tools.RGBA_WHITE
        cr.set_source_rgb(white.red, white.green, white.blue)
        cr.move_to(rect[0] + pad, rect[1] + pad)
        PangoCairo.update_layout(cr, layout)
        PangoCairo.show_layout(cr, layout)

# vim: expandtab:sw=4:ts=4
