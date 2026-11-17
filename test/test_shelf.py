"""The library's covers in the main window, while no book is open."""

import gc
import os
import shutil
import unittest.mock
import weakref

from gi.repository import Gdk, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for
from .test_key_press import _Controller

from mcomix import constants
from mcomix import icons
from mcomix import keybindings
from mcomix import main
from mcomix.library import backend
from mcomix.library import shelf
from mcomix.preferences import prefs


class _ShelfWindowTest(MComixTest):

    """A main window of its own, with two books to show."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        keybindings._manager = None
        self.window = None
        #: Two books of the reader's own, away from the test files.
        self.books = []
        for name in ('01-ZIP-Normal.zip', '02-TAR-Normal.tar'):
            path = os.path.join(self.tmp_dir, name)
            shutil.copy(get_testfile_path('archives', name), path)
            self.books.append(path)

    def tearDown(self):
        if self.window is not None:
            self.window.terminate_program()
            self.window.destroy()
            main.set_main_window(None)
            self.window = None
            pump()
        super().tearDown()

    def _window(self, open_path=None):
        self.window = main.MainWindow(open_path=open_path)
        main.set_main_window(self.window)
        pump()
        return self.window

    def _shown(self):
        """The Shelf, if the window shows one."""
        found = self.window._shelf
        return found if found is not None and found.get_visible() else None

    def _has_pages(self):
        return self.window.imagehandler.get_number_of_pages() > 0


class ShelfTest(_ShelfWindowTest):

    def test_a_window_without_a_book_shows_every_book(self):
        for path in self.books:
            backend.LibraryBackend().add_book(path)
        self._window()
        found = self._shown()
        self.assertIsInstance(found, shelf.Shelf)
        self.assertEqual('All books', found._heading.get_text())
        self.assertTrue(found.book_area.get_visible())
        self.assertFalse(found._empty.get_visible())
        self.assertCountEqual(self.books, found.book_area.shown_paths())

    def test_the_books_last_read_come_before_every_book(self):
        library = backend.LibraryBackend()
        for path in self.books:
            library.add_book(path)
        library.add_book_to_collection(
            library.get_book_by_path(self.books[1]).id,
            constants.COLLECTION_RECENT)
        self._window()
        found = self._shown()
        self.assertEqual('Recent', found._heading.get_text())
        self.assertEqual([self.books[1]], found.book_area.shown_paths())

    def test_an_empty_library_says_where_books_come_from(self):
        self._window()
        found = self._shown()
        self.assertIsNotNone(found)
        self.assertTrue(found._empty.get_visible())
        self.assertFalse(found.book_area.get_visible())
        self.assertFalse(found._heading.get_visible())

    def test_the_preference_turned_off_shows_nothing(self):
        prefs['show library without book'] = False
        self._window()
        self.assertIsNone(self.window._shelf)

    def test_the_preference_is_followed_at_once(self):
        self._window()
        prefs['show library without book'] = False
        self.window.update_shelf()
        self.assertIsNone(self._shown())
        prefs['show library without book'] = True
        self.window.update_shelf()
        self.assertIsNotNone(self._shown())

    def test_a_window_opened_on_a_book_shows_the_book(self):
        self._window(open_path=self.books[0])
        self.assertTrue(wait_for(self._has_pages, seconds=20))
        pump()
        self.assertIsNone(self._shown())

    def test_a_cover_opens_its_book_and_the_covers_go(self):
        for path in self.books:
            backend.LibraryBackend().add_book(path)
        self._window()
        found = self._shown()
        paths = found.book_area.shown_paths()
        found.book_area._book_activated(found.book_area._covers, 1)
        self.assertTrue(wait_for(self._has_pages, seconds=20))
        pump()
        self.assertEqual(paths[1], self.window.filehandler.get_path_to_base())
        self.assertIsNone(self._shown())

    def test_the_covers_come_back_when_the_book_is_closed(self):
        self._window(open_path=self.books[0])
        self.assertTrue(wait_for(self._has_pages, seconds=20))
        pump()
        self.window.filehandler.close_file()
        self.assertTrue(wait_for(
            lambda: self._shown() is not None, seconds=10))

    def test_moving_to_the_next_book_shows_no_covers_between(self):
        """The book going is closed before the next is listed, and the
        covers came up for that moment: drawn, and taken away again
        once the next book was there."""
        backend.LibraryBackend().add_book(self.books[0])
        self._window(self.books[0])
        self.assertTrue(wait_for(self._has_pages, seconds=10))
        shown = []
        original = shelf.Shelf.show_books

        def show_books(found):
            shown.append(found)
            original(found)
        with unittest.mock.patch.object(shelf.Shelf, 'show_books',
                                        show_books):
            self.assertTrue(self.window.filehandler.open_next_archive())
            self.assertTrue(wait_for(
                lambda: self.window.filehandler.file_loaded
                and self._has_pages(), seconds=10))
            pump()
        self.assertEqual(self.books[1],
                         self.window.filehandler.get_path_to_base())
        self.assertEqual([], shown)
        self.assertIsNone(self._shown())

    def test_a_book_that_fails_to_open_over_another_shows_the_covers(self):
        backend.LibraryBackend().add_book(self.books[1])
        self._window(self.books[0])
        self.assertTrue(wait_for(self._has_pages, seconds=10))
        self.window.filehandler.open_file(
            os.path.join(self.tmp_dir, 'gone.zip'))
        self.assertTrue(wait_for(lambda: self._shown() is not None,
                                 seconds=10))
        self.assertEqual([self.books[1]], self._shown().book_area.shown_paths())

    def test_covers_on_show_are_not_drawn_again(self):
        backend.LibraryBackend().add_book(self.books[0])
        self._window()
        found = self._shown()
        self.assertIsNotNone(found)
        with unittest.mock.patch.object(shelf.Shelf, 'show_books') as again:
            self.window.update_shelf()
        again.assert_not_called()

    def test_nothing_is_dragged_dropped_or_added_here(self):
        backend.LibraryBackend().add_book(self.books[0])
        self._window()
        area = self._shown().book_area
        controllers = [controller for controller
                       in area._covers.observe_controllers()]
        self.assertEqual([], [
            controller for controller in controllers
            if isinstance(controller, (Gtk.DragSource, Gtk.DropTarget))])
        area._covers.get_model().select_item(0, True)
        area._popup_book_menu()
        pump()
        actions = area._popup_actions
        self.assertFalse(actions.lookup_action('add').get_enabled())
        self.assertFalse(
            actions.lookup_action('open-keep-library').get_enabled())
        self.assertTrue(actions.lookup_action('open').get_enabled())

    def test_the_window_is_freed_with_its_covers(self):
        backend.LibraryBackend().add_book(self.books[0])
        window = self._window()
        self.assertIsNotNone(self._shown())
        held = weakref.ref(window)
        del window
        self.tearDown_window_only()
        gc.collect()
        pump()
        gc.collect()
        self.assertIsNone(held())

    def tearDown_window_only(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        self.window = None
        pump()


class ShelfKeysTest(_ShelfWindowTest):

    """Up and Down did nothing on the covers the window shows while no
    book is open, nor did Enter, Space, Home, End or the page keys:
    the window takes every key before anything in it, for its own
    shortcuts, and kept these from the thumbnail bar. The covers in
    the library window had them."""

    def setUp(self):
        super().setUp()
        for path in self.books:
            backend.LibraryBackend().add_book(path)
        self._window()
        self.covers = self._shown().book_area._covers
        self.executed = []
        manager = keybindings.keybinding_manager(self.window)
        patcher = unittest.mock.patch.object(
            manager, 'execute', side_effect=self.executed.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _press(self, keyval, state=Gdk.ModifierType(0)):
        """Press the key that types <keyval> unshifted, with <state> held."""
        display = self.window.get_display()
        found, keys = display.map_keyval(keyval)
        self.assertTrue(found, 'the keymap has no key for %r' % keyval)
        key = min(keys, key=lambda key: (key.group, key.level))
        _ok, typed, _group, _level, _consumed = \
            display.translate_key(key.keycode, state, 0)
        return self.window.event_handler.key_press_event(
            _Controller(), typed, key.keycode, state)

    def test_the_covers_have_the_keys_that_move_among_them(self):
        self.covers.grab_focus()
        self.assertTrue(wait_for(
            lambda: self.window.get_focus() is not None))
        for keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left,
                       Gdk.KEY_Right, Gdk.KEY_Home, Gdk.KEY_End,
                       Gdk.KEY_Page_Up, Gdk.KEY_Page_Down, Gdk.KEY_Return,
                       Gdk.KEY_KP_Enter, Gdk.KEY_space, Gdk.KEY_KP_Down):
            with self.subTest(key=Gdk.keyval_name(keyval)):
                self.assertEqual(Gdk.EVENT_PROPAGATE, self._press(keyval))
                self.assertEqual(
                    Gdk.EVENT_PROPAGATE,
                    self._press(keyval, Gdk.ModifierType.SHIFT_MASK))
        self.assertEqual([], self.executed)

    def test_the_window_s_shortcuts_still_work_there(self):
        self.covers.grab_focus()
        self._press(Gdk.KEY_o, Gdk.ModifierType.CONTROL_MASK)
        self._press(Gdk.KEY_Left, Gdk.ModifierType.ALT_MASK)
        self.assertEqual(2, len(self.executed))

    def test_away_from_the_covers_the_keys_are_the_window_s(self):
        self.window.set_focus(None)
        self.assertEqual(Gdk.EVENT_STOP, self._press(Gdk.KEY_Down))
        self.assertEqual(1, len(self.executed))


# vim: expandtab:sw=4:ts=4
