"""The library window itself, which nothing else covered.

open_dialog() keeps one window: opening the library again brings the
one that is up forward rather than building a second, and closing it
lets the next call build a new one. It used to answer False for a tree
with no sqlite, which the plain "from sqlite3 import dbapi2" in the
backend made unreachable.
"""

import os
import unittest.mock

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import column_list
from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.dialog import Response
from mcomix.library import book_area
from mcomix.library import collection_area
from mcomix.library import main_dialog
from mcomix.library import watchlist
from mcomix.preferences import prefs


class _LibraryWindowTest(MComixTest):

    """A main window with a book open in it, and a library over that.

    The fixture rather than the tests: opening the library opens the
    database, so every class here needs the same window to open it from.
    """

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


class LibraryDialogTest(_LibraryWindowTest):

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

    def test_a_closed_library_is_not_told_about_books_filed_later(self):
        """The cover view stayed subscribed to the backend, which outlives
        the window, and put a cover in its grid for every book filed
        after the library had closed - once for each time it had been
        opened."""
        prefs['last library collection'] = constants.COLLECTION_ALL
        dialog = self._open()
        self.assertEqual(constants.COLLECTION_ALL,
                         dialog.collection_area.get_current_collection())
        backend = dialog.backend
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        backend.add_book(path)
        book = backend.get_book_by_path(path)
        dialog.close()
        pump()

        with unittest.mock.patch.object(book_area._BookArea,
                                        'add_books') as added:
            # A book filed in no collection counts as one in "All books".
            backend.book_added_to_collection(book, None)
            pump()
        added.assert_not_called()

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


class WatchListScanTest(_LibraryWindowTest):

    """The watch list dialog's "Scan now" reaching the real library.

    The watch list dialog is covered against a stub library that counts
    the calls, and the library's own scan is covered from the library
    side; nothing put the two together, so nothing would have noticed
    the two halves drifting apart - a renamed method, or a scan that no
    longer reaches the pointer.
    """

    def _watch_list(self, dialog):
        watch_list = watchlist.WatchListDialog(dialog)
        self.addCleanup(watch_list.destroy)
        pump()
        return watch_list

    @staticmethod
    def _cursor_name(dialog):
        cursor = dialog.get_cursor()
        return None if cursor is None else cursor.get_name()

    def test_scan_now_scans_the_library_it_was_opened_from(self):
        dialog = self._open()
        directory = os.path.join(self.tmp_dir, 'watched')
        os.makedirs(directory, exist_ok=True)
        dialog.backend.watchlist.add_directory(directory)
        watch_list = self._watch_list(dialog)

        watch_list.response(watchlist.WatchListDialog.RESPONSE_SCANNOW)
        # Read before pumping: an empty directory is walked at once, and
        # the finish that puts the pointer back is waiting in the idle
        # queue for the first pump to deliver it.
        self.assertEqual('wait', self._cursor_name(dialog),
                         'Scan now did not start a scan of the library')
        pump()
        self.assertTrue(watch_list.get_visible(),
                        'Scan now took the watch list away')
        self.assertTrue(
            wait_for(lambda: self._cursor_name(dialog) is None, seconds=20),
            'the library was left showing the wait pointer')

    def test_closing_an_edited_watch_list_scans_the_library(self):
        """The edits are written as they are made, so closing owes a
        scan; Scan now has already covered them, so closing after one
        does not."""
        dialog = self._open()
        directory = os.path.join(self.tmp_dir, 'watched')
        os.makedirs(directory, exist_ok=True)
        dialog.backend.watchlist.add_directory(directory)
        watch_list = self._watch_list(dialog)
        watch_list._changed = True

        with unittest.mock.patch.object(dialog, 'scan_for_new_files') as scan:
            watch_list.response(Response.CLOSE)
            pump()
        scan.assert_called_once_with()

    def test_closing_an_unedited_watch_list_scans_nothing(self):
        dialog = self._open()
        watch_list = self._watch_list(dialog)

        with unittest.mock.patch.object(dialog, 'scan_for_new_files') as scan:
            watch_list.response(Response.CLOSE)
            pump()
        scan.assert_not_called()


class LibraryScanCursorTest(_LibraryWindowTest):

    """The pointer over the library while the watch list is scanned.

    The library window has slow work of its own, and the main window's
    cursor handler cannot show it: that one draws on the page area of a
    window the reader is not looking at while the library is up.
    """

    def _watching(self, dialog):
        """Watch an empty directory, so that a scan has work to report."""
        directory = os.path.join(self.tmp_dir, 'watched')
        os.makedirs(directory, exist_ok=True)
        dialog.backend.watchlist.add_directory(directory)
        return directory

    @staticmethod
    def _cursor_name(dialog):
        cursor = dialog.get_cursor()
        return None if cursor is None else cursor.get_name()

    def test_a_scan_puts_the_wait_pointer_over_the_library(self):
        dialog = self._open()
        self._watching(dialog)
        dialog.scan_for_new_files()
        self.assertEqual('wait', self._cursor_name(dialog))

    def test_the_pointer_goes_back_when_the_scan_is_over(self):
        dialog = self._open()
        self._watching(dialog)
        dialog.scan_for_new_files()
        self.assertTrue(
            wait_for(lambda: self._cursor_name(dialog) is None, seconds=20),
            'the library was left showing the wait pointer')

    def test_a_scan_with_nothing_watched_never_says_it_is_busy(self):
        """There is no walk to wait for, and no thread to clear the
        pointer afterwards either."""
        dialog = self._open()
        self.assertEqual([], dialog.backend.watchlist.get_watchlist())
        dialog.scan_for_new_files()
        self.assertIsNone(self._cursor_name(dialog))

    def test_the_pointer_stays_up_while_a_second_scan_runs(self):
        """Two scans overlap easily: the watch list dialog stays open
        after Scan now, and the library starts one of its own when it is
        opened. The first of them to finish must not put the pointer
        back while the other is still walking."""
        dialog = self._open()
        self._watching(dialog)
        # No thread, so that the only finishes are the ones below.
        with unittest.mock.patch.object(dialog.backend.watchlist,
                                        'scan_for_new_files'):
            dialog.scan_for_new_files()
            dialog.scan_for_new_files()
        self.assertEqual('wait', self._cursor_name(dialog))
        dialog._scan_finished()
        self.assertEqual('wait', self._cursor_name(dialog),
                         'one scan of two finishing put the pointer back')
        dialog._scan_finished()
        self.assertIsNone(self._cursor_name(dialog))

    def test_a_finish_with_no_scan_running_leaves_the_pointer_alone(self):
        """The count cannot go negative: a stray finish would otherwise
        owe the next scan an extra one before the pointer came back."""
        dialog = self._open()
        dialog._scan_finished()
        self._watching(dialog)
        with unittest.mock.patch.object(dialog.backend.watchlist,
                                        'scan_for_new_files'):
            dialog.scan_for_new_files()
        self.assertEqual('wait', self._cursor_name(dialog))
        dialog._scan_finished()
        self.assertIsNone(self._cursor_name(dialog))

    def test_the_scan_says_it_has_finished_even_where_a_walk_fails(self):
        """The pointer is cleared from the finish callback, so a scan
        that raises halfway through would leave it waiting for good."""
        dialog = self._open()
        self._watching(dialog)
        finished = []
        dialog.backend.watchlist.scan_finished += lambda: finished.append(True)
        with unittest.mock.patch.object(
                dialog.backend, 'get_paths_of_books_outside_recent',
                side_effect=OSError('the database went away')):
            dialog.scan_for_new_files()
            self.assertTrue(wait_for(lambda: finished, seconds=20),
                            'a scan that raised never reported a finish')
        self.assertTrue(
            wait_for(lambda: self._cursor_name(dialog) is None, seconds=20),
            'the library was left showing the wait pointer')


# vim: expandtab:sw=4:ts=4
