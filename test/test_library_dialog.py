"""The library window itself, which nothing else covered.

open_dialog() keeps one window: opening the library again brings the
one that is up forward rather than building a second, and closing it
lets the next call build a new one. It used to answer False for a tree
with no sqlite, which the plain "from sqlite3 import dbapi2" in the
backend made unreachable.
"""

import os

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import column_list
from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.library import collection_area
from mcomix.library import main_dialog


class LibraryDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)

    def tearDown(self):
        main_dialog._close_dialog()
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, main_dialog._LibraryDialog):
                window.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _open(self):
        main_dialog.open_dialog(None, self.window)
        pump()
        return main_dialog._dialog

    def test_opening_the_library_builds_a_window_on_the_database(self):
        dialog = self._open()
        self.assertIsNotNone(dialog)
        self.assertIsNotNone(dialog.backend.watchlist)
        # A fresh database holds the "Recent" pseudo collection and
        # nothing else.
        self.assertEqual(dialog.backend.get_all_collections(),
                         [constants.COLLECTION_RECENT])

    def test_the_window_carries_the_three_areas(self):
        dialog = self._open()
        self.assertIsNotNone(dialog.book_area)
        self.assertIsNotNone(dialog.collection_area)
        self.assertIsNotNone(dialog.control_area)

    def test_opening_it_again_brings_the_same_window_forward(self):
        first = self._open()
        second = self._open()
        self.assertIs(first, second)
        libraries = [window for window in Gtk.Window.list_toplevels()
                     if isinstance(window, main_dialog._LibraryDialog)]
        self.assertEqual(len(libraries), 1)

    def test_closing_it_lets_the_next_call_build_another(self):
        first = self._open()
        main_dialog._close_dialog()
        pump()
        self.assertIsNone(main_dialog._dialog)
        self.assertIsNot(self._open(), first)

    def _sidebar_width(self, dialog):
        """What the collection sidebar asks for, at least and at most."""
        return dialog.collection_area.measure(Gtk.Orientation.HORIZONTAL, -1)

    def test_the_sidebar_asks_for_room_to_draw_a_collection_name(self):
        # A Gtk.ScrolledWindow asks for its child's minimum width, and an
        # ellipsized label will shrink to a single character: the sidebar
        # came out 39 pixels wide, drawing every collection as "...".
        dialog = self._open()
        minimum = self._sidebar_width(dialog).minimum
        self.assertGreaterEqual(
            minimum, column_list._text_width(collection_area._SIDEBAR_MIN_CHARS))

    def test_one_long_collection_name_does_not_widen_the_sidebar(self):
        dialog = self._open()
        dialog.backend.add_collection('A collection whose name goes on and '
                                      'on and on for a very long time indeed')
        dialog.collection_area.display_collections()
        pump()
        natural = self._sidebar_width(dialog).natural
        # The name is far wider than the cap; what the sidebar asks for
        # is the cap plus whatever the expander and the padding take.
        self.assertLess(
            natural,
            2 * column_list._text_width(collection_area._SIDEBAR_MAX_CHARS))


# vim: expandtab:sw=4:ts=4
