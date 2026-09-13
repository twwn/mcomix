""" Library watch list dialog and backend classes. """

import os
from gi.repository import Gio, Gtk, GLib

from mcomix.library import backend_types
from mcomix.dialog import Dialog
from mcomix import column_list
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix.i18n import _


class WatchListDialog(Dialog):
    """ Dialog for managing watched directories. """

    RESPONSE_SCANNOW = 1000

    def __init__(self, library):
        """ Dialog constructor.
        @param library: Dialog parent window, should be library window.
        """
        super(WatchListDialog, self).__init__(
            title=_("Library watch list"), transient_for=library,
            destroy_with_parent=True, modal=True)
        self.add_buttons(_('_Scan now'), WatchListDialog.RESPONSE_SCANNOW,
                         _('_Close'), Gtk.ResponseType.CLOSE)

        #: Stores a reference to the library
        self.library = library
        #: True if changes were made to the watchlist. Not 100% accurate.
        self._changed = False

        self.set_default_response(Gtk.ResponseType.CLOSE)

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
        # as soon as there are rows to select.
        self._fill_model()

        self.set_default_size(475, 350)
        self.connect('response', self._close_cb)
        self.set_visible(True)

    def get_selected_watchlist_entry(self):
        """ Returns the selected watchlist entry, or C{None} if no
        item is selected. """
        row = self._list.get_selected_row()
        if row is None:
            return None
        return self.library.backend.watchlist.get_watchlist_entry(
            row.directory)

    def _fill_model(self):
        """ Empties the list and updates it from the database. """
        self._list.set_rows(
            column_list.Row(directory=entry.directory,
                            collection_id=(-1 if entry.collection.id is None
                                           else entry.collection.id),
                            recursive=entry.recursive)
            for entry in self.library.backend.watchlist.get_watchlist())

    def _collection_names(self):
        """ The name of every collection a directory can be watched into. """
        names = [backend_types.DefaultCollection.name]
        for id in self.library.backend.get_all_collections():
            names.append(self.library.backend.get_collection_name(id))
        return names

    def _collection_id_for(self, name):
        """ The id of the collection called <name>, -1 for the default. """
        for id in self.library.backend.get_all_collections():
            if self.library.backend.get_collection_name(id) == name:
                return id
        return -1

    def _collection_name_of(self, row):
        """ The name of the collection <row> is watched into. """
        if row.collection_id == -1:
            return backend_types.DefaultCollection.name
        return self.library.backend.get_collection_name(row.collection_id)

    def _collection_chosen(self, row, name):
        """ A new collection was set for a watched directory. """
        new_id = self._collection_id_for(name)
        if new_id == row.collection_id:
            return
        collection = self.library.backend.get_collection_by_id(new_id)
        self.library.backend.watchlist.get_watchlist_entry(
            row.directory).set_collection(collection)
        row.collection_id = new_id

        self._changed = True

    def _recursive_changed_cb(self, row, status):
        """ Recursive reading was enabled or disabled. """
        self.library.backend.watchlist.get_watchlist_entry(
            row.directory).set_recursive(status)
        row.recursive = status

        self._changed = True

    def _add_cb(self, button, *args):
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

    def _remove_cb(self, button, *args):
        """ Called when a watch list entry should be removed. """
        row = self._list.get_selected_row()
        if row is None:
            return
        entry = self.library.backend.watchlist.get_watchlist_entry(
            row.directory)
        if entry:
            entry.remove()
            self._list.remove_row(row)

    def _item_selected_cb(self, selection, *args):
        """ Called when an item is selected. Enables or disables the "Remove"
        button. """
        self._remove_button.set_sensitive(
            bool(self._list.get_selected_positions()))

    def _auto_scan_toggled_cb(self, checkbox, *args):
        """ Toggles automatic library book scanning. """
        prefs['scan for new books on library startup'] = checkbox.get_active()

    def _close_cb(self, dialog, response, *args):
        """ Trigger scan for new files after watch dialog closes. """
        self.destroy()
        if response == Gtk.ResponseType.CLOSE and self._changed:
            self.library.scan_for_new_files()
        elif response == WatchListDialog.RESPONSE_SCANNOW:
            self.library.scan_for_new_files()


# vim: expandtab:sw=4:ts=4
