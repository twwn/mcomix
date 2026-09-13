"""The dialog that lists the bookmarks.

It was a Gtk.TreeView over a Gtk.ListStore whose sixth column held the
bookmark itself. The things it did with that store are what these pin:
listing newest first, removing the selected one, opening one, writing
the order back on close, and the headings that sort.
"""

import datetime
import os

from gi.repository import Gdk, GLib, Gtk

from . import MComixTest, pump

from mcomix import bookmark_backend
from mcomix import bookmark_dialog
from mcomix import bookmark_menu_item
from mcomix import constants
from mcomix.dialog import Response
from mcomix.preferences import prefs


class _StubFileHandler:

    archive_type = None
    _base_path = None

    def __init__(self):
        self.opened = []

    def open_file(self, path, page=1):
        self.opened.append((path, page))
        return True


class _StubWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.filehandler = _StubFileHandler()
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

    def test_closing_writes_the_shown_order_back_to_the_store(self):
        """Dragging a bookmark somewhere else is what the dialog is for.

        The store keeps them oldest first and the dialog shows them
        newest first, so what is written back is the shown order
        reversed.
        """
        self.assertTrue(self.dialog._list.move_row(0, 2))
        self.assertEqual(self._names(), ['beta', 'alpha', 'gamma'])
        self.dialog._close()
        self.assertEqual([mark._name for mark in self.store.get_bookmarks()],
                         ['gamma', 'alpha', 'beta'])

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
        self.dialog._add_bookmark(self._bookmark('zipped', 4, archive_type=0))
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
        for attr in ('icon', 'page', 'added'):
            self._toggle(attr)
        self.assertEqual(['name'], [attr for attr in ('icon', 'name', 'page',
                                                      'path', 'added')
                                    if attr not in
                                    self.dialog._list.hidden_columns()])
        self._toggle('name')
        self.assertTrue(self.dialog._name_col.get_visible())

# vim: expandtab:sw=4:ts=4
