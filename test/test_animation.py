"""The frames of a page that moves.

GdkPixbuf.PixbufAnimation, which used to be both the answer to "does
this page move" and the source of its frames, is deprecated as of GTK
4.10 with nothing in its place. Pillow decodes what it can open,
glycin - the decoder gdk-pixbuf itself hands to - decodes the rest, and
the deprecated iterator is left for a tree that has neither.
"""

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
        frames = animation.frames(get_image_path('animated.webp'))
        self.assertIsInstance(frames, animation._PillowFrames)
        self.assertTrue(frames.ahead,
                        'the next frame cannot be decoded before it is due')

    def test_a_frame_lasts_as_long_as_it_says(self):
        # Which is not what the frame before it said: a WebP fills the
        # delay in as it decodes, so reading it before the pixels are
        # asked for gives the frame before's.
        frames = animation.frames(get_image_path('animated.webp'))
        self.assertEqual([frames.next()[1] for _ in range(5)],
                         [120, 120, 40, 80, 40])

    def test_an_animation_goes_round_again(self):
        frames = animation.frames(get_image_path('animated.webp'))
        first = frames.next()[1]
        for _ in range(4):
            frames.next()
        self.assertEqual(frames.next()[1], first,
                         'the animation stopped at its last frame')

    def test_a_frame_that_says_no_time_at_all_is_not_hurried(self):
        # A GIF written with a delay of zero means "as fast as you
        # like"; taking it at its word plays it ten times too fast.
        frames = animation.frames(get_image_path('no-delay.gif'))
        self.assertEqual(frames.next()[1], animation.DEFAULT_DELAY)

    def test_a_page_that_is_one_picture_has_no_frames_to_decode(self):
        """Nothing asks for the frames of a still page - load_pixbuf()
        does not mark one - but if something did, the one frame it has
        says it lasts no time, which is what stops the decoder.

        Zero from glycin, -1 from gdk-pixbuf where there is no glycin:
        Frames.next() counts both as the end.
        """
        frames = animation.frames(get_image_path('blue.png'))
        self.assertNotIsInstance(frames, animation._PillowFrames)
        self.assertLessEqual(frames.next()[1], 0)

    def test_a_page_that_is_not_there_at_all_says_so(self):
        self.assertRaises(Exception, animation.frames,
                          get_image_path('no-such-file.gif'))


class GlycinFramesTest(MComixTest):

    """What decodes a moving page Pillow will not open.

    Pillow opens every animated format the test files hold, so this
    drives the decoder directly rather than through frames().
    """

    def setUp(self):
        super().setUp()
        try:
            image_tools.glycin()
        except Exception as error:
            self.skipTest('this tree has no glycin (%s)' % error)

    def test_the_frames_come_out_as_textures(self):
        frames = animation._GlycinFrames(get_image_path('animated.gif'))
        texture, delay = frames.next()
        self.assertEqual((texture.get_width(), texture.get_height()),
                         (210, 210))
        self.assertGreater(delay, 0)

    def test_a_frame_can_be_decoded_before_it_is_due(self):
        """glycin hands out a sequence, where the deprecated iterator
        could only be asked what belongs on screen at this instant."""
        self.assertTrue(animation._GlycinFrames.ahead)

    def test_the_delay_is_in_milliseconds(self):
        # glycin counts a frame in microseconds; the page waits in
        # milliseconds.
        frames = animation._GlycinFrames(get_image_path('animated.webp'))
        self.assertEqual([frames.next()[1] for _ in range(3)],
                         [120, 120, 40])

    def test_an_animation_goes_round_again(self):
        frames = animation._GlycinFrames(get_image_path('animated.webp'))
        delays = [frames.next()[1] for _ in range(6)]
        self.assertEqual(delays[5], delays[0],
                         'the animation stopped at its last frame')

    def test_one_picture_runs_out_after_its_one_frame(self):
        frames = animation._GlycinFrames(get_image_path('blue.png'))
        frames.next()
        # Going round again gives the same one picture rather than
        # raising, which is what a still image loops as.
        texture, delay = frames.next()
        self.assertEqual(delay, 0)


class PixbufFramesTest(MComixTest):

    """The deprecated iterator, kept for a tree with no glycin."""

    def test_the_frames_come_out_as_textures(self):
        frames = animation._PixbufFrames(get_image_path('animated.gif'))
        texture, delay = frames.next()
        self.assertEqual((texture.get_width(), texture.get_height()),
                         (210, 210))
        self.assertGreater(delay, 0)

    def test_a_frame_cannot_be_decoded_before_it_is_due(self):
        self.assertFalse(animation._PixbufFrames.ahead)

# vim: expandtab:sw=4:ts=4
