# coding: utf-8

from gi.repository import GdkPixbuf, Gtk

from . import MComixTest, pump

from mcomix import image_tools
from mcomix.canvas import PageCanvas


class PageCanvasTest(MComixTest):

    """The canvas stands in for Gtk.Layout, which GTK4 removed."""

    #: Larger than any window the tests can be given, so that there is
    #: always something left to scroll over.
    CONTENT = (5000, 4000)

    def setUp(self):
        super(PageCanvasTest, self).setUp()
        self.canvas = PageCanvas()
        texture = image_tools.pixbuf_to_texture(
            GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 300, 400))
        self.children = []
        for _ in range(2):
            picture = Gtk.Picture()
            picture.set_paintable(texture)
            picture.set_can_shrink(False)
            self.children.append(picture)
        self.window = Gtk.Window()
        self.window.set_child(self.canvas)
        self.window.present()
        pump()

    def tearDown(self):
        self.window.destroy()
        pump()
        super(PageCanvasTest, self).tearDown()

    def _settle(self):
        # A queued allocation is run from the frame clock, so give it
        # frames to run in rather than only draining what is pending.
        for _ in range(20):
            pump()
            self.canvas.allocate(self.canvas.get_width(),
                                 self.canvas.get_height(), -1, None)

    def _position(self, child):
        ok, bounds = child.compute_bounds(self.canvas)
        self.assertTrue(ok)
        return (bounds.origin.x, bounds.origin.y)

    def test_a_child_is_placed_where_it_was_put(self):
        self.canvas.put(self.children[0], 40, 70)
        self._settle()
        self.assertEqual(self._position(self.children[0]), (40, 70))

    def test_a_child_keeps_the_size_it_asks_for(self):
        self.canvas.put(self.children[0], 0, 0)
        self._settle()
        self.assertEqual((self.children[0].get_width(),
                          self.children[0].get_height()), (300, 400))

    def test_moving_a_child_moves_it(self):
        self.canvas.put(self.children[0], 0, 0)
        self._settle()
        self.canvas.move(self.children[0], 130, 90)
        self._settle()
        self.assertEqual(self._position(self.children[0]), (130, 90))

    def test_moving_a_child_that_is_not_there_is_an_error(self):
        self.assertRaises(ValueError, self.canvas.move, self.children[0], 0, 0)

    def test_removing_a_child_takes_it_off(self):
        self.canvas.put(self.children[0], 0, 0)
        self.canvas.remove(self.children[0])
        self.assertIsNone(self.children[0].get_parent())
        self.assertRaises(ValueError, self.canvas.remove, self.children[0])

    def test_the_canvas_asks_for_no_room_of_its_own(self):
        # Gtk.Layout requested nothing, so that the window is sized by
        # what is around the pages rather than by the pages.
        self.canvas.set_content_size(*self.CONTENT)
        self.assertEqual(self.canvas.measure(Gtk.Orientation.HORIZONTAL, -1)[:2],
                         (0, 0))
        self.assertEqual(self.canvas.measure(Gtk.Orientation.VERTICAL, -1)[:2],
                         (0, 0))

    def test_the_size_is_what_was_set(self):
        self.canvas.set_content_size(*self.CONTENT)
        self.assertEqual(self.canvas.get_content_size(), self.CONTENT)

    def test_the_canvas_does_not_shadow_the_widget_size_accessor(self):
        # Gtk.Widget.get_size() answers with the allocation along one
        # orientation. The canvas' own accessor answers with the extent
        # that is scrolled over, which is a different number of a
        # different shape, so it may not be called get_size() too.
        self.canvas.set_content_size(*self.CONTENT)
        self._settle()
        self.assertEqual(self.canvas.get_size(Gtk.Orientation.HORIZONTAL),
                         self.canvas.get_width())
        self.assertEqual(self.canvas.get_size(Gtk.Orientation.VERTICAL),
                         self.canvas.get_height())
        self.assertNotEqual(self.canvas.get_content_size(),
                            (self.canvas.get_width(), self.canvas.get_height()))

    def test_the_adjustments_range_over_the_canvas(self):
        self.canvas.set_content_size(*self.CONTENT)
        self._settle()
        for adjustment, content, viewport in (
                (self.canvas.get_hadjustment(), self.CONTENT[0],
                 self.canvas.get_width()),
                (self.canvas.get_vadjustment(), self.CONTENT[1],
                 self.canvas.get_height())):
            self.assertEqual(adjustment.get_lower(), 0)
            self.assertEqual(adjustment.get_upper(), content)
            self.assertEqual(adjustment.get_page_size(), viewport)

    def test_a_canvas_smaller_than_the_window_has_nothing_to_scroll(self):
        self.canvas.set_content_size(1, 1)
        self._settle()
        adjustment = self.canvas.get_hadjustment()
        self.assertEqual(adjustment.get_upper(), self.canvas.get_width())
        self.assertEqual(adjustment.get_page_size(), self.canvas.get_width())

    def test_scrolling_moves_the_children(self):
        self.canvas.set_content_size(*self.CONTENT)
        self.canvas.put(self.children[0], 200, 300)
        self._settle()
        self.canvas.get_hadjustment().set_value(150)
        self.canvas.get_vadjustment().set_value(80)
        self._settle()
        self.assertEqual(self._position(self.children[0]), (50, 220))

    def test_scrolling_stops_at_the_edge(self):
        self.canvas.set_content_size(*self.CONTENT)
        self._settle()
        adjustment = self.canvas.get_hadjustment()
        adjustment.set_value(self.CONTENT[0] * 2)
        self._settle()
        self.assertEqual(adjustment.get_value(),
                         self.CONTENT[0] - self.canvas.get_width())

# vim: expandtab:sw=4:ts=4
