# coding: utf-8

from gi.repository import Gdk, GdkPixbuf, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import image_tools
from mcomix.page_image import PageImage


def get_image_path(basename):
    return get_testfile_path('images', basename)


class PageImageTest(MComixTest):

    def setUp(self):
        super(PageImageTest, self).setUp()
        self.image = PageImage()
        self.window = Gtk.Window()
        self.window.set_child(self.image)
        self.window.present()
        pump()

    def tearDown(self):
        self.window.destroy()
        pump()
        super(PageImageTest, self).tearDown()

    def test_a_page_is_drawn_at_its_own_size(self):
        pixbuf = image_tools.load_pixbuf(get_image_path('blue.png'))
        self.image.set_pixbuf(pixbuf)
        paintable = self.image.get_paintable()
        self.assertEqual((paintable.get_intrinsic_width(),
                          paintable.get_intrinsic_height()), (100, 100))
        # Gtk.Image would have asked for an icon's worth of room.
        self.assertEqual(self.image.get_preferred_size()[1].width, 100)

    def test_a_page_keeps_the_pixels_it_was_given(self):
        pixbuf = image_tools.load_pixbuf(get_image_path('blue.png'))
        texture = image_tools.pixbuf_to_texture(pixbuf)
        self.assertPixbufsEqual(Gdk.pixbuf_get_from_texture(texture), pixbuf)

    def test_a_transparent_page_keeps_its_alpha(self):
        pixbuf = image_tools.load_pixbuf(
            get_image_path('pattern-transparent-rgba.png'))
        self.assertTrue(pixbuf.get_has_alpha())
        texture = image_tools.pixbuf_to_texture(pixbuf)
        self.assertPixbufsEqual(Gdk.pixbuf_get_from_texture(texture), pixbuf)

    def test_an_animated_page_advances_on_its_own(self):
        animation = GdkPixbuf.PixbufAnimation.new_from_file(
            get_image_path('animated.gif'))
        self.assertTrue(image_tools.is_animation(animation))
        self.image.set_pixbuf(animation)
        first = self.image.get_paintable()
        self.assertIsNotNone(first)
        wait_for(lambda: self.image.get_paintable() is not first)
        self.assertIsNot(self.image.get_paintable(), first,
                         'the animation never advanced past its first frame')

    def test_a_still_page_stops_the_animation_before_it(self):
        animation = GdkPixbuf.PixbufAnimation.new_from_file(
            get_image_path('animated.gif'))
        self.image.set_pixbuf(animation)
        self.image.set_pixbuf(image_tools.load_pixbuf(get_image_path('blue.png')))
        still = self.image.get_paintable()
        wait_for(lambda: self.image.get_paintable() is not still,
                       seconds=2)
        self.assertIs(self.image.get_paintable(), still,
                      'the page went on animating after it had been replaced')

    def test_clearing_a_page_stops_the_animation(self):
        animation = GdkPixbuf.PixbufAnimation.new_from_file(
            get_image_path('animated.gif'))
        self.image.set_pixbuf(animation)
        self.image.clear()
        self.assertIsNone(self.image.get_paintable())
        wait_for(lambda: self.image.get_paintable() is not None,
                       seconds=2)
        self.assertIsNone(self.image.get_paintable(),
                          'the page went on animating after it was cleared')

    def assertPixbufsEqual(self, one, two):
        self.assertEqual((one.get_width(), one.get_height()),
                         (two.get_width(), two.get_height()))
        self.assertEqual(one.get_has_alpha(), two.get_has_alpha())
        self.assertEqual(one.get_pixels(), two.get_pixels())

# vim: expandtab:sw=4:ts=4
