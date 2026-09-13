"""slideshow.py - Slideshow handler."""

from gi.repository import GLib

from mcomix.preferences import prefs
from mcomix.i18n import _

from typing import TYPE_CHECKING

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

    def toggle(self, action: "ui._Action") -> None:
        """Toggle a slideshow on or off."""
        if action.get_active():
            self._start()
            self._window.uimanager.slideshow_button.set_icon_name('media-playback-stop')
            self._window.uimanager.slideshow_button.set_tooltip_text( _('Stop slideshow')  )
        else:
            self._stop()
            self._window.uimanager.slideshow_button.set_icon_name('media-playback-start')
            self._window.uimanager.slideshow_button.set_tooltip_text( _('Start slideshow') )

    def is_running(self) -> bool:
        """Return True if a slideshow is currently running."""
        return self._running

    def update_delay(self) -> None:
        """Update the delay time a started slideshow is using."""
        if self.is_running():
            self._stop()
            self._start()


# vim: expandtab:sw=4:ts=4
