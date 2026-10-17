"""Portability functions for MComix."""

import ctypes
import locale
import sys
import time
from collections.abc import Callable

from mcomix import constants


def invalid_filesystem_chars() -> str:
    """List of characters that cannot be used in filenames on the target platform."""
    if sys.platform == "win32":
        return r':*?"<>|' + "".join([chr(i) for i in range(0, 32)])
    else:
        return ""


def get_default_locale() -> str:
    """Gets the user's default locale."""
    if sys.platform == "win32":
        windll = ctypes.windll.kernel32
        code = windll.GetUserDefaultUILanguage()
        # Python's table leaves out some of the languages Windows can be
        # displayed in, such as K'iche' (0x0486).
        return locale.windows_locale.get(code, "C")
    else:
        try:
            lang = locale.getdefaultlocale(
                ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"))[0]
        except ValueError:
            # A name locale.normalize() has no entry for, such as the
            # BCP 47 shaped zh_Hans_CN. Nothing better than "C" is known.
            return "C"
        if lang:
            return str(lang)
        else:
            return "C"


def seconds_since_process_start() -> float | None:
    """How long ago, by the system's clock, this process was created.

    Known on Windows only, where MComix.exe loads its DLLs before any
    Python runs; None elsewhere.
    """
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32
        # FILETIMEs, counted in 100 ns, read as the 64-bit numbers they are.
        created, exited, kernel, user, now = (ctypes.c_uint64() for _ in range(5))
        # The handle GetCurrentProcess() answers with, as a pointer:
        # ctypes would pass the int it returns as 32 bits.
        this_process = ctypes.c_void_p(-1)
        if not kernel32.GetProcessTimes(this_process, ctypes.byref(created),
                                        ctypes.byref(exited), ctypes.byref(kernel),
                                        ctypes.byref(user)):
            return None
        kernel32.GetSystemTimeAsFileTime(ctypes.byref(now))
        return (now.value - created.value) / 10_000_000
    return None


# What Windows answers a rename of a file that is open, in this process
# or another: ERROR_SHARING_VIOLATION, and ERROR_ACCESS_DENIED from
# os.replace() over one.
_WINDOWS_ERRORS_OF_AN_OPEN_FILE = frozenset((5, 32))
# The seconds waited before each attempt after the first: under one in all.
_WAITS_FOR_AN_OPEN_FILE = (0.01, 0.02, 0.05, 0.1, 0.2, 0.4)


def rename_once_closed(rename: Callable[[str, str], None], source: str,
                       target: str) -> None:
    """Rename <source> to <target> with <rename>, os.rename or os.replace.

    Windows refuses to rename a file that something has open, where
    Linux lets it go.  The thumbnail bar reading a page again, a virus
    scanner or Explorer's preview holds a file for a moment, so the
    rename is tried again for up to a second, and then fails as its
    last attempt does.
    """
    for wait in _WAITS_FOR_AN_OPEN_FILE:
        try:
            rename(source, target)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in _WINDOWS_ERRORS_OF_AN_OPEN_FILE:
                raise
        time.sleep(wait)
    rename(source, target)


def is_system_ui_dark_themed() -> constants.SystemThemeLightness:
    """Determine if the system is configured to use a dark theme by default."""
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
            ) as personalize_handle:
                _, values_count, _ = winreg.QueryInfoKey(personalize_handle)
                for key_index in range(values_count):
                    key_name, key_value, _ = winreg.EnumValue(
                        personalize_handle, key_index
                    )

                    if key_name == "AppsUseLightTheme":
                        if key_value == 0:
                            return constants.SystemThemeLightness.DARK
                        else:
                            return constants.SystemThemeLightness.LIGHT

                return constants.SystemThemeLightness.LIGHT
        except OSError:
            return constants.SystemThemeLightness.UNKNOWN
    return _colour_scheme_from_portal()


#: Where a freedesktop session keeps the colour scheme, and how long to
#: wait for the answer.  It is one round trip on a healthy session.
_APPEARANCE_NAMESPACE = "org.freedesktop.appearance"
_PORTAL_TIMEOUT_MS = 1000
#: What the portal answers with.
_PORTAL_NO_PREFERENCE, _PORTAL_DARK, _PORTAL_LIGHT = range(3)


def _colour_scheme_from_portal() -> constants.SystemThemeLightness:
    """Ask the desktop portal which colour scheme the session prefers.

    This is where a Wayland desktop keeps the setting.  GTK4 reads the
    portal for settings of its own, but does not turn a dark colour
    scheme into gtk-application-prefer-dark-theme by itself - libadwaita
    is what usually does that - so a plain GTK4 program stays light
    unless it asks.
    """
    from gi.repository import Gio, GLib

    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        return constants.SystemThemeLightness.UNKNOWN

    arguments = GLib.Variant("(ss)", (_APPEARANCE_NAMESPACE, "color-scheme"))
    for method in ("ReadOne", "Read"):
        # ReadOne is the newer of the two; a portal that predates it
        # answers Read instead, wrapped in one more variant.
        try:
            answer = connection.call_sync(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings",
                method, arguments, None, Gio.DBusCallFlags.NONE,
                _PORTAL_TIMEOUT_MS, None)
        except GLib.Error:
            continue
        value = answer.unpack()[0]
        while isinstance(value, GLib.Variant):
            value = value.unpack()
        if value == _PORTAL_DARK:
            return constants.SystemThemeLightness.DARK
        if value == _PORTAL_LIGHT:
            return constants.SystemThemeLightness.LIGHT
        return constants.SystemThemeLightness.UNKNOWN

    return constants.SystemThemeLightness.UNKNOWN


# vim: expandtab:sw=4:ts=4
