# -*- coding: utf-8 -*-

"""The library's sidebar, which lists the collections.

It was a Gtk.TreeView over a Gtk.TreeStore of (name, id) rows. Dragging
is what most of it is about: a collection dropped on another goes into
it, a collection dropped between two goes beside them, and books
dropped on a collection are moved into it - none of which a Gtk.TreeView
answered for by itself either, but which it did give a
Gtk.TreeViewDropPosition for.
"""

import os

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import constants
from mcomix.library import backend
from mcomix.library import collection_area
from mcomix.preferences import prefs


class _Event(object):

    def __iadd__(self, handler):
        return self


class _BookArea(object):

    def __init__(self):
        self.displayed = []
        self.removed = []

    def display_covers(self, collection):
        self.displayed.append(collection)

    def remove_books(self, books):
        self.removed.extend(books)

    def get_book_at_path(self, position):
        return position


class _Library(Gtk.Window):

    def __init__(self, library_backend):
        super(_Library, self).__init__()
        self.backend = library_backend
        self.book_area = _BookArea()
        self.messages = []

    def set_status_message(self, message):
        self.messages.append(message)


class CollectionAreaTest(MComixTest):

    def setUp(self):
        super(CollectionAreaTest, self).setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.backend = backend.LibraryBackend()
        self.backend.book_added_to_collection = _Event()
        for name in ('Comics', 'Manga', 'Inner'):
            self.assertTrue(self.backend.add_collection(name))
        self.comics = self.backend.get_collection_by_name('Comics').id
        self.manga = self.backend.get_collection_by_name('Manga').id
        self.inner = self.backend.get_collection_by_name('Inner').id
        self.backend.add_collection_to_collection(self.inner, self.comics)
        self.library = _Library(self.backend)
        self.library.collection_area = self.area = \
            collection_area._CollectionArea(self.library)
        self.window = Gtk.Window()
        self.window.set_default_size(300, 400)
        self.window.set_child(self.area)
        self.window.present()
        self._settle()

    def tearDown(self):
        self.window.destroy()
        self.library.destroy()
        pump()
        self.backend.close()
        super(CollectionAreaTest, self).tearDown()

    def _settle(self):
        for _ in range(20):
            pump()
            self.area.allocate(300, 400, -1, None)

    def _shown(self):
        return [row.collection for row in self.area._list.each_row()]

    def _row_for(self, collection):
        for row in self.area._list.each_row():
            if row.collection == collection:
                return row
        return None

    # -- What it lists ----------------------------------------------------

    def test_all_books_comes_first(self):
        self.assertEqual(self._shown()[0], collection_area._COLLECTION_ALL)

    def test_the_top_level_collections_are_listed(self):
        # "Recent" is one the backend keeps for itself, beside the
        # collections the user made.
        self.assertEqual(
            sorted(self._shown()),
            sorted([collection_area._COLLECTION_ALL,
                    collection_area._COLLECTION_RECENT,
                    self.comics, self.manga]))

    def test_a_collection_inside_another_is_under_it(self):
        self.area._list.expand_to(self._collection_row(self.inner))
        self.assertIn(self.inner, self._shown())

    def _collection_row(self, collection):
        def walk(rows):
            for row in rows:
                if row.collection == collection:
                    return row
                found = walk(row.children)
                if found is not None:
                    return found
            return None
        return walk(list(self.area._list.store))

    def test_the_name_is_drawn_as_markup(self):
        row = self._row_for(collection_area._COLLECTION_ALL)
        self.assertTrue(row.name.startswith('<b>'))

    # -- Selection --------------------------------------------------------

    def test_nothing_is_selected_to_begin_with(self):
        self.assertIsNone(self.area.get_current_collection())

    def test_the_selected_collection_is_the_one_the_row_names(self):
        self.area._list.select_row(self._row_for(self.manga))
        self.assertEqual(self.area.get_current_collection(), self.manga)

    def test_selecting_a_collection_shows_its_books(self):
        prefs['last library collection'] = None
        self.area._list.select_row(self._row_for(self.manga))
        pump()
        self.assertIn(self.manga, self.library.book_area.displayed)

    # -- Removing and renaming --------------------------------------------

    def test_removing_the_selected_collection_takes_it_out(self):
        self.area._list.select_row(self._row_for(self.manga))
        self.area._remove_collection()
        self.assertNotIn(self.manga, self._shown())

    def test_all_books_is_not_a_collection_that_can_be_removed(self):
        self.area._list.select_row(
            self._row_for(collection_area._COLLECTION_ALL))
        self.area._remove_collection()
        self.assertIn(collection_area._COLLECTION_ALL, self._shown())

    def test_duplicating_a_collection_adds_another_one(self):
        before = len(self._shown())
        self.area._list.select_row(self._row_for(self.comics))
        self.area._duplicate_collection(None)
        self.assertEqual(len(self._shown()), before + 1)

    # -- Where a drop lands -----------------------------------------------

    def test_a_drop_below_every_row_lands_after_the_last_one(self):
        row, position = self.area._drop_row_at(10.0, 10000.0)
        self.assertIs(row, list(self.area._list.each_row())[-1])
        self.assertEqual(position, self.area._list.DROP_AFTER)

    def test_a_collection_dropped_on_another_goes_into_it(self):
        self.area._list.select_row(self._row_for(self.manga))
        self.assertTrue(self.area._drag_data_received(
            None, '%s:%d' % (constants.LIBRARY_DRAG_COLLECTION, self.manga),
            *self._middle_of(self.comics)))
        self.assertEqual(self.backend.get_supercollection(self.manga),
                         self.comics)

    def test_a_collection_is_not_dropped_into_itself(self):
        """A collection inside one of its own is a cycle, which the
        library has no way back out of."""
        self.area._list.select_row(self._row_for(self.comics))
        x, y = self._middle_of(self.comics)
        self.area._drag_motion(_StubDrop('%s:%d' % (
            constants.LIBRARY_DRAG_COLLECTION, self.comics)), x, y)
        self.assertFalse(self.area._acceptable_drop)

    def test_books_are_not_dropped_between_two_collections(self):
        x, y = self._edge_of(self.comics)
        self.assertEqual(
            0, self.area._drag_motion(_StubDrop('%s:0' % (
                constants.LIBRARY_DRAG_BOOKS,)), x, y))
        self.assertFalse(self.area._acceptable_drop)

    def test_a_drag_of_something_else_is_left_alone(self):
        self.assertEqual(0, self.area._drag_motion(_StubDrop(None), 0.0, 0.0))

    def _bounds_of(self, collection):
        row = self._row_for(collection)
        for cell in self.area._list._each_cell():
            if cell.row is row:
                found, bounds = cell.compute_bounds(self.area._list)
                if found:
                    return bounds
        self.fail('collection %r is not drawn' % (collection,))

    def _middle_of(self, collection):
        bounds = self._bounds_of(collection)
        return (10.0, bounds.origin.y + bounds.size.height / 2)

    def _edge_of(self, collection):
        bounds = self._bounds_of(collection)
        return (10.0, bounds.origin.y + 1.0)


class _StubDrop(object):

    """Stands in for the Gtk.DropTarget a motion handler is told about."""

    def __init__(self, value):
        self._value = value

    def get_value(self):
        return self._value

# vim: expandtab:sw=4:ts=4
