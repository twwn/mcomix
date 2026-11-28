"""The library window itself, which nothing else covered.

open_dialog() keeps one window: opening the library again brings the
one that is up forward rather than building a second, and closing it
lets the next call build a new one. It used to answer False for a tree
with no sqlite, which the plain "from sqlite3 import dbapi2" in the
backend made unreachable.
"""

import dataclasses
import datetime
import gettext
import io
import os
import shutil
import tarfile
import threading
import types
import unittest.mock
import zipfile

import PIL.Image

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from . import (FolderDialogStub, MComixTest, NORMAL_ZIP, descendants,
               get_testfile_path, line_art_png, mounted_at, pixel, pump,
               solid_pixbuf, visible_prompts, wait_for, wait_frames)

from mcomix import archive_packer
from mcomix import archive_tools
from mcomix import bookmark_backend
from mcomix import bookmark_menu_item
from mcomix import column_list
from mcomix import constants
from mcomix import file_actions
from mcomix import i18n
from mcomix import icons
from mcomix import last_read_page
from mcomix import openwith
from mcomix import page_marks
from mcomix import page_rotations
from mcomix import reading_directions
from mcomix import thumbnail_list
from mcomix import webp_books
from mcomix import widgets
from mcomix.dialog import Response
from mcomix.library import backend_types
from mcomix.library import book_area
from mcomix.library import collection_area
from mcomix.library import control_area
from mcomix.library import folder_watcher
from mcomix.library import main_dialog
from mcomix.library import pixbuf_cache
from mcomix.library import relocate_dialog
from mcomix.library import watchlist
from mcomix import webp_dialog
from mcomix.preferences import prefs
from mcomix import tools


class _LibraryWindowTest(MComixTest):

    """A main window with a book open in it, and a library over that.

    The fixture rather than the tests: opening the library opens the
    database, so every class here needs the same window to open it from.
    """

    def setUp(self):
        super().setUp()
        self.open_main_window_on_a_book()

    def _written(self, asked):
        """Answer <asked>, a window that offers to write books, with OK,
        and the progress window once they are done."""
        asked.response(Response.OK)
        pump()
        progress, = [window for window in Gtk.Window.list_toplevels()
                     if isinstance(window, webp_dialog._ProgressDialog)]
        self.addCleanup(progress.destroy)
        self.assertTrue(wait_for(lambda: progress.finished, seconds=20))
        return progress

    def tearDown(self):
        main_dialog._close_dialog()
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, main_dialog._LibraryDialog):
                window.destroy()
        self.close_main_window()
        super().tearDown()

    def _open(self):
        main_dialog.open_dialog(None, self.window)
        pump()
        return main_dialog._dialog

    def _open_all(self):
        """Open the library on "All books", whatever collection it
        showed when it last closed."""
        prefs['last library collection'] = constants.COLLECTION_ALL
        return self._open()

    def _covers_drawn(self, dialog):
        """Wait until <dialog> shows covers and has drawn every one of
        them, which it reads from the books on a worker thread; fail the
        test if that does not come."""
        def drawn():
            items = list(dialog.book_area._covers.each_item())
            return items and all(item.thumbnail is not None
                                 for item in items)
        self.assertTrue(wait_for(drawn), 'the cover was never drawn')

    def _held(self, dialog, *paths):
        """Put the books at <paths> in the library, show "All books" and
        wait until their covers are drawn: Windows refuses to delete or
        move a file that is open, as one is while its cover is read
        (WinError 32 on GitHub's runner)."""
        for path in paths:
            self.assertTrue(dialog.backend.add_book(path))
        dialog.book_area.display_covers(constants.COLLECTION_ALL)
        self._covers_drawn(dialog)

    def _one_gone_from_all(self):
        """The library open on "All books", holding a book whose file
        has since been deleted; and that book's path."""
        dialog = self._open_all()
        path = os.path.join(self.tmp_dir, 'gone.cbz')
        shutil.copy(NORMAL_ZIP, path)
        self._held(dialog, path)
        os.remove(path)
        self.assertEqual(constants.COLLECTION_ALL,
                         dialog.collection_area.get_current_collection())
        return dialog, path

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

    def test_it_opens_on_all_books_where_none_was_chosen_before(self):
        """The collection last on show is opened on again; with none
        recorded - the library opened the first time, or its collection
        gone - nothing was selected and no cover shown, until one was
        clicked."""
        dialog = self._open()
        dialog.backend.add_book(NORMAL_ZIP)
        dialog.close()
        pump()
        for chosen in (None, 12345):
            with self.subTest(chosen=chosen):
                prefs['last library collection'] = chosen
                dialog = self._open()
                self.assertEqual(
                    constants.COLLECTION_ALL,
                    dialog.collection_area.get_current_collection())
                self.assertTrue(wait_for(
                    lambda: any(dialog.book_area._each_item())))
                dialog.close()
                pump()

    def test_covers_asked_for_just_before_closing_are_not_drawn(self):
        """A search, a collection picked or books removed ask for the
        covers from an idle; a main loop busy elsewhere, extracting a
        book, can run that idle only after the library has closed."""
        dialog = self._open()
        area = dialog.book_area
        GLib.idle_add(area.display_covers, constants.COLLECTION_ALL)
        dialog.close()
        del dialog
        with unittest.mock.patch.object(
                area._covers, 'set_items') as set_items:
            pump()
        set_items.assert_not_called()

    def test_a_long_status_message_does_not_widen_the_window(self):
        """A watched folder named in the status line made the library
        1495 pixels wide for a 150-character path."""
        dialog = self._open()
        dialog.present()
        self.assertTrue(wait_for(lambda: dialog.get_width() > 0))
        width = dialog.get_width()
        message = '/a/watched/folder/' + 'n' * 150
        dialog.set_status_message(message)
        pump()
        wait_for(lambda: dialog.get_width() != width, seconds=0.3)
        self.assertEqual(width, dialog.get_width())
        self.assertEqual(message, dialog._statusbar.get_tooltip_text())

    def test_the_window_lets_go_of_the_focus_before_its_surface(self):
        # See DialogTest's test of the same name.
        dialog = self._open()
        entry = next(widget for widget in widgets._descendants(dialog)
                     if isinstance(widget, Gtk.Entry))
        entry.grab_focus()
        self.assertIs(dialog.get_focus().get_parent(), entry)
        focus_when_unrealized = []
        entry.connect('unrealize', lambda _entry: focus_when_unrealized.append(
            dialog.get_focus()))
        main_dialog._close_dialog()
        self.assertEqual(focus_when_unrealized, [None])

    def _press(self, dialog, keyval, state=Gdk.ModifierType.CONTROL_MASK):
        return dialog._key_press_event(None, keyval, 0, state)

    def test_control_w_closes_the_library_as_its_close_button_does(self):
        dialog = self._open()
        with unittest.mock.patch.object(
                dialog, 'close', wraps=dialog.close) as closed:
            self.assertEqual(Gdk.EVENT_STOP, self._press(dialog, Gdk.KEY_w))
        closed.assert_called_once_with()
        self.assertIsNone(main_dialog.get_dialog())

    def test_control_f_goes_to_the_search_field(self):
        dialog = self._open()
        dialog.present()
        dialog.book_area.grab_focus()
        pump()
        self.assertEqual(Gdk.EVENT_STOP, self._press(dialog, Gdk.KEY_f))
        self.assertTrue(dialog.control_area.search_entry.has_focus()
                        or dialog.get_focus().get_parent()
                        is dialog.control_area.search_entry)

    def test_a_plain_w_or_f_is_left_to_the_focused_widget(self):
        dialog = self._open()
        for keyval in (Gdk.KEY_w, Gdk.KEY_f):
            self.assertEqual(Gdk.EVENT_PROPAGATE, self._press(
                dialog, keyval, Gdk.ModifierType(0)))
        self.assertIs(dialog, main_dialog.get_dialog())

    #: The pause the search waits for, in the tests that wait it out:
    #: a later search a keystroke put off would come within it of the
    #: first.
    PAUSE_MS = 50

    def _pausing(self):
        return unittest.mock.patch.object(
            control_area._ControlArea, 'SEARCH_DELAY_MS', self.PAUSE_MS)

    def test_the_search_follows_the_typing_once_it_pauses(self):
        """Books were filtered only on Enter.  Each keystroke now waits
        for the next; the books follow once the typing pauses."""
        dialog = self._open()
        entry = dialog.control_area.search_entry
        # Run from the idle queue, where a true answer, as a bare mock
        # gives, would have it run again for ever.
        with self._pausing(), unittest.mock.patch.object(
                dialog.book_area, 'display_covers',
                return_value=False) as shown:
            entry.set_text('nig')
            entry.set_text('night')
            # Synchronously nothing yet: the search waits for a pause.
            self.assertIsNone(dialog.filter_string)
            self.assertTrue(wait_for(
                lambda: dialog.filter_string == 'night', seconds=3))
            pump()
            wait_for(lambda: False, seconds=3 * self.PAUSE_MS / 1000)
        self.assertEqual(1, shown.call_count,
                         'the books were filtered more than once')

    def test_enter_searches_at_once_and_the_pause_adds_nothing(self):
        dialog = self._open()
        entry = dialog.control_area.search_entry
        # Run from the idle queue, where a true answer, as a bare mock
        # gives, would have it run again for ever.
        with self._pausing(), unittest.mock.patch.object(
                dialog.book_area, 'display_covers',
                return_value=False) as shown:
            entry.set_text('night')
            entry.emit('activate')
            self.assertEqual('night', dialog.filter_string)
            wait_for(lambda: False, seconds=3 * self.PAUSE_MS / 1000)
        self.assertEqual(1, shown.call_count)

    def test_a_reading_state_picked_narrows_the_books_at_once(self):
        """The choice beside the search field: picking a state shows
        the books again, with the search as it stands, and "All books"
        puts every one back."""
        dialog = self._open()
        control = dialog.control_area
        chooser = control.read_state_chooser
        states = backend_types.ReadState
        self.assertIs(states.ANY, chooser.get_value())
        control.search_entry.set_text('night')
        control.search_entry.emit('activate')
        with unittest.mock.patch.object(
                dialog.book_area, 'display_covers',
                return_value=False) as shown:
            chooser.set_value(states.FINISHED)
            self.assertIs(states.FINISHED, dialog.read_state)
            self.assertEqual('night', dialog.filter_string)
            pump()
            self.assertEqual(1, shown.call_count)
            chooser.set_value(states.ANY)
            self.assertIs(states.ANY, dialog.read_state)
            pump()
            self.assertEqual(2, shown.call_count)

    def test_a_search_typed_as_the_library_closes_is_dropped(self):
        dialog = self._open()
        entry = dialog.control_area.search_entry
        entry.set_text('night')
        self.assertTrue(dialog.control_area._pending_filter.running)
        control = dialog.control_area
        dialog.close()
        pump()
        self.assertFalse(control._pending_filter.running)

    def test_escape_in_a_search_empties_it_before_it_hides_the_library(self):
        dialog = self._open()
        dialog.present()
        entry = dialog.control_area.search_entry
        entry.set_text('night')
        entry.emit('activate')
        entry.grab_focus()
        pump()
        self.assertEqual('night', dialog.filter_string)
        none = Gdk.ModifierType(0)
        self.assertEqual(Gdk.EVENT_STOP,
                         self._press(dialog, Gdk.KEY_Escape, none))
        self.assertEqual('', entry.get_text())
        self.assertIsNone(dialog.filter_string)
        self.assertTrue(dialog.get_visible(), 'the library was hidden')
        self._press(dialog, Gdk.KEY_Escape, none)
        self.assertFalse(dialog.get_visible())

    def test_escape_with_the_covers_focused_hides_the_library(self):
        """A search left in the field is kept: the focus is elsewhere."""
        dialog = self._open()
        dialog.present()
        dialog.control_area.search_entry.set_text('night')
        dialog.book_area.grab_focus()
        pump()
        self._press(dialog, Gdk.KEY_Escape, Gdk.ModifierType(0))
        self.assertFalse(dialog.get_visible())
        self.assertEqual('night', dialog.control_area.search_entry.get_text())

    def _type_over_the_covers(self, dialog, keyval, state=0):
        return dialog.book_area._key_press(
            None, keyval, 0, Gdk.ModifierType(state))

    def test_a_letter_typed_over_the_covers_begins_a_search(self):
        """As a file manager does: the search field takes the focus and
        the letter, and the next letters follow it there."""
        dialog = self._open()
        dialog.present()
        dialog.book_area.grab_focus()
        pump()
        entry = dialog.control_area.search_entry
        self.assertEqual(Gdk.EVENT_STOP,
                         self._type_over_the_covers(dialog, Gdk.KEY_n))
        self.assertEqual('n', entry.get_text())
        self.assertTrue(entry.has_focus()
                        or dialog.get_focus().get_parent() is entry)
        self.assertEqual(1, entry.get_position())
        self.assertTrue(dialog.control_area._pending_filter.running)

    def test_keys_that_are_not_letters_stay_with_the_covers(self):
        dialog = self._open()
        entry = dialog.control_area.search_entry
        for keyval, state in ((Gdk.KEY_space, 0), (Gdk.KEY_Return, 0),
                              (Gdk.KEY_Down, 0),
                              (Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK),
                              (Gdk.KEY_n, Gdk.ModifierType.ALT_MASK)):
            with self.subTest(key=Gdk.keyval_name(keyval), state=state):
                self.assertEqual(Gdk.EVENT_PROPAGATE,
                                 self._type_over_the_covers(
                                     dialog, keyval, state))
        self.assertEqual('', entry.get_text())

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

    def test_a_book_that_cannot_be_read_is_named_in_the_status_bar(self):
        dialog = self._open()
        damaged = os.path.join(self.tmp_dir, 'bad.cbz')
        with open(damaged, 'wb') as book:
            book.write(b'not a book')
        dialog.add_books([damaged])
        pump()
        self.assertIn('Could not add 1 book to the library: bad.cbz',
                      dialog._statusbar.get_text())

    def test_a_closed_library_is_not_told_about_books_filed_later(self):
        """The cover view stayed subscribed to the backend, which outlives
        the window, and put a cover in its grid for every book filed
        after the library had closed - once for each time it had been
        opened."""
        dialog = self._open_all()
        self.assertEqual(constants.COLLECTION_ALL,
                         dialog.collection_area.get_current_collection())
        backend = dialog.backend
        path = NORMAL_ZIP
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

    def test_scan_now_scans_the_library_it_was_opened_from(self):
        dialog = self._open()
        self._watching(dialog)
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
        self._watching(dialog)
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


class FolderWatchTest(_LibraryWindowTest):

    """The watched folders, watched while the library is open: a book
    copied in was added only at the next scan, when the library was
    opened again or by hand."""

    def setUp(self):
        super().setUp()
        delay = unittest.mock.patch.object(folder_watcher, 'DELAY', 0.1)
        delay.start()
        self.addCleanup(delay.stop)
        prefs['scan for new books on library startup'] = True

    def _watched(self, name='watched'):
        directory = os.path.normpath(os.path.join(self.tmp_dir, name))
        os.makedirs(directory, exist_ok=True)
        return directory

    def _open_watching(self, *folders):
        """The library, opened on a database that watches <folders>,
        (folder, with subfolders) each."""
        dialog = self._open()
        for folder, recursive in folders:
            dialog.backend.watchlist.add_directory(folder)
            dialog.backend.watchlist.get_watchlist_entry(folder).set_recursive(recursive)
        dialog.watch_folders()
        expected = sorted(folder for folder, _recursive in folders)
        self.assertTrue(wait_for(lambda: expected == [
            f for f in dialog._watcher.folders if f in expected], seconds=10))
        return dialog

    def _arrive(self, folder, name='new.cbz'):
        """Copy a book into <folder>, as a file manager would: written,
        then closed."""
        path = os.path.join(folder, name)
        shutil.copy(NORMAL_ZIP, path)
        return path

    def _no_scan_after(self, folder, scan, act):
        """Assert that what <act> does in <folder> is not followed by
        <scan>.

        Not by waiting a second and hoping that was long enough: a
        monitor of the test's own on <folder> says when the file has
        arrived whole, which is when the watcher's monitors say so too,
        and with no DELAY the scan would follow at once.
        """
        arrived = []
        control = Gio.File.new_for_path(folder).monitor_directory(
            Gio.FileMonitorFlags.NONE, None)
        self.addCleanup(control.cancel)
        control.connect('changed', lambda monitor, file, other, event:
                        arrived.append(event))
        with unittest.mock.patch.object(folder_watcher, 'DELAY', 0.001):
            act()
            self.assertTrue(wait_for(
                lambda: Gio.FileMonitorEvent.CHANGES_DONE_HINT in arrived,
                seconds=20))
            self.assertFalse(wait_for(lambda: scan.called, seconds=0.1))

    def test_a_book_copied_in_is_added(self):
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        path = self._arrive(folder)
        self.assertTrue(wait_for(
            lambda: dialog.backend.get_book_by_path(path) is not None, seconds=20),
            'the book copied into a watched folder was not added')

    def test_a_book_in_a_new_subfolder_is_added_where_subfolders_are_watched(self):
        folder = self._watched()
        dialog = self._open_watching((folder, True))
        subfolder = os.path.join(folder, 'series')
        os.makedirs(subfolder)
        self.assertTrue(wait_for(lambda: subfolder in dialog._watcher.folders,
                                 seconds=10), 'the new subfolder is not watched')
        path = self._arrive(subfolder)
        self.assertTrue(wait_for(
            lambda: dialog.backend.get_book_by_path(path) is not None, seconds=20))

    def test_a_subfolder_is_not_watched_where_subfolders_are_not(self):
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        os.makedirs(os.path.join(folder, 'series'))
        pump()
        self.assertEqual([folder], dialog._watcher.folders)

    def test_no_more_folders_than_the_limit_are_watched(self):
        """Each is an inotify watch, of which a user has a few thousand
        for every program together."""
        folder = self._watched()
        for name in ('a', 'b', 'c', 'd'):
            os.makedirs(os.path.join(folder, name))
        with unittest.mock.patch.object(folder_watcher, 'LIMIT', 3):
            dialog = self._open()
            dialog.backend.watchlist.add_directory(folder)
            dialog.backend.watchlist.get_watchlist_entry(folder).set_recursive(True)
            dialog.watch_folders()
            self.assertTrue(wait_for(lambda: len(dialog._watcher.folders) == 3,
                                     seconds=10))
            os.makedirs(os.path.join(folder, 'e'))
            pump()
            self.assertEqual(3, len(dialog._watcher.folders))
            self.assertIn(folder, dialog._watcher.folders)

    def test_a_book_deleted_from_a_watched_folder_is_removed(self):
        """Only books arriving were scanned for, and the library kept a
        book deleted from a watched folder until "Clean up"."""
        folder = self._watched()
        kept = self._arrive(folder, 'kept.cbz')
        deleted = self._arrive(folder, 'deleted.cbz')
        prefs['last library collection'] = constants.COLLECTION_ALL
        dialog = self._open_watching((folder, False))
        self._held(dialog, kept, deleted)
        os.remove(deleted)
        self.assertTrue(wait_for(
            lambda: dialog.backend.get_book_by_path(deleted) is None,
            seconds=20), 'the book deleted was kept')
        self.assertIsNotNone(dialog.backend.get_book_by_path(kept))
        self.assertTrue(wait_for(lambda: [kept] == [
            item.path for item in dialog.book_area._covers.each_item()]),
            'the deleted book is still shown')

    def test_a_book_moved_within_a_watched_folder_keeps_its_place(self):
        """Removed and added again, it would lose its collections, cover
        and the page it was left at."""
        folder = self._watched()
        os.makedirs(os.path.join(folder, 'a'))
        os.makedirs(os.path.join(folder, 'b'))
        old = self._arrive(os.path.join(folder, 'a'), 'book.cbz')
        dialog = self._open_watching((folder, True))
        self._held(dialog, old)
        dialog.backend.add_collection('Shelf')
        shelf = dialog.backend.get_collection_by_name('Shelf').id
        book = dialog.backend.get_book_by_path(old).id
        dialog.backend.add_book_to_collection(book, shelf)
        new = os.path.join(folder, 'b', 'book.cbz')
        os.rename(old, new)
        self.assertTrue(wait_for(
            lambda: dialog.backend.get_book_by_path(new) is not None,
            seconds=20), 'the book moved was not found')
        pump()
        self.assertEqual(book, dialog.backend.get_book_by_path(new).id)
        self.assertIsNone(dialog.backend.get_book_by_path(old))
        self.assertIn(book, dialog.backend.get_books_in_collection(shelf))

    def test_books_moved_within_a_watched_folder_follow_in_one_transaction(self):
        """A commit a book, an fsync each, took 16.9 s over 2,000 books
        moved on a real disk."""
        folder = self._watched()
        os.makedirs(os.path.join(folder, 'a'))
        old = [self._arrive(os.path.join(folder, 'a'), name)
               for name in ('one.cbz', 'two.cbz')]
        dialog = self._open()
        self._held(dialog, *old)
        dialog.backend.watchlist.add_directory(folder)
        entry = dialog.backend.watchlist.get_watchlist_entry(folder)
        entry.set_recursive(True)
        os.rename(os.path.join(folder, 'a'), os.path.join(folder, 'b'))
        new = [os.path.join(folder, 'b', os.path.basename(path))
               for path in old]
        statements = []
        dialog.backend._con.set_trace_callback(statements.append)
        try:
            answer = dialog._follow_and_remove(new, entry)
        finally:
            dialog.backend._con.set_trace_callback(None)
        self.assertEqual(([], 0), answer)
        self.assertTrue(all(dialog.backend.get_book_by_path(path)
                            for path in new))
        self.assertEqual(1, sum(statement.startswith('BEGIN')
                                for statement in statements))

    def test_a_book_that_cannot_be_added_is_not_reported_as_added(self):
        """It is new again at every scan, and "Scan now" said "Added 21
        new books" at every click over 21 such books."""
        folder = self._watched()
        good = self._arrive(folder, 'good.cbz')
        damaged = os.path.join(folder, 'bad.cbz')
        with open(damaged, 'wb') as book:
            book.write(b'not a book')
        dialog = self._open()
        dialog.backend.watchlist.add_directory(folder)
        entry = dialog.backend.watchlist.get_watchlist_entry(folder)
        dialog._new_files_found([damaged, good], entry)
        pump()
        self.assertEqual(
            "Added new book 'good.cbz' from folder '%s'. Could not add 1 "
            "book to the library: bad.cbz" % folder,
            dialog._statusbar.get_text().strip())
        dialog._new_files_found([damaged], entry)
        pump()
        self.assertEqual('Could not add 1 book to the library: bad.cbz',
                         dialog._statusbar.get_text().strip())

    def test_a_book_that_cannot_be_added_is_passed_over_until_it_changes(self):
        folder = self._watched()
        damaged = os.path.join(folder, 'bad.cbz')
        with open(damaged, 'wb') as book:
            book.write(b'not a book')
        dialog = self._open()
        watchlist = dialog.backend.watchlist
        watchlist.add_directory(folder)

        def scanned():
            dialog.set_status_message('')
            watchlist.scan_for_new_files()
            self.assertTrue(wait_for(
                lambda: dialog._statusbar.get_text().strip(), seconds=10))
            return dialog._statusbar.get_text().strip()

        refused = 'Could not add 1 book to the library: bad.cbz'
        self.assertEqual(refused, scanned())
        self.assertEqual("No new books found in folder '%s'." % folder,
                         scanned())
        with open(damaged, 'ab') as book:
            book.write(b'!')
        self.assertEqual(refused, scanned())

    def test_a_batch_of_books_is_one_scan(self):
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        with unittest.mock.patch.object(folder_watcher, 'DELAY', 0.5), \
                unittest.mock.patch.object(dialog._watcher, '_scan') as scan:
            for number in range(3):
                self._arrive(folder, 'book%d.cbz' % number)
            self.assertTrue(wait_for(lambda: scan.called, seconds=10))
            pump()
        scan.assert_called_once_with()

    def test_what_is_no_book_scans_nothing(self):
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        def write():
            with open(os.path.join(folder, 'notes.txt'), 'w') as fp:
                fp.write('x')
        with unittest.mock.patch.object(dialog._watcher, '_scan') as scan:
            self._no_scan_after(folder, scan, write)

    def test_an_archive_being_written_again_scans_nothing(self):
        """Its name ends as a book's does, and it is gone a moment
        later: the scan it started reported it as a book it could not
        add."""
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        with unittest.mock.patch.object(dialog._watcher, '_scan') as scan:
            self._no_scan_after(folder, scan, lambda: self._arrive(
                folder, archive_tools.WORKING_PREFIX + 'x1y2.new.cbz'))

    def test_nothing_is_watched_with_the_scan_at_opening_off(self):
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        prefs['scan for new books on library startup'] = False
        dialog.watch_folders()
        self.assertEqual([], dialog._watcher.folders)

    def test_closing_the_library_stops_watching(self):
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        watcher = dialog._watcher
        dialog.close()
        pump()
        self.assertEqual([], watcher.folders)
        with unittest.mock.patch.object(watcher, '_scan') as scan:
            self._no_scan_after(folder, scan, lambda: self._arrive(folder))

    def test_a_library_destroyed_without_close_stops_watching(self):
        """_close_dialog() destroys the window without close().  A scan
        still pending then ran on the closed database, during whatever
        test came next on the CI's floors and Windows jobs (Tests
        41211974279, Windows tests 41211974270), whose GLib reported a
        copied book once more after the test that copied it."""
        folder = self._watched()
        dialog = self._open_watching((folder, False))
        watcher = dialog._watcher
        with unittest.mock.patch.object(watcher, '_scan') as scan, \
                unittest.mock.patch.object(folder_watcher, 'DELAY', 0.001):
            # Due a millisecond on: a wait of 0 is no wait at all.
            watcher._later()
            main_dialog._close_dialog()
            pump()
            self.assertEqual([], watcher.folders)
            self.assertFalse(wait_for(lambda: scan.called, seconds=0.1))

    def test_an_edited_watch_list_is_watched_as_it_now_stands(self):
        dialog = self._open()
        folder = self._watched()
        watch_list = watchlist.WatchListDialog(dialog)
        self.addCleanup(watch_list.destroy)
        dialog.backend.watchlist.add_directory(folder)
        watch_list._changed = True
        watch_list.response(Response.CLOSE)
        self.assertTrue(wait_for(lambda: dialog._watcher.folders == [folder],
                                 seconds=10))


class FolderWatcherRootTest(MComixTest):

    def test_a_new_subfolder_of_a_drive_root_is_watched(self):
        """A watched folder that is a whole drive, D:\\ or /: what ends in
        a separator already took a second one, which no path below it
        starts with, and its new subfolders went unwatched."""
        watched: list[str] = []
        watcher = folder_watcher.FolderWatcher(lambda: None)
        watcher._watch = watched.append
        watcher._later = lambda: None
        arrived = os.path.join(self.tmp_dir, 'New')
        os.mkdir(arrived)
        watcher._recursive = [os.path.abspath(os.sep)]
        watcher._changed(None, Gio.File.new_for_path(arrived), None,
                         Gio.FileMonitorEvent.CREATED)
        self.assertEqual([arrived], watched)


class LibraryScanCursorTest(_LibraryWindowTest):

    """The pointer over the library while the watch list is scanned.

    The library window has slow work of its own, and the main window's
    cursor handler cannot show it: that one draws on the page area of a
    window the reader is not looking at while the library is up.
    """

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

    def _a_scan_that_fails(self):
        """The library open over a watched directory; the list each
        finish of a scan adds to; and a patch under which the scan's
        read of the database fails."""
        dialog = self._open()
        self._watching(dialog)
        finished = []
        dialog.backend.watchlist.scan_finished += lambda: finished.append(True)
        failing = unittest.mock.patch.object(
            dialog.backend, 'get_paths_of_books_outside_recent',
            side_effect=OSError('the database went away'))
        return dialog, finished, failing

    def test_the_scan_says_it_has_finished_even_where_a_walk_fails(self):
        """The pointer is cleared from the finish callback, so a scan
        that raises halfway through would leave it waiting for good."""
        dialog, finished, failing = self._a_scan_that_fails()
        with failing:
            dialog.scan_for_new_files()
            self.assertTrue(wait_for(lambda: finished, seconds=20),
                            'a scan that raised never reported a finish')
        self.assertTrue(
            wait_for(lambda: self._cursor_name(dialog) is None, seconds=20),
            'the library was left showing the wait pointer')

    def test_a_scan_that_fails_is_logged_rather_than_raised(self):
        """Nothing joins the scan thread, so an exception it let out went
        to threading.excepthook as a bare traceback on stderr."""
        dialog, finished, failing = self._a_scan_that_fails()
        with failing, \
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
        prompts = visible_prompts()
        self.assertEqual(1, len(prompts))
        prompts[0].response(Response.CANCEL)
        pump()
        self.assertEqual(constants.SIZE_NORMAL, prefs['library cover size'])
        self.assertEqual(constants.SIZE_NORMAL, action.get_state().get_int32())


class _OneBookTest(_LibraryWindowTest):

    """The library open on "All books", which holds one book."""

    def setUp(self):
        super().setUp()
        self.dialog = self._open_all()
        self.path = self._book()
        self.dialog.backend.add_book(self.path)
        self.dialog.book_area.display_covers(constants.COLLECTION_ALL)
        pump()

    def _book(self):
        """The book the library holds."""
        return NORMAL_ZIP

    def _left_on(self, page):
        lastread = last_read_page.LastReadPage(self.dialog.backend)
        lastread.set_enabled(True)
        lastread.set_page(self.path, page)

    def _item(self):
        """The book's cover, as the covers list holds it."""
        return next(iter(self.dialog.book_area._covers.each_item()))

    def _cover_made(self):
        """Wait for the cover, and for its worker to have done with it: the
        worker hands the cover over before it takes the order off its list,
        and until then a new order for this book is dropped as a duplicate."""
        covers = self.dialog.book_area._covers
        self.assertTrue(wait_for(
            lambda: (self._item().thumbnail is not None
                     and not covers._thread._orders_set),
            seconds=10))
        pump()


class SortKeysKeptTest(_OneBookTest):

    """The keys a sort puts the covers in order by are made once a book
    while the library is open.  Entries are made anew for the books a
    search had hidden, and tools.natural_key() keeps only the keys it
    made last: over 10000 books every display made all of them again,
    13 of the 79 ms it took to clear a search."""

    def test_an_entry_made_again_takes_the_key_made_before(self):
        area = self.dialog.book_area
        shown = next(area._each_item())
        key = shown.path_key
        # New entries, as for the books a search had hidden.
        area._entries_reusable = False
        with unittest.mock.patch.object(
                book_area.tools, 'natural_key',
                side_effect=AssertionError('a key made again')):
            area.display_covers(constants.COLLECTION_ALL)
        again = next(area._each_item())
        self.assertIsNot(shown, again)
        self.assertIs(key, again.path_key)

    def test_the_keys_go_with_the_window(self):
        area = self.dialog.book_area
        self.assertTrue(area._keys)
        # What the window's close button does.
        self.dialog.close()
        pump()
        self.assertEqual({}, area._keys)


class CoverAtTheNextStartTest(_OneBookTest):

    """A cover drawn once is read back as it was drawn, from a file of
    its own, where it used to be decoded from the cover stored at its
    largest and scaled down for every book in view at every start."""

    def setUp(self):
        # The covers in memory are the program's, not the window's, and
        # another test's cover of this book would be shown without one
        # being drawn here at all.
        pixbuf_cache.get_pixbuf_cache().invalidate_all()
        super().setUp()
        self._cover_made()

    def _book(self):
        # With a cover large enough to be stored 500 pixels high: one
        # drawn at nearly the size it is stored at is not kept.
        path = os.path.join(self.tmp_dir, 'book.cbz')
        page = io.BytesIO()
        PIL.Image.new('RGB', (1000, 1500), 'teal').save(page, 'JPEG')
        with zipfile.ZipFile(path, 'w') as book:
            book.writestr('01.jpg', page.getvalue())
        return path

    def _shown_again(self):
        """Have the cover made again with nothing in memory, and answer
        how often the cover stored was read for it."""
        area = self.dialog.book_area
        area._cache.invalidate_all()
        backend = self.dialog.backend
        shown = self._item().thumbnail
        with unittest.mock.patch.object(
                backend, 'get_book_thumbnail',
                wraps=backend.get_book_thumbnail) as read:
            area._covers.redraw_item(self._item())
            self.assertTrue(wait_for(
                lambda: self._item().thumbnail is not shown, seconds=10))
            self._cover_made()
        return read.call_count

    def test_the_cover_stored_is_not_decoded_for_it(self):
        self.assertEqual(0, self._shown_again())

    def test_at_another_size_it_is_once(self):
        prefs['library cover size'] = constants.SIZE_TINY
        self.assertEqual(1, self._shown_again())
        self.assertEqual(0, self._shown_again())


class CoverInFlightTest(_OneBookTest):

    """A cover a worker is making when what it should look like changes."""

    def _nothing_kept_as_drawn(self):
        """While this holds, a cover is read from the one stored at its
        largest, where a test parks its worker: the cover kept as it was
        last drawn, which is read first, is not found."""
        return unittest.mock.patch.object(
            self.dialog.backend, 'get_sized_book_cover',
            lambda path, made_for: None)

    def _with_a_cover_in_flight(self, meanwhile):
        """Run <meanwhile> with a worker parked in reading the cover."""
        area = self.dialog.book_area
        self._cover_made()
        area._cache.invalidate_all()
        entered, go_on = threading.Event(), threading.Event()
        self.addCleanup(go_on.set)
        read = self.dialog.backend.get_book_thumbnail
        self.cover_read = threading.Event()
        self.reads = []

        def parked(path, *size):
            self.reads.append(path)
            entered.set()
            go_on.wait(10)
            self.cover_read.set()
            return read(path, *size)

        with unittest.mock.patch.object(self.dialog.backend,
                                        'get_book_thumbnail', parked), \
                self._nothing_kept_as_drawn():
            area._covers.redraw_item(self._item())
            self.assertTrue(wait_for(entered.is_set, seconds=10))
            meanwhile()
            go_on.set()
            pump()
            self._cover_made()

    def test_a_cover_begun_at_the_old_size_is_not_kept(self):
        """It was stored once the cache had been emptied, and the new
        size then found it there: half the size of its cell, until it
        was next invalidated or evicted."""
        area = self.dialog.book_area
        prefs['library cover size'] = 100
        area.load_covers()
        pump()

        def larger():
            prefs['library cover size'] = 200
            area.load_covers()

        self._with_a_cover_in_flight(larger)
        wanted = area._pixbuf_size()[0]
        self.assertLessEqual(abs(self._item().thumbnail.get_width() - wanted), 4)

    def test_a_cover_invalidated_while_it_is_made_is_not_kept(self):
        """A new cover chosen for the book, say."""
        area = self.dialog.book_area
        self._with_a_cover_in_flight(
            lambda: area._cache.invalidate(self.path))
        # Which waits for the worker to have done with it.
        area._covers.stop_update()
        self.assertIsNone(area._cache.get(self.path))

    def test_showing_other_books_does_not_wait_for_the_cover(self):
        """A collection chosen or a letter typed in the search box: the
        window stood still until the cover was read, five seconds of it
        for one deep in a 400 MB solid archive."""
        area = self.dialog.book_area

        def other_books():
            area.display_covers(constants.COLLECTION_ALL)
            self.assertFalse(self.cover_read.is_set(),
                             'the main thread waited for the cover')

        self._with_a_cover_in_flight(other_books)

    def test_a_book_asked_for_again_is_not_read_twice_at_once(self):
        """Not waiting for the read must not mean starting another: eight
        letters typed read that archive eight times at once.  A letter
        typed keeps the entries on show now, so the book is asked for
        again where they are made anew, as for a new cover size; the
        worker that takes the order waits for the read under way."""
        area = self.dialog.book_area
        waiting = threading.Event()
        wait = area._reading.wait

        def wait_noted(*args, **kwargs):
            waiting.set()
            return wait(*args, **kwargs)

        def drawn_anew():
            with unittest.mock.patch.object(area._reading, 'wait',
                                            wait_noted):
                for _size in range(3):
                    area.load_covers()
                # The new entry's order is taken by a worker that either
                # waits for the read under way or begins one of its own.
                self.assertTrue(wait_for(
                    lambda: waiting.is_set() or len(self.reads) > 1),
                    'the book was not asked for again')
            self.assertEqual(self.reads, [self.path])

        self._with_a_cover_in_flight(drawn_anew)


    def test_closing_the_window_does_not_wait_for_the_cover(self):
        """close() joined the worker: five seconds for a cover deep in a
        400 MB solid archive, with the window frozen on its way out."""
        area = self.dialog.book_area
        self._cover_made()
        area._cache.invalidate_all()
        entered, go_on, done = (threading.Event(), threading.Event(),
                                threading.Event())
        self.addCleanup(go_on.set)
        read = self.dialog.backend.get_book_thumbnail
        failures, workers = [], []

        def parked(path, *size):
            workers.append(threading.current_thread())
            entered.set()
            go_on.wait(10)
            try:
                return read(path, *size)
            finally:
                done.set()

        with unittest.mock.patch.object(self.dialog.backend,
                                        'get_book_thumbnail', parked), \
                self._nothing_kept_as_drawn(), \
                unittest.mock.patch.object(threading, 'excepthook',
                                           failures.append):
            area._covers.redraw_item(self._item())
            self.assertTrue(wait_for(entered.is_set, seconds=10))
            self.dialog.close()
            self.assertFalse(done.is_set(),
                             'closing the window waited for the cover')
            go_on.set()
            # The worker finishes its order and ends, rather than parking
            # for orders that will never come.
            self.assertTrue(wait_for(
                lambda: not any(t.is_alive() for t in workers), seconds=10))
        self.assertTrue(done.is_set())
        self.assertEqual([], failures)


    def test_quitting_with_a_cover_in_flight_leaves_the_library_closed(self):
        """The worker closing the window let go of went on to ask for the
        book's last page after quitting had closed the library, which
        opened the database again; tearDown() fails on that."""
        area = self.dialog.book_area
        self._cover_made()
        area._cache.invalidate_all()
        entered, go_on = threading.Event(), threading.Event()
        read = self.dialog.backend.get_book_thumbnail

        def parked(path, *size):
            entered.set()
            go_on.wait(10)
            return read(path, *size)

        with unittest.mock.patch.object(self.dialog.backend,
                                        'get_book_thumbnail', parked), \
                self._nothing_kept_as_drawn():
            area._covers.redraw_item(self._item())
            self.assertTrue(wait_for(entered.is_set, seconds=10))
        self.dialog.close()
        # Let go once quitting has begun, which tearDown() does.
        later = threading.Timer(0.3, go_on.set)
        later.daemon = True
        later.start()


class LibraryWalkTest(_LibraryWindowTest):

    """A book opened from the library: Next and Previous archive walk the
    books the library shows, in the order shown, not the book's folder
    (upstream bug 42)."""

    def setUp(self):
        super().setUp()
        prefs['last library collection'] = constants.COLLECTION_ALL
        source = NORMAL_ZIP
        self.paths = {}
        for name in ('first/one.zip', 'first/two.zip', 'second/three.zip'):
            # Joined a part at a time: the handler's paths have Windows'
            # separators there, and "/" would never compare equal.
            path = os.path.join(self.tmp_dir, *name.split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(source, path)
            self.paths[name] = path
        self.dialog = self._open()
        # first/two.zip is beside first/one.zip in its folder, but not in
        # the library.
        for name in ('first/one.zip', 'second/three.zip'):
            self.dialog.backend.add_book(self.paths[name])
        self.dialog.book_area.display_covers(constants.COLLECTION_ALL)
        pump()

    def _open_from_library(self, name):
        book = self.dialog.backend.get_book_by_path(self.paths[name])
        self.dialog.open_book([book.id])
        self._wait_for(name)

    def _wait_for(self, name):
        handler = self.window.filehandler
        self.assertTrue(wait_for(
            lambda: handler.file_loaded
            and handler.get_path_to_base() == self.paths[name],
            seconds=20), handler.get_path_to_base())

    def test_next_archive_goes_to_the_next_book_shown(self):
        self._open_from_library('first/one.zip')
        self.assertTrue(self.window.filehandler.open_next_archive())
        self._wait_for('second/three.zip')

    def test_previous_archive_comes_back_the_same_way(self):
        self._open_from_library('second/three.zip')
        self.assertTrue(self.window.filehandler.open_previous_archive())
        self._wait_for('first/one.zip')

    def test_the_last_book_shown_has_no_next(self):
        self._open_from_library('second/three.zip')
        self.assertFalse(self.window.filehandler.open_next_archive())

    def test_the_file_number_counts_the_books_shown(self):
        self._open_from_library('second/three.zip')
        self.assertEqual((2, 2), self.window.filehandler.get_file_number())

    def test_a_book_opened_from_its_folder_still_walks_the_folder(self):
        self.window.filehandler.open_file(self.paths['first/one.zip'])
        self._wait_for('first/one.zip')
        self.assertTrue(self.window.filehandler.open_next_archive())
        self._wait_for('first/two.zip')


class ReadingListTest(_LibraryWindowTest):

    """A collection whose books are put in order by hand, and read in
    that order (upstream feature request 19).

    Sorted "By hand", the covers stand in the places the collection
    keeps; a cover dragged onto another, or moved with Alt and an arrow,
    takes a new place, and Next archive walks the covers as shown.
    """

    NAMES = ('1.zip', '2.zip', '3.zip', '4.zip')

    def setUp(self):
        super().setUp()
        prefs['last library collection'] = constants.COLLECTION_ALL
        prefs['lib sort key'] = constants.SORT_HAND
        prefs['lib sort order'] = constants.SORT_ASCENDING
        source = NORMAL_ZIP
        self.dialog = self._open()
        self.area = self.dialog.book_area
        self.backend = self.dialog.backend
        self.list = self.backend.add_collection('List')
        self.paths = {}
        for name in self.NAMES:
            path = os.path.join(self.tmp_dir, name)
            shutil.copyfile(source, path)
            self.paths[name] = path
            self.backend.add_book(path, self.list)
        self._show(self.list)

    def _show(self, collection):
        prefs['last library collection'] = collection
        self.dialog.collection_area.display_collections()
        pump()
        self.assertEqual(
            collection, self.dialog.collection_area.get_current_collection())
        self.area.display_covers(collection)
        # Nothing here looks at a cover, and a worker drawing one would
        # be waited for by every change of what is shown.
        self.area.stop_update()

    def _shown(self):
        return ''.join(os.path.basename(path)[0]
                       for path in self.area.shown_paths())

    def _kept(self):
        """The order the collection keeps, whatever the covers show."""
        return ''.join(os.path.basename(self.backend.get_book_path(book))[0]
                       for book in self.backend.get_collection_order(
                           self.list))

    def _selected(self):
        return ''.join(os.path.basename(item.path)[0]
                       for item in self.area._selected_items())

    def _drop(self, dragged, onto):
        """Drag the covers at the positions <dragged> onto the cover at
        the position <onto>, or onto no cover if that is -1."""
        value = '%s:%s' % (constants.LIBRARY_DRAG_BOOKS,
                           ','.join(str(position) for position in dragged))
        with unittest.mock.patch.object(self.area._covers, 'position_at',
                                        return_value=onto):
            return self.area._books_dropped(None, value, 5.0, 5.0)

    def _alt(self, key):
        return self.area._key_press(None, key, 0, Gdk.ModifierType.ALT_MASK)

    def test_books_nobody_placed_are_shown_by_their_paths(self):
        self.assertEqual('1234', self._shown())
        self.assertEqual({}, self.backend.get_book_positions(self.list))

    def test_a_cover_dropped_on_a_later_one_goes_after_it(self):
        self.assertTrue(self._drop([0], 2))
        self.assertEqual('2314', self._shown())
        self.assertEqual('2314', self._kept())

    def test_a_cover_dropped_on_an_earlier_one_goes_before_it(self):
        self.assertTrue(self._drop([3], 1))
        self.assertEqual('1423', self._shown())

    def test_several_covers_keep_their_order_among_themselves(self):
        self.assertTrue(self._drop([0, 2], 3))
        self.assertEqual('2413', self._shown())

    def test_a_cover_dropped_on_no_cover_goes_last(self):
        self.assertTrue(self._drop([1], -1))
        self.assertEqual('1342', self._shown())

    def test_the_covers_moved_stay_selected(self):
        self.area._covers.select_positions([0, 1])
        self.assertTrue(self._drop([0, 1], 3))
        self.assertEqual('3412', self._shown())
        self.assertEqual('12', self._selected())

    def test_a_cover_dropped_on_itself_stays(self):
        self.assertFalse(self._drop([1], 1))
        self.assertFalse(self._drop([1, 2], 2))
        self.assertEqual({}, self.backend.get_book_positions(self.list))

    def test_the_order_is_there_when_the_collection_is_shown_again(self):
        self._drop([0], 3)
        self._show(constants.COLLECTION_ALL)
        self._show(self.list)
        self.assertEqual('2341', self._shown())

    def test_descending_shows_and_moves_the_other_way_round(self):
        self._drop([0], 3)
        prefs['lib sort order'] = constants.SORT_DESCENDING
        self.area.set_sort_order()
        self.assertEqual('1432', self._shown())
        # The first cover shown onto the third: after it, as shown.
        self.assertTrue(self._drop([0], 2))
        self.assertEqual('4312', self._shown())
        self.assertEqual('2134', self._kept())

    def test_under_a_filter_the_books_hidden_keep_their_places(self):
        os.rename(self.paths['2.zip'],
                  os.path.join(self.tmp_dir, '2 other.zip'))
        self.backend.update_book_path(
            self.paths['2.zip'], os.path.join(self.tmp_dir, '2 other.zip'))
        self.dialog.filter_string = 'other'
        self._show(self.list)
        self.assertEqual('2', self._shown())
        self.dialog.filter_string = None
        self._show(self.list)
        self._drop([3], 0)
        self.assertEqual('4123', self._shown())
        self.dialog.filter_string = '.zip'
        self._show(self.list)
        hidden = self.backend.get_book_by_path(
            os.path.join(self.tmp_dir, '2 other.zip')).id
        self.area.remove_books([hidden])
        self.assertEqual('413', self._shown())
        # Onto the last cover shown; the hidden book stays between.
        self.assertTrue(self._drop([0], 2))
        self.assertEqual('1234', self._kept())

    def test_nothing_moves_under_another_sort(self):
        prefs['lib sort key'] = constants.SORT_NAME
        self.area.set_sort_order()
        self.assertFalse(self._drop([0], 2))
        self.assertEqual('1234', self._shown())
        self.assertEqual({}, self.backend.get_book_positions(self.list))

    def test_all_books_keep_no_order(self):
        self._show(constants.COLLECTION_ALL)
        self.assertEqual('1234', self._shown())
        self.assertFalse(self._drop([0], 2))
        self.assertEqual('1234', self._shown())
        self.assertEqual(
            [], self.backend.fetchall(
                'select book from Contain where position is not null'))

    def test_what_is_dropped_has_to_be_books(self):
        for value in ('collection:1', 'books:x', 'file:///tmp/1.zip'):
            with self.subTest(value=value), unittest.mock.patch.object(
                    self.area._covers, 'position_at', return_value=2):
                self.assertFalse(
                    self.area._books_dropped(None, value, 5.0, 5.0))
        self.assertEqual('1234', self._shown())

    def test_only_a_drag_from_this_program_is_taken_for_books(self):
        """A file manager offers its files as text as well, and that
        drop belongs to the target that adds them to the library."""
        ours = types.SimpleNamespace(get_drag=lambda: object())
        theirs = types.SimpleNamespace(get_drag=lambda: None)
        self.assertTrue(self.area._accepts_books(None, ours))
        self.assertFalse(self.area._accepts_books(None, theirs))

    def test_a_book_of_a_collection_under_it_follows_and_stays_there(self):
        inner = self.backend.add_collection('Inner')
        self.backend.add_collection_to_collection(inner, self.list)
        path = os.path.join(self.tmp_dir, '0.zip')
        shutil.copyfile(self.paths['1.zip'], path)
        self.backend.add_book(path, inner)
        self._show(self.list)
        # Nothing has a place yet, so every book goes by its path.
        self.assertEqual('01234', self._shown())
        self.assertTrue(self._drop([2], 1))
        self.assertEqual('21340', self._shown())
        self.assertFalse(self._drop([4], 0))
        # Dropped on it, a book of the list goes last among the list's.
        self.assertTrue(self._drop([0], 4))
        self.assertEqual('13420', self._shown())

    def test_alt_and_an_arrow_move_the_selected_cover_one_place(self):
        self.area._covers.select_only(1)
        self.assertEqual(Gdk.EVENT_STOP, self._alt(Gdk.KEY_Right))
        self.assertEqual('1324', self._shown())
        self.assertEqual('2', self._selected())
        self.assertEqual(Gdk.EVENT_STOP, self._alt(Gdk.KEY_Left))
        self.assertEqual(Gdk.EVENT_STOP, self._alt(Gdk.KEY_Left))
        self.assertEqual('2134', self._shown())
        self.assertEqual('2', self._selected())

    def test_the_keypad_arrows_move_it_too(self):
        """ALT+KeyPadLeft and ALT+KeyPadRight turn the page in the
        reader as ALT+Left and ALT+Right do, and moved no cover."""
        self.area._covers.select_only(1)
        self.assertEqual(Gdk.EVENT_STOP, self._alt(Gdk.KEY_KP_Right))
        self.assertEqual('1324', self._shown())
        self.assertEqual(Gdk.EVENT_STOP, self._alt(Gdk.KEY_KP_Left))
        self.assertEqual('1234', self._shown())

    def test_at_either_end_the_arrow_is_left_to_the_view(self):
        self.area._covers.select_only(0)
        self.assertEqual(Gdk.EVENT_PROPAGATE, self._alt(Gdk.KEY_Left))
        self.area._covers.select_only(3)
        self.assertEqual(Gdk.EVENT_PROPAGATE, self._alt(Gdk.KEY_Right))
        self.area._covers.unselect_all()
        self.assertEqual(Gdk.EVENT_PROPAGATE, self._alt(Gdk.KEY_Right))
        self.assertEqual({}, self.backend.get_book_positions(self.list))

    def test_where_rows_start_on_the_right_the_arrows_change_sides(self):
        self.area.set_direction(Gtk.TextDirection.RTL)
        self.area._covers.select_only(1)
        self.assertEqual(Gdk.EVENT_STOP, self._alt(Gdk.KEY_Left))
        self.assertEqual('1324', self._shown())

    def test_an_arrow_alone_moves_nothing(self):
        self.area._covers.select_only(1)
        self.assertEqual(Gdk.EVENT_PROPAGATE, self.area._key_press(
            None, Gdk.KEY_Right, 0, Gdk.ModifierType(0)))
        self.assertEqual('1234', self._shown())

    def test_the_sort_menu_offers_the_order_by_hand(self):
        self._drop([0], 3)
        actions = self.area._popup_actions
        actions.change_action_state(
            'sort-key', GLib.Variant('i', constants.SORT_PATH))
        self.assertEqual('1234', self._shown())
        actions.change_action_state(
            'sort-key', GLib.Variant('i', constants.SORT_HAND))
        self.assertEqual(constants.SORT_HAND, prefs['lib sort key'])
        self.assertEqual('2341', self._shown())

    def test_next_archive_reads_the_list_in_its_order(self):
        self._drop([0], 3)
        self.assertEqual('2341', self._shown())
        handler = self.window.filehandler

        def reading(name):
            return wait_for(
                lambda: handler.file_loaded
                and handler.get_path_to_base() == self.paths[name],
                seconds=20)

        book = self.backend.get_book_by_path(self.paths['4.zip'])
        self.dialog.open_book([book.id])
        self.assertTrue(reading('4.zip'), handler.get_path_to_base())
        self.assertTrue(handler.open_next_archive())
        self.assertTrue(reading('1.zip'), handler.get_path_to_base())
        self.assertFalse(handler.open_next_archive())
        self.assertTrue(handler.open_previous_archive())
        self.assertTrue(reading('4.zip'), handler.get_path_to_base())


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


class ChosenCoverShownTest(_OneBookTest):

    """A cover chosen while the library is open is drawn again there."""

    def test_the_cover_on_show_is_drawn_again(self):
        self.dialog.book_area.stop_update()
        covers = self.dialog.book_area._covers
        with unittest.mock.patch.object(covers, 'redraw_item') as redrawn:
            self.assertTrue(self.dialog.backend.set_chosen_cover(
                self.path, 'images/02.jpg'))
        item, = redrawn.call_args.args
        self.assertEqual(self.path, item.path)

    def test_a_closed_library_draws_nothing(self):
        area = self.dialog.book_area
        self.dialog.close()
        pump()
        with unittest.mock.patch.object(area, '_each_item') as looked:
            main_dialog.library_backend.LibraryBackend().set_chosen_cover(
                self.path, None)
        looked.assert_not_called()


class MissingBooksTest(_LibraryWindowTest):

    """Books whose files have gone can be taken out of the library from
    the covers' own menu, not only from the collections' menu beside
    them."""

    def test_clean_up_in_the_covers_menu_takes_out_the_books_gone(self):
        dialog, path = self._one_gone_from_all()
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

    def test_a_book_gone_says_so_when_opened(self):
        """A book whose file was moved or deleted outside MComix stays
        in the library until it is cleaned up.  Opened, it says that its
        file is not there, rather than showing nothing."""
        dialog = self._open()
        path = os.path.join(self.tmp_dir, 'gone.cbz')
        shutil.copy(NORMAL_ZIP, path)
        dialog.backend.add_book(path)
        os.remove(path)
        book = dialog.backend.get_book_by_path(path)
        with unittest.mock.patch.object(self.window.osd, 'show') as shown:
            dialog.open_book([book.id])
            pump()
        message = 'Could not open %s: No such file.' % path
        self.assertEqual([unittest.mock.call(message)], shown.call_args_list)
        self.assertFalse(self.window.filehandler.file_loaded)


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
        return pixel(cover, cover.get_width() - 12,
                     cover.get_height() - 12)[:3]

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
        white = solid_pixbuf(16, 16, 0xFFFFFFFF, has_alpha=True)
        with unittest.mock.patch.object(icons, 'load_pixbuf',
                                        return_value=white):
            mark = self.dialog.book_area._finished_mark

        self.assertLess(max(pixel(mark, 12, 12)[:3]), 64, 'the tick is not dark')
        self.assertGreater(min(pixel(mark, 2, 12)[:3]), 200,
                           'the disc is not light')
        self.assertGreater(pixel(mark, 2, 12)[3], 200, 'the disc is not opaque')
        self.assertEqual(0, pixel(mark, 0, 0)[3], 'the mark is not round')

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

    def test_several_books_selected_are_summed_up(self):
        """Not the first of them alone, as if it were all there was."""
        other = os.path.join(self.tmp_dir, 'Other.cbz')
        shutil.copy(self.path, other)
        self.dialog.backend.add_book(other)
        self.dialog.book_area.display_covers(constants.COLLECTION_ALL)
        pump()
        self._left_on(4)
        covers = self.dialog.book_area._covers
        covers.selection.select_all()
        pump()
        info = self.dialog.control_area
        self.assertEqual('2 books', info._namelabel.get_text())
        self.assertEqual('8 pages, %s' % tools.format_byte_size(
            2 * os.path.getsize(self.path)), info._filelabel.get_text())
        self.assertEqual('Started: 0, finished: 1', info._dirlabel.get_text())
        self.assertTrue(info._open_button.get_sensitive())

    def test_selecting_nothing_tells_what_was_read_of_the_books_shown(self):
        """Upstream feature request 46: with no book selected, the box
        speaks for the books on show rather than standing empty."""
        info = self._select()
        self.dialog.book_area._covers.unselect_all()
        pump()
        self.assertEqual('1 book', info._namelabel.get_text())
        self.assertEqual('Started: 0, finished: 0', info._filelabel.get_text())
        self.assertEqual('Pages read: 0', info._dirlabel.get_text())
        self.assertFalse(info._open_button.get_sensitive())

    def test_a_book_left_part_read_counts_as_started_with_its_pages(self):
        self._left_on(3)
        info = self.dialog.control_area
        self.dialog.book_area._covers.unselect_all()
        info.update_info([])
        self.assertEqual('Started: 1, finished: 0', info._filelabel.get_text())
        self.assertTrue(info._dirlabel.get_text().startswith(
            'Pages read: 3, last read on '), info._dirlabel.get_text())

    def test_only_the_books_asked_about_are_counted(self):
        """The recent table holds every book read; the box speaks for
        the ones on show, which a search or a collection narrows."""
        self._left_on(3)
        stats = self.dialog.backend.reading_statistics([])
        self.assertEqual((0, 0, 0, 0, None), tuple(stats))

    def test_a_book_read_to_its_last_page_counts_as_finished(self):
        """And no longer as started: the two numbers are those of the
        books the choice beside the search field shows as Started and
        as Finished, where a finished book used to count in both."""
        self._left_on(4)
        info = self.dialog.control_area
        info.update_info([])
        self.assertEqual('Started: 0, finished: 1', info._filelabel.get_text())
        states = backend_types.ReadState
        for state, books in ((states.STARTED, 0), (states.FINISHED, 1)):
            self.assertEqual(books, len(
                backend_types.DefaultCollection.get_books(None, state)))
        self.assertTrue(info._dirlabel.get_text().startswith('Pages read: 4,'))


class OpenFromLibraryTest(_LibraryWindowTest):

    """Opening a book from the library while its covers are drawn."""

    def _open_while_drawing(self, open_it):
        """Open the one book by <open_it>(book area) while its cover is
        still being drawn, then show the library again.

        Opening a book stopped the worker that draws the covers - a
        guard against a hang at exit that closing the library now sees
        to - so every cover still to be drawn stayed blank for good once
        the library was shown again."""
        dialog = self._open_all()
        path = NORMAL_ZIP
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
        self._covers_drawn(dialog)

    def test_a_cover_double_clicked_while_drawing(self):
        self._open_while_drawing(
            lambda area: area._book_activated(area._covers, 0))

    def test_open_from_the_menu_while_drawing(self):
        def open_selected(area):
            area._covers.select_only(0)
            area.open_selected_book()

        self._open_while_drawing(open_selected)


class OpenAsByHandTest(_OneBookTest):

    """CTRL+Enter opens a book as one opened by hand is opened."""

    def _open_with(self, state):
        area = self.dialog.book_area
        area._covers.select_only(0)
        pump()
        handler = self.dialog.main_window.filehandler
        with unittest.mock.patch.object(handler, 'open_file') as open_file:
            stopped = area._key_press(None, Gdk.KEY_Return, 0, state)
        self.assertTrue(stopped)
        open_file.assert_called_once()
        self.assertEqual((self.path,), open_file.call_args.args)
        return open_file.call_args.kwargs.get('listed')

    def test_ctrl_enter_leaves_the_neighbours_to_its_folder(self):
        # Without the covers shown, Next and Previous book walk the
        # book's folder in natural order.
        self.assertIsNone(self._open_with(Gdk.ModifierType.CONTROL_MASK))
        self.assertFalse(self.dialog.get_visible())

    def test_enter_still_opens_it_among_the_covers_shown(self):
        area = self.dialog.book_area
        area._covers.select_only(0)
        pump()
        handler = self.dialog.main_window.filehandler
        with unittest.mock.patch.object(handler, 'open_file') as open_file:
            area._book_activated(area._covers, 0)
        self.assertEqual([self.path], open_file.call_args.kwargs['listed'])


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


class CoverScaleTest(_OneBookTest):

    """Covers on a screen with more pixels than the window: made with
    the screen's and drawn at the window's size, as the pages are."""

    def _cover_at(self, scale):
        area = self.dialog.book_area
        with unittest.mock.patch.object(type(area), '_device_scale',
                                        return_value=scale):
            area.load_covers()
            pump()
            item = area._covers.get_item(0)
            self.assertIsNotNone(item)
            self.assertTrue(wait_for(lambda: item.thumbnail is not None
                                     and item.scale == scale, seconds=20))
        return area, item

    def test_at_twice_the_pixels_a_cover_has_twice_as_many(self):
        area, item = self._cover_at(1.0)
        width, height = (item.thumbnail.get_width(),
                         item.thumbnail.get_height())
        self.assertIs(item.thumbnail, thumbnail_list._shown(item))
        area, item = self._cover_at(2.0)
        texture = item.thumbnail
        # Twice the cover, give or take the rounding of each side, with
        # a border of two of the screen's pixels where there was one.
        self.assertAlmostEqual(2 * width, texture.get_width(), delta=2)
        self.assertAlmostEqual(2 * height, texture.get_height(), delta=2)
        shown = thumbnail_list._shown(item)
        self.assertEqual((round(texture.get_width() / 2),
                          round(texture.get_height() / 2)),
                         (shown.get_intrinsic_width(),
                          shown.get_intrinsic_height()))

    def test_a_change_of_the_surface_s_scale_makes_the_covers_again(self):
        area = self.dialog.book_area
        surface = area.get_native().get_surface()
        with unittest.mock.patch.object(area, 'load_covers') as made:
            surface.notify('scale')
        made.assert_called_once_with()

    def test_the_tick_of_a_finished_book_grows_with_the_scale(self):
        area = self.dialog.book_area
        self.assertEqual(24, area._finished_mark_at(1).get_width())
        self.assertEqual(48, area._finished_mark_at(2.0).get_width())
        self.assertIs(area._finished_mark_at(2.0), area._finished_mark_at(2.0))


class MenuHeadingTest(_OneBookTest):

    """The two menus' headings were items bound to an action that is
    never enabled, from when GTK 3 drew a section's label as a bare
    separator; a GTK 4 popover draws it as a title."""

    def _heading(self, menu):
        model = menu.get_menu_model()
        label = model.get_item_attribute_value(0, 'label', None)
        return label.get_string() if label is not None else None

    def test_each_menu_is_headed_by_its_first_section_s_label(self):
        self.assertEqual('Library books',
                         self._heading(self.dialog.book_area._book_menu))
        self.assertEqual('Library collections', self._heading(
            self.dialog.collection_area._collection_menu))

    def test_there_is_no_dead_item_to_stand_for_it(self):
        self.assertIsNone(self.dialog.book_area._popup_actions
                          .lookup_action('title'))
        self.assertIsNone(self.dialog.collection_area._popup_actions
                          .lookup_action('title'))


class ShowInFolderTest(_OneBookTest):

    """"Open containing folder" in the menu over the covers, which the
    main window had and the library did not."""

    def test_it_shows_the_selected_book_over_the_library(self):
        area = self.dialog.book_area
        area._covers.select_only(0)
        pump()
        with unittest.mock.patch.object(
                file_actions.Gtk, 'FileLauncher') as launcher:
            area._popup_actions.activate_action('open-containing-folder',
                                                None)
        given = launcher.new.call_args.args[0]
        self.assertEqual(self.path, given.get_path())
        opened = launcher.new.return_value.open_containing_folder
        self.assertIs(self.dialog, opened.call_args.args[0])

    def test_it_is_offered_for_one_book_alone(self):
        area = self.dialog.book_area
        actions = area._popup_actions
        area._covers.unselect_all()
        pump()
        with unittest.mock.patch.object(widgets, 'popup_at'):
            area._popup_book_menu()
        self.assertFalse(actions.lookup_action(
            'open-containing-folder').get_enabled())
        area._covers.select_only(0)
        pump()
        with unittest.mock.patch.object(widgets, 'popup_at'):
            area._popup_book_menu()
        self.assertTrue(actions.lookup_action(
            'open-containing-folder').get_enabled())


class OpenWithTest(_OneBookTest):

    """"Open with" in the menu over the covers, which the main window had
    and the library did not."""

    COMMANDS = [('View', 'viewer %A', '', False),
                ('-', '', '', False),
                ('Edit page', 'editor %F', '', False),
                ('Off in archives', 'other %A', '', True)]

    def setUp(self):
        super().setUp()
        patcher = unittest.mock.patch.object(openwith.process, 'popen')
        self.popen = patcher.start()
        self.addCleanup(patcher.stop)
        platform = unittest.mock.patch.object(openwith.sys, 'platform', 'linux')
        platform.start()
        self.addCleanup(platform.stop)
        prefs['openwith commands'] = self.COMMANDS
        self.area = self.dialog.book_area

    def _popup(self):
        with unittest.mock.patch.object(widgets, 'popup_at'):
            self.area._popup_book_menu()

    def _submenu(self):
        """The submenu's sections, each the labels and actions of its
        entries; None without a submenu."""
        section = self.area._open_with_section
        if not section.get_n_items():
            return None
        submenu = section.get_item_link(0, Gio.MENU_LINK_SUBMENU)
        found = []
        for index in range(submenu.get_n_items()):
            entries = submenu.get_item_link(index, Gio.MENU_LINK_SECTION)
            found.append([
                (entries.get_item_attribute_value(
                    position, Gio.MENU_ATTRIBUTE_LABEL).get_string(),
                 entries.get_item_attribute_value(
                     position, Gio.MENU_ATTRIBUTE_ACTION).get_string())
                for position in range(entries.get_n_items())])
        return found

    def _enabled(self, name):
        return self.area._popup_actions.lookup_action(name).get_enabled()

    def test_the_menu_lists_the_commands_in_their_sections(self):
        self.area._covers.select_only(0)
        pump()
        self._popup()
        self.assertEqual(
            [[('View', 'books.open-with-0')],
             [('Edit page', 'books.open-with-2'),
              ('Off in archives', 'books.open-with-3')]],
            self._submenu())

    def test_only_a_command_that_can_run_on_a_book_can_be_chosen(self):
        self.area._covers.select_only(0)
        pump()
        self._popup()
        self.assertTrue(self._enabled('open-with-0'))
        self.assertFalse(self._enabled('open-with-2'))
        self.assertFalse(self._enabled('open-with-3'))

    def test_with_no_book_selected_none_can_be_chosen(self):
        self.area._covers.unselect_all()
        pump()
        self._popup()
        self.assertFalse(self._enabled('open-with-0'))

    def test_with_no_commands_set_up_there_is_no_submenu(self):
        for commands in ([], [('-', '', '', False)]):
            with self.subTest(commands=commands):
                prefs['openwith commands'] = commands
                self._popup()
                self.assertIsNone(self._submenu())

    def test_a_command_edited_since_is_what_the_menu_offers(self):
        self.area._covers.select_only(0)
        pump()
        self._popup()
        prefs['openwith commands'] = [('New', 'new %A', '', False)]
        self._popup()
        self.assertEqual([[('New', 'books.open-with-0')]], self._submenu())
        self.assertIsNone(
            self.area._popup_actions.lookup_action('open-with-3'))
        self.area._popup_actions.activate_action('open-with-0', None)
        self.assertEqual(['new', self.path], self.popen.call_args.args[0])

    def test_it_runs_once_for_each_book_selected(self):
        other = get_testfile_path('archives', '02-TAR-Normal.tar')
        self.dialog.backend.add_book(other)
        self.area.display_covers(constants.COLLECTION_ALL)
        pump()
        self.area._covers.select_all()
        pump()
        self._popup()
        self.area._popup_actions.activate_action('open-with-0', None)
        self.assertCountEqual(
            [['viewer', self.path], ['viewer', other]],
            [call.args[0] for call in self.popen.call_args_list])

    def test_what_goes_wrong_is_said_in_the_status_bar(self):
        self.popen.side_effect = OSError('no such program')
        self.area._covers.select_only(0)
        pump()
        self._popup()
        self.area._popup_actions.activate_action('open-with-0', None)
        self.assertIn('no such program', self.dialog._statusbar.get_text())


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
        self.path = NORMAL_ZIP

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
        comics = self._open_all().backend.add_collection('Comics')
        dialog = self._showing(comics)
        self._drop(dialog)
        book = dialog.backend.get_book_by_path(self.path)
        self.assertEqual([(comics, book.id)], self._filed(dialog))

    def test_a_watched_directory_with_no_collection_files_in_none(self):
        comics = self._open_all().backend.add_collection('Comics')
        dialog = self._showing(comics)
        entry = types.SimpleNamespace(
            collection=backend_types.DefaultCollection, directory='/comics',
            recursive=False)
        dialog._new_files_found([self.path], entry)
        self._wait_for_book(dialog)
        self.assertEqual([], self._filed(dialog))

    def test_a_collection_a_scan_filed_books_in_still_shows_them(self):
        # add_books() made the collection the books went into the "last
        # library collection" while another stayed on show, and picking
        # that collection then did nothing: it was already the last one.
        backend = self._open_all().backend
        comics = backend.add_collection('Comics')
        manga = backend.add_collection('Manga')
        dialog = self._showing(comics)
        entry = types.SimpleNamespace(
            collection=backend.get_collection_by_id(manga),
            directory='/manga', recursive=False)
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
            backend = unittest.mock.Mock()

            def add_books(self, paths, collection):
                return len(paths), []

            def set_status_message(self, message):
                self.message = message

            def _follow_and_remove(self, filelist, entry):
                return filelist, 0

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
        prompts = visible_prompts()
        self.assertEqual(1, len(prompts))
        entry = self._entry_in(prompts[0])
        entry.set_text(name)
        prompts[0].response(response)
        pump()
        return dialog

    @staticmethod
    def _entry_in(widget):
        for entry in (widget, *descendants(widget)):
            if isinstance(entry, Gtk.Entry):
                return entry
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
        dialog, path = self._one_gone_from_all()
        dialog.collection_area._clean_collection()
        pump()
        self.assertIsNone(dialog.backend.get_book_by_path(path))

    def test_clean_up_keeps_the_books_of_a_drive_not_connected_and_says_so(
            self):
        dialog = self._open_all()
        folder = os.path.join(self.tmp_dir, 'drive')
        os.mkdir(folder)
        self.enterContext(mounted_at(folder))
        path = os.path.join(folder, 'away.cbz')
        shutil.copy(NORMAL_ZIP, path)
        self._held(dialog, path)
        # The drive taken away: its folder goes with it.
        shutil.rmtree(folder)
        dialog.collection_area._clean_collection()
        pump()
        self.assertIsNotNone(dialog.backend.get_book_by_path(path))
        self.assertEqual(
            'Removed 0 books from the library. Kept 1 book whose folder'
            ' is not there, as on a drive not connected.',
            dialog._statusbar.get_tooltip_text())

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

    def test_a_collection_name_is_shown_as_typed_whatever_it_holds(self):
        # The tree's names are Pango markup: one that holds markup's own
        # characters is escaped, and must read back as it was typed.
        dialog = self._open()
        name = 'Tom & "Jerry" <1>\'s'
        dialog.backend.add_collection(name)
        dialog.collection_area.display_collections()
        rows = [row for row in dialog.collection_area._list.each_row()
                if row.collection == self._id(dialog, name)]
        self.assertEqual(name, Pango.parse_markup(rows[0].name, -1, '\0')[2])

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


class RelocateBooksTest(_LibraryWindowTest):

    """"Relocate..." in the collections' menu: a folder of books moved
    or renamed outside MComix left every one of them in the library
    with no file, and nothing but removing and adding them again, less
    their collections and the pages they were read to, brought them
    back (upstream feature requests 122, 56 and 102)."""

    def setUp(self):
        super().setUp()
        self.dialog = self._open_all()
        # The covers are drawn here, on this thread: a worker still
        # drawing one would be reading a file the test is moving.
        self.dialog.book_area.stop_update()
        self.old = os.path.join(self.tmp_dir, 'shelf')
        self.new = os.path.join(self.tmp_dir, 'elsewhere', 'comics')
        self.names = [('a.cbz',), ('sub', 'b.cbz')]
        for name in self.names:
            book = os.path.join(self.old, *name)
            os.makedirs(os.path.dirname(book), exist_ok=True)
            shutil.copy2(NORMAL_ZIP, book)
            self.dialog.backend.add_book(book)
            self.assertIsNotNone(self.dialog.backend.get_book_thumbnail(book))
        self.dialog.book_area.stop_update()
        self.covers = self.dialog.backend._covers()

    def _books(self, folder):
        return [os.path.join(folder, *name) for name in self.names]

    def _move(self):
        os.makedirs(os.path.dirname(self.new))
        os.rename(self.old, self.new)

    def _ask(self):
        widgets.simple_action(self.dialog.collection_area._popup_actions,
                              'relocate').activate(None)
        pump()
        prompts = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, relocate_dialog.RelocateDialog)
                   and window.get_visible()]
        self.assertEqual(1, len(prompts))
        self.addCleanup(self._dismiss, prompts[0])
        return prompts[0]

    @staticmethod
    def _dismiss(prompt):
        if prompt.get_visible():
            prompt.response(Response.CANCEL)
            pump()

    @staticmethod
    def _offers_ok(prompt):
        return prompt.get_widget_for_response(Response.OK).get_sensitive()

    def test_it_is_offered_over_every_row_and_over_none(self):
        area = self.dialog.collection_area
        for collection in (None, constants.COLLECTION_ALL,
                           constants.COLLECTION_RECENT):
            area._popup_collection_menu(collection)
            self.assertTrue(widgets.simple_action(
                area._popup_actions, 'relocate').get_enabled(), collection)
            area._collection_menu.popdown()
        pump()

    def test_the_folder_that_has_gone_is_offered_as_the_old_one(self):
        self._move()
        prompt = self._ask()
        self.assertEqual(self.old, prompt._old.get_text())
        self.assertEqual('', prompt._new.get_text())
        self.assertFalse(self._offers_ok(prompt))

    def test_no_folder_is_offered_while_no_book_is_gone(self):
        self.assertEqual('', self._ask()._old.get_text())

    def test_no_folder_is_offered_that_still_holds_a_book(self):
        """Relocating takes every book under the folder with it, the
        ones whose files are there as well."""
        os.remove(self._books(self.old)[0])
        self.assertEqual('', self._ask()._old.get_text())

    def test_ok_follows_everything_that_names_the_books(self):
        backend = self.dialog.backend
        old_a, old_b = self._books(self.old)
        new_a, new_b = self._books(self.new)
        book = backend.get_book_by_path(old_a)
        backend.add_collection('Shelf')
        shelf = backend.get_collection_by_name('Shelf').id
        backend.add_book_to_collection(book.id, shelf)
        store = bookmark_backend.BookmarksStore
        store.add_bookmark(bookmark_menu_item._Bookmark(
            self.window, self.window.filehandler, 'b.cbz', old_b, 2, 4,
            None, datetime.datetime(2026, 1, 1)))
        page_marks.mark(old_a, 'p02.jpg', page_marks.SKIP, True)
        page_rotations.remember(old_b, 'p03.jpg', 90)
        reading_directions.remember(old_b, True)
        self._move()

        prompt = self._ask()
        prompt._new.set_text('  %s ' % self.new)
        self.assertTrue(self._offers_ok(prompt))
        prompt.response(Response.OK)

        self.assertFalse(prompt.get_visible())
        self.assertIsNone(backend.get_book_by_path(old_a))
        self.assertEqual(book.id, backend.get_book_by_path(new_a).id)
        self.assertIsNotNone(backend.get_book_by_path(new_b))
        self.assertEqual([book.id], backend.get_books_in_collection(shelf))
        self.assertIn('Books relocated: 2', self.dialog._statusbar.get_text())
        self.assertEqual([new_b],
                         [bookmark._path for bookmark in store.get_bookmarks()])
        self.assertTrue(page_marks.marked(new_a, 'p02.jpg', page_marks.SKIP))
        self.assertEqual(90, page_rotations.rotation(new_b, 'p03.jpg'))
        self.assertIs(True, reading_directions.direction(new_b))
        self.assertIsNone(reading_directions.direction(old_b))
        for path in (new_a, new_b):
            self.assertTrue(os.path.isfile(
                self.covers._path_to_thumbpath(path)), path)
        self.assertEqual(2, len(os.listdir(constants.LIBRARY_COVERS_PATH)))

        # And the covers are drawn again, of the books where they are.
        self.assertTrue(wait_for(
            lambda: sorted(self.dialog.book_area.shown_paths())
            == [new_a, new_b]))
        self.dialog.book_area.stop_update()

    def test_cancel_follows_nothing(self):
        self._move()
        prompt = self._ask()
        prompt._new.set_text(self.new)
        prompt.response(Response.CANCEL)
        pump()
        for path in self._books(self.old):
            self.assertIsNotNone(self.dialog.backend.get_book_by_path(path))

    def test_ok_wants_two_folders_and_the_new_one_there(self):
        self._move()
        prompt = self._ask()
        for old, new, offered in (
                (self.old, self.new, True),
                (self.old, os.path.join(self.new, 'a.cbz'), False),
                (self.old, os.path.join(self.tmp_dir, 'nowhere'), False),
                (self.old, '', False), ('', self.new, False),
                ('shelf', self.new, False),
                (self.new + os.sep, self.new, False)):
            prompt._old.set_text(old)
            prompt._new.set_text(new)
            self.assertEqual(offered, self._offers_ok(prompt), (old, new))

    def test_a_folder_named_from_the_home_directory_is_read_as_one(self):
        prompt = self._ask()
        prompt._old.set_text('~/shelf')
        # Normalised, as relocate() reads it: on Windows the home
        # directory comes with backslashes and the rest as typed.
        self.assertEqual(os.path.join(os.path.expanduser('~'), 'shelf'),
                         os.path.normpath(prompt.folders()[0]))

    def test_a_folder_chosen_is_written_as_the_new_one(self):
        self._move()
        prompt = self._ask()
        prompt._folder_chosen(FolderDialogStub(self.new), None)
        self.assertEqual(self.new, prompt._new.get_text())
        self.assertTrue(self._offers_ok(prompt))

    def test_a_dismissed_chooser_leaves_what_was_typed(self):
        prompt = self._ask()
        prompt._new.set_text('typed')
        prompt._folder_chosen(FolderDialogStub(None), None)
        self.assertEqual('typed', prompt._new.get_text())

    def test_the_chooser_opens_over_the_question_at_the_folder_typed(self):
        self._move()
        prompt = self._ask()
        prompt._new.set_text(self.new)
        with unittest.mock.patch.object(Gtk, 'FileDialog') as chooser:
            prompt._browse()
        chooser.return_value.select_folder.assert_called_once_with(
            prompt, None, prompt._folder_chosen)
        shown, = chooser.return_value.set_initial_folder.call_args.args
        self.assertEqual(self.new, shown.get_path())


class StorePagesAsWebpTest(_LibraryWindowTest):

    """"Make pages smaller without loss..." on the books selected, from the
    question it asks to the summary it ends with."""

    def setUp(self):
        super().setUp()
        self.dialog = self._open_all()
        self.book = os.path.join(self.tmp_dir, 'drawn.cbz')
        with zipfile.ZipFile(self.book, 'w') as book:
            book.writestr('01.png', line_art_png())
            book.writestr('02.png', line_art_png(size=(200, 300)))

    def _store(self, *paths, response=Response.OK, done=True, damaged=None):
        """Hold <paths> in the library, select every cover, give the
        command and answer its question with <response>, its check
        button for books with damaged files set to <damaged> where that
        is not None; answer with the progress dialog, once it is <done>
        where that is True, or None where there is none."""
        self._held(self.dialog, *paths)
        self.dialog.book_area._covers.select_all()
        self.dialog.book_area.store_pages_as_webp()
        pump()
        prompt, = visible_prompts()
        check, = [widget for widget in descendants(prompt)
                  if isinstance(widget, Gtk.CheckButton)
                  and widget.get_visible()]
        self.assertFalse(check.get_active() and damaged is None,
                         'books with damaged files are written unasked')
        if damaged is not None:
            check.set_active(damaged)
        prompt.response(response)
        pump()
        progress = [window for window in Gtk.Window.list_toplevels()
                    if isinstance(window, webp_dialog._ProgressDialog)]
        if not progress:
            return None
        self.addCleanup(progress[0].destroy)
        if not done:
            return progress[0]
        self.assertTrue(wait_for(
            lambda: progress[0].finished, seconds=20))
        return progress[0]

    @staticmethod
    def _names(path):
        with zipfile.ZipFile(path) as book:
            return sorted(book.namelist())

    def test_books_with_damaged_files_are_written_only_when_asked(self):
        """Unticked, the check leaves them alone; ticked, it is kept
        for the next time."""
        asked = []

        def convert(path, stop, progress, shrink=None, repack=False,
                    without_damaged=False):
            asked.append(without_damaged)
            raise webp_books.Skipped('looked at')

        with unittest.mock.patch.object(webp_dialog.webp_books, 'convert',
                                        convert):
            self._store(self.book).destroy()
            self._store(self.book, damaged=True).destroy()
            self.assertTrue(prefs['write without damaged files'])
            self._store(self.book, damaged=False).destroy()
        self.assertEqual([False, True, False], asked)
        self.assertFalse(prefs['write without damaged files'])

    def test_the_pages_are_stored_as_webp(self):
        progress = self._store(self.book)
        self.assertEqual(['01.webp', '02.webp'], self._names(self.book))
        self.assertTrue(progress._status.get_text().startswith(
            '1 book stored with WebP pages'))
        stored = self.dialog.backend.get_book_by_path(self.book)
        self.assertEqual(os.path.getsize(self.book), stored.size)

    def test_what_is_kept_by_a_page_name_follows_it(self):
        """A page in a folder of the archive too, whose name is kept
        with "/" on Windows as well."""
        with zipfile.ZipFile(self.book, 'w') as book:
            book.writestr('01.png', line_art_png())
            book.writestr('art/02.png', line_art_png(size=(200, 300)))
        self._held(self.dialog, self.book)
        backend = self.dialog.backend
        backend.set_chosen_cover(self.book, 'art/02.png')
        backend.get_book_by_path(self.book).set_last_read_page(
            2, member='art/02.png')
        self._store(self.book)
        self.assertEqual('art/02.webp', backend.get_chosen_cover(self.book))
        self.assertEqual('art/02.webp', backend.get_book_by_path(
            self.book).get_last_read_member())

    def _repack(self, path, mode='w', members=None):
        """A tar at <path>, written with <mode>, of <members> or of two
        PNG pages, put in the library and repacked as a ZIP; answer
        with the progress dialog once it is done."""
        if members is None:
            members = {'01.png': line_art_png(),
                       '02.png': line_art_png(size=(200, 300))}
        with tarfile.open(path, mode) as book:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                book.addfile(info, io.BytesIO(data))
        self._held(self.dialog, path)
        self.dialog.backend.set_chosen_cover(path, sorted(members)[-1])
        self.dialog.book_area._covers.select_all()
        self.dialog.book_area.repack_as_zip()
        pump()
        prompt, = visible_prompts()
        return self._written(prompt)

    def test_a_tar_repacked_as_a_zip_keeps_its_library_book(self):
        """"Repack as ZIP...": the book takes the ZIP's name, and what the
        library kept by the old one follows it there."""
        tar_book = os.path.join(self.tmp_dir, 'strip.cbt')
        progress = self._repack(tar_book)
        zip_book = os.path.join(self.tmp_dir, 'strip.cbz')
        self.assertFalse(os.path.exists(tar_book))
        self.assertEqual(['01.png', '02.png'], self._names(zip_book))
        self.assertTrue(progress._status.get_text().startswith(
            '1 book repacked as ZIP, '))
        self.assertTrue(progress._status.get_text().split('\n')[0]
                        .endswith(' smaller'))
        backend = self.dialog.backend
        self.assertIsNone(backend.get_book_by_path(tar_book))
        self.assertEqual(os.path.getsize(zip_book),
                         backend.get_book_by_path(zip_book).size)
        self.assertEqual('02.png', backend.get_chosen_cover(zip_book))

    def test_a_book_that_comes_out_larger_is_told_so(self):
        """An xz tar of text packs smaller than a ZIP can."""
        words = [b'%d' % (number * 7919 % 1000) for number in range(40000)]
        progress = self._repack(
            os.path.join(self.tmp_dir, 'notes.tar.xz'), 'w:xz',
            {'01.png': line_art_png(), 'notes.txt': b' '.join(words)})
        line = progress._status.get_text().split('\n')[0]
        self.assertTrue(line.startswith('1 book repacked as ZIP, '), line)
        self.assertTrue(line.endswith(' larger'), line)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp_dir, 'notes.zip')))

    def test_saying_no_writes_nothing(self):
        with open(self.book, 'rb') as book:
            before = book.read()
        self.assertIsNone(self._store(self.book, response=Response.CANCEL))
        with open(self.book, 'rb') as book:
            self.assertEqual(before, book.read())

    def test_the_book_open_in_the_main_window_is_left_alone(self):
        """The main window reads NORMAL_ZIP, which has PNG pages."""
        with open(NORMAL_ZIP, 'rb') as book:
            before = book.read()
        progress = self._store(NORMAL_ZIP, self.book)
        with open(NORMAL_ZIP, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertIn('1 book left as it was: open in the main window',
                      progress._status.get_text())

    def test_a_stop_keeps_the_book_done_and_counts_the_rest(self):
        second = os.path.join(self.tmp_dir, 'second.cbz')
        shutil.copy(self.book, second)
        with open(second, 'rb') as book:
            before = book.read()
        real = webp_books.convert

        def first_then_stop(path, stop, progress, shrink=None, repack=False,
                    without_damaged=False):
            converted = real(path, stop, progress, shrink)
            stop.set()
            return converted
        self.enterContext(unittest.mock.patch.object(
            webp_books, 'convert', first_then_stop))
        progress = self._store(self.book, second)
        done = [path for path in (self.book, second)
                if self._names(path) == ['01.webp', '02.webp']]
        self.assertEqual(1, len(done))
        untouched = second if done == [self.book] else self.book
        with open(untouched, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertIn('Stopped with 1 book not yet looked at',
                      progress._status.get_text())

    def test_closing_the_window_stops_and_shows_the_summary(self):
        started = threading.Event()

        def until_stopped(path, stop, progress, shrink=None, repack=False,
                    without_damaged=False):
            started.set()
            stop.wait(10)
            raise archive_packer.Cancelled()
        self.enterContext(unittest.mock.patch.object(
            webp_books, 'convert', until_stopped))
        second = os.path.join(self.tmp_dir, 'second.cbz')
        shutil.copy(self.book, second)
        progress = self._store(self.book, second, done=False)
        self.assertTrue(started.wait(10))
        progress.close()
        self.assertTrue(wait_for(
            lambda: progress.finished, seconds=10))
        self.assertTrue(progress.get_visible())
        self.assertIn('Stopped with 2 books not yet looked at',
                      progress._status.get_text())

    def _copies(self, count, stem):
        """<count> copies of the book, named <stem> and a number."""
        paths = [os.path.join(self.tmp_dir, '%s %d.cbz' % (stem, number))
                 for number in range(count)]
        for path in paths:
            shutil.copy(self.book, path)
        return paths

    def _failing(self, *failing, left_out=(), damaged=None):
        """convert() failing on <failing>, and answering for <damaged>
        that it left out <left_out>."""
        real = webp_books.convert

        def convert(path, stop, progress, shrink=None, repack=False,
                    without_damaged=False):
            if path in failing:
                raise OSError('the disk went away')
            converted = real(path, stop, progress, shrink)
            if path == damaged:
                return dataclasses.replace(converted,
                                           left_out=dict(left_out))
            return converted
        self.enterContext(unittest.mock.patch.object(
            webp_books, 'convert', convert))

    def test_long_names_and_many_failures_do_not_widen_it(self):
        """The window took the width of the name being written, and the
        summary joined the books that failed into one line: a few long
        names made it wider than the screen, its Close button out of
        reach at the edge."""
        failing = self._copies(12, 'long-name-' + 'x' * 120)
        self._failing(*failing)
        progress = self._store(*failing)
        self.assertTrue(wait_frames(progress))
        self.assertLessEqual(progress.get_width(), webp_dialog._WIDTH)
        self.assertLessEqual(progress.get_height(),
                             webp_dialog._SUMMARY_HEIGHT + 200)
        self.assertEqual(webp_dialog._FAILURES_NAMED,
                         progress._status.get_text().count(
                             'Could not be written: long-name-'))
        # The name of the book being written asks for no more either.
        progress._book.set_text(os.path.basename(failing[0]))
        progress._book.set_visible(True)
        self.assertLessEqual(progress._book.measure(
            Gtk.Orientation.HORIZONTAL, -1)[1], webp_dialog._WIDTH)

    def test_the_log_names_every_book_by_what_became_of_it(self):
        failing, damaged = self._copies(2, 'book')
        self._failing(failing, damaged=damaged,
                      left_out={'02.png': 'Bad CRC-32'})
        progress = self._store(self.book, failing, damaged, NORMAL_ZIP)
        self.assertIn('1 book stored without its damaged files',
                      progress._status.get_text())
        save = progress.get_widget_for_response(webp_dialog._SAVE_LOG)
        self.assertEqual('_Save Log…', save.get_label())
        log_path = os.path.join(self.tmp_dir, 'webp.txt')
        progress.save_log(log_path)
        with open(log_path, encoding='utf-8') as log_file:
            sections = log_file.read().split('\n\n')
        self.assertTrue(sections[0].startswith(
            '2 books stored with WebP pages'))
        # In the order the library holds them.
        self.assertEqual(sorted(['  ' + self.book, '  ' + damaged]),
                         sorted(sections[0].splitlines()[1:]))
        self.assertEqual(['1 book stored without its damaged files',
                          '  ' + damaged, '    - 02.png: Bad CRC-32'],
                         sections[1].splitlines())
        self.assertEqual(['1 book left as it was: open in the main window',
                          '  ' + NORMAL_ZIP], sections[2].splitlines())
        self.assertEqual(['Could not be written: ' + failing,
                          '    the disk went away'],
                         sections[3].splitlines())
        self.assertEqual(4, len(sections))

    def test_the_books_with_errors_can_be_selected(self):
        """A run over a whole library ends with a few books to move or
        remove: those that could not be written, written without their
        damaged files, or not readable at all.  Those left alone for
        want of PNG pages are no fault."""
        failing, damaged, unreadable = self._copies(3, 'book')
        self._failing(failing, damaged=damaged,
                      left_out={'02.png': 'Bad CRC-32'})
        failing_convert = webp_books.convert

        def spoilt(path, stop, progress, shrink=None, repack=False,
                    without_damaged=False):
            # Spoilt once the library holds it, which it would not take.
            if path == unreadable:
                with open(unreadable, 'wb') as book:
                    book.write(b'not an archive at all')
            return failing_convert(path, stop, progress, shrink)
        self.enterContext(unittest.mock.patch.object(
            webp_books, 'convert', spoilt))
        # NORMAL_ZIP is left alone as open in the main window: no fault.
        progress = self._store(self.book, failing, damaged, unreadable,
                               NORMAL_ZIP)
        self.assertEqual(sorted([failing, damaged, unreadable]),
                         sorted(progress.faulty()))
        select = progress.get_widget_for_response(webp_dialog._SELECT)
        self.assertEqual('Select Books with _Errors', select.get_label())
        self.dialog.book_area._covers.unselect_all()
        progress.response(webp_dialog._SELECT)
        pump()
        self.assertFalse(progress.get_visible())
        selected = {item.path for item in
                    self.dialog.book_area._selected_items()}
        self.assertEqual({failing, damaged, unreadable}, selected)

    def test_a_run_without_errors_offers_no_selection(self):
        progress = self._store(self.book)
        self.assertIsNone(
            progress.get_widget_for_response(webp_dialog._SELECT))

# vim: expandtab:sw=4:ts=4
