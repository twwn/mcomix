"""Pages on a screen with more pixels than the window has.

At a scale of 200 per cent there are two of the screen's pixels to each
of the window's along a side.  The pages are laid out in the window's
pixels, as everything else is, and were scaled to that layout alone, so
GTK drew them twice as large as they had been scaled: blurred.  They
are now scaled to the screen's pixels and drawn into the layout's box.
"""

import unittest.mock

from gi.repository import Gdk, GdkPixbuf, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import edit_image_area
from mcomix import icons
from mcomix import image_tools
from mcomix import keybindings
from mcomix import main
from mcomix import pageselect
from mcomix import properties_page
from mcomix import widgets
from mcomix import thumbnail_list
from mcomix.preferences import prefs


class DeviceScaleTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.make_user_directories()
        icons.load_icons()
        keybindings._manager = None
        self.window = main.MainWindow()
        main.set_main_window(self.window)

    def tearDown(self):
        self.close_main_window()
        super().tearDown()

    def _draw_at(self, scale):
        with unittest.mock.patch.object(main.MainWindow, 'device_scale',
                                        return_value=scale):
            self.window.filehandler.open_file(
                get_testfile_path('images', 'landscape-no-exif.jpg'))
            self.assertTrue(wait_for(
                lambda: self.window.imagehandler.get_number_of_pages() > 0))
            pump()
            self.window.draw_image()
            pump()
        box = self.window.layout.get_content_boxes()[0].get_size()
        return box, self.window.images[0].get_paintable()

    def test_at_twice_the_pixels_the_page_is_scaled_to_them(self):
        (width, height), shown = self._draw_at(2.0)
        # Laid out where it was, at the window's size...
        self.assertEqual((width, height), (shown.get_intrinsic_width(),
                                           shown.get_intrinsic_height()))
        # ...from a picture with the screen's pixels in it.
        texture = shown._texture
        self.assertEqual((2 * width, 2 * height),
                         (texture.get_width(), texture.get_height()))

    def test_a_fractional_scale_rounds_to_whole_pixels(self):
        (width, height), shown = self._draw_at(1.5)
        texture = shown._texture
        self.assertEqual((round(1.5 * width), round(1.5 * height)),
                         (texture.get_width(), texture.get_height()))

    def test_at_one_pixel_to_one_the_page_is_a_plain_texture(self):
        (width, height), shown = self._draw_at(1.0)
        self.assertIsInstance(shown, Gdk.Texture)
        self.assertEqual((width, height),
                         (shown.get_width(), shown.get_height()))

    def test_the_scale_is_asked_of_the_window_s_surface(self):
        pump()
        surface = self.window.get_surface()
        self.assertIsNotNone(surface)
        with unittest.mock.patch.object(type(surface), 'get_scale',
                                        return_value=1.25):
            self.assertEqual(1.25, self.window.device_scale())

    def test_a_change_of_the_surface_s_scale_draws_everything_again(self):
        pump()
        surface = self.window.get_surface()
        with unittest.mock.patch.object(self.window, 'draw_image') as drawn, \
                unittest.mock.patch.object(self.window.thumbnailsidebar,
                                           'resize') as resized:
            surface.notify('scale')
        drawn.assert_called_once_with()
        resized.assert_called_once_with()

    def test_a_window_without_a_surface_counts_one_to_one(self):
        with unittest.mock.patch.object(main.MainWindow, 'get_surface',
                                        return_value=None):
            self.assertEqual(1.0, self.window.device_scale())



class ThumbnailScaleTest(MComixTest):

    """The thumbnail bar's thumbnails, made with the screen's pixels and
    drawn at the window's size."""

    def setUp(self):
        super().setUp()
        self.make_user_directories()
        prefs['show thumbnails'] = True
        icons.load_icons()
        keybindings._manager = None
        self.window = main.MainWindow(
            open_path=get_testfile_path(
                'pepper-and-carrot',
                'Pepper-and-Carrot_E01_The-Potion-of-Flight.cbz'))
        main.set_main_window(self.window)
        self.sidebar = self.window.thumbnailsidebar
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0,
            seconds=20))

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump(2000)
        super().tearDown()

    def _first_at(self, scale):
        with unittest.mock.patch.object(main.MainWindow, 'device_scale',
                                        return_value=scale):
            self.sidebar.resize()
        item = self.sidebar._list.store.get_item(0)
        self.assertTrue(wait_for(lambda: item.thumbnail is not None,
                                 seconds=20))
        return item

    def test_at_twice_the_pixels_a_thumbnail_has_twice_as_many(self):
        logical = self.sidebar._pixbuf_size
        item = self._first_at(2.0)
        self.assertEqual(2.0, item.scale)
        texture = item.thumbnail
        self.assertGreater(max(texture.get_width(), texture.get_height()),
                           logical)
        self.assertLessEqual(max(texture.get_width(), texture.get_height()),
                             2 * logical)
        shown = thumbnail_list._shown(item)
        self.assertEqual(round(texture.get_width() / 2),
                         shown.get_intrinsic_width())
        self.assertEqual(round(texture.get_height() / 2),
                         shown.get_intrinsic_height())

    def test_at_one_to_one_the_cell_draws_the_texture_itself(self):
        item = self._first_at(1.0)
        self.assertEqual(1.0, item.scale)
        self.assertIs(item.thumbnail, thumbnail_list._shown(item))



class EditorScaleTest(MComixTest):

    """The archive editor's page thumbnails, made with the screen's
    pixels where there are more of them than the window's."""

    def setUp(self):
        super().setUp()
        self.make_user_directories()
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.area.cleanup()
        self.area.release()
        self.close_main_window()
        super().tearDown()

    def _area_at(self, scale):
        with unittest.mock.patch.object(main.MainWindow, 'device_scale',
                                        return_value=scale):
            self.area = edit_image_area._ImageArea(unittest.mock.Mock(),
                                                   self.window)
        return self.area

    def test_at_twice_the_pixels_the_thumbnails_are_made_twice_as_large(self):
        area = self._area_at(2.0)
        self.assertEqual(2.0, area._grid.device_scale)
        self.assertEqual(2 * area._thumbnail_size, area._made_size)
        self.assertEqual((area._made_size,) * 2, (area._thumbnailer.width,
                                                  area._thumbnailer.height))

    def test_at_one_to_one_they_are_made_at_the_size_shown(self):
        area = self._area_at(1.0)
        self.assertEqual(1.0, area._grid.device_scale)
        self.assertEqual(area._thumbnail_size, area._made_size)



class PreviewScaleTest(MComixTest):

    """The previews in the page selector and the properties dialog, made
    with the screen's pixels and drawn at the window's size."""

    def setUp(self):
        super().setUp()
        self.make_user_directories()
        icons.load_icons()
        self.window = main.MainWindow(open_path=get_testfile_path(
            'pepper-and-carrot',
            'Pepper-and-Carrot_E01_The-Potion-of-Flight.cbz'))
        main.set_main_window(self.window)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.page_is_available(1),
            seconds=20))
        self.dialog = None

    def tearDown(self):
        if self.dialog is not None:
            if hasattr(self.dialog, '_stop_thumbnailing'):
                self.dialog._stop_thumbnailing()
            self.dialog.destroy()
        self.close_main_window()
        super().tearDown()

    def test_the_page_selector_asks_for_the_screen_s_pixels(self):
        with unittest.mock.patch.object(main.MainWindow, 'device_scale',
                                        return_value=2.0):
            self.dialog = pageselect.Pageselector(self.window)
            pump()
            self.assertTrue(wait_for(
                lambda: self.dialog._image_preview.get_width() > 0))
            with unittest.mock.patch.object(
                    self.dialog._thread, 'append_order') as asked:
                self.dialog._update_thumbnail(1)
        page, width, height, scale = asked.call_args.args[0]
        self.assertEqual(2.0, scale)
        self.assertEqual(2 * self.dialog._image_preview.get_width(), width)

    def test_the_page_selector_draws_it_at_the_window_s_size(self):
        self.dialog = pageselect.Pageselector(self.window)
        pump()
        pixbuf = self.window.imagehandler.get_thumbnail(1, width=200,
                                                        height=200)
        self.dialog._thumbnail_page = 1
        self.dialog._thumbnail_finished(1, pixbuf, 2.0)
        shown = self.dialog._image_preview.get_paintable()
        self.assertEqual(round(pixbuf.get_width() / 2),
                         shown.get_intrinsic_width())

    def test_the_properties_thumbnail_is_made_with_the_screen_s_pixels(self):
        page = properties_page._Page()
        pixbuf = self.window.imagehandler.get_thumbnail(1, width=256,
                                                        height=256)
        page.set_thumbnail(pixbuf, 2.0)
        shown = page._thumb.get_paintable()
        self.assertIsInstance(shown, widgets.ScaledTexture)
        # The border is two of the screen's pixels on each side.
        self.assertEqual(round((pixbuf.get_width() + 4) / 2),
                         shown.get_intrinsic_width())


class ScaledTextureTest(MComixTest):

    def test_it_is_as_large_as_the_texture_over_the_scale(self):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8,
                                      200, 100)
        pixbuf.fill(0x336699ff)
        texture = image_tools.pixbuf_to_texture(pixbuf)
        scaled = widgets.at_scale(texture, 2.0)
        self.assertEqual((100, 50), (scaled.get_intrinsic_width(),
                                     scaled.get_intrinsic_height()))
        self.assertIs(texture, widgets.at_scale(texture, 1))

    def test_it_draws_the_whole_texture_into_the_box_it_is_given(self):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8,
                                      200, 100)
        pixbuf.fill(0x336699ff)
        scaled = widgets.at_scale(image_tools.pixbuf_to_texture(pixbuf), 2.0)
        snapshot = Gtk.Snapshot()
        scaled.snapshot(snapshot, 100, 50)
        # A paintable rather than the render node itself: PyGObject hands
        # render nodes to Python only from 3.48 on, and a paintable made
        # without a size is as large as the node's bounds.
        drawn = snapshot.to_paintable(None)
        self.assertIsNotNone(drawn)
        self.assertEqual((100, 50), (drawn.get_intrinsic_width(),
                                     drawn.get_intrinsic_height()))


# vim: expandtab:sw=4:ts=4
