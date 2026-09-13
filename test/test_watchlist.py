"""The library's watch list dialog.

The pieces that matter are the two editable columns, which write
straight to the database, the Remove button that follows the selection,
and the two answers the dialog gives: Scan now, which scans and stays
open, and everything else, which closes it and scans if anything was
edited.
"""

import os

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import constants
from mcomix.dialog import Response
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

    # -- Editing ----------------------------------------------------------

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

    def test_turning_subdirectories_on_writes_it_to_the_database(self):
        row = self.dialog._list.get_row(0)
        self.assertFalse(row.recursive)
        self.dialog._recursive_changed_cb(row, True)
        entry = self.backend.watchlist.get_watchlist_entry(row.directory)
        self.assertTrue(entry.recursive)
        self.assertTrue(row.recursive)
        self.assertTrue(self.dialog._changed)

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
