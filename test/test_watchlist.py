"""The library's watch list dialog.

The pieces that matter are the two editable columns, which write
straight to the database, the Remove button that follows the selection,
and the two answers the dialog gives: Scan now, which scans and stays
open, and everything else, which closes it and scans if anything was
edited.
"""

import os

from gi.repository import Gio, GLib, Gtk

from . import MComixTest, pump

from mcomix import constants
from mcomix.dialog import Response
from mcomix.preferences import prefs
from mcomix.library import backend
from mcomix.library import watchlist


class _StubLibrary(Gtk.Window):

    def __init__(self, library_backend):
        super().__init__()
        self.backend = library_backend
        self.scans = 0

    def scan_for_new_files(self):
        self.scans += 1


class WatchListDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.backend = backend.LibraryBackend()
        self.watched = []
        for name in ('one', 'two'):
            path = os.path.join(self.tmp_dir, name)
            os.makedirs(path, exist_ok=True)
            self.backend.watchlist.add_directory(path)
            self.watched.append(os.path.normpath(os.path.abspath(path)))
        self.collection = self.backend.add_collection('Shelf')
        self.library = _StubLibrary(self.backend)
        self.dialog = watchlist.WatchListDialog(self.library)
        pump()

    def tearDown(self):
        for window in Gtk.Window.list_toplevels():
            if window.get_visible():
                window.destroy()
        pump()
        self.backend.close()
        super().tearDown()

    def _directories(self):
        return sorted(row.directory for row in self.dialog._list.each_row())

    # -- What it lists ----------------------------------------------------

    def test_every_watched_directory_is_listed(self):
        self.assertEqual(self._directories(), sorted(self.watched))

    def test_a_directory_with_no_collection_shows_the_default_one(self):
        row = self.dialog._list.get_row(0)
        self.assertEqual(row.collection_id, -1)
        self.assertEqual(self.dialog._collection_name_of(row), 'All books')

    def test_the_collections_to_choose_from_include_the_default_one(self):
        names = self.dialog._collection_names()
        self.assertEqual(names[0], 'All books')
        self.assertIn('Shelf', names)

    def test_recent_is_not_offered(self):
        # It holds the books that have been read, and the library files
        # nothing a scan finds there.
        self.assertNotIn('Recent', self.dialog._collection_names())

    def test_a_directory_watched_into_recent_shows_the_default_one(self):
        row = self.dialog._list.get_row(0)
        row.collection_id = constants.COLLECTION_RECENT
        self.assertEqual(self.dialog._collection_name_of(row), 'All books')

    # -- Editing ----------------------------------------------------------

    def test_a_collection_of_its_own_called_recent_can_be_chosen(self):
        """Files dropped on "Recent" once made a collection of that name,
        and picking it filed the directory's books in the real "Recent",
        whose name is the same once translated."""
        own = self.backend.add_collection('Recent')
        row = self.dialog._list.get_row(0)
        self.dialog._collection_chosen(row, 'Recent')
        entry = self.backend.watchlist.get_watchlist_entry(row.directory)
        self.assertEqual(entry.collection.id, own)

    def test_choosing_a_collection_writes_it_to_the_database(self):
        row = self.dialog._list.get_row(0)
        self.dialog._collection_chosen(row, 'Shelf')
        entry = self.backend.watchlist.get_watchlist_entry(row.directory)
        self.assertEqual(entry.collection.id, self.collection)
        self.assertEqual(row.collection_id, self.collection)
        self.assertTrue(self.dialog._changed)

    def test_the_default_collection_wins_over_one_that_shares_its_name(self):
        """The list offers collections by name, and a reader can call a
        collection of their own "All books".  Picking the default entry
        then filed the directory's books into that collection instead,
        where the dialog before GTK4 kept the id of what was picked."""
        self.backend.add_collection('All books')
        row = self.dialog._list.get_row(0)
        self.dialog._collection_chosen(row, 'Shelf')
        self.dialog._collection_chosen(row, 'All books')
        entry = self.backend.watchlist.get_watchlist_entry(row.directory)
        self.assertIsNone(entry.collection.id)
        self.assertEqual(row.collection_id, -1)

    def test_choosing_the_collection_it_already_has_changes_nothing(self):
        row = self.dialog._list.get_row(0)
        self.dialog._collection_chosen(row, 'All books')
        self.assertFalse(self.dialog._changed)

    def test_a_directory_watched_into_a_collection_shows_its_name(self):
        row = self.dialog._list.get_row(0)
        self.dialog._collection_chosen(row, 'Shelf')
        self.assertEqual('Shelf', self.dialog._collection_name_of(row))

    def test_a_name_no_collection_has_any_longer_is_the_default_one(self):
        """The names are offered as the list was filled.  One whose
        collection was removed in the meantime is taken as the default
        collection, which this directory has already, so nothing is
        written."""
        row = self.dialog._list.get_row(0)
        names = self.dialog._collection_names()
        self.backend.remove_collection(self.collection)
        self.assertIn('Shelf', names)
        self.dialog._collection_chosen(row, 'Shelf')
        entry = self.backend.watchlist.get_watchlist_entry(row.directory)
        self.assertIsNone(entry.collection.id)
        self.assertFalse(self.dialog._changed)

    def test_turning_subdirectories_on_writes_it_to_the_database(self):
        row = self.dialog._list.get_row(0)
        self.assertFalse(row.recursive)
        self.dialog._recursive_changed_cb(row, True)
        entry = self.backend.watchlist.get_watchlist_entry(row.directory)
        self.assertTrue(entry.recursive)
        self.assertTrue(row.recursive)
        self.assertTrue(self.dialog._changed)

    # -- Adding a directory -----------------------------------------------

    class _FolderDialog:

        """Stands in for the Gtk.FileDialog, answering with <folder>, or
        raising as a dismissed one does."""

        def __init__(self, folder):
            self._folder = folder

        def select_folder_finish(self, result):
            if self._folder is None:
                raise GLib.Error('dismissed')
            return Gio.File.new_for_path(self._folder)

    def test_a_folder_chosen_is_watched(self):
        folder = os.path.join(self.tmp_dir, 'three')
        os.makedirs(folder)
        self.dialog._directory_chosen(self._FolderDialog(folder), None)
        self.assertIn(os.path.normpath(folder), self._directories())
        self.assertIsNotNone(
            self.backend.watchlist.get_watchlist_entry(folder))
        self.assertTrue(self.dialog._changed)

    def test_a_dismissed_chooser_or_a_path_that_is_no_folder_adds_nothing(self):
        before = self._directories()
        self.dialog._directory_chosen(self._FolderDialog(None), None)
        self.dialog._directory_chosen(
            self._FolderDialog(os.path.join(self.tmp_dir, 'not-there')), None)
        self.assertEqual(before, self._directories())
        self.assertFalse(self.dialog._changed)

    def test_the_scan_at_start_is_turned_on_and_off_here(self):
        for active in (True, False):
            checkbox = Gtk.CheckButton(active=active)
            self.dialog._auto_scan_toggled_cb(checkbox)
            self.assertIs(active,
                          prefs['scan for new books on library startup'])

    # -- The Remove button ------------------------------------------------

    def test_the_remove_button_is_off_until_something_is_selected(self):
        self.assertFalse(self.dialog._remove_button.get_sensitive())
        self.dialog._list.select_only(0)
        self.assertTrue(self.dialog._remove_button.get_sensitive())

    def test_removing_takes_the_directory_out_of_the_database(self):
        row = self.dialog._list.get_row(0)
        self.dialog._list.select_only(0)
        self.dialog._remove_cb(None)
        self.assertNotIn(row.directory, self._directories())
        self.assertEqual(
            [entry.directory
             for entry in self.backend.watchlist.get_watchlist()],
            [directory for directory in self.watched
             if directory != row.directory])

    def test_removing_with_nothing_selected_removes_nothing(self):
        self.dialog._list.unselect_all()
        self.dialog._remove_cb(None)
        self.assertEqual(self._directories(), sorted(self.watched))

    def test_the_selected_entry_is_the_one_the_row_names(self):
        row = self.dialog._list.get_row(1)
        self.dialog._list.select_only(1)
        entry = self.dialog.get_selected_watchlist_entry()
        self.assertEqual(entry.directory, row.directory)

    def test_no_selection_means_no_entry(self):
        self.dialog._list.unselect_all()
        self.assertIsNone(self.dialog.get_selected_watchlist_entry())

    # -- What the buttons answer with -------------------------------------

    def test_scan_now_scans_without_closing_the_dialog(self):
        self.dialog.response(watchlist.WatchListDialog.RESPONSE_SCANNOW)
        pump()
        self.assertEqual(self.library.scans, 1)
        self.assertTrue(self.dialog.get_visible(),
                        'Scan now took the watch list away')

    def test_scan_now_covers_the_edits_made_so_far(self):
        """The scan it starts is the one closing would have owed."""
        self.dialog._recursive_changed_cb(self.dialog._list.get_row(0), True)
        self.dialog.response(watchlist.WatchListDialog.RESPONSE_SCANNOW)
        self.dialog.response(Response.CLOSE)
        pump()
        self.assertEqual(self.library.scans, 1)

    def test_closing_an_unchanged_watch_list_scans_nothing(self):
        self.dialog.response(Response.CLOSE)
        pump()
        self.assertEqual(self.library.scans, 0)

    def test_closing_a_changed_watch_list_scans(self):
        self.dialog._recursive_changed_cb(self.dialog._list.get_row(0), True)
        self.dialog.response(Response.CLOSE)
        pump()
        self.assertEqual(self.library.scans, 1)

    def test_escaping_a_changed_watch_list_scans_as_well(self):
        """The edits are in the database either way it was closed."""
        self.dialog._recursive_changed_cb(self.dialog._list.get_row(0), True)
        self.dialog.response(Response.DELETE_EVENT)
        pump()
        self.assertEqual(self.library.scans, 1)

    def test_scan_now_is_offered_while_a_directory_is_watched(self):
        self.assertTrue(self.dialog.get_widget_for_response(
            watchlist.WatchListDialog.RESPONSE_SCANNOW).get_sensitive())

    def test_scan_now_is_off_once_the_last_directory_is_removed(self):
        for position in (1, 0):
            self.dialog._list.select_only(position)
            self.dialog._remove_cb(None)
        self.assertEqual(self._directories(), [])
        self.assertFalse(
            self.dialog.get_widget_for_response(
                watchlist.WatchListDialog.RESPONSE_SCANNOW).get_sensitive(),
            'Scan now was offered over an empty watch list')

# vim: expandtab:sw=4:ts=4
