"""The library's covers in the main window, while no book is open."""

import os
import shutil
import unittest.mock
import weakref

from gi.repository import Gdk, Gio, Graphene, Gtk

from . import (MainWindowLaterTest, collect_garbage, get_testfile_path, pump,
               wait_for, wait_frames)
from .test_key_press import _Controller, bindings_recorded

from mcomix import constants
from mcomix import keybindings
from mcomix.library import backend
from mcomix.library import shelf
from mcomix.preferences import prefs


class _ShelfWindowTest(MainWindowLaterTest):

    """A main window of its own, with two books to show."""

    def setUp(self):
        super().setUp()
        #: Two books of the reader's own, away from the test files.
        self.books = []
        for name in ('01-ZIP-Normal.zip', '02-TAR-Normal.tar'):
            path = os.path.join(self.tmp_dir, name)
            shutil.copy(get_testfile_path('archives', name), path)
            self.books.append(path)

    def _window(self, open_path=None):
        self.open_main_window(open_path=open_path)
        pump()
        return self.window

    def _shown(self):
        """The Shelf, if the window shows one."""
        found = self.window._shelf
        return found if found is not None and found.get_visible() else None

    def _has_pages(self):
        return self.window.imagehandler.get_number_of_pages() > 0

    def _key(self, keyval, state=Gdk.ModifierType(0)):
        """The keycode of the key that types <keyval> unshifted, and what
        it types with <state> held."""
        display = self.window.get_display()
        found, keys = display.map_keyval(keyval)
        self.assertTrue(found, 'the keymap has no key for %r' % keyval)
        key = min(keys, key=lambda key: (key.group, key.level))
        _ok, typed, _group, _level, _consumed = \
            display.translate_key(key.keycode, state, 0)
        return key.keycode, typed

    def _press(self, keyval, state=Gdk.ModifierType(0)):
        """Press the key that types <keyval> unshifted, with <state> held."""
        keycode, typed = self._key(keyval, state)
        return self.window.event_handler.key_press_event(
            _Controller(), typed, keycode, state)


class ShelfTest(_ShelfWindowTest):

    def test_a_window_without_a_book_shows_every_book(self):
        for path in self.books:
            backend.LibraryBackend().add_book(path)
        self._window()
        found = self._shown()
        self.assertIsInstance(found, shelf.Shelf)
        self.assertEqual(constants.COLLECTION_ALL, found._collection)
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
        self.assertEqual(constants.COLLECTION_RECENT, found._collection)
        self.assertEqual([self.books[1]], found.book_area.shown_paths())

    def test_an_empty_library_says_where_books_come_from(self):
        self._window()
        found = self._shown()
        self.assertIsNotNone(found)
        self.assertTrue(found._empty.get_visible())
        self.assertFalse(found.book_area.get_visible())

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
        controllers = list(area._covers.observe_controllers())
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

    def test_files_dropped_on_the_covers_are_opened(self):
        # GTK hands a drop to a target on the widget under the pointer
        # or on one holding it; the covers lie over the page area, not
        # inside it, so the window's target has to hold them too.
        backend.LibraryBackend().add_book(self.books[0])
        self._window()
        covers = self._shown().book_area._covers
        targets = []
        widget = covers
        while widget is not None:
            targets += [
                controller for controller in widget.observe_controllers()
                if isinstance(controller, Gtk.DropTarget)
                and Gdk.FileList.__gtype__ in controller.get_gtypes()]
            widget = widget.get_parent()
        self.assertEqual(1, len(targets))
        dropped = Gdk.FileList.new_from_array(
            [Gio.File.new_for_path(self.books[1])])
        with unittest.mock.patch.object(
                self.window.filehandler, 'open_file') as opened:
            self.assertTrue(targets[0].emit('drop', dropped, 0, 0))
        opened.assert_called_once_with(self.books[1])

    def test_the_window_is_freed_with_its_covers(self):
        backend.LibraryBackend().add_book(self.books[0])
        window = self._window()
        self.assertIsNotNone(self._shown())
        held = weakref.ref(window)
        del window
        self.close_main_window()
        self.window = None
        collect_garbage()
        self.assertIsNone(held())


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
        self.executed = bindings_recorded(self, self.window)

    def test_the_covers_have_the_keys_that_move_among_them(self):
        self.covers.grab_focus()
        self.assertTrue(wait_for(
            lambda: self.window.get_focus() is not None))
        for keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left,
                       Gdk.KEY_Right, Gdk.KEY_Home, Gdk.KEY_End,
                       Gdk.KEY_Page_Up, Gdk.KEY_Page_Down, Gdk.KEY_Return,
                       Gdk.KEY_KP_Enter, Gdk.KEY_space, Gdk.KEY_KP_Down):
            with self.subTest(key=Gdk.keyval_name(keyval)):
                if self._key(keyval)[1] != keyval:
                    # Windows' keymap has the keypad's 2 type "2", one of
                    # the window's own shortcuts, rather than its Down.
                    self.skipTest('the keymap types %s with this key'
                                  % Gdk.keyval_name(self._key(keyval)[1]))
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


class ShelfDrawnAgainTest(_ShelfWindowTest):

    """A collection drawn again showed every cover in an entry and a
    cell built anew, 44 ms for 400 covers against 3 once the entries
    on show are kept.  What a kept entry shows has to be what a new
    one would."""

    def setUp(self):
        super().setUp()
        library = backend.LibraryBackend()
        for path in self.books:
            library.add_book(path)
        self._window()
        self.area = self._shown().book_area
        self.assertTrue(wait_for(lambda: len(self._entries()) == 2))
        self.assertTrue(wait_for(lambda: all(
            item.thumbnail is not None for item in self._entries())))

    def _entries(self):
        return list(self.area._each_item())

    def _again(self):
        self.area.display_covers(constants.COLLECTION_ALL)
        return self._entries()

    def _cells(self):
        """Each book's cell, by book id."""
        return {cell.list_item.get_item().uid: cell
                for cell in self.area._covers._each_cell()
                if cell.list_item.get_item() is not None}

    def test_the_entries_on_show_are_kept_with_their_cells(self):
        before, cells = self._entries(), self._cells()
        self.assertEqual(2, len(cells))
        after = self._again()
        pump()
        self.assertEqual([id(item) for item in before],
                         [id(item) for item in after])
        self.assertEqual(cells, self._cells())

    def test_none_is_kept_once_the_covers_are_drawn_anew(self):
        before = {id(item) for item in self._entries()}
        self.area.load_covers()
        self.assertTrue(wait_for(lambda: len(self._entries()) == 2
                                 and not before & {id(item) for item in self._entries()}))

    def test_a_book_moved_meanwhile_has_an_entry_of_its_own(self):
        moved = self._entries()[0]
        moved.path += '.old'
        self.assertNotIn(moved, self._again())

    def test_what_is_shown_again_is_shown_from_the_top(self):
        """GTK keeps the place of the first entry: a search cleared,
        which brought back books before it, showed the covers from
        that one on."""
        library = backend.LibraryBackend()
        # The search looks at the path too.  A word the temporary
        # folder's name could hold - 'b0' did, one run in 200 - found
        # the two books of setUp() as well: mkdtemp() names it with
        # letters, digits and underscores, never a dash.
        for index in range(8):
            path = os.path.join(self.tmp_dir, 'b-%02d.zip' % index)
            shutil.copy(self.books[0], path)
            library.add_book(path)
        prefs['library cover size'] = constants.SIZE_HUGE
        shelf = self._shown()
        shelf.filter_string = 'b-0'
        self.area.load_covers()
        adjustment = self.area.get_vadjustment()
        # Two waits, so that a failure says which of them timed out
        # and what it saw (one in a full suite under eight workers).
        self.assertTrue(wait_for(lambda: len(self._entries()) == 8),
                        len(self._entries()))
        self.assertTrue(wait_for(lambda: adjustment.get_upper()
                                 > 2 * adjustment.get_page_size()),
                        (adjustment.get_upper(), adjustment.get_page_size()))
        first = self._entries()[0]
        shelf.filter_string = None
        self._again()
        # GTK scrolls to the entry it keeps its place by at the layout.
        self.assertTrue(wait_frames(self.window))
        self.assertEqual(10, len(self._entries()))
        # Kept, and no longer first.
        self.assertIn(first, self._entries()[1:])
        self.assertEqual(0, adjustment.get_value())

    def test_a_clean_up_that_removes_nothing_does_not_draw_them_again(self):
        """Drawn again, they were shown from the top: the clean-up
        answers how many books it removed and how many it kept, and
        the pair read as true even when both were 0."""
        with unittest.mock.patch.object(self._shown(), 'show_books',
                                        return_value=None) as shown:
            self.area._clean_up()
            pump()
        shown.assert_not_called()

    def test_a_clean_up_takes_out_a_book_whose_file_is_gone(self):
        os.remove(self.books[0])
        self.area._clean_up()
        self.assertTrue(wait_for(lambda: len(self._entries()) == 1))

    def test_nothing_stays_selected(self):
        self.area._covers.select_all()
        self._again()
        self.assertEqual([], self.area._covers.get_selected_positions())

    def test_a_book_read_since_has_its_cover_drawn_again(self):
        """The cover of a book read to the end carries a tick."""
        library = backend.LibraryBackend()
        book = library.get_book_by_path(self.books[0])
        book.set_last_read_page(book.pages)
        drawn = []
        with unittest.mock.patch.object(
                self.area._covers, 'redraw_item', side_effect=drawn.append):
            after = self._again()
        self.assertEqual([book.id], [item.uid for item in drawn])
        self.assertEqual(library.last_read_times()[book.id],
                         next(item.read for item in after
                              if item.uid == book.id))


class ShelfSearchTest(_ShelfWindowTest):

    """There was no way to find a book on the covers the window shows
    while no book is open by its name: the library window searches,
    and every letter typed here is a shortcut.  CTRL+F opens a search
    field over them, which looks among every book."""

    def setUp(self):
        super().setUp()
        library = backend.LibraryBackend()
        for path in self.books:
            library.add_book(path)
        # The zip was read: the shelf shows "Recent", which holds it
        # alone.
        library.add_book_to_collection(
            library.get_book_by_path(self.books[0]).id,
            constants.COLLECTION_RECENT)
        self._window()
        self.shelf = self._shown()
        self.assertEqual([self.books[0]], self.shelf.book_area.shown_paths())
        # The field slides in over a quarter of a second, which the
        # tests that look at it laid out waited out; shown at once, it
        # is where it is when animations are off, as on the Windows
        # runner.
        self.shelf._search_bar.get_first_child().set_transition_duration(0)

    def _search_for(self, text):
        self.shelf._search.set_text(text)
        # At once, rather than once the typing pauses.
        self.shelf._search.emit('activate')

    def _field_has_focus(self):
        return wait_for(self.shelf.search_has_focus)

    def test_ctrl_f_opens_the_search_field_with_the_keyboard(self):
        self.assertFalse(self.shelf._search_bar.get_search_mode())
        self._press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(self.shelf._search_bar.get_search_mode())
        self.assertTrue(self._field_has_focus())

    def _reveal_the_field(self):
        """Open the search field and wait until it is laid out.  Where
        animations are off, as on the Windows runner, the revealer says
        its child is revealed before the child has a size."""
        self.shelf.search()
        revealer = self.shelf._search_bar.get_first_child()
        self.assertTrue(wait_for(revealer.get_child_revealed))
        self.assertTrue(wait_for(lambda: self.shelf._search.get_width() > 0))

    def test_the_field_moves_no_cover(self):
        """It lies over the top of the covers: in a bar of its own above
        them, it pushed every cover down by its height."""
        def top():
            return self.shelf.book_area.compute_bounds(self.window)[1].get_y()
        self.assertTrue(wait_for(lambda: self.shelf.book_area.get_height() > 0))
        before = top()
        self.shelf.search()
        revealer = self.shelf._search_bar.get_first_child()
        self.assertTrue(wait_for(revealer.get_child_revealed))
        # Laid out with the field shown.
        self.assertTrue(wait_frames(self.window))
        self.assertEqual(before, top())

    def test_the_covers_start_at_the_top_and_the_field_is_centred(self):
        """A heading line, "Recent" or "All books", was a bar across the
        top of the window whenever no book was open, and the field sat
        in the corner at its end."""
        self.assertTrue(wait_for(lambda: self.shelf.book_area.get_height() > 0))
        self.assertEqual(
            self.shelf.compute_bounds(self.window)[1].get_y(),
            self.shelf.book_area.compute_bounds(self.window)[1].get_y())
        self._reveal_the_field()
        shelf = self.shelf.compute_bounds(self.window)[1]
        field = self.shelf._search.compute_bounds(self.window)[1]
        middle = field.get_x() + field.get_width() / 2
        self.assertLess(abs(middle - (shelf.get_x() + shelf.get_width() / 2)),
                        # The close button beside the field.
                        40)
        self.assertLess(field.get_y() - shelf.get_y(), 20)

    def test_the_field_is_drawn_solid_over_the_covers(self):
        """libadwaita draws an entry as a tenth of its writing's colour
        over whatever lies behind it: over the shelf, white writing on
        black and on the covers' tops, barely to be read."""
        translucent = Gtk.CssProvider()
        translucent.load_from_string(
            'entry { background-color: alpha(currentColor, 0.1); }')
        display = self.window.get_display()
        Gtk.StyleContext.add_provider_for_display(
            display, translucent, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display,
                        display, translucent)
        self._reveal_the_field()
        field = self.shelf._search
        width, height = field.get_width(), field.get_height()
        snapshot = Gtk.Snapshot()
        Gtk.WidgetPaintable(widget=field).snapshot(snapshot, width, height)
        try:
            node = snapshot.to_node()
        except TypeError:
            # PyGObject 3.46, the oldest MComix runs on, cannot hand a
            # render node to Python ("No means to translate ... for
            # 'GskClipNode'"); the stylesheet is the same under it.
            self.skipTest('PyGObject cannot pass a render node here')
        texture = self.window.get_renderer().render_texture(
            node, Graphene.Rect().init(0, 0, width, height))
        downloader = Gdk.TextureDownloader.new(texture)
        downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
        pixels, stride = downloader.download_bytes()
        # Its middle, among the letters of no text.
        middle = height // 2 * stride + width // 2 * 4
        self.assertEqual(255, pixels.get_data()[middle + 3])

    def test_a_search_looks_among_every_book(self):
        self.shelf.search()
        self._search_for('tar')
        self.assertEqual([self.books[1]], self.shelf.book_area.shown_paths())
        self.assertEqual(constants.COLLECTION_ALL, self.shelf._collection)
        self._search_for('')
        self.assertEqual([self.books[0]], self.shelf.book_area.shown_paths())
        self.assertEqual(constants.COLLECTION_RECENT, self.shelf._collection)

    def test_escape_closes_it_and_shows_the_shelf_as_it_was(self):
        self.shelf.search()
        self.assertTrue(self._field_has_focus())
        self._search_for('tar')
        # What Escape does in a search field.
        self.shelf._search.emit('stop-search')
        self.assertFalse(self.shelf._search_bar.get_search_mode())
        self.assertEqual('', self.shelf._search.get_text())
        self.assertEqual([self.books[0]], self.shelf.book_area.shown_paths())
        self.assertTrue(wait_for(self.window.shelf_has_focus))
        self.assertFalse(self.shelf.search_has_focus())

    def test_letters_typed_into_it_are_not_shortcuts(self):
        executed = []
        manager = keybindings.keybinding_manager(self.window)
        with unittest.mock.patch.object(manager, 'execute',
                                        side_effect=executed.append):
            self.shelf.search()
            self.assertTrue(self._field_has_focus())
            for keyval in (Gdk.KEY_f, Gdk.KEY_space, Gdk.KEY_Escape):
                with self.subTest(key=Gdk.keyval_name(keyval)):
                    self.assertEqual(Gdk.EVENT_PROPAGATE,
                                     self._press(keyval))
            self.assertEqual([], executed)
            # Over the covers, f is the window's again.
            self.shelf.book_area.focus_covers()
            self.assertTrue(wait_for(
                lambda: not self.shelf.search_has_focus()))
            self._press(Gdk.KEY_f)
            self.assertEqual(1, len(executed))

    def test_what_the_field_leaves_is_the_window_s(self):
        """F11 or CTRL+O, which a text field has no use for, come back
        up from it to the Shelf."""
        executed = []
        manager = keybindings.keybinding_manager(self.window)
        with unittest.mock.patch.object(manager, 'execute',
                                        side_effect=executed.append):
            self.shelf.search()
            self.assertTrue(self._field_has_focus())
            self.shelf._key_left_by_search(
                _Controller(), Gdk.KEY_F11,
                self.window.get_display().map_keyval(Gdk.KEY_F11)[1][0].keycode,
                Gdk.ModifierType(0))
            self.assertEqual(1, len(executed))


# vim: expandtab:sw=4:ts=4
