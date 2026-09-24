"""recent.py - Recent files handler."""

from gi.repository import Gio, GLib, Gtk
import os

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main
    from mcomix import ui as ui_module

from mcomix import preferences
from mcomix import process
from mcomix import archive_tools
from mcomix import image_tools
from mcomix import log
from mcomix import widgets
from mcomix.i18n import _


def _uri(path: str) -> str:
    """The URI the recently-used list keeps <path> under.

    GLib's: GTK keeps every entry the way GLib writes its URI, and
    urllib's pathname2url() escapes the brackets, commas and plus signs
    GLib leaves alone, and from Python 3.14 on begins an absolute path
    with "///", so an entry named by it was never found to remove.
    """
    return Gio.File.new_for_path(path).get_uri()


class RecentFilesMenu:

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

    def _items(self) -> list[Gtk.RecentInfo]:
        """The entries worth offering: local files only, most recently
        used first, as Gtk.RecentChooserMenu picked them."""
        items = [info for info in self._manager.get_items()
                 if info.is_local() and self._is_supported(info)]
        items.sort(key=self._modified, reverse=True)
        return items

    def paths(self) -> list[str]:
        """Where the files on the list are, most recently used first."""
        paths = []
        for info in self._items():
            path = Gio.File.new_for_uri(info.get_uri()).get_path()
            if path is not None:
                paths.append(path)
        return paths

    def _rebuild(self) -> None:
        """Fill the menu with the files that are still worth offering."""
        self.model.remove_all()

        items = self._items()
        for info in items[:self._LIMIT]:
            entry = Gio.MenuItem.new(
                widgets.menu_label(info.get_display_name()), None)
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
        uri = target.get_string()
        if widgets.take_middle_click():
            self._open_in_new_instance(uri)
        else:
            self._load(uri)

    def _load(self, uri: str) -> None:
        path = Gio.File.new_for_uri(uri).get_path()
        if path is None:
            return
        did_file_load = self._window.filehandler.open_file(path)

        if not did_file_load:
            self.remove_path(path)

    def _open_in_new_instance(self, uri: str) -> None:
        """Open what <uri> names in an MComix of its own.

        The book being read stays where it is, which is what the middle
        button means everywhere it opens something: a window of its own
        rather than this one's contents replaced.
        """
        path = Gio.File.new_for_uri(uri).get_path()
        if path is not None:
            process.launch_mcomix(path)

    def count(self) -> int:
        """How many entries the menu has to offer, shown or not."""
        return len(self._items())

    def add_path(self, path: str) -> None:
        """Record <path> as recently opened."""
        if not preferences.prefs['store recent file info']:
            return
        uri = _uri(path)
        self._manager.add_item(uri)

    def remove_path(self, path: str) -> None:
        """Forget <path>, which could not be opened."""
        if not preferences.prefs['store recent file info']:
            return
        uri = _uri(path)
        try:
            self._manager.remove_item(uri)
        except GLib.GError:
            # Could not remove item
            pass

    def remove_all(self) -> None:
        """Take every entry the menu offers off the recently-used list.

        Those alone: the list is the whole desktop's, and purging it, as
        this used to, took every other program's history with it.
        """
        for info in self._items():
            try:
                self._manager.remove_item(info.get_uri())
            except GLib.GError as error:
                log.debug(error)


# vim: expandtab:sw=4:ts=4
