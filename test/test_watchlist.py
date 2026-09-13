"""The library's watch list dialog.

It was a Gtk.TreeView with a text column, a Gtk.CellRendererCombo and a
Gtk.CellRendererToggle over a three-column Gtk.ListStore. The pieces
that mattered are the two editable ones, which write straight to the
database, and the Remove button that follows the selection.
"""

import os

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import constants
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

# vim: expandtab:sw=4:ts=4
