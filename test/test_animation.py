# coding: utf-8

from gi.repository import GdkPixbuf

from . import MComixTest, get_testfile_path

from mcomix import animation
from mcomix import image_tools


def get_image_path(basename):
    return get_testfile_path('images', basename)


class FramesTest(MComixTest):

    def test_the_frames_of_a_page_are_decoded_in_this_process(self):
        # gdk-pixbuf decodes in a process of its own, a whole frame at a
        # time over shared memory, far too slowly to keep up with a page
        # that is really a video.
        pixbuf = image_tools.load_pixbuf(get_image_path('animated.webp'))
        frames = animation.frames(pixbuf, pixbuf.path)
        self.assertTrue(frames.ahead,
                        'the next frame cannot be decoded before it is due')

    def test_the_frames_of_a_page_of_an_unknown_kind_still_come(self):
        # Whatever Pillow will not open is still better shown late than
        # not at all.
        animated = GdkPixbuf.PixbufAnimation.new_from_file(
            get_image_path('animated.gif'))
        frames = animation.frames(animated, get_image_path('no-such-file.gif'))
        texture, delay = frames.next()
        self.assertEqual((texture.get_width(), texture.get_height()),
                         (210, 210))
        self.assertGreater(delay, 0)

    def test_a_frame_lasts_as_long_as_it_says(self):
        # Which is not what the frame before it said: a WebP fills the
        # delay in as it decodes, so reading it before the pixels are
        # asked for gives the frame before's.
        pixbuf = image_tools.load_pixbuf(get_image_path('animated.webp'))
        frames = animation.frames(pixbuf, pixbuf.path)
        self.assertEqual([frames.next()[1] for _ in range(5)],
                         [120, 120, 40, 80, 40])

    def test_an_animation_goes_round_again(self):
        pixbuf = image_tools.load_pixbuf(get_image_path('animated.webp'))
        frames = animation.frames(pixbuf, pixbuf.path)
        first = frames.next()[1]
        for _ in range(4):
            frames.next()
        self.assertEqual(frames.next()[1], first,
                         'the animation stopped at its last frame')

    def test_a_frame_that_says_no_time_at_all_is_not_hurried(self):
        # A GIF written with a delay of zero means "as fast as you
        # like"; taking it at its word plays it ten times too fast.
        pixbuf = image_tools.load_pixbuf(get_image_path('no-delay.gif'))
        frames = animation.frames(pixbuf, pixbuf.path)
        self.assertEqual(frames.next()[1], animation.DEFAULT_DELAY)

    def test_a_page_that_is_one_picture_has_no_frames_to_decode(self):
        still = GdkPixbuf.PixbufAnimation.new_from_file(
            get_image_path('blue.png'))
        self.assertTrue(still.is_static_image())
        frames = animation.frames(still, get_image_path('blue.png'))
        # Pillow will not animate it, so nothing tries to.
        self.assertFalse(frames.ahead)

# vim: expandtab:sw=4:ts=4
