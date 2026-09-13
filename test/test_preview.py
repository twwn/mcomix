# -*- coding: utf-8 -*-

""" How large a preview of a page is drawn. """

from gi.repository import GdkPixbuf, Gsk, Gtk

from . import MComixTest, wait_for

from mcomix import preview


def drawn_sizes(view):
    """The size every picture in <view> is actually painted at.

    What a cell is measured at and what it draws are two different
    numbers in GTK4, and only the second one is visible, so ask the
    render node rather than the cell.
    """
    # A style change reaches the cells when the frame clock next ticks,
    # not the moment it is asked for.
    wait_for(lambda: False, seconds=0.2)
    paintable = Gtk.WidgetPaintable.new(view)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, view.get_width(), view.get_height())
    sizes = []

    def walk(node):
        if node is None:
            return
        if node.get_node_type() == Gsk.RenderNodeType.TEXTURE_NODE:
            bounds = node.get_bounds().size
            sizes.append((round(bounds.width), round(bounds.height)))
        if node.get_node_type() == Gsk.RenderNodeType.CONTAINER_NODE:
            for index in range(node.get_n_children()):
                walk(node.get_child(index))
        elif hasattr(node, 'get_child'):
            try:
                walk(node.get_child())
            except TypeError:
                pass

    walk(snapshot.to_node())
    return sizes


class PreviewSizeTest(MComixTest):

    def test_a_preview_is_never_smaller_than_it_was_asked_for(self):
        widget = Gtk.Window()
        self.assertGreaterEqual(preview.scaled(80, widget), 80)
        widget.destroy()

    def test_the_factor_stays_between_one_and_three(self):
        widget = Gtk.Window()
        factor = preview.screen_factor(widget)
        self.assertGreaterEqual(factor, 1.0)
        self.assertLessEqual(factor, preview._MAX_FACTOR)
        widget.destroy()

    def test_a_screen_with_nothing_to_say_changes_nothing(self):
        # No widget, no display, no monitors: the size stands.
        self.assertEqual(preview.screen_factor(None), 1.0)
        self.assertEqual(preview.scaled(125, None), 125)

    def test_every_previewer_asks_the_same_way(self):
        # The sidebar, the library and the archive editor all drew their
        # own fixed size, so all three were small on a tall screen.
        import inspect
        from mcomix import (edit_image_area, file_chooser_base_dialog,
                            thumbbar)
        from mcomix.library import book_area
        for module in (thumbbar, book_area, edit_image_area,
                       file_chooser_base_dialog):
            self.assertIn('preview.scaled', inspect.getsource(module),
                          '%s sizes its preview by itself'
                          % module.__name__)


class CellPictureTest(MComixTest):

    """A page in a cell is a picture, not an icon.

    GTK4 draws a Gtk.CellRendererPixbuf's contents at the icon size the
    style asks for - sixteen pixels - however large the picture is.  The
    cell is still measured at the picture's own size, so the library and
    the archive editor drew specks in the middle of correctly sized
    cells, and no amount of asking for a larger thumbnail changed it.
    """

    _PICTURE = (167, 250)

    def setUp(self):
        super(CellPictureTest, self).setUp()
        picture = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                       *self._PICTURE)
        picture.fill(0xFF0000FF)
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf)
        self.store.append([picture])
        self.view = Gtk.IconView(model=self.store)
        self.view.set_pixbuf_column(0)
        self.window = Gtk.Window()
        self.window.set_default_size(400, 400)
        self.window.set_child(self.view)
        self.window.present()
        wait_for(lambda: self.view.get_visible_range() is not None)

    def tearDown(self):
        self.window.destroy()
        super(CellPictureTest, self).tearDown()

    def test_a_cell_draws_its_picture_at_full_size(self):
        preview.draw_cells_at(self.view, max(self._PICTURE))
        self.assertEqual(drawn_sizes(self.view), [self._PICTURE])

    def test_the_size_can_be_raised_again(self):
        # The library redraws its covers at a new size on demand.
        preview.draw_cells_at(self.view, 64)
        self.assertEqual(drawn_sizes(self.view), [(43, 64)])
        preview.draw_cells_at(self.view, max(self._PICTURE))
        self.assertEqual(drawn_sizes(self.view), [self._PICTURE])

    def test_asking_twice_keeps_the_one_provider(self):
        preview.draw_cells_at(self.view, 128)
        provider = self.view._preview_cell_provider
        preview.draw_cells_at(self.view, 128)
        self.assertIs(self.view._preview_cell_provider, provider)

    def test_every_view_of_pages_asks(self):
        import inspect
        from mcomix import edit_image_area, thumbbar
        from mcomix.library import book_area
        for module in (thumbbar, book_area, edit_image_area):
            self.assertIn('preview.draw_cells_at', inspect.getsource(module),
                          '%s draws its pages as icons' % module.__name__)


# vim: expandtab:sw=4:ts=4
