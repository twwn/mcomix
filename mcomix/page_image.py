"""page_image.py - The widget a page is drawn in."""

from gi.repository import GLib, Gtk

from mcomix import image_tools


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
        self._iterator = None
        self._tick = None

    def set_pixbuf(self, pixbuf) -> None:
        """Show <pixbuf>, which may be an animation."""
        self._stop()
        if image_tools.is_animation(pixbuf):
            self._iterator = pixbuf.get_iter(None)
            pixbuf = self._iterator.get_pixbuf()
            # Gtk.Image.set_from_animation() is gone, and nothing GTK4
            # ships animates a pixbuf.  Advancing from the frame clock,
            # rather than from a timeout of its own, means the animation
            # runs while the page is on screen and stops with it - there
            # is no timer left over to turn off, and none running for a
            # page that has been turned past.
            self._tick = self.add_tick_callback(PageImage._advance)
        self.set_paintable(image_tools.pixbuf_to_texture(pixbuf))

    def clear(self) -> None:
        """Stop showing anything."""
        self._stop()
        self.set_paintable(None)

    def _stop(self) -> None:
        if self._tick is not None:
            self.remove_tick_callback(self._tick)
            self._tick = None
        self._iterator = None

    def _advance(self, _clock) -> bool:
        if self._iterator.advance(None):
            self.set_paintable(
                image_tools.pixbuf_to_texture(self._iterator.get_pixbuf()))
        return GLib.SOURCE_CONTINUE

# vim: expandtab:sw=4:ts=4
