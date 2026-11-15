"""The library's covers in the main window, while no book is open."""

import gc
import os
import shutil
import weakref

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import keybindings
from mcomix import main
from mcomix.library import backend
from mcomix.library import shelf
from mcomix.preferences import prefs


class ShelfTest(MComixTest):

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

# vim: expandtab:sw=4:ts=4
