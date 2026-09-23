"""Portability functions for MComix."""

import ctypes
import locale
import sys

from mcomix import constants


def uri_prefix() -> str:
    """The prefix used for creating file URIs. This is 'file://' on
    Linux, but 'file:' on Windows due to urllib using a different
    URI creating scheme here."""
    if sys.platform == "win32":
        return "file:"
    else:
        return "file://"


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
