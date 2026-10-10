"""The dialog that lists the bookmarks.

It was a Gtk.TreeView over a Gtk.ListStore whose sixth column held the
bookmark itself. The things it did with that store are what these pin:
listing newest first, removing the selected one, opening one, writing
the order back on close, and the headings that sort.
"""

import datetime
import os
from unittest import mock

from gi.repository import Gdk, GLib, Gtk

from . import MComixTest, pump

from mcomix import bookmark_backend
from mcomix import bookmark_dialog
from mcomix import bookmark_menu_item
from mcomix import constants
from mcomix import tools
from mcomix.dialog import Response
from mcomix.preferences import prefs


class _StubImageHandler:

    def get_image_files(self):
        return []


class _StubFileHandler:

    archive_type = None

    def get_path_to_base(self):
        return None

    def __init__(self):
        self.opened = []

    def open_file(self, path, page=1, start_member=None):
        self.opened.append((path, page))
        return True


class _StubWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.filehandler = _StubFileHandler()
        self.imagehandler = _StubImageHandler()
        self.pages = []

    def set_page(self, page):
        self.pages.append(page)


class BookmarksDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.window = _StubWindow()
        self.store = bookmark_backend.BookmarksStore
        self.store._initialized = False
        self.store._bookmarks = []
        for number, name in enumerate(('alpha', 'beta', 'gamma')):
            self.store.add_bookmark(self._bookmark(name, number + 1))
        self.dialog = bookmark_dialog._BookmarksDialog(self.window, self.store)
        pump()

    def tearDown(self):
        for window in Gtk.Window.list_toplevels():
            if window.get_visible():
                window.destroy()
        pump()
        super().tearDown()

    def _bookmark(self, name, page, archive_type=None):
        return bookmark_menu_item._Bookmark(
            self.window, self.window.filehandler, name,
            '/tmp/%s.cbz' % name, page, 20, archive_type,
            datetime.datetime(2020, 1, page))

    def _names(self):
        return [row.name for row in self.dialog._list.each_row()]

    # -- What it lists ----------------------------------------------------

    def test_the_bookmarks_are_listed_newest_first(self):
        self.assertEqual(self._names(), ['gamma', 'beta', 'alpha'])

    def test_a_row_carries_what_the_columns_show(self):
        row = self.dialog._list.get_row(0)
        self.assertEqual(row.name, 'gamma')
        self.assertEqual(row.page, '3 / 20')
        self.assertEqual(row.path, '/tmp/gamma.cbz')
        self.assertEqual(row.icon, 'mcomix-image')

    def test_a_note_is_given_to_the_selected_bookmark(self):
        """Only the file's name told one bookmark from the next
        (upstream feature request 138)."""
        entry = self.dialog._note
        self.assertFalse(entry.get_sensitive(), 'a note on nothing')
        self.dialog._list.select_only(0)
        pump()
        self.assertTrue(entry.get_sensitive())
        self.assertEqual('', entry.get_text())
        entry.set_text(' where the fight starts ')
        entry.emit('activate')
        row = self.dialog._list.get_row(0)
        self.assertEqual('where the fight starts', row.note)
        self.assertEqual('where the fight starts', row.bookmark.get_note())
        stored, _mtime = self.store.load_bookmarks()
        self.assertEqual(
            {'gamma': 'where the fight starts', 'beta': '', 'alpha': ''},
            {bookmark.get_name(): bookmark.get_note() for bookmark in stored})

    def test_a_note_typed_is_kept_when_the_selection_moves_on(self):
        self.dialog._list.select_only(0)
        pump()
        self.dialog._note.set_text('first')
        self.dialog._list.select_only(1)
        pump()
        self.assertEqual('', self.dialog._note.get_text())
        self.assertEqual('first', self.dialog._list.get_row(0).note)
        self.dialog._note.set_text('second')
        # Closing keeps what was typed last, and the order as it was.
        order = [bookmark.get_name() for bookmark in self.store._bookmarks]
        self.dialog.response(Response.CLOSE)
        pump()
        self.assertEqual(
            {'gamma': 'first', 'beta': 'second', 'alpha': ''},
            {bookmark.get_name(): bookmark.get_note()
             for bookmark in self.store._bookmarks})
        self.assertEqual(order, [bookmark.get_name()
                                 for bookmark in self.store._bookmarks])

    def test_an_unchanged_note_writes_nothing(self):
        self.dialog._list.select_only(0)
        pump()
        with mock.patch.object(
                self.store, 'write_bookmarks_file') as written:
            self.dialog._note.emit('activate')
            self.dialog._list.select_only(1)
            pump()
        written.assert_not_called()

    def test_an_archive_and_a_loose_image_get_different_icons(self):
        archived = self._bookmark('zip', 4, archive_type=0).to_row()
        self.assertEqual(archived.icon, 'mcomix-archive')

    # -- Removing ---------------------------------------------------------

    def test_removing_the_selected_bookmark_drops_it_from_the_store(self):
        self.dialog._list.select_only(0)
        self.dialog._remove_selected()
        self.assertEqual(self._names(), ['beta', 'alpha'])
        self.assertEqual([mark._name for mark in self.store.get_bookmarks()],
                         ['alpha', 'beta'])

    def test_removing_selects_whatever_takes_its_place(self):
        """Delete has to work down a run of bookmarks.  A
        Gtk.SingleSelection leaves nothing selected when what was
        selected goes, where a Gtk.TreeView moved the selection on, so
        the second Delete found nothing to remove."""
        self.dialog._list.select_only(0)
        self.dialog._remove_selected()
        self.assertEqual(self.dialog._list.get_selected_row().name, 'beta')
        self.dialog._remove_selected()
        self.assertEqual(self._names(), ['alpha'])

    def test_removing_the_last_one_selects_the_one_above_it(self):
        self.dialog._list.select_only(2)
        self.dialog._remove_selected()
        self.assertEqual(self.dialog._list.get_selected_row().name, 'beta')

    def test_removing_the_only_one_leaves_nothing_selected(self):
        for _each in range(3):
            self.dialog._list.select_only(0)
            self.dialog._remove_selected()
        self.assertEqual(self._names(), [])
        self.assertIsNone(self.dialog._list.get_selected_row())

    # -- The buttons ------------------------------------------------------

    def _remove_button(self):
        return self.dialog.get_widget_for_response(constants.RESPONSE_REMOVE)

    def test_remove_is_insensitive_until_something_is_selected(self):
        """It answered a press with nothing at all, where the "open
        with" editor's Remove is insensitive until a row is picked."""
        self.assertFalse(self._remove_button().get_sensitive())
        self.dialog._list.select_only(1)
        self.assertTrue(self._remove_button().get_sensitive())

    def test_remove_goes_insensitive_again_when_the_list_empties(self):
        self.dialog._list.select_only(0)
        self.dialog.response(constants.RESPONSE_CLEAR)
        pump()
        self._dialogs()[0].response(Response.YES)
        pump()
        self.assertFalse(self._remove_button().get_sensitive())

    def test_removing_with_nothing_selected_removes_nothing(self):
        self.dialog._list.unselect_all()
        self.dialog._remove_selected()
        self.assertEqual(self._names(), ['gamma', 'beta', 'alpha'])

    def test_delete_removes_the_selected_bookmark(self):
        self.dialog._list.select_only(1)
        self.assertEqual(
            self.dialog._key_press_event(None, Gdk.KEY_Delete, 0, 0),
            Gdk.EVENT_STOP)
        self.assertEqual(self._names(), ['gamma', 'alpha'])

    # -- Opening ----------------------------------------------------------

    def _dialogs(self):
        """The prompts the dialog has put on screen."""
        from mcomix import message_dialog
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_visible()]

    def test_clearing_asks_before_it_removes_anything(self):
        self.dialog.response(constants.RESPONSE_CLEAR)
        pump()
        self.assertEqual(len(self._dialogs()), 1, 'nothing was asked')
        self.assertEqual(self._names(), ['gamma', 'beta', 'alpha'])

    def test_clearing_empties_the_list_and_the_store(self):
        """The rows have to go with the store: _close() writes back
        whatever is left in the list, so a cleared store under a full
        list would be refilled from it on the way out."""
        self.dialog.response(constants.RESPONSE_CLEAR)
        pump()
        self._dialogs()[0].response(Response.YES)
        pump()
        self.assertEqual(self._names(), [])
        self.assertEqual(self.store.get_bookmarks(), [])

        self.dialog._close()
        self.assertEqual(self.store.get_bookmarks(), [],
                         'closing put the cleared bookmarks back')

    def test_answering_no_keeps_them(self):
        self.dialog.response(constants.RESPONSE_CLEAR)
        pump()
        self._dialogs()[0].response(Response.NO)
        pump()
        self.assertEqual(self._names(), ['gamma', 'beta', 'alpha'])
        self.assertEqual(len(self.store.get_bookmarks()), 3)

    def test_the_clear_button_follows_whether_there_is_anything_to_clear(self):
        self.assertTrue(self.dialog._clear_button.get_sensitive())
        self.dialog.response(constants.RESPONSE_CLEAR)
        pump()
        self._dialogs()[0].response(Response.YES)
        pump()
        self.assertFalse(self.dialog._clear_button.get_sensitive())

    def test_activating_a_bookmark_opens_it(self):
        self.dialog._bookmark_activated(self.dialog._list, 1)
        self.assertEqual(self.window.filehandler.opened,
                         [('/tmp/beta.cbz', 2)])

    def test_activating_a_position_that_is_not_there_opens_nothing(self):
        self.dialog._bookmark_activated(self.dialog._list, 99)
        self.assertEqual(self.window.filehandler.opened, [])

    # -- The order the store keeps ----------------------------------------

    def _stored(self):
        return [mark._name for mark in self.store.get_bookmarks()]

    def _writes(self, action):
        """How many times <action> writes the bookmarks file."""
        written = []
        real = tools.atomic_write

        def counted(*args, **kwargs):
            written.append(args[0])
            return real(*args, **kwargs)

        with mock.patch.object(tools, 'atomic_write', counted):
            action()
        return len(written)

    def test_closing_writes_the_order_it_holds_back_to_the_store(self):
        """Dragging a bookmark somewhere else is what the dialog is for.

        The store keeps them oldest first and the dialog shows them
        newest first, so what is written back is the shown order
        reversed.
        """
        self.assertTrue(self.dialog._list.move_row(0, 2))
        self.assertEqual(self._names(), ['beta', 'alpha', 'gamma'])
        self.dialog._close()
        self.assertEqual(self._stored(), ['gamma', 'alpha', 'beta'])

    def test_sorting_by_a_heading_and_closing_leaves_the_order_alone(self):
        """A heading sorts the view, and the view is not the order.

        Sorting by a heading to look at the bookmarks by date and then
        closing wrote the sorted order back over the stored one, which
        nothing could undo.  A drag is refused while a heading sorts
        for the same reason: the order belongs to the list, not to what
        it happens to be drawing.
        """
        self.dialog._list.sort_by(self.dialog._name_col)
        self.assertEqual(self._names(), ['alpha', 'beta', 'gamma'])
        self.dialog._close()
        self.assertEqual(self._stored(), ['alpha', 'beta', 'gamma'])

    def test_escape_keeps_a_reordering_like_the_close_button(self):
        """Escape threw the reordering away; the close button kept it."""
        self.assertTrue(self.dialog._list.move_row(0, 2))
        self.dialog._escaped()
        pump()
        self.assertEqual(self._stored(), ['gamma', 'alpha', 'beta'])

    def test_the_window_being_closed_keeps_it_too(self):
        self.assertTrue(self.dialog._list.move_row(0, 2))
        self.dialog.close()
        pump()
        self.assertEqual(self._stored(), ['gamma', 'alpha', 'beta'])

    def test_closing_an_order_that_did_not_change_writes_nothing(self):
        """It was a remove and an add of every bookmark in turn, each
        re-pickling and fsyncing the whole file and rebuilding the
        bookmarks menu: opening the dialog and closing it again cost
        six writes for three bookmarks."""
        self.assertEqual(self._writes(self.dialog._close), 0)

    def test_a_reordering_is_one_write_however_many_bookmarks(self):
        self.assertTrue(self.dialog._list.move_row(0, 2))
        self.assertEqual(self._writes(self.dialog._close), 1)

    def test_a_closed_dialog_hears_nothing_more_about_a_moved_book(self):
        """The dialog follows the store while it is open, and lets go of
        it when it closes.  A handler left subscribed runs on a window
        that has been destroyed, and the store goes on holding the
        dialog it belongs to."""
        def paths():
            return [row.bookmark._path
                    for row in self.dialog._list.each_stored_row()]

        before = paths()
        self.assertIn('/tmp/alpha.cbz', before)
        self.dialog._close()
        pump()

        self.store.update_path('/tmp/alpha.cbz', '/elsewhere/alpha.cbz')
        pump()

        self.assertEqual(paths(), before,
                         'the closed dialog still followed the store')

    def test_closing_does_not_bring_back_a_bookmark_removed_elsewhere(self):
        """A second dialog over the same store held a list of its own.

        Closing it removed and re-added every bookmark in that list,
        and remove_bookmark() raises a ValueError for a bookmark the
        store no longer holds, so closing the older of two dialogs
        after the newer had removed something aborted half way through
        and left the dialog standing.
        """
        another = bookmark_dialog._BookmarksDialog(self.window, self.store)
        pump()
        self.dialog._list.select_only(0)
        self.dialog._remove_selected()
        self.dialog._close()
        another._close()
        self.assertEqual(self._stored(), ['alpha', 'beta'])

    def test_closing_keeps_a_bookmark_added_since_it_opened(self):
        """Closing writes back an order that has the newcomer in it,
        rather than one that moves it to the front or drops it."""
        self.store.add_bookmark(self._bookmark('delta', 4))
        self.dialog._close()
        self.assertEqual(self._stored(), ['alpha', 'beta', 'gamma', 'delta'])

    # -- Following the store ----------------------------------------------

    def test_a_bookmark_added_while_it_is_open_is_listed(self):
        """The store is a backend for the menu and the dialog alike, so
        Ctrl+D with the dialog open, or a second window adding one, has
        to show in it.  The dialog listed what the store held when it
        opened and nothing after that."""
        self.store.add_bookmark(self._bookmark('delta', 4))
        self.assertEqual(self._names(), ['delta', 'gamma', 'beta', 'alpha'])

    def test_a_bookmark_removed_elsewhere_leaves_the_list(self):
        self.store.remove_bookmark(self.store.get_bookmarks()[1])
        self.assertEqual(self._names(), ['gamma', 'alpha'])

    def test_the_store_being_cleared_empties_the_list(self):
        self.store.clear_bookmarks()
        self.assertEqual(self._names(), [])
        self.assertFalse(self.dialog._clear_button.get_sensitive())

    def test_a_bookmark_added_after_a_clear_can_be_cleared_again(self):
        self.store.clear_bookmarks()
        self.store.add_bookmark(self._bookmark('delta', 4))
        self.assertEqual(self._names(), ['delta'])
        self.assertTrue(self.dialog._clear_button.get_sensitive())

    def test_a_closed_dialog_no_longer_follows_the_store(self):
        """The store keeps the callbacks it is given, so a dialog that
        does not take them back is one the store still talks to."""
        self.dialog._close()
        self.store.add_bookmark(self._bookmark('delta', 4))
        self.assertEqual(self._names(), ['gamma', 'beta', 'alpha'])

    # -- The headings that sort -------------------------------------------

    def test_sorting_by_name_orders_the_rows_by_it(self):
        self.dialog._list.sort_by(self.dialog._name_col)
        self.assertEqual(self._names(), ['alpha', 'beta', 'gamma'])

    def test_sorting_the_other_way_reverses_it(self):
        self.dialog._list.sort_by(self.dialog._name_col, descending=True)
        self.assertEqual(self._names(), ['gamma', 'beta', 'alpha'])

    def test_sorting_by_type_over_a_mixed_list_does_not_raise(self):
        """_archive_type is None for a loose image and a number for an
        archive, and the sort compared the two directly: clicking the
        Type heading on a list holding both raised a TypeError.  A
        bookmark with no archive type sorts before every one that has
        one."""
        self.store.add_bookmark(self._bookmark('zipped', 4, archive_type=0))
        self.dialog._list.sort_by(self.dialog._icon_col)
        self.assertEqual(self._names(),
                         ['alpha', 'beta', 'gamma', 'zipped'])

    def test_sorting_by_nothing_puts_them_back_in_the_order_they_came(self):
        self.dialog._list.sort_by(self.dialog._name_col)
        self.dialog._list.sort_by(None)
        self.assertEqual(self._names(), ['gamma', 'beta', 'alpha'])

    # -- The columns the headings' menu offers -----------------------------

    def _toggle(self, attr):
        """Pick the column showing <attr> out of the headings' menu."""
        self.dialog._list.activate_action('columns.%s' % attr, None)
        pump()

    def test_location_starts_out_hidden_and_the_rest_are_drawn(self):
        self.assertEqual(['path'], self.dialog._list.hidden_columns())
        self.assertFalse(self.dialog._path_col.get_visible())
        self.assertTrue(self.dialog._name_col.get_visible())

    def test_the_menu_offers_every_column_from_every_heading(self):
        titles = [self.dialog._list.get_columns().get_item(index).get_title()
                  for index in
                  range(self.dialog._list.get_columns().get_n_items())]
        menu = self.dialog._icon_col.get_header_menu()
        self.assertIsNotNone(menu)
        labels = [menu.get_item_attribute_value(index, 'label',
                                                GLib.VariantType('s')).get_string()
                  for index in range(menu.get_n_items())]
        self.assertEqual(titles, labels)
        for column in (self.dialog._name_col, self.dialog._path_col):
            self.assertIs(menu, column.get_header_menu())

    def test_asking_for_location_draws_it(self):
        self._toggle('path')
        self.assertTrue(self.dialog._path_col.get_visible())
        self.assertEqual([], self.dialog._list.hidden_columns())

    def test_what_the_menu_was_told_outlives_the_dialog(self):
        self._toggle('path')
        self._toggle('added')
        self.assertEqual(['added'], prefs['hidden bookmark columns'])
        another = bookmark_dialog._BookmarksDialog(self.window, self.store)
        pump()
        try:
            self.assertEqual(['added'], another._list.hidden_columns())
            self.assertTrue(another._path_col.get_visible())
        finally:
            another.destroy()

    def test_the_last_column_left_cannot_be_hidden_as_well(self):
        # The menu hangs off the headings, and a list with no columns
        # has none: hiding the last would take away the way back.
        for attr in ('icon', 'page', 'added', 'note'):
            self._toggle(attr)
        self.assertEqual(['name'], [attr for attr in ('icon', 'name', 'page',
                                                      'path', 'added', 'note')
                                    if attr not in
                                    self.dialog._list.hidden_columns()])
        self._toggle('name')
        self.assertTrue(self.dialog._name_col.get_visible())

# vim: expandtab:sw=4:ts=4
