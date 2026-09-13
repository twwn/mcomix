"""animation.py - The frames of an animated page, one at a time."""

from gi.repository import Gdk, GdkPixbuf, Gio, GLib

from PIL import Image

from mcomix import image_tools
from mcomix import log

from typing import Any


#: However short a frame says it is, no faster than this.
MINIMUM_DELAY = 10

#: What a frame that gives no time of its own is shown for.  A GIF
#: written with a delay of zero means "as fast as you like", and both
#: gdk-pixbuf and the browsers have long since settled on this.
DEFAULT_DELAY = 100


class Frames(object):

    """The frames of one animation, in order, for ever.

    Nothing here draws anything: a frame is decoded and turned into the
    texture it will be drawn from, and the caller decides when.
    """

    #: Whether a frame can be decoded before the moment it is due.
    ahead = False

    def next(self) -> tuple[Gdk.Texture, int]:
        """Return the next (texture, milliseconds it is shown for).

        A delay of zero or less means the animation has run out and
        there is nothing more to draw.
        """
        raise NotImplementedError


class _PillowFrames(Frames):

    """Frames decoded by Pillow, in this process.

    gdk-pixbuf hands its loaders to glycin, which decodes in a process
    of its own and passes whole frames back over shared memory: one
    1080x1920 WebP frame costs around 34 ms that way against 9 ms
    decoded here.  At thirty frames a second that is longer than the
    frame is allowed to last, so the page could only ever fall further
    behind, and it did - such a page played at about a third speed with
    a core pinned the whole time.

    Pillow also numbers its frames, so the next one can be decoded while
    the current one is still on screen; gdk-pixbuf's iterator only
    answers "what should be on screen now".
    """

    ahead = True

    def __init__(self, path: str) -> None:
        self._image = Image.open(path)
        self._frames = getattr(self._image, 'n_frames', 1)
        if self._frames < 2:
            raise ValueError('%s holds a single picture' % path)
        self._index = -1

    def next(self) -> tuple[Gdk.Texture, int]:
        self._index = (self._index + 1) % self._frames
        self._image.seek(self._index)
        # Seeking only says which frame is wanted; a WebP fills in how
        # long that frame lasts as it decodes it, so the delay has to be
        # read after the pixels have been asked for and not before.
        texture = image_tools.pil_to_texture(self._image)
        return texture, self._image.info.get('duration') or DEFAULT_DELAY


class _GlycinFrames(Frames):

    """Frames decoded by glycin, which is what gdk-pixbuf hands to.

    GdkPixbuf.PixbufAnimation and its iterator, which this replaces, are
    deprecated as of GTK 4.10 with nothing in their place.  glycin is
    the decoder underneath them, and it hands out a Gdk.Texture rather
    than a pixbuf to convert, so nothing is copied on the way.

    Unlike the iterator, which could only be asked for the frame that
    belongs on screen at this instant, this is a sequence: the next
    frame can be decoded while the current one is still up.  It runs out
    at the end of the file, and starts again where the animation loops.
    """

    ahead = True

    def __init__(self, path: str) -> None:
        self._Gly, self._GlyGtk4 = image_tools.glycin()
        self._file = Gio.File.new_for_path(path)
        self._image = self._load()

    def _load(self) -> Any:
        return self._Gly.Loader.new(self._file).load()

    def next(self) -> tuple[Gdk.Texture, int]:
        try:
            frame = self._image.next_frame()
        except GLib.Error:
            # There are no more; a page that moves goes round again,
            # which is what the iterator did on its own.
            self._image = self._load()
            frame = self._image.next_frame()
        # glycin counts a frame in microseconds.
        return self._GlyGtk4.frame_get_texture(frame), frame.get_delay() // 1000


class _PixbufFrames(Frames):

    """Frames from gdk-pixbuf's own iterator.

    The last resort: GdkPixbuf.PixbufAnimation is deprecated as of GTK
    4.10, and this is here for a tree that has no glycin - Windows,
    where GTK ships gdk-pixbuf's loaders and nothing else - and a file
    Pillow will not open.

    The one thing it can be asked for is the frame that belongs on
    screen at this instant, so a frame cannot be decoded ahead of time
    and a slow decode silently drops the frames it ran past.
    """

    def __init__(self, path: str) -> None:
        animation = GdkPixbuf.PixbufAnimation.new_from_file(path)
        if animation is None:
            raise ValueError('%s holds no animation' % path)
        self._iterator = animation.get_iter(None)
        self._started = False

    def next(self) -> tuple[Gdk.Texture, int]:
        if self._started:
            self._iterator.advance(None)
        self._started = True
        # The iterator hands out one pixbuf and paints the next frame
        # over it, so the texture gets a copy of its own rather than a
        # window onto whatever is being decoded next.
        pixbuf = self._iterator.get_pixbuf()
        frame = pixbuf.copy() if pixbuf is not None else None
        if frame is None:
            raise ValueError('the animation has no frame to draw')
        return image_tools.pixbuf_to_texture(frame), \
            self._iterator.get_delay_time()


#: The decoders frames() tries, in order.
_DECODERS = (_PillowFrames, _GlycinFrames, _PixbufFrames)


def frames(path: str) -> Frames:
    """Return the Frames of the animation in <path>."""
    last_error = None
    for decoder in _DECODERS:
        try:
            return decoder(path)
        except Exception as error:
            last_error = error
            log.debug('%s will not animate %s (%s)',
                      decoder.__name__, path, error)
    raise last_error or ValueError('%s holds no animation' % path)

# vim: expandtab:sw=4:ts=4
