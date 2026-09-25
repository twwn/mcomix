"""The library's sidebar, which lists the collections.

Dragging is what most of these tests are about, because it is where the
sidebar has rules of its own: a collection dropped on another goes into
it, a collection dropped between two goes beside them, and books
dropped on a collection are moved into it, while a drop that would make
a cycle or that lands between two collections is refused.  The drag
handlers are called directly, with a stub standing in for the
Gtk.DropTarget, since a real drag needs a pointer no test has.
"""

import os

from gi.repository import Gdk, Gtk

from . import MComixTest, hold_open, pump

from mcomix import constants
from mcomix.dialog import Response
from mcomix import message_dialog
from mcomix.library import backend
from mcomix.library import collection_area
from mcomix.preferences import prefs


class _Event:

    def __iadd__(self, handler):
        return self


class _BookArea:

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
        super().__init__()
        self.backend = library_backend
        self.book_area = _BookArea()
        self.messages = []

    def set_status_message(self, message):
        self.messages.append(message)


class CollectionAreaTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.backend = backend.LibraryBackend()
        self.backend.book_added_to_collection = _Event()
        self.comics, self.manga, self.inner = (
            self.backend.add_collection(name)
            for name in ('Comics', 'Manga', 'Inner'))
        for collection in (self.comics, self.manga, self.inner):
            self.assertIsNotNone(collection)
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
        super().tearDown()

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

    # -- Naming a collection ---------------------------------------------

    def test_a_new_name_of_spaces_alone_makes_no_collection(self):
        """The name was taken as typed, so spaces alone made a collection
        whose name showed as nothing."""
        before = self.backend.get_collection_by_name('   ')
        self.area._add_answered(Response.OK, '   ')
        self.assertIsNone(self.backend.get_collection_by_name('   '))
        self.assertIsNone(before)

    def test_spaces_around_a_new_name_are_dropped(self):
        self.area._add_answered(Response.OK, '  Shelf  ')
        self.assertIsNotNone(self.backend.get_collection_by_name('Shelf'))
        self.assertIsNone(self.backend.get_collection_by_name('  Shelf  '))

    def test_a_collection_is_not_renamed_to_spaces(self):
        self.area._rename_answered(Response.OK, self.manga, '  ')
        self.assertEqual('Manga',
                         self.backend.get_collection_by_id(self.manga).name)

    def test_spaces_around_a_new_name_are_dropped_on_renaming(self):
        self.area._rename_answered(Response.OK, self.manga, ' Mangas ')
        self.assertEqual('Mangas',
                         self.backend.get_collection_by_id(self.manga).name)

    # -- What it lists ----------------------------------------------------

    def test_all_books_comes_first(self):
        self.assertEqual(self._shown()[0], constants.COLLECTION_ALL)

    def test_the_top_level_collections_are_listed(self):
        # "Recent" is one the backend keeps for itself, beside the
        # collections the user made.
        self.assertEqual(
            sorted(self._shown()),
            sorted([constants.COLLECTION_ALL,
                    constants.COLLECTION_RECENT,
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

    def test_the_tree_is_drawn_from_one_statement(self):
        # It used to ask for the collections under every row it found
        # and then for the name of each of those, so redrawing the
        # sidebar cost two statements per collection.
        statements = []
        self.backend._con.set_trace_callback(statements.append)
        try:
            self.area.display_collections()
        finally:
            self.backend._con.set_trace_callback(None)

        self.assertEqual(1, len(statements), statements)

    def test_the_name_is_drawn_as_markup(self):
        row = self._row_for(constants.COLLECTION_ALL)
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

    # -- Redrawing ---------------------------------------------------------

    def _expanded(self):
        return [row.collection for row in self.area._list.expanded_rows()]

    def test_an_expanded_collection_stays_expanded_on_redrawing(self):
        self.area._list.toggle_expanded(self._row_for(self.comics))
        self.area._list.select_row(self._row_for(self.manga))
        pump()
        self.area.display_collections()
        self.assertEqual([self.comics], self._expanded())
        self.assertEqual(self.manga, self.area.get_current_collection())

    def test_the_selected_collection_stays_expanded_on_redrawing(self):
        self.area._list.toggle_expanded(self._row_for(self.comics))
        self.area._list.select_row(self._row_for(self.comics))
        pump()
        self.area.display_collections()
        self.assertEqual([self.comics], self._expanded())
        self.assertEqual(self.comics, self.area.get_current_collection())

    # -- Removing and renaming --------------------------------------------

    def test_removing_the_selected_collection_takes_it_out(self):
        self.area._list.select_row(self._row_for(self.manga))
        self.area._remove_collection()
        self.assertNotIn(self.manga, self._shown())

    def test_all_books_is_not_a_collection_that_can_be_removed(self):
        self.area._list.select_row(
            self._row_for(constants.COLLECTION_ALL))
        self.area._remove_collection()
        self.assertIn(constants.COLLECTION_ALL, self._shown())

    def test_duplicating_a_collection_adds_another_one(self):
        before = len(self._shown())
        self.area._list.select_row(self._row_for(self.comics))
        self.area._duplicate_collection(None)
        self.assertEqual(len(self._shown()), before + 1)

    # -- The right-click menu ---------------------------------------------

    def _activate(self, name):
        """Run one of the popup menu's items the way Gio runs it.

        Gio hands an activate handler both the action and the parameter
        it was activated with, so a handler that takes only the action
        raises TypeError - which GObject prints and swallows, leaving
        the menu item doing nothing at all.
        """
        self.area._popup_actions.lookup_action(name).activate(None)
        pump()

    def test_the_menu_item_removes_the_selected_collection(self):
        self.area._list.select_row(self._row_for(self.manga))
        self._activate('remove')
        self.assertNotIn(self.manga, self._shown())

    def test_the_menu_item_duplicates_the_selected_collection(self):
        before = len(self._shown())
        self.area._list.select_row(self._row_for(self.comics))
        self._activate('duplicate')
        self.assertEqual(len(self._shown()), before + 1)

    def test_the_menu_item_asks_what_to_rename_the_collection_to(self):
        self.area._list.select_row(self._row_for(self.manga))
        before = set(Gtk.Window.list_toplevels())
        self._activate('rename')
        opened = [window for window in
                  set(Gtk.Window.list_toplevels()) - before
                  if isinstance(window, message_dialog.MessageDialog)]
        try:
            self.assertEqual(1, len(opened))
        finally:
            # A dialog left standing is answered by whichever test next
            # goes looking for one.
            for dialog in opened:
                dialog.destroy()
            pump()

    def test_the_menu_key_and_shift_f10_both_open_the_menu(self):
        """A GTK3 widget's popup-menu signal answered both keys.

        Shift+F10 is the only one a keyboard without a menu key has.
        """
        hold_open(self.area._collection_menu)
        for keyval, state in ((Gdk.KEY_Menu, Gdk.ModifierType(0)),
                              (Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK)):
            self.assertFalse(self.area._collection_menu.get_visible())
            self.assertEqual(Gdk.EVENT_STOP,
                             self.area._key_press(None, keyval, 0, state))
            # Read before the main loop turns, although hold_open() has
            # taken away what closed it after a pump under xdist.
            self.assertTrue(self.area._collection_menu.get_visible(),
                            'the menu did not open for %s'
                            % Gdk.keyval_name(keyval))
            self.area._collection_menu.popdown()
            pump()

    def test_f10_on_its_own_is_left_to_gtk(self):
        self.assertEqual(Gdk.EVENT_PROPAGATE,
                         self.area._key_press(None, Gdk.KEY_F10, 0,
                                              Gdk.ModifierType(0)))
        self.assertFalse(self.area._collection_menu.get_visible())

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

    def test_a_collection_dropped_beside_a_top_level_one_goes_to_the_root(self):
        """A drop above or below a row puts the collection beside it,
        in the collection that one is in - none at all, for a
        collection at the top."""
        self.area._list.expand_to(self._collection_row(self.inner))
        self._settle()
        self.area._list.select_row(self._row_for(self.inner))
        self.assertTrue(self.area._drag_data_received(
            None, '%s:%d' % (constants.LIBRARY_DRAG_COLLECTION, self.inner),
            *self._edge_of(self.manga)))
        self.assertIsNone(self.backend.get_supercollection(self.inner))

    def test_dragging_a_collection_says_where_it_would_go(self):
        self.area._list.select_row(self._row_for(self.manga))
        payload = _StubDrop('%s:%d' % (constants.LIBRARY_DRAG_COLLECTION,
                                       self.manga))
        self.assertEqual(Gdk.DragAction.MOVE, self.area._drag_motion(
            payload, *self._middle_of(self.comics)))
        self.assertEqual("Put the collection 'Manga' in the collection "
                         "'Comics'.", self.library.messages[-1])
        self.area._list.expand_to(self._collection_row(self.inner))
        self._settle()
        self.area._list.select_row(self._row_for(self.inner))
        payload = _StubDrop('%s:%d' % (constants.LIBRARY_DRAG_COLLECTION,
                                       self.inner))
        self.assertEqual(Gdk.DragAction.MOVE, self.area._drag_motion(
            payload, *self._edge_of(self.manga)))
        self.assertEqual("Put the collection 'Inner' in the collection "
                         "'Root'.", self.library.messages[-1])

    def test_a_collection_is_not_dropped_into_itself(self):
        """A collection inside one of its own is a cycle, which the
        library has no way back out of."""
        self.area._list.select_row(self._row_for(self.comics))
        x, y = self._middle_of(self.comics)
        self.assertEqual(0, self.area._drag_motion(_StubDrop('%s:%d' % (
            constants.LIBRARY_DRAG_COLLECTION, self.comics)), x, y))

    def test_books_are_not_dropped_between_two_collections(self):
        x, y = self._edge_of(self.comics)
        self.assertEqual(
            0, self.area._drag_motion(_StubDrop('%s:0' % (
                constants.LIBRARY_DRAG_BOOKS,)), x, y))

    def test_books_moved_into_a_collection_under_it_keep_their_covers(self):
        """The covers of "Comics" include those of "Inner", filed under
        it, so books moved from one to the other are still on show; the
        covers were taken away all the same."""
        self.area._list.expand_to(self._collection_row(self.inner))
        self._settle()
        self.area._list.select_row(self._row_for(self.comics))
        self.assertTrue(self.area._drag_data_received(
            None, '%s:4,5' % (constants.LIBRARY_DRAG_BOOKS,),
            *self._middle_of(self.inner)))
        self.assertEqual(self.library.book_area.removed, [])
        self.assertTrue(self.area._drag_data_received(
            None, '%s:6' % (constants.LIBRARY_DRAG_BOOKS,),
            *self._middle_of(self.manga)))
        self.assertEqual(self.library.book_area.removed, [6])

    def test_a_book_moved_out_that_is_still_under_it_keeps_its_cover(self):
        """A book filed in "Inner" is among the covers of "Comics", and
        moving it from there to "Manga" takes it out of "Comics" alone,
        which it was never in; it is still under "Comics", but its cover
        was taken away all the same."""
        cursor = self.backend._con.execute(
            '''insert into book (name, path, pages, format, size)
               values ('inner.cbz', '/books/inner.cbz', 20, 1, 1)''')
        book = cursor.lastrowid
        cursor.close()
        self.backend._con.execute(
            'insert into contain (collection, book) values (?, ?)',
            (self.inner, book))
        self.backend.book_added_to_collection = lambda *_args: None
        self.area._list.select_row(self._row_for(self.comics))
        self.assertTrue(self.area._drag_data_received(
            None, '%s:%d' % (constants.LIBRARY_DRAG_BOOKS, book),
            *self._middle_of(self.manga)))
        self.assertEqual(self.library.book_area.removed, [])

    def test_books_moved_are_written_in_one_transaction(self):
        """Every book moved is filed in one collection and taken out of
        another; each of those writes was a transaction of its own, a
        journal write and an fsync each on a real disk."""
        self.area._list.select_row(self._row_for(self.comics))
        statements = []
        self.backend._con.set_trace_callback(statements.append)
        try:
            self.assertTrue(self.area._drag_data_received(
                None, '%s:4,5,6' % (constants.LIBRARY_DRAG_BOOKS,),
                *self._middle_of(self.manga)))
        finally:
            self.backend._con.set_trace_callback(None)
        writes = [index for index, statement in enumerate(statements)
                  if statement.lstrip().lower().startswith(
                      ('insert', 'delete'))]
        self.assertEqual(6, len(writes))
        begins = [index for index, statement in enumerate(statements)
                  if statement.upper().startswith('BEGIN')]
        commits = [index for index, statement in enumerate(statements)
                   if statement.upper().startswith('COMMIT')]
        self.assertEqual(1, len(begins), statements)
        self.assertEqual(1, len(commits), statements)
        self.assertLess(begins[0], writes[0])
        self.assertGreater(commits[0], writes[-1])

    def test_books_are_not_dropped_into_recent(self):
        """"Recent" is what MComix files a book in when it is read.
        Books moved there left the collection they were dragged from,
        and clearing the recent books then took them out of the library
        as books that were only there for having been read."""
        self.area._list.select_row(self._row_for(self.comics))
        payload = _StubDrop('%s:0' % (constants.LIBRARY_DRAG_BOOKS,))
        self.assertEqual(Gdk.DragAction.MOVE, self.area._drag_motion(
            payload, *self._middle_of(self.manga)))
        self.assertEqual(0, self.area._drag_motion(
            payload, *self._middle_of(constants.COLLECTION_RECENT)))

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


class _StubDrop:

    """Stands in for the Gtk.DropTarget a motion handler is told about."""

    def __init__(self, value):
        self._value = value

    def get_value(self):
        return self._value

# vim: expandtab:sw=4:ts=4
