"""slideshow.py - Slideshow handler."""

from gi.repository import GLib, Gtk

from mcomix.preferences import prefs
from mcomix.i18n import _

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from mcomix import main
    from mcomix import ui


class Slideshow:

    """Slideshow handler that manages starting and stopping of slideshows."""

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        self._running = False
        self._id: int | None = None

    def _start(self) -> None:
        if not self._running:
            self._id = GLib.timeout_add(prefs['slideshow delay'], self._next)
            self._running = True
            self._window.update_title()

    def _stop(self) -> None:
        if self._running and self._id is not None:
            GLib.source_remove(self._id)
            self._running = False
            self._window.update_title()

    def _next(self) -> bool:
        if prefs['number of pixels to scroll per slideshow event'] != 0:

            self._window.scroll_with_flipping(0, prefs['number of pixels to scroll per slideshow event'])
        else:
            self._window.flip_page(+1)

        return True

    def toggle(self, action: "ui.Action") -> None:
        """Toggle a slideshow on or off."""
        if action.get_active():
            self._start()
            self._show_on_button('media-playback-stop-symbolic',
                                 _('Stop slideshow'))
        else:
            self._stop()
            self._show_on_button('media-playback-start-symbolic',
                                 _('Start slideshow'))

    def _show_on_button(self, icon_name: str, tooltip: str) -> None:
        """Show on the tool bar's button what pressing it would do.

        The icon goes into the image the tool bar made for the button,
        at the tool bar's icon size: Gtk.Button.set_icon_name() would put
        an image of the default size in its place.
        """
        button = self._window.uimanager.slideshow_button
        cast(Gtk.Image, button.get_child()).set_from_icon_name(icon_name)
        button.set_tooltip_text(tooltip)

    def is_running(self) -> bool:
        """Return True if a slideshow is currently running."""
        return self._running

    def update_delay(self) -> None:
        """Update the delay time a started slideshow is using."""
        if self.is_running():
            self._stop()
            self._start()


# vim: expandtab:sw=4:ts=4
