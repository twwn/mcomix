import time

from gi.repository import Gdk, GdkPixbuf, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import animation
from mcomix import image_tools
from mcomix.page_image import PageImage


def get_image_path(basename):
    return get_testfile_path('images', basename)


class PageImageTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.image = PageImage()
        self.window = Gtk.Window()
        self.window.set_child(self.image)
        self.window.present()
        pump()

    def tearDown(self):
        # An animation is decoded in a thread of its own which runs until
        # the page is replaced or cleared, and destroying the window is
        # neither: a test that leaves one animating leaves its thread
        # decoding for the rest of the suite.
        self.image.clear()
        self.window.destroy()
        pump()
        super().tearDown()

    def test_a_page_is_drawn_at_its_own_size(self):
        pixbuf = image_tools.load_pixbuf(get_image_path('blue.png'))
        self.image.show_pixbuf(pixbuf)
        paintable = self.image.get_paintable()
        self.assertEqual((paintable.get_intrinsic_width(),
                          paintable.get_intrinsic_height()), (100, 100))
        # Gtk.Image would have asked for an icon's worth of room.
        self.assertEqual(self.image.get_preferred_size()[1].width, 100)

    def test_a_page_keeps_the_pixels_it_was_given(self):
        pixbuf = image_tools.load_pixbuf(get_image_path('blue.png'))
        texture = image_tools.pixbuf_to_texture(pixbuf)
        self.assertTextureMatches(texture, pixbuf)

    def test_a_transparent_page_keeps_its_alpha(self):
        pixbuf = image_tools.load_pixbuf(
            get_image_path('pattern-transparent-rgba.png'))
        self.assertTrue(pixbuf.get_has_alpha())
        texture = image_tools.pixbuf_to_texture(pixbuf)
        self.assertTextureMatches(texture, pixbuf)

    def test_an_animated_page_advances_on_its_own(self):
        animation = image_tools.load_pixbuf(get_image_path('animated.gif'))
        self.assertTrue(image_tools.is_animation(animation))
        self.image.show_pixbuf(animation)
        paintable = self.image.get_paintable()
        self.assertIsNotNone(paintable)
        # The paintable stays; only what it draws changes, so that a
        # frame damages the page rather than the whole window.
        frames = []
        paintable.connect('invalidate-contents',
                          lambda *args: frames.append(1))
        wait_for(lambda: bool(frames))
        self.assertTrue(frames,
                        'the animation never advanced past its first frame')
        self.assertIs(self.image.get_paintable(), paintable,
                      'a frame replaced the paintable, which lays out anew')

    def test_an_animation_is_drawn_at_the_size_the_page_was_laid_out_at(self):
        # Animations skipped the fit and zoom modes, so every frame was
        # drawn at the full size of the picture and uploaded whole,
        # however small the window.
        animation = image_tools.load_pixbuf(get_image_path('animated.gif'))
        self.image.show_pixbuf(animation, (64, 48))
        paintable = self.image.get_paintable()
        self.assertEqual((paintable.get_intrinsic_width(),
                          paintable.get_intrinsic_height()), (64, 48))
        # And it stays that size as the animation runs, so that no frame
        # ever asks the window to be laid out again.
        resized = []
        frames = []
        paintable.connect('invalidate-size', lambda *args: resized.append(1))
        paintable.connect('invalidate-contents',
                          lambda *args: frames.append(1))
        wait_for(lambda: bool(frames))
        self.assertTrue(frames, 'the animation never advanced')
        self.assertFalse(resized, 'a frame asked for a new size')
        self.assertEqual((paintable.get_intrinsic_width(),
                          paintable.get_intrinsic_height()), (64, 48))

    def test_a_page_with_no_size_is_left_alone(self):
        pixbuf = image_tools.load_pixbuf(get_image_path('blue.png'))
        self.image.show_pixbuf(pixbuf)
        paintable = self.image.get_paintable()
        self.assertEqual((paintable.get_intrinsic_width(),
                          paintable.get_intrinsic_height()), (100, 100))

    def test_an_animation_always_has_a_next_frame_coming(self):
        # A loader that has decoded nothing yet reports the same "no
        # more frames" a finished animation does, and taking it at its
        # word left the page standing still until something else redrew
        # it - seconds, on a slow first frame.
        animation = image_tools.load_pixbuf(get_image_path('animated.gif'))
        self.assertTrue(image_tools.is_animation(animation))
        self.image.show_pixbuf(animation)
        self.assertIsNotNone(self.image._worker,
                             'nothing is decoding the next frame')

    def test_one_picture_waits_for_nothing(self):
        still = image_tools.load_pixbuf(get_image_path('blue.png'))
        self.assertFalse(image_tools.is_animation(still))
        self.image.show_pixbuf(still)
        self.assertIsNone(self.image._worker,
                          'a single picture left a thread running')

    def test_a_still_page_stops_the_animation_before_it(self):
        animation = image_tools.load_pixbuf(get_image_path('animated.gif'))
        self.image.show_pixbuf(animation)
        self.image.show_pixbuf(image_tools.load_pixbuf(get_image_path('blue.png')))
        still = self.image.get_paintable()
        wait_for(lambda: self.image.get_paintable() is not still,
                 seconds=2)
        self.assertIs(self.image.get_paintable(), still,
                      'the page went on animating after it had been replaced')

    def test_clearing_a_page_stops_the_animation(self):
        animation = image_tools.load_pixbuf(get_image_path('animated.gif'))
        self.image.show_pixbuf(animation)
        self.image.clear()
        self.assertIsNone(self.image.get_paintable())
        wait_for(lambda: self.image.get_paintable() is not None,
                 seconds=2)
        self.assertIsNone(self.image.get_paintable(),
                          'the page went on animating after it was cleared')

    def test_decoding_a_frame_does_not_add_to_the_wait_for_it(self):
        # Waiting the frame out and only then decoding the next one
        # makes a page as slow as the two together.  A page-sized
        # animation costs about as long to decode as a frame is allowed
        # to last, so thirty frames a second came out as fifteen; with
        # the wait counted from when the frame was due, decoding it is
        # paid for once rather than twice.
        cost = delay = 30
        frames = _SlowFrames(cost, delay)
        original = animation.frames
        animation.frames = lambda *args: frames
        try:
            animated = image_tools.load_pixbuf(
                get_image_path('animated.gif'))
            self.image.show_pixbuf(animated)
            drawn = []
            self.image.get_paintable().connect(
                'invalidate-contents', lambda *args: drawn.append(1))
            # A second of 30 ms frames is 33 of them when the decode
            # comes out of the frame's own time, and 16 when it is
            # added to it - which is what this measured before.
            wait_for(lambda: len(drawn) >= 25, seconds=1)
        finally:
            animation.frames = original
        self.assertGreaterEqual(
            len(drawn), 25,
            'the page paid for decoding each frame on top of showing it')

    def assertTextureMatches(self, texture, pixbuf):
        """<texture> holds the pixels of <pixbuf>.

        Gdk.pixbuf_get_from_texture(), which read them back as a pixbuf
        of their own, is deprecated as of GTK 4.10.  A
        Gdk.TextureDownloader is what reads a texture out now, and it is
        asked for the format to read it in - straight RGBA rather than
        the premultiplied BGRA that download() has always answered with.
        """
        self.assertEqual((texture.get_width(), texture.get_height()),
                         (pixbuf.get_width(), pixbuf.get_height()))
        downloader = Gdk.TextureDownloader.new(texture)
        downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
        data, stride = downloader.download_bytes()
        self.assertEqual(data.get_data(), self._as_rgba(pixbuf, stride))

    @staticmethod
    def _as_rgba(pixbuf, stride):
        """<pixbuf> as the rows of RGBA a texture downloads as."""
        pixels = pixbuf.get_pixels()
        channels = pixbuf.get_n_channels()
        rowstride = pixbuf.get_rowstride()
        out = bytearray()
        for y in range(pixbuf.get_height()):
            row = y * rowstride
            for x in range(pixbuf.get_width()):
                offset = row + x * channels
                out.extend(pixels[offset:offset + 3])
                out.append(pixels[offset + 3] if channels == 4 else 255)
            # Whatever the downloader pads each row out to.
            out.extend(b'\x00' * (stride - pixbuf.get_width() * 4))
        return bytes(out)

    # -- Pausing an animated page (upstream feature request 11) ---------

    def _frames_of(self, paintable):
        frames = []
        paintable.connect('invalidate-contents',
                          lambda *args: frames.append(1))
        return frames

    def test_a_paused_animation_draws_no_more_frames(self):
        self.image.show_pixbuf(
            image_tools.load_pixbuf(get_image_path('animated.gif')))
        self.assertTrue(self.image.is_animating())
        self.image.set_paused(True)
        self.assertTrue(self.image.is_paused())
        # A frame already handed to the main loop may still arrive.
        pump()
        frames = self._frames_of(self.image.get_paintable())
        wait_for(lambda: bool(frames), seconds=1)
        self.assertEqual([], frames, 'a paused animation went on')

    def test_a_resumed_animation_goes_on(self):
        self.image.show_pixbuf(
            image_tools.load_pixbuf(get_image_path('animated.gif')))
        self.image.set_paused(True)
        pump()
        frames = self._frames_of(self.image.get_paintable())
        self.image.set_paused(False)
        self.assertFalse(self.image.is_paused())
        wait_for(lambda: bool(frames))
        self.assertTrue(frames, 'the animation stayed paused')

    def test_the_same_page_drawn_again_stays_paused(self):
        """A zoom or a resize draws the page again, which is no reason
        for it to start running."""
        pixbuf = image_tools.load_pixbuf(get_image_path('animated.gif'))
        self.image.show_pixbuf(pixbuf)
        self.image.set_paused(True)
        self.image.show_pixbuf(pixbuf, (64, 48))
        self.assertTrue(self.image.is_paused())

    def test_another_page_starts_running(self):
        self.image.show_pixbuf(
            image_tools.load_pixbuf(get_image_path('animated.gif')))
        self.image.set_paused(True)
        self.image.show_pixbuf(
            image_tools.load_pixbuf(get_image_path('blue.png')))
        self.assertFalse(self.image.is_animating())
        self.image.show_pixbuf(
            image_tools.load_pixbuf(get_image_path('animated.gif')))
        self.assertFalse(self.image.is_paused())

    def test_stopping_a_paused_animation_ends_its_thread(self):
        self.image.show_pixbuf(
            image_tools.load_pixbuf(get_image_path('animated.gif')))
        self.image.set_paused(True)
        worker = self.image._worker
        # Long enough for the decoder to have parked on the pause, which
        # is where a stop that did not wake it would leave it.
        time.sleep(0.5)
        self.image.clear()
        worker.join(5)
        self.assertFalse(worker.is_alive(),
                         'a paused decoder did not notice the stop')


class _SlowFrames(animation.Frames):

    """A decoder that takes about as long as the frame it decodes."""

    ahead = True

    def __init__(self, cost, delay):
        self._cost = cost
        self._delay = delay
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
        pixbuf.fill(0)
        self._texture = image_tools.pixbuf_to_texture(pixbuf)

    def next(self):
        time.sleep(self._cost / 1000.0)
        return self._texture, self._delay

# vim: expandtab:sw=4:ts=4
