"""watchlist.py - The dialog for the directories the library watches.

A list of the watched directories, one row each, with the collection
what turns up there is filed in and whether subdirectories are walked
as well.  Both of those are edited in place and write straight to the
watchlist table, and the Remove button follows the selection.  The
checkbox below them is the "scan on startup" preference, and Scan now
starts by hand the same search that preference runs when the library
opens, without closing the dialog - as does closing it after a change.
It is offered only while there is a directory to scan.
"""

import os
from gi.repository import Gio, Gtk, GLib

from mcomix.library import backend_types
from mcomix.dialog import Dialog
from mcomix import column_list
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library import main_dialog


class WatchListDialog(Dialog):
    """ Dialog for managing watched directories. """

    RESPONSE_SCANNOW = 1000

    def __init__(self, library: "main_dialog._LibraryDialog") -> None:
        super().__init__(
            title=_("Library watch list"), transient_for=library,
            destroy_with_parent=True, modal=True)
        self.add_buttons(_('_Scan now'), WatchListDialog.RESPONSE_SCANNOW,
                         _('_Close'), Response.CLOSE)

        #: Stores a reference to the library
        self.library = library
        #: True if changes were made to the watchlist. Not 100% accurate.
        self._changed = False

        self.set_default_response(Response.CLOSE)

        # Initialize the list control showing existing watch directories
        self._list = column_list.ColumnListView()
        self._list.add_text_column(_("Directory"), 'directory', expand=True)
        self._list.add_choice_column(_("Collection"), 'collection_id',
                                     self._collection_names,
                                     self._collection_chosen,
                                     shown=self._collection_name_of)
        self._list.add_toggle_column(_("With subdirectories"), 'recursive',
                                     self._recursive_changed_cb)
        self._list.selection.connect('selection-changed',
                                     self._item_selected_cb)

        add_button = Gtk.Button.new_with_mnemonic(_('_Add'))
        add_button.connect('clicked', self._add_cb)
        self._remove_button = remove_button = Gtk.Button.new_with_mnemonic(_('_Remove'))
        remove_button.set_sensitive(False)
        remove_button.connect('clicked', self._remove_cb)

        button_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        widgets.pack(button_box, add_button, False, False, 0)
        widgets.pack(button_box, remove_button, False, False, 2)

        main_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        scroll_window = Gtk.ScrolledWindow()
        scroll_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll_window.set_child(self._list)
        widgets.pack(main_box, scroll_window, True, True, 2)
        widgets.pack(main_box, button_box, False, False, 0, end=True)
        widgets.pack(self.get_content_area(), main_box, True, True, 0)

        auto_checkbox = Gtk.CheckButton(
            label=_('Automatically scan for new books when library is _opened'),
            use_underline=True)
        auto_checkbox.set_active(prefs['scan for new books on library startup'])
        auto_checkbox.connect('toggled', self._auto_scan_toggled_cb)
        widgets.pack(self.get_content_area(), auto_checkbox, False, False, 5, end=True)

        # After the Remove button, which the selection turns on and off
        # as soon as there are rows to select, and after the Scan now
        # button that _fill_model() turns on and off with the list.
        self._fill_model()

        self.set_default_size(475, 350)
        self.connect('response', self._response_cb)
        self.set_visible(True)

    def get_selected_watchlist_entry(
            self) -> "backend_types._WatchListEntry | None":
        """ Returns the selected watchlist entry, or None if no row is
        selected. """
        row = self._list.get_selected_row()
        if row is None:
            return None
        return self.library.backend.watchlist.get_watchlist_entry(
            row.directory)

    def _fill_model(self) -> None:
        """ Empties the list and updates it from the database. """
        self._list.set_rows(
            column_list.Row(directory=entry.directory,
                            collection_id=(-1
                                           if entry.collection is None
                                           or entry.collection.id is None
                                           else entry.collection.id),
                            recursive=entry.recursive)
            for entry in self.library.backend.watchlist.get_watchlist())
        self._update_scan_button()

    def _update_scan_button(self) -> None:
        """Offer Scan now only while there is a directory to scan.

        A scan of an empty watch list walks nothing and reports nothing,
        so the button pressed over an empty list looks broken; a
        disabled one says there is nothing to scan for.
        """
        self.set_response_sensitive(WatchListDialog.RESPONSE_SCANNOW,
                                    self._list.store.get_n_items() > 0)

    def _collection_names(self) -> list[str]:
        """ The name of every collection a directory can be watched into. """
        names = [backend_types.DefaultCollection.name]
        for id in self.library.backend.get_all_collections():
            name = self.library.backend.get_collection_name(id)
            if name is not None:
                names.append(name)
        return names

    def _collection_id_for(self, name: str) -> int:
        """ The id of the collection called <name>, -1 for the default. """
        for id in self.library.backend.get_all_collections():
            if self.library.backend.get_collection_name(id) == name:
                return id
        return -1

    def _collection_name_of(self, row: column_list.Row) -> str:
        """ The name of the collection <row> is watched into. """
        if row.collection_id == -1:
            return backend_types.DefaultCollection.name
        name = self.library.backend.get_collection_name(row.collection_id)
        # A directory whose collection has gone is watched into the default
        # one, which is what the next refill of the list says as well.
        return name if name is not None else backend_types.DefaultCollection.name

    def _collection_chosen(self, row: column_list.Row, name: str) -> None:
        """ A new collection was set for a watched directory. """
        new_id = self._collection_id_for(name)
        if new_id == row.collection_id:
            return
        collection = self.library.backend.get_collection_by_id(new_id)
        if collection is None:
            # The collection was removed since the list was filled in.
            return
        self.library.backend.watchlist.get_watchlist_entry(
            row.directory).set_collection(collection)
        row.collection_id = new_id

        self._changed = True

    def _recursive_changed_cb(self, row: column_list.Row,
                              status: bool) -> None:
        """ Recursive reading was enabled or disabled. """
        self.library.backend.watchlist.get_watchlist_entry(
            row.directory).set_recursive(status)
        row.recursive = status

        self._changed = True

    def _add_cb(self, button: Gtk.Button, *args: object) -> None:
        """ Called when a new watch list entry should be added. """
        # Gtk.FileChooserDialog is deprecated as of GTK 4.10; a
        # Gtk.FileDialog answers in a callback with the folder that was
        # picked, or raises when the user dismissed it.
        chooser = Gtk.FileDialog(modal=True)
        chooser.select_folder(self, None, self._directory_chosen)

    def _directory_chosen(self, chooser: Gtk.FileDialog,
                          result: Gio.AsyncResult) -> None:
        """ Add the directory the file chooser came back with. """
        try:
            chosen = chooser.select_folder_finish(result)
        except GLib.Error:
            # The only thing it fails with is the user closing it.
            return
        directory = (chosen.get_path() if chosen is not None else None) or ""

        if os.path.isdir(directory):

            self.library.backend.watchlist.add_directory(directory)
            self._fill_model()

            self._changed = True

    def _remove_cb(self, button: Gtk.Button, *args: object) -> None:
        """ Called when a watch list entry should be removed. """
        row = self._list.get_selected_row()
        if row is None:
            return
        entry = self.library.backend.watchlist.get_watchlist_entry(
            row.directory)
        if entry:
            entry.remove()
            self._list.remove_row(row)
            self._update_scan_button()

    def _item_selected_cb(self, selection: Gtk.SelectionModel,
                          *args: object) -> None:
        """ Called when an item is selected. Enables or disables the "Remove"
        button. """
        self._remove_button.set_sensitive(
            bool(self._list.get_selected_positions()))

    def _auto_scan_toggled_cb(self, checkbox: Gtk.CheckButton,
                              *args: object) -> None:
        """ Toggles automatic library book scanning. """
        prefs['scan for new books on library startup'] = checkbox.get_active()

    def _response_cb(self, dialog: Dialog, response: int,
                     *args: object) -> None:
        """Scan now scans and stays open; anything else closes.

        Scan now used to close the dialog as well, which took the list
        away from a reader who had pressed it to see what the directory
        they had just added held.  The scan it starts covers every edit
        made so far, so the dialog no longer owes one when it closes.

        Closing counts whichever way it was done: the edits are written
        to the database as they are made, so escape and the window's own
        close button leave exactly as much to scan for as Close does.
        """
        if response == WatchListDialog.RESPONSE_SCANNOW:
            self._changed = False
            self.library.scan_for_new_files()
            return
        self.destroy()
        if self._changed:
            self.library.scan_for_new_files()


# vim: expandtab:sw=4:ts=4
