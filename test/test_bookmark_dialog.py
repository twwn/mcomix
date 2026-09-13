# -*- coding: utf-8 -*-

"""The dialog that lists the bookmarks.

It was a Gtk.TreeView over a Gtk.ListStore whose sixth column held the
bookmark itself. The things it did with that store are what these pin:
listing newest first, removing the selected one, opening one, writing
the order back on close, and the headings that sort.
"""

import datetime
import os

from gi.repository import Gdk, Gtk

from . import MComixTest, pump

from mcomix import bookmark_backend
from mcomix import bookmark_dialog
from mcomix import bookmark_menu_item
from mcomix import constants


class _StubFileHandler(object):

    archive_type = None
    _base_path = None

    def __init__(self):
        self.opened = []

    def open_file(self, path, page=1):
        self.opened.append((path, page))
        return True


class _StubWindow(Gtk.Window):

    def __init__(self):
        super(_StubWindow, self).__init__()
        self.filehandler = _StubFileHandler()
        self.pages = []

    def set_page(self, page):
        self.pages.append(page)


class BookmarksDialogTest(MComixTest):

    def setUp(self):
        super(BookmarksDialogTest, self).setUp()
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
        super(BookmarksDialogTest, self).tearDown()

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

# vim: expandtab:sw=4:ts=4
