"""The on-screen display's font scaling and drawing.

_scale_font() is the only arithmetic in the OSD: the rest of it lays
out a box and draws it.  Neither reads anything off the window but the
canvas the box is drawn on, so both can be exercised without one.
"""

import types

from gi.repository import Gdk, Graphene, Gsk, Gtk
from gi.repository import Pango

from . import MComixTest

from mcomix.osd import OnScreenDisplay


class ScaleFontTest(MComixTest):

    """What size the OSD settles on for a given width."""

    def setUp(self):
        super().setUp()
        # __init__ only stores the window, and _scale_font() never looks
        # at it, so the OSD needs no main window to be measured.
        self.osd = OnScreenDisplay(None)
        self.label = Gtk.Label()

    def _scaled(self, text, max_width):
        """The point size _scale_font() leaves behind for <text>."""
        layout = self.label.create_pango_layout(text)
        font = layout.get_context().get_font_description()
        if font is None:
            font = Pango.FontDescription()
        font.set_weight(Pango.Weight.BOLD)
        self.osd._scale_font(font, layout, max_width)
        return font.get_size() // Pango.SCALE

    def test_text_that_always_fits_reaches_the_largest_size(self):
        # SIZE_MAX is 60 and the docstring calls it a size that is
        # tried; the range that walks up to it used to stop at 55.
        self.assertEqual(60, self._scaled('1', 1 << 20))

    def test_the_font_the_layout_holds_is_the_one_returned(self):
        layout = self.label.create_pango_layout('1')
        font = layout.get_context().get_font_description()
        if font is None:
            font = Pango.FontDescription()
        self.osd._scale_font(font, layout, 1 << 20)
        described = layout.get_font_description()
        self.assertIsNotNone(described)
        self.assertEqual(font.get_size(), described.get_size())

    def test_text_that_never_fits_stays_at_the_smallest_size(self):
        # Every size is too wide, including the first, so the loop puts
        # back what the font came in with rather than a tried size.
        layout = self.label.create_pango_layout('a very long line indeed')
        font = layout.get_context().get_font_description()
        if font is None:
            font = Pango.FontDescription()
        before = font.get_size()
        self.osd._scale_font(font, layout, 1)
        self.assertEqual(before, font.get_size())


class DrawTest(MComixTest):

    """What the OSD draws over the pages: no test drew it before, since
    the canvas only runs its overlays when a frame is rendered."""

    def _rendered(self, text, rect, size=(200, 100)):
        """Draw the OSD of <text> at <rect>, render it over a <size>
        field of grey, and answer with the rendered texture."""
        overlays = {}
        page_area = types.SimpleNamespace(
            set_overlay=lambda name, draw: overlays.__setitem__(name, draw))
        osd = OnScreenDisplay(types.SimpleNamespace(page_area=page_area))
        layout = Gtk.Label().create_pango_layout(text)
        osd._draw_osd(layout, rect)
        self.assertEqual([OnScreenDisplay._OVERLAY], list(overlays))

        snapshot = Gtk.Snapshot()
        field = Graphene.Rect().init(0, 0, *size)
        grey = Gdk.RGBA()
        grey.parse('#808080')
        snapshot.append_color(grey, field)
        overlays[OnScreenDisplay._OVERLAY](snapshot)
        renderer = Gsk.CairoRenderer()
        renderer.realize_for_display(Gdk.Display.get_default())
        self.addCleanup(renderer.unrealize)
        return renderer.render_texture(snapshot.to_node(), field)

    def _pixels(self, texture):
        """The texture's pixels, as rows of (red, green, blue)."""
        downloader = Gdk.TextureDownloader.new(texture)
        downloader.set_format(Gdk.MemoryFormat.R8G8B8)
        data, stride = downloader.download_bytes()
        data = data.get_data()
        return [[tuple(data[y * stride + 3 * x:y * stride + 3 * x + 3])
                 for x in range(texture.get_width())]
                for y in range(texture.get_height())]

    def test_the_box_is_black_and_drawn_where_it_is_asked(self):
        pixels = self._pixels(self._rendered('', (20, 30, 100, 40)))
        self.assertEqual((0, 0, 0), pixels[31][21])
        self.assertEqual((0, 0, 0), pixels[68][118])
        self.assertEqual((128, 128, 128), pixels[29][21])
        self.assertEqual((128, 128, 128), pixels[71][118])
        self.assertEqual((128, 128, 128), pixels[50][19])
        self.assertEqual((128, 128, 128), pixels[50][121])

    def test_the_text_is_white_inside_the_box(self):
        # The drawing is clipped to the box, so text laid out anywhere
        # but at the box would not show at all: the box stands well
        # away from the origin for that to tell.
        pixels = self._pixels(self._rendered('MMMM', (100, 30, 90, 60)))
        # Near white rather than white: how much of a glyph comes out
        # at full white is the font renderer's to decide.
        white = [(x, y) for y, row in enumerate(pixels)
                 for x, pixel in enumerate(row) if min(pixel) > 200]
        self.assertTrue(white, 'no text was drawn in the box')
        self.assertTrue(all(100 <= x < 190 and 30 <= y < 90
                            for x, y in white))
