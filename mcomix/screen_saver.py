"""screen_saver.py - Keeping the screen on while nobody touches a key.

A slideshow left to run gets no key and no mouse event, so the desktop
dims, blanks and locks the screen in the middle of it.  ScreenHold asks
the desktop not to, for as long as it is held:

- on Windows with SetThreadExecutionState();
- elsewhere with the desktop portal's Inhibit request on the session
  bus, which GNOME, KDE and the others answer and which is the one way
  out of a Flatpak's sandbox.  Where no portal answers, the screen
  blanks as it did.

Nothing here waits: the bus and the portal answer through the main
loop, and what was asked for is let go again if it is no longer wanted
by the time the answer comes.
"""

import ctypes
import sys

from gi.repository import Gio, GLib

from mcomix import log

from collections.abc import Callable

_PORTAL_NAME = 'org.freedesktop.portal.Desktop'
_PORTAL_PATH = '/org/freedesktop/portal/desktop'
#: The portal's flag for "the session going idle", which is what dims
#: and locks; the others are logging out, switching user and suspending.
_INHIBIT_IDLE = 8

#: SetThreadExecutionState(): ES_CONTINUOUS makes a state last until the
#: next call rather than resetting the idle timer once, and
#: ES_DISPLAY_REQUIRED is the state that keeps the display on.
_ES_CONTINUOUS = 0x80000000
_ES_DISPLAY_REQUIRED = 0x00000002


def _session_bus(ready: 'Callable[[Gio.DBusConnection | None], None]') -> None:
    """Call <ready> with the session bus once it is connected, or with
    None where there is none.  The one place that reaches the bus: the
    test suite replaces it, since a test must not keep the screen of
    whoever runs it on."""

    def connected(source: object, result: Gio.AsyncResult) -> None:
        try:
            ready(Gio.bus_get_finish(result))
        except GLib.Error as error:
            log.debug('No session bus to keep the screen on through: %s',
                      error.message)
            ready(None)

    Gio.bus_get(Gio.BusType.SESSION, None, connected)


class ScreenHold:

    """A request to the desktop to leave the screen on, held and let go
    any number of times."""

    def __init__(self, reason: str) -> None:
        #: What the desktop may show as the reason, a few words.
        self._reason = reason
        self._wanted = False
        #: True from asking the bus until the portal has answered.
        self._asking = False
        #: The portal's request while it holds, and the bus it is on.
        self._request: tuple[Gio.DBusConnection, str] | None = None

    def is_held(self) -> bool:
        """Whether the screen is to stay on, as far as was asked."""
        return self._wanted

    def hold(self) -> None:
        """Keep the screen on from now until release()."""
        if self._wanted:
            return
        self._wanted = True
        if sys.platform == 'win32':
            ctypes.windll.kernel32.SetThreadExecutionState(
                ctypes.c_uint(_ES_CONTINUOUS | _ES_DISPLAY_REQUIRED))
        elif self._request is None and not self._asking:
            self._asking = True
            _session_bus(self._inhibit)

    def release(self) -> None:
        """Let the screen dim and lock again as the desktop sees fit."""
        if not self._wanted:
            return
        self._wanted = False
        if sys.platform == 'win32':
            ctypes.windll.kernel32.SetThreadExecutionState(
                ctypes.c_uint(_ES_CONTINUOUS))
        else:
            # A request still on its way is closed when it arrives.
            self._close()

    def _inhibit(self, bus: 'Gio.DBusConnection | None') -> None:
        if bus is None or not self._wanted:
            self._asking = False
            return
        bus.call(
            _PORTAL_NAME, _PORTAL_PATH, 'org.freedesktop.portal.Inhibit',
            'Inhibit',
            # The parent window, which only places a dialog the portal
            # never shows for this; the flags; the options.
            GLib.Variant('(sua{sv})', ('', _INHIBIT_IDLE, {
                'reason': GLib.Variant('s', self._reason)})),
            GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, -1, None,
            self._inhibited)

    def _inhibited(self, bus: 'Gio.DBusConnection | None',
                   result: Gio.AsyncResult) -> None:
        self._asking = False
        if bus is None:
            return
        try:
            (request,) = bus.call_finish(result).unpack()
        except GLib.Error as error:
            # No portal, or one whose desktop has no Inhibit.
            log.debug('The desktop will not keep the screen on: %s',
                      error.message)
            return
        self._request = (bus, request)
        if not self._wanted:
            self._close()

    def _close(self) -> None:
        """Close the portal's request, which is what ends it; the portal
        also ends it by itself when MComix leaves the bus."""
        if self._request is None:
            return
        bus, request = self._request
        self._request = None
        bus.call(_PORTAL_NAME, request, 'org.freedesktop.portal.Request',
                 'Close', None, None, Gio.DBusCallFlags.NONE, -1, None,
                 None)


# vim: expandtab:sw=4:ts=4
