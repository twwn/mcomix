"""page_image.py - The widget a page is drawn in."""

import threading
import time

from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk

from collections.abc import Sequence

from mcomix import animation
from mcomix import image_tools
from mcomix import log
from mcomix.i18n import _


# pygobject-stubs declares props on GObject.Object and on the
# interface base with signatures that do not match, so any class
# implementing a GTK interface is reported.
class _AnimationPaintable(GObject.GObject, Gdk.Paintable):  # type: ignore[misc]

    """One frame of an animation at a time, at a size that never moves.

    Handing a Gtk.Picture a new texture for every frame made it a new
    picture as far as GTK was concerned: the whole window was measured,
    laid out and drawn again thirty times a second.  A paintable that
    keeps its size and only says its contents changed damages the page
    and nothing else.
    """

    __gtype_name__ = 'MComixAnimationPaintable'

    def __init__(self, width: int, height: int) -> None:
        super().__init__()
        self._width = width
        self._height = height
        self._texture: Gdk.Texture | None = None

    def set_texture(self, texture: Gdk.Texture) -> None:
        self._texture = texture
        self.invalidate_contents()

    def do_get_intrinsic_width(self) -> int:
        return self._width

    def do_get_intrinsic_height(self) -> int:
        return self._height

    def do_get_flags(self) -> Gdk.PaintableFlags:
        # Every frame is the same size; only what is drawn changes.
        # GDK_PAINTABLE_STATIC_SIZE by its value: what PyGObject 3.46,
        # the floor, calls the flag depends on the GTK it reads it from
        # - SIZE from GTK 4.14's typelib, STATIC_SIZE from 4.22's - and
        # only newer PyGObject answers to both.
        return Gdk.PaintableFlags(1)

    def do_snapshot(self, snapshot: Gtk.Snapshot, width: float,
                    height: float) -> None:
        if self._texture is not None:
            # The frame arrives at the size it was decoded at and is
            # drawn at the size the page was laid out at.  Letting the
            # texture do that is a scale on the graphics card, where
            # scaling every frame with gdk-pixbuf first cost about nine
            # milliseconds of a page-sized frame's thirty-three.
            self._texture.snapshot(snapshot, width, height)


class _Playback:

    """Whether the frames of one animation go on: running, paused, or
    stopped for good.

    The main thread pauses and stops it; the thread decoding the frames
    waits on it, and a pause or a stop reaches that thread at once
    rather than after the frame it was waiting out.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._stopped = False
        self.paused = False
        #: How many times as fast as the file says the frames come.
        self.speed = 1.0

    def is_stopped(self) -> bool:
        # Read without the lock: it only ever goes from False to True.
        return self._stopped

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()

    def set_paused(self, paused: bool) -> None:
        with self._condition:
            self.paused = paused
            self._condition.notify_all()

    def wait_until(self, due: float) -> float | None:
        """Wait until <due>, later by however long the animation is
        paused meanwhile, so that the frame on screen keeps what was left
        of its time.  The time it waited until, or None if the animation
        was stopped instead."""
        with self._condition:
            while not self._stopped:
                if self.paused:
                    since = time.monotonic()
                    self._condition.wait()
                    due += time.monotonic() - since
                    continue
                left = due - time.monotonic()
                if left <= 0:
                    return due
                self._condition.wait(left)
            return None


class PageImage(Gtk.Picture):

    """Draws one page, animated or not.

    Pages were Gtk.Images up to GTK3.  In GTK4 a Gtk.Image draws whatever
    it is given at an icon size, so pages are pictures now, and a picture
    draws a Gdk.Paintable rather than a pixbuf.
    """

    __gtype_name__ = 'MComixPageImage'

    def __init__(self) -> None:
        super().__init__()
        # A page is drawn at its own size, on a canvas that scrolls over
        # it, rather than shrunk to whatever room happens to be left.
        self.set_can_shrink(False)
        #: Told to pause or stop, and the thread it is told to.
        self._playback: _Playback | None = None
        #: The file the animation on screen comes from.
        self._path: str | None = None
        self._worker: threading.Thread | None = None
        #: What draws the frames, while there are frames to draw.
        self._animation: _AnimationPaintable | None = None
        #: What set_speed() asked for, which a page shown later keeps.
        self._speed = 1.0

    def show_pixbuf(self, pixbuf: GdkPixbuf.Pixbuf,
                    size: Sequence[float] | None = None) -> None:
        """Show <pixbuf>, which may be an animation.

        <size> is what the page has been laid out at.  A still page
        arrives already scaled to it; an animation cannot be, since only
        one of its frames exists at a time, so the paintable takes the
        size and every frame is drawn into it.

        Not set_pixbuf(): that is a Gtk.Picture method, deprecated in GTK
        4.12, and overriding it with a second argument left the widget
        answering to a name of the base class's with a signature the base
        class does not have.
        """
        path = image_tools.animation_path(pixbuf)
        # The same page drawn again, at another size or zoom, stays
        # paused; another page starts running.
        paused = path is not None and path == self._path and self.is_paused()
        self._stop()
        if path is not None:
            # <pixbuf> is the first frame; the rest are read from the
            # file it came out of.
            if size is None:
                size = (pixbuf.get_width(), pixbuf.get_height())
            width, height = (max(1, int(round(side))) for side in size)
            self._animation = _AnimationPaintable(width, height)
            self._animation.set_texture(image_tools.pixbuf_to_texture(pixbuf))
            # Nothing GTK4 ships animates a pixbuf.  The frames are
            # advanced from a thread of their own rather than from a tick
            # callback: a tick callback only runs while something is
            # redrawing the window, and a paintable that damages nothing
            # but itself does not keep the frame clock going, which then
            # runs at one frame a second.
            self.set_paintable(self._animation)
            self._start(path, paused)
            return
        self.set_paintable(image_tools.pixbuf_to_texture(pixbuf))

    def clear(self) -> None:
        """Stop showing anything."""
        self._stop()
        self.set_paintable(None)

    def is_animating(self) -> bool:
        """Whether the page on screen is an animation, paused or not."""
        return self._playback is not None

    def set_speed(self, speed: float) -> None:
        """Play this page's animation, and those it shows later, <speed>
        times as fast as their files say (upstream feature request 11)."""
        self._speed = speed
        if self._playback is not None:
            self._playback.speed = speed

    def is_paused(self) -> bool:
        """Whether the animation on screen is paused."""
        return self._playback is not None and self._playback.paused

    def set_paused(self, paused: bool) -> None:
        """Pause the animation on screen at the frame it shows, or let it
        go on from there.  The next page shown starts running."""
        if self._playback is not None:
            self._playback.set_paused(paused)

    def _stop(self) -> None:
        if self._playback is not None:
            # The thread notices and goes; nothing waits for it, and
            # whatever it hands over afterwards is thrown away.
            self._playback.stop()
            self._playback = None
            self._worker = None
        self._animation = None
        self._path = None

    def _start(self, path: str, paused: bool) -> None:
        """Decode the frames somewhere other than the main thread.

        Decoding one frame of a page-sized animation costs more than the
        frame is allowed to last, and doing that on the main thread both
        capped the rate and held up everything else the program had to
        do.  A thread of its own decodes and the main thread is left
        with nothing but handing the finished texture to the paintable.
        """
        frames = animation.frames(path)
        self._path = path
        self._playback = _Playback()
        self._playback.set_paused(paused)
        self._playback.speed = self._speed
        self._worker = threading.Thread(target=self._decode,
                                        args=(frames, self._animation,
                                              self._playback),
                                        name='animation')
        self._worker.daemon = True
        self._worker.start()

    def _decode(self, frames: animation.Frames,
                paintable: _AnimationPaintable,
                playback: _Playback) -> None:
        """Hand <paintable> a frame at a time until asked to stop."""
        due = time.monotonic()
        while not playback.is_stopped():
            if not frames.ahead:
                # This decoder is only ever asked for the frame that
                # belongs on screen now, so the wait has to come first
                # and the frame is late by however long it takes.
                waited = playback.wait_until(due)
                if waited is None:
                    return
                due = waited
            try:
                texture, delay = frames.next()
            except Exception as error:
                log.error(_('! Could not draw the next frame: %s'), error)
                return
            if delay <= 0:
                # The end of an animation that does not go round again.
                return
            if frames.ahead:
                waited = playback.wait_until(due)
                if waited is None:
                    return
                due = waited
            if playback.is_stopped():
                return
            GLib.idle_add(self._show_frame, paintable, texture, playback)
            # Frame times are counted from where the last frame was due
            # rather than from now, so that a decode that took too long
            # is not paid for twice; a page that cannot keep up at all
            # starts counting again rather than running up a debt.
            due = max(time.monotonic(),
                      due + max(animation.MINIMUM_DELAY, delay)
                      / 1000.0 / playback.speed)

    def _show_frame(self, paintable: _AnimationPaintable,
                    texture: Gdk.Texture, playback: _Playback) -> bool:
        """Put a decoded frame on screen, if it is still wanted."""
        if not playback.is_stopped() and paintable is self._animation:
            paintable.set_texture(texture)
        return GLib.SOURCE_REMOVE

# vim: expandtab:sw=4:ts=4
