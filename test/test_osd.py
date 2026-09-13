"""The on-screen display's font scaling.

_scale_font() is the only arithmetic in the OSD: the rest of it lays
out a box and draws it.  It reads nothing off the window, so it can be
exercised without one.
"""

from gi.repository import Gtk
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
