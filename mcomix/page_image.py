"""page_image.py - The widget a page is drawn in."""

import threading
import time

from gi.repository import Gdk, GLib, GObject, Gtk

from mcomix import animation
from mcomix import image_tools
from mcomix import log


class _AnimationPaintable(GObject.GObject, Gdk.Paintable):

    """One frame of an animation at a time, at a size that never moves.

    Handing a Gtk.Picture a new texture for every frame made it a new
    picture as far as GTK was concerned: the whole window was measured,
    laid out and drawn again thirty times a second.  A paintable that
    keeps its size and only says its contents changed damages the page
    and nothing else.
    """

    __gtype_name__ = 'MComixAnimationPaintable'

    def __init__(self, width: int, height: int) -> None:
        super(_AnimationPaintable, self).__init__()
        self._width = width
        self._height = height
        self._texture = None

    def set_texture(self, texture) -> None:
        self._texture = texture
        self.invalidate_contents()

    def get_texture(self):
        return self._texture

    def do_get_intrinsic_width(self) -> int:
        return self._width

    def do_get_intrinsic_height(self) -> int:
        return self._height

    def do_get_flags(self) -> Gdk.PaintableFlags:
        # Every frame is the same size; only what is drawn changes.
        return Gdk.PaintableFlags.SIZE

    def do_snapshot(self, snapshot, width, height) -> None:
        if self._texture is not None:
            # The frame arrives at the size it was decoded at and is
            # drawn at the size the page was laid out at.  Letting the
            # texture do that is a scale on the graphics card, where
            # scaling every frame with gdk-pixbuf first cost about nine
            # milliseconds of a page-sized frame's thirty-three.
            self._texture.snapshot(snapshot, width, height)


class PageImage(Gtk.Picture):

    """Draws one page, animated or not.

    Pages were Gtk.Images up to GTK3.  In GTK4 a Gtk.Image draws whatever
    it is given at an icon size, so pages are pictures now, and a picture
    draws a Gdk.Paintable rather than a pixbuf.
    """

    __gtype_name__ = 'MComixPageImage'

    def __init__(self) -> None:
        super(PageImage, self).__init__()
        # A page is drawn at its own size, on a canvas that scrolls over
        # it, rather than shrunk to whatever room happens to be left.
        self.set_can_shrink(False)
        #: Told to stop, and the thread it is told to.
        self._stopping = None
        self._worker = None
        #: What draws the frames, while there are frames to draw.
        self._animation = None

    def set_pixbuf(self, pixbuf, size=None) -> None:
        """Show <pixbuf>, which may be an animation.

        <size> is what the page has been laid out at.  A still page
        arrives already scaled to it; an animation cannot be, since only
        one of its frames exists at a time, so the paintable takes the
        size and every frame is drawn into it.
        """
        self._stop()
        if image_tools.is_animation(pixbuf):
            frame = pixbuf.get_static_image()
            if size is None:
                size = (frame.get_width(), frame.get_height())
            width, height = (max(1, int(round(side))) for side in size)
            self._animation = _AnimationPaintable(width, height)
            self._animation.set_texture(image_tools.pixbuf_to_texture(frame))
            # Gtk.Image.set_from_animation() is gone, and nothing GTK4
            # ships animates a pixbuf.  The frames are advanced from a
            # thread of its own rather than from a tick callback: a tick
            # callback only runs while something is redrawing the
            # window, and a paintable that damages nothing but itself is
            # not enough to keep the frame clock going - it ran at one
            # frame a second.
            self.set_paintable(self._animation)
            if not pixbuf.is_static_image():
                self._start(pixbuf)
            return
        self.set_paintable(image_tools.pixbuf_to_texture(pixbuf))

    def clear(self) -> None:
        """Stop showing anything."""
        self._stop()
        self.set_paintable(None)

    def _stop(self) -> None:
        if self._stopping is not None:
            # The thread notices and goes; nothing waits for it, and
            # whatever it hands over afterwards is thrown away.
            self._stopping.set()
            self._stopping = None
            self._worker = None
        self._animation = None

    def _start(self, pixbuf) -> None:
        """Decode the frames somewhere other than the main thread.

        Decoding one frame of a page-sized animation costs more than the
        frame is allowed to last, and doing that on the main thread both
        capped the rate and held up everything else the program had to
        do.  A thread of its own decodes and the main thread is left
        with nothing but handing the finished texture to the paintable.
        """
        frames = animation.frames(pixbuf, getattr(pixbuf, 'path', None))
        self._stopping = threading.Event()
        self._worker = threading.Thread(target=self._decode,
                                        args=(frames, self._animation,
                                              self._stopping),
                                        name='animation')
        self._worker.daemon = True
        self._worker.start()

    def _decode(self, frames, paintable, stopping) -> None:
        """Hand <paintable> a frame at a time until asked to stop."""
        due = time.monotonic()
        while not stopping.is_set():
            if not frames.ahead and self._wait(stopping, due):
                # This decoder is only ever asked for the frame that
                # belongs on screen now, so the wait has to come first
                # and the frame is late by however long it takes.
                return
            try:
                texture, delay = frames.next()
            except Exception as error:
                log.error('! Could not draw the next frame: %s', error)
                return
            if delay <= 0:
                # The end of an animation that does not go round again.
                return
            if frames.ahead and self._wait(stopping, due):
                return
            if stopping.is_set():
                return
            GLib.idle_add(self._show_frame, paintable, texture, stopping)
            # Frame times are counted from where the last frame was due
            # rather than from now, so that a decode that took too long
            # is not paid for twice; a page that cannot keep up at all
            # starts counting again rather than running up a debt.
            due = max(time.monotonic(),
                      due + max(animation.MINIMUM_DELAY, delay) / 1000.0)

    @staticmethod
    def _wait(stopping, due) -> bool:
        """Wait until <due>.  True if the animation was stopped instead."""
        return stopping.wait(max(0.0, due - time.monotonic()))

    def _show_frame(self, paintable, texture, stopping) -> bool:
        """Put a decoded frame on screen, if it is still wanted."""
        if not stopping.is_set() and paintable is self._animation:
            paintable.set_texture(texture)
        return GLib.SOURCE_REMOVE

# vim: expandtab:sw=4:ts=4
