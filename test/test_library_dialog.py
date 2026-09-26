"""The library window itself, which nothing else covered.

open_dialog() keeps one window: opening the library again brings the
one that is up forward rather than building a second, and closing it
lets the next call build a new one. It used to answer False for a tree
with no sqlite, which the plain "from sqlite3 import dbapi2" in the
backend made unreachable.
"""

import gettext
import os
import shutil
import threading
import types
import unittest.mock

from gi.repository import GdkPixbuf, Gio, GLib, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import column_list
from mcomix import constants
from mcomix import i18n
from mcomix import icons
from mcomix import last_read_page
from mcomix import main
from mcomix import message_dialog
from mcomix import widgets
from mcomix.dialog import Response
from mcomix.library import backend_types
from mcomix.library import book_area
from mcomix.library import collection_area
from mcomix.library import main_dialog
from mcomix.library import watchlist
from mcomix.preferences import prefs
from mcomix import tools


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

    def test_quitting_closes_the_library(self):
        """Its covers are drawn by a worker thread, which only close()
        stops, and close() is also what keeps the window's size for the
        next time."""
        dialog = self._open()
        with unittest.mock.patch.object(
                dialog, 'close', wraps=dialog.close) as closed:
            self.window.terminate_program()
        closed.assert_called_once_with()
        self.assertIsNone(main_dialog.get_dialog())

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

    def test_a_scan_that_fails_is_logged_rather_than_raised(self):
        """Nothing joins the scan thread, so an exception it let out went
        to threading.excepthook as a bare traceback on stderr."""
        dialog = self._open()
        self._watching(dialog)
        finished = []
        dialog.backend.watchlist.scan_finished += lambda: finished.append(True)
        with unittest.mock.patch.object(
                dialog.backend, 'get_paths_of_books_outside_recent',
                side_effect=OSError('the database went away')), \
                unittest.mock.patch('threading.excepthook') as excepthook, \
                self.assertLogs('mcomix', 'ERROR') as logs:
            dialog.scan_for_new_files()
            self.assertTrue(wait_for(lambda: finished, seconds=20),
                            'a scan that raised never reported a finish')
            for thread in threading.enumerate():
                if thread.name.endswith('-scan_for_new_files'):
                    thread.join(5)
        excepthook.assert_not_called()
        self.assertEqual(
            ['ERROR:mcomix:! Could not scan for new books: '
             'the database went away'], logs.output)


class LibraryMenuPositionTest(_LibraryWindowTest):

    """A right click opens the library's two menus where it was made, as
    every other menu in MComix opens.  Both were pointed at the corner of
    their list, whichever row or cover had been clicked."""

    def _right_click(self, area, widget, x, y):
        """Where <area>'s menu is pointed after a click at (<x>, <y>) on
        <widget>, the widget its click gesture is attached to."""
        gesture = unittest.mock.Mock()
        gesture.get_widget.return_value = widget
        with unittest.mock.patch.object(widgets, 'popup_at') as popup:
            area._button_press(gesture, 1, x, y)
        popup.assert_called_once()
        _popover, over, at_x, at_y = popup.call_args.args
        return over, at_x, at_y

    def test_the_cover_menu_opens_at_the_click(self):
        area = self._open().book_area
        self.assertEqual((area._covers, 120.0, 45.0),
                         self._right_click(area, area._covers, 120.0, 45.0))

    def test_the_collection_menu_opens_at_the_click(self):
        area = self._open().collection_area
        self.assertEqual((area._list, 30.0, 60.0),
                         self._right_click(area, area._list, 30.0, 60.0))


class CustomCoverSizeTest(_LibraryWindowTest):

    def _prompts(self):
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_visible()]

    def test_cancelling_the_custom_size_leaves_the_size_that_was_ticked(self):
        """Picking "Custom..." ticked it before the size dialog had been
        answered, and cancelling that dialog left it ticked over a size
        that had not changed."""
        prefs['library cover size'] = constants.SIZE_NORMAL
        action = self._open().book_area._popup_actions.lookup_action(
            'cover-size')
        self.assertEqual(constants.SIZE_NORMAL, action.get_state().get_int32())
        action.change_state(GLib.Variant('i', 0))
        pump()
        prompts = self._prompts()
        self.assertEqual(1, len(prompts))
        prompts[0].response(Response.CANCEL)
        pump()
        self.assertEqual(constants.SIZE_NORMAL, prefs['library cover size'])
        self.assertEqual(constants.SIZE_NORMAL, action.get_state().get_int32())

# vim: expandtab:sw=4:ts=4


class _OneBookTest(_LibraryWindowTest):

    """The library open on "All books", which holds one book."""

    def setUp(self):
        super().setUp()
        prefs['last library collection'] = constants.COLLECTION_ALL
        self.dialog = self._open()
        self.path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.dialog.backend.add_book(self.path)
        self.dialog.book_area.display_covers(constants.COLLECTION_ALL)
        pump()

    def _left_on(self, page):
        lastread = last_read_page.LastReadPage(self.dialog.backend)
        lastread.set_enabled(True)
        lastread.set_page(self.path, page)


class ReloadCoversTest(_OneBookTest):

    """load_covers(), which a new cover size and the Exif and enhance
    preferences ask for: the covers are drawn again, at the size the
    preference says, and none of them from the cache."""

    def test_the_covers_are_drawn_again_at_the_new_size(self):
        area = self.dialog.book_area
        prefs['library cover size'] = 64
        with unittest.mock.patch.object(area._cache,
                                        'invalidate_all') as emptied, \
                unittest.mock.patch.object(area, 'display_covers',
                                           return_value=False) as shown:
            area.load_covers()
            emptied.assert_called_once_with()
            self.assertEqual(area._pixbuf_size(),
                             (area._covers._thumbnail_width,
                              area._covers._thumbnail_height))
            shown.assert_not_called()
            pump()
        shown.assert_called_once_with(constants.COLLECTION_ALL)


class MissingBooksTest(_LibraryWindowTest):

    """Books whose files have gone can be taken out of the library from
    the covers' own menu, not only from the collections' menu beside
    them."""

    def test_clean_up_in_the_covers_menu_takes_out_the_books_gone(self):
        prefs['last library collection'] = constants.COLLECTION_ALL
        dialog = self._open()
        path = os.path.join(self.tmp_dir, 'gone.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), path)
        dialog.backend.add_book(path)
        dialog.book_area.display_covers(constants.COLLECTION_ALL)
        pump()
        os.remove(path)
        self.assertEqual(constants.COLLECTION_ALL,
                         dialog.collection_area.get_current_collection())
        dialog.book_area._popup_book_menu()
        cleanup = widgets.simple_action(dialog.book_area._popup_actions,
                                        'cleanup')
        self.assertTrue(cleanup.get_enabled())
        cleanup.activate(None)
        pump()
        self.assertIsNone(dialog.backend.get_book_by_path(path))
        for popover in (dialog.book_area._book_menu,):
            popover.popdown()
        pump()


class FinishedMarkTest(_OneBookTest):

    """The tick on the cover of a book read to its last page."""

    def setUp(self):
        super().setUp()
        # The covers are drawn here, on the main thread.  A worker still
        # drawing the one display_covers() asked for could otherwise
        # draw it finished and make the mark before a test looks.
        self.dialog.book_area.stop_update()

    def _corner(self):
        """The pixel inside the tick's lower right corner, on the cover."""
        uid = self.dialog.backend.get_book_by_path(self.path).id
        cover = self.dialog.book_area._get_pixbuf(uid)
        x, y = cover.get_width() - 12, cover.get_height() - 12
        offset = y * cover.get_rowstride() + x * cover.get_n_channels()
        return tuple(cover.get_pixels()[offset:offset + 3])

    def test_a_finished_book_carries_the_mark_and_an_unread_one_not(self):
        unread = self._corner()
        self._left_on(4)
        self.assertNotEqual(unread, self._corner())

    def test_a_part_read_book_carries_no_mark(self):
        unread = self._corner()
        self._left_on(2)
        self.assertEqual(unread, self._corner())

    def test_covers_too_small_for_the_mark_go_without(self):
        prefs['library cover size'] = 40
        unread = self._corner()
        self._left_on(4)
        self.assertEqual(unread, self._corner())

    def test_the_mark_shows_whatever_colour_the_theme_draws_the_icon(self):
        # A symbolic icon loaded as a pixbuf keeps the colour it was
        # drawn in, which GTK would otherwise have recoloured: Adwaita's
        # dark grey vanished on a dark cover, and a theme that draws its
        # symbolic icons white would vanish on a light one.  The mark is
        # the icon's shape, dark on a light disc, for any theme.
        white = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                     16, 16)
        white.fill(0xFFFFFFFF)
        with unittest.mock.patch.object(icons, 'load_pixbuf',
                                        return_value=white):
            mark = self.dialog.book_area._finished_mark
        pixels = mark.get_pixels()

        def pixel(x, y):
            offset = y * mark.get_rowstride() + x * mark.get_n_channels()
            return tuple(pixels[offset:offset + 4])

        self.assertLess(max(pixel(12, 12)[:3]), 64, 'the tick is not dark')
        self.assertGreater(min(pixel(2, 12)[:3]), 200, 'the disc is not light')
        self.assertGreater(pixel(2, 12)[3], 200, 'the disc is not opaque')
        self.assertEqual(0, pixel(0, 0)[3], 'the mark is not round')

    def test_the_mark_is_loaded_once_for_every_cover(self):
        # Loading it is loading an SVG file, about 5 ms, and it was done
        # for every finished book each time its cover was drawn.
        self._left_on(4)
        with unittest.mock.patch.object(
                icons, 'load_pixbuf', wraps=icons.load_pixbuf) as load:
            for _ in range(3):
                self._corner()
        self.assertEqual(1, load.call_count)


class BookInfoTest(_OneBookTest):

    """The line under the covers that describes the selected book."""

    def _select(self):
        covers = self.dialog.book_area._covers
        covers.unselect_all()
        covers.select_only(0)
        pump()
        return self.dialog.control_area

    def _size(self):
        """The book's size, as GLib writes it in the machine's language."""
        return GLib.format_size(os.path.getsize(self.path))

    def test_an_unread_book_shows_its_name_folder_and_page_count(self):
        info = self._select()
        self.assertEqual('01-ZIP-Normal.zip', info._namelabel.get_text())
        self.assertEqual(os.path.dirname(self.path),
                         info._dirlabel.get_text())
        self.assertEqual('4 pages, %s' % self._size(), info._filelabel.get_text())
        self.assertTrue(info._open_button.get_sensitive())

    def test_the_size_is_written_as_everywhere_else(self):
        # It was the only size MComix wrote in MiB whatever the file:
        # a book of 1,344 bytes read "0.0 MiB".
        info = self._select()
        self.assertTrue(info._filelabel.get_text().endswith(
            tools.format_byte_size(os.path.getsize(self.path))))

    def test_a_book_left_part_read_shows_the_page_it_was_left_on(self):
        self._left_on(2)
        info = self._select()
        self.assertEqual('Page 2/4, %s' % self._size(),
                         info._filelabel.get_text())

    def test_a_book_read_to_the_end_says_when_it_was_finished(self):
        self._left_on(4)
        info = self._select()
        self.assertTrue(info._filelabel.get_text().startswith(
            '4 pages, %s, Finished reading on ' % self._size()))

    def test_selecting_nothing_empties_the_line(self):
        info = self._select()
        self.dialog.book_area._covers.unselect_all()
        pump()
        self.assertEqual('', info._namelabel.get_text())
        self.assertEqual('', info._filelabel.get_text())
        self.assertEqual('', info._dirlabel.get_text())
        self.assertFalse(info._open_button.get_sensitive())


class OpenFromLibraryTest(_LibraryWindowTest):

    """Opening a book from the library while its covers are drawn."""

    def _open_while_drawing(self, open_it):
        """Open the one book by <open_it>(book area) while its cover is
        still being drawn, then show the library again.

        Opening a book stopped the worker that draws the covers - a
        guard against a hang at exit that closing the library now sees
        to - so every cover still to be drawn stayed blank for good once
        the library was shown again."""
        prefs['last library collection'] = constants.COLLECTION_ALL
        dialog = self._open()
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        dialog.backend.add_book(path)
        covers = dialog.book_area._covers
        # The cover is held back until the book has been opened, so it
        # is still being drawn when that happens.  Not for long: opening
        # the book can redraw the covers, which waits for the worker.
        opened = threading.Event()
        draw = covers.generate_thumbnail

        def held_back(uid):
            opened.wait(1)
            return draw(uid)

        covers.generate_thumbnail = held_back
        dialog.book_area.display_covers(constants.COLLECTION_ALL)
        self.assertTrue(wait_for(lambda: any(covers.each_item())))
        pump()
        open_it(dialog.book_area)
        opened.set()
        self.assertFalse(dialog.get_visible())

        main_dialog.open_dialog(None, self.window)
        self.assertTrue(wait_for(
            lambda: all(item.thumbnail is not None
                        for item in covers.each_item()), seconds=5),
            'the cover was never drawn')

    def test_a_cover_double_clicked_while_drawing(self):
        self._open_while_drawing(
            lambda area: area._book_activated(area._covers, 0))

    def test_open_from_the_menu_while_drawing(self):
        def open_selected(area):
            area._covers.select_only(0)
            area.open_selected_book()

        self._open_while_drawing(open_selected)


class CopyBookTest(_OneBookTest):

    """"Copy" in the menu over the covers."""

    def test_copy_puts_the_selected_book_on_the_clipboard(self):
        area = self.dialog.book_area
        area._covers.select_only(0)
        pump()
        clipboard = self.dialog.main_window.clipboard
        with unittest.mock.patch.object(clipboard, 'copy') as copy:
            area._popup_actions.activate_action('copy-to-clipboard', None)
        copy.assert_called_once()
        path, cover = copy.call_args.args
        self.assertEqual(self.path, path)
        self.assertIsInstance(cover, GdkPixbuf.Pixbuf)


class AddBooksTest(_LibraryWindowTest):

    """Which collection books added to the library are filed in.

    add_books() took a collection's name, and with none the collection
    on show: files dropped on "Recent" made a second collection called
    "Recent", since the row of the real one holds the untranslated
    RECENT; files dropped on "All books" were filed under its id -1,
    which no row has; and a watched directory that files its books in
    no collection filed them in whichever one was on show.
    """

    def setUp(self):
        super().setUp()
        self.path = get_testfile_path('archives', '01-ZIP-Normal.zip')

    def _showing(self, collection):
        prefs['last library collection'] = collection
        dialog = self._open()
        # Read again, for a library that was open already.
        dialog.collection_area.display_collections()
        pump()
        self.assertEqual(collection,
                         dialog.collection_area.get_current_collection())
        return dialog

    def _drop(self, dialog):
        files = types.SimpleNamespace(
            get_files=lambda: [Gio.File.new_for_path(self.path)])
        self.assertTrue(dialog.book_area._drag_data_received(
            None, files, 0, 0))
        self._wait_for_book(dialog)

    def _wait_for_book(self, dialog):
        self.assertTrue(wait_for(
            lambda: dialog.backend.get_book_by_path(self.path) is not None,
            seconds=10))
        pump()

    @staticmethod
    def _filed(dialog):
        return dialog.backend.fetchall(
            'select collection, book from Contain order by collection')

    def test_files_dropped_on_all_books_are_filed_in_no_collection(self):
        dialog = self._showing(constants.COLLECTION_ALL)
        self._drop(dialog)
        self.assertEqual([], self._filed(dialog))
        book = dialog.backend.get_book_by_path(self.path)
        self.assertTrue(wait_for(lambda: [item.uid for item in
                                          dialog.book_area._each_item()]
                                 == [book.id]))

    def test_files_dropped_on_recent_make_no_collection_of_that_name(self):
        dialog = self._showing(constants.COLLECTION_RECENT)
        self._drop(dialog)
        self.assertEqual([constants.COLLECTION_RECENT],
                         dialog.backend.get_all_collections())
        self.assertEqual([], self._filed(dialog))

    def test_files_dropped_on_a_collection_are_filed_in_it(self):
        prefs['last library collection'] = constants.COLLECTION_ALL
        comics = self._open().backend.add_collection('Comics')
        dialog = self._showing(comics)
        self._drop(dialog)
        book = dialog.backend.get_book_by_path(self.path)
        self.assertEqual([(comics, book.id)], self._filed(dialog))

    def test_a_watched_directory_with_no_collection_files_in_none(self):
        prefs['last library collection'] = constants.COLLECTION_ALL
        comics = self._open().backend.add_collection('Comics')
        dialog = self._showing(comics)
        entry = types.SimpleNamespace(
            collection=backend_types.DefaultCollection, directory='/comics')
        dialog._new_files_found([self.path], entry)
        self._wait_for_book(dialog)
        self.assertEqual([], self._filed(dialog))

    def test_a_collection_a_scan_filed_books_in_still_shows_them(self):
        # add_books() made the collection the books went into the "last
        # library collection" while another stayed on show, and picking
        # that collection then did nothing: it was already the last one.
        prefs['last library collection'] = constants.COLLECTION_ALL
        backend = self._open().backend
        comics = backend.add_collection('Comics')
        manga = backend.add_collection('Manga')
        dialog = self._showing(comics)
        entry = types.SimpleNamespace(
            collection=backend.get_collection_by_id(manga),
            directory='/manga')
        dialog._new_files_found([self.path], entry)
        self._wait_for_book(dialog)
        book = backend.get_book_by_path(self.path)
        self.assertEqual([(manga, book.id)], self._filed(dialog))

        sidebar = dialog.collection_area._list
        sidebar.select_row(next(row for row in sidebar.each_stored_row()
                                if row.collection == manga))
        self.assertTrue(wait_for(lambda: [item.uid for item in
                                          dialog.book_area._each_item()]
                                 == [book.id]),
                        'the covers of "Manga" never showed')


class NewBooksMessageTest(MComixTest):

    """What the status bar says after a scan of a watched directory.

    The count of new books was translated with one form for every
    number, so Polish said "2 nowych książek", which is the form for
    five."""

    def _message(self, count):
        class _Library:
            def add_books(self, paths, collection):
                pass

            def set_status_message(self, message):
                self.message = message

        library = _Library()
        entry = types.SimpleNamespace(collection=None, directory='/comics')
        main_dialog._LibraryDialog._new_files_found(
            library, ['/comics/%d.cbz' % n for n in range(count)], entry)
        return library.message

    def test_polish_counts_two_books_and_five_books_differently(self):
        catalogue = os.path.join(os.path.dirname(i18n.__file__), 'messages',
                                 'pl', 'LC_MESSAGES', 'mcomix.mo')
        with open(catalogue, 'rb') as mo:
            polish = gettext.GNUTranslations(mo)
        with unittest.mock.patch.object(i18n, '_translation', polish):
            self.assertIn('2 nowe książki', self._message(2))
            self.assertIn('5 nowych książek', self._message(5))


class AddCollectionTest(_LibraryWindowTest):

    """"New collection...", through the dialog that asks for its name."""

    def _add(self, name, response=Response.OK):
        dialog = self._open()
        dialog.collection_area.add_collection()
        pump()
        prompts = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, message_dialog.MessageDialog)
                   and window.get_visible()]
        self.assertEqual(1, len(prompts))
        entry = self._entry_in(prompts[0])
        entry.set_text(name)
        prompts[0].response(response)
        pump()
        return dialog

    @staticmethod
    def _entry_in(widget):
        pending = [widget]
        while pending:
            widget = pending.pop()
            if isinstance(widget, Gtk.Entry):
                return widget
            child = widget.get_first_child()
            while child is not None:
                pending.append(child)
                child = child.get_next_sibling()
        raise AssertionError('the dialog has no entry')

    def _names(self, dialog):
        """The collections, less the Recent one the library keeps."""
        return sorted(dialog.backend.get_collection_name(collection)
                      for collection in dialog.backend.get_all_collections()
                      if dialog.backend.get_collection_name(collection)
                      != 'Recent')

    def test_a_new_collection_is_made_and_shown(self):
        dialog = self._add('Shelf')
        self.assertEqual(['Shelf'], self._names(dialog))
        shelf = dialog.backend.get_collection_by_name('Shelf')
        self.assertEqual(shelf.id,
                         dialog.collection_area.get_current_collection())

    def test_spaces_around_the_name_are_not_part_of_it(self):
        dialog = self._add('  Shelf ')
        self.assertEqual(['Shelf'], self._names(dialog))

    def test_a_name_of_nothing_but_spaces_makes_nothing(self):
        dialog = self._add('   ')
        self.assertEqual([], self._names(dialog))

    def test_cancel_makes_nothing(self):
        dialog = self._add('Shelf', Response.CANCEL)
        self.assertEqual([], self._names(dialog))

    def test_a_name_already_taken_is_refused_and_said_so(self):
        dialog = self._open()
        dialog.backend.add_collection('Shelf')
        self._add('Shelf')
        self.assertEqual(['Shelf'], self._names(dialog))
        self.assertIn('already exists', dialog._statusbar.get_text())


class CollectionMenuTest(_LibraryWindowTest):

    """What the collections' own menu does beside adding one."""

    def _id(self, dialog, name):
        return dialog.backend.get_collection_by_name(name).id

    def test_clean_up_of_all_books_takes_out_the_books_gone(self):
        prefs['last library collection'] = constants.COLLECTION_ALL
        dialog = self._open()
        path = os.path.join(self.tmp_dir, 'gone.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), path)
        dialog.backend.add_book(path)
        os.remove(path)
        self.assertEqual(constants.COLLECTION_ALL,
                         dialog.collection_area.get_current_collection())
        dialog.collection_area._clean_collection()
        pump()
        self.assertIsNone(dialog.backend.get_book_by_path(path))

    def test_renaming_takes_the_name_without_its_spaces(self):
        dialog = self._open()
        dialog.backend.add_collection('Box')
        box = self._id(dialog, 'Box')
        dialog.collection_area._rename_answered(Response.OK, box, ' Crate ')
        self.assertEqual('Crate', dialog.backend.get_collection_name(box))

    def test_renaming_to_a_name_taken_is_refused_and_said_so(self):
        dialog = self._open()
        dialog.backend.add_collection('Shelf')
        dialog.backend.add_collection('Box')
        box = self._id(dialog, 'Box')
        dialog.collection_area._rename_answered(Response.OK, box, 'Shelf')
        self.assertEqual('Box', dialog.backend.get_collection_name(box))
        self.assertIn('already exists', dialog._statusbar.get_text())

    def test_a_duplicate_that_fails_is_said_so(self):
        dialog = self._open()
        dialog.backend.add_collection('Box')
        dialog.collection_area.display_collections()
        rows = [row for row in dialog.collection_area._list.each_row()
                if row.collection == self._id(dialog, 'Box')]
        dialog.collection_area._list.select_row(rows[0])
        with unittest.mock.patch.object(dialog.backend, 'duplicate_collection',
                                        return_value=False):
            dialog.collection_area._duplicate_collection()
        self.assertIn('Could not duplicate collection.',
                      dialog._statusbar.get_text())
