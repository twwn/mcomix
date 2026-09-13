"""recent.py - Recent files handler."""

import urllib.request, urllib.parse, urllib.error
from gi.repository import Gio, GLib, GObject, Gtk
import os

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main
    from mcomix import ui as ui_module

from mcomix import preferences
from mcomix import portability
from mcomix import archive_tools
from mcomix import image_tools
from mcomix import log
from mcomix.i18n import _


class RecentFilesMenu(object):

    """The "Recent" submenu, built from the recently-used file list GTK
    keeps for every application.

    Gtk.RecentChooserMenu used to assemble this by itself.  GTK4 removes
    every RecentChooser widget while keeping Gtk.RecentManager, which is
    not deprecated and still holds the list, so the menu is put together
    here from what the manager reports.

    What is kept up to date is a Gio.Menu model, which is what the menu
    bar takes.  Opening an entry goes through one action carrying the
    file's URI, under its own prefix.
    """

    #: Where this menu's action lives, as menu items address it.
    ACTION_PREFIX = 'recent'
    OPEN_ACTION = 'open' 

    #: How many entries to show, which is what Gtk.RecentChooserMenu did.
    _LIMIT = 10

    def __init__(self, ui: "ui_module.MainUI",
                 window: "main.MainWindow") -> None:
        self._window = window
        self._manager = Gtk.RecentManager.get_default()

        supported_formats = {}
        supported_formats.update(image_tools.get_supported_formats())
        supported_formats.update(archive_tools.get_supported_formats())
        self._mime_types: set[str] = set()
        self._extensions: set[str] = set()
        for name in supported_formats:
            mime_types, extensions = supported_formats[name]
            self._mime_types.update(mime_types)
            self._extensions.update('.%s' % ext.lower() for ext in extensions)

        self.model = Gio.Menu()
        self._actions = Gio.SimpleActionGroup()
        open_action = Gio.SimpleAction.new(self.OPEN_ACTION,
                                           GLib.VariantType.new('s'))
        open_action.connect('activate', self._open_activated)
        self._actions.add_action(open_action)
        if window is not None:
            window.insert_action_group(self.ACTION_PREFIX, self._actions)

        self._manager.connect('changed', self._changed)
        self._rebuild()

    def _changed(self, *args: object) -> None:
        self._rebuild()

    def _is_supported(self, info: Gtk.RecentInfo) -> bool:
        """Whether <info> names a file MComix knows how to open.

        Gtk.RecentFilter matched an item if either its mime type or its
        name did; this asks the same two questions.
        """
        if info.get_mime_type() in self._mime_types:
            return True
        return os.path.splitext(info.get_uri())[1].lower() in self._extensions

    @staticmethod
    def _modified(info: Gtk.RecentInfo) -> int:
        """When <info> was last modified, as a number that sorts.

        Gtk.RecentInfo.get_modified() answers with a GLib.DateTime, and
        seconds since the epoch is what the sort wants.
        """
        modified = info.get_modified()
        return modified.to_unix() if modified is not None else 0

    def _rebuild(self) -> None:
        """Fill the menu with the files that are still worth offering."""
        self.model.remove_all()

        # Local files only, most recently used first, as the chooser did.
        items = [info for info in self._manager.get_items()
                 if info.is_local() and self._is_supported(info)]
        items.sort(key=self._modified, reverse=True)

        for info in items[:self._LIMIT]:
            entry = Gio.MenuItem.new(info.get_display_name(), None)
            entry.set_action_and_target_value(
                '%s.%s' % (self.ACTION_PREFIX, self.OPEN_ACTION),
                GLib.Variant('s', info.get_uri()))
            self.model.append_item(entry)

        if not items:
            # Nothing to offer; say so with an entry that cannot be picked.
            empty = Gio.SimpleAction.new('nothing', None)
            empty.set_enabled(False)
            if self._actions.lookup_action('nothing') is None:
                self._actions.add_action(empty)
            self.model.append(_('No entries found'),
                              '%s.nothing' % self.ACTION_PREFIX)


    def _open_activated(self, action: Gio.SimpleAction,
                        target: GLib.Variant) -> None:
        self._load(target.get_string())

    def _load(self, uri: str) -> None:
        path = urllib.request.url2pathname(uri[7:])
        did_file_load = self._window.filehandler.open_file(path)

        if not did_file_load:
            self.remove_path(path)

    def count(self) -> int:
        """ Returns the amount of stored entries. """
        return len(self._manager.get_items())

    def add_path(self, path: str) -> None:
        """Record <path> as recently opened."""
        if not preferences.prefs['store recent file info']:
            return
        uri = portability.uri_prefix() + urllib.request.pathname2url(path)
        self._manager.add_item(uri)

    def remove_path(self, path: str) -> None:
        """Forget <path>, which could not be opened."""
        if not preferences.prefs['store recent file info']:
            return
        uri = portability.uri_prefix() + urllib.request.pathname2url(path)
        try:
            self._manager.remove_item(uri)
        except GLib.GError:
            # Could not remove item
            pass

    def remove_all(self) -> None:
        """ Removes all entries to recently opened files. """
        try:
            self._manager.purge_items()
        except GObject.GError as error:
            log.debug(error)


# vim: expandtab:sw=4:ts=4
