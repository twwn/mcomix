""" Tests for the bookmarks menu, which is a Gio.Menu model now. """

import datetime
import os
import shutil
import unittest.mock

from gi.repository import Gdk, GLib, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import bookmark_backend
from mcomix import bookmark_menu_item
from mcomix import constants
from mcomix import bookmark_dialog
from mcomix import bookmark_menu
from mcomix import icons
from mcomix import main
from mcomix import message_dialog
from mcomix import process
from mcomix import widgets
from mcomix.dialog import Response
from mcomix.preferences import prefs


class _StubImageHandler:

    page = 3
    path = '/tmp/book.cbz'

    pretty_name = 'book'

    def get_pretty_current_filename(self):
        return self.pretty_name

    def get_real_path(self):
        return self.path

    def get_current_page(self):
        return self.page

    def get_number_of_pages(self):
        return 20

    def get_image_files(self):
        return []


class _StubFileHandler:

    archive_type = None
    base_path = None

    def get_path_to_base(self):
        return self.base_path

    def __init__(self):
        self.opened = []

    def open_file(self, path, page=1):
        self.opened.append((path, page))
        return True


class _StubWindow(Gtk.Window):

    """A real window, so the menu's action group has somewhere to live."""

    def __init__(self):
        super().__init__()
        self.filehandler = _StubFileHandler()
        self.imagehandler = _StubImageHandler()
        self.pages = []
        self.toolbar = Gtk.Box()

    def set_page(self, page):
        self.pages.append(page)


class _StubUI:

    """Stands in for MainUI, which tells the menu the key each keybinding
    action answers to."""

    def __init__(self):
        self.accelerators = {'add_bookmark': '<Control>D',
                             'edit_bookmarks': '<Control>B'}

    def accelerator(self, name):
        return self.accelerators.get(name)


class BookmarksMenuTest(MComixTest):

    def setUp(self):
        super().setUp()
        # The store writes its pickle here as soon as a bookmark is added.
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.window = _StubWindow()
        self.ui = _StubUI()
        self.store = bookmark_backend.BookmarksStore
        self.store._initialized = False
        self.store._bookmarks = []
        self.menu = bookmark_menu.BookmarksMenu(self.ui, self.window)
        # A press left over from another test would be handed to the
        # first activation here that asks.
        widgets.take_middle_click()

    def tearDown(self):
        # Anything left on screen would be answered by the next test that
        # goes looking for a dialog.
        for dialog in self._dialogs():
            dialog.destroy()
        if self.menu._dialog is not None:
            self.menu._dialog.destroy()
        pump()
        super().tearDown()

    def _dialogs(self):
        """The prompts this menu has put on screen.

        They are message_dialog.MessageDialog, which is a Gtk.Window of
        its own making: there has been no Gtk.MessageDialog to look for
        since the dialogs were ported.
        """
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_visible()]

    def test_a_bookmark_in_the_open_file_leaves_the_tool_bar_alone(self):
        """Loading a bookmark that is already the open file only turns the
        page. It used to hide and immediately show the tool bar, which is
        a redraw of nothing that ends with the bar visible - so it came
        back for anyone who had turned it off."""
        self.window.toolbar.set_visible(False)
        self.window.filehandler.archive_type = constants.ZIP
        self.window.filehandler.base_path = _StubImageHandler.path
        bookmark = bookmark_menu_item._Bookmark(
            self.window, self.window.filehandler, 'book',
            _StubImageHandler.path, 3, 20, None, 0)
        bookmark.load()
        self.assertEqual([3], self.window.pages, 'the page was not turned')
        self.assertFalse(self.window.toolbar.get_visible(),
                         'a hidden tool bar came back')

    def _sections(self):
        sections = []
        for index in range(self.menu.model.get_n_items()):
            link = self.menu.model.get_item_link(index, 'section')
            sections.append([link.get_item_attribute_value(inner, 'label').get_string()
                             for inner in range(link.get_n_items())])
        return sections

    def _bookmark(self, page, path=None):
        """Bookmark a page.  A second bookmark on the same file asks the
        user whether to replace the first, so give each its own path
        unless the test is about that."""
        self.window.imagehandler.page = page
        if path is not None:
            self.window.imagehandler.path = path
        self.store.add_current_to_bookmarks()

    # -- A second bookmark in the same book --------------------------------

    def _pages(self):
        return sorted(bookmark._page for bookmark in self.store.get_bookmarks())

    def _bookmark_again(self, page, response):
        """Bookmark <page> in the book bookmarked on page 3, and answer
        the question that asks whether to replace it with <response>."""
        self._bookmark(3)
        self._bookmark(page)
        pump()
        prompts = self._dialogs()
        self.assertEqual(1, len(prompts), 'nothing asked about page 3')
        prompts[0].response(response)
        pump()

    def test_the_same_page_again_is_neither_added_nor_asked_about(self):
        self._bookmark(3)
        self._bookmark(3)
        pump()
        self.assertEqual([], self._dialogs())
        self.assertEqual([3], self._pages())

    def test_yes_replaces_the_bookmarks_already_in_the_book(self):
        self._bookmark_again(5, Response.YES)
        self.assertEqual([5], self._pages())

    def test_no_keeps_them_beside_the_new_one(self):
        self._bookmark_again(5, Response.NO)
        self.assertEqual([3, 5], self._pages())

    def test_cancel_adds_nothing(self):
        self._bookmark_again(5, Response.CANCEL)
        self.assertEqual([3], self._pages())

    def test_a_remembered_yes_replaces_without_asking(self):
        choices = prefs['stored dialog choices']
        key = message_dialog.RememberedDialog.REPLACE_EXISTING_BOOKMARK
        choices[key] = Response.YES
        self.addCleanup(choices.pop, key)
        self._bookmark(3)
        self._bookmark(5)
        pump()
        self.assertEqual([], self._dialogs())
        self.assertEqual([5], self._pages())

    def test_the_fixed_entries_are_always_there(self):
        self.assertEqual(self._sections(),
                         [['Add _Bookmark', '_Edit Bookmarks...',
                           'C_lear bookmarks...']])

    def _clear_action(self):
        return widgets.simple_action(self.menu._actions, 'clear')

    def test_clearing_is_offered_only_when_there_is_something_to_clear(self):
        self.assertFalse(self._clear_action().get_enabled(),
                         'an empty list offered to be cleared')
        self._bookmark(3)
        self.assertTrue(self._clear_action().get_enabled(),
                        'a list with a bookmark in it did not')

    def test_an_underscore_in_a_name_is_not_eaten(self):
        """A bookmark is named after the file it is in, which names no
        mnemonic - but GTK reads one out of it, because every item of a
        menu model is built with use-underline set.  Gtk.MenuItem, which
        the menu was made of before the port, showed the underscore."""
        self.window.imagehandler.pretty_name = 'two_words'
        self._bookmark(3)
        self.assertEqual(self._sections()[-1], ['two__words, (3 / 20)'])

    def test_clearing_asks_before_it_removes_anything(self):
        """It throws away every bookmark at once and there is no undo."""
        self._bookmark(3)
        self.menu._clear_activated()
        pump()
        self.assertEqual(len(self._dialogs()), 1, 'nothing was asked')
        self.assertEqual(len(self.store.get_bookmarks()), 1,
                         'the bookmarks went before the question was answered')

    def test_enter_is_not_what_clears_them(self):
        self._bookmark(3)
        self.menu._clear_activated()
        pump()
        dialog = self._dialogs()[0]
        keeps = dialog.get_widget_for_response(Response.NO)
        clears = dialog.get_widget_for_response(Response.YES)
        self.assertIs(dialog.get_default_widget(), keeps,
                      'Enter would clear the bookmarks')
        self.assertTrue(clears.has_css_class('destructive-action'),
                        'the clearing button is drawn as an ordinary one')

    def test_answering_no_keeps_them(self):
        self._bookmark(3)
        self.menu._clear_activated()
        pump()
        self._dialogs()[0].response(Response.NO)
        pump()
        self.assertEqual(len(self.store.get_bookmarks()), 1)

    def test_answering_yes_removes_them_all(self):
        self._bookmark(3, '/tmp/one.cbz')
        self._bookmark(4, '/tmp/two.cbz')
        self.menu._clear_activated()
        pump()
        self._dialogs()[0].response(Response.YES)
        pump()
        self.assertEqual(self.store.get_bookmarks(), [])
        self.assertEqual(self._sections(),
                         [['Add _Bookmark', '_Edit Bookmarks...',
                           'C_lear bookmarks...']],
                         'the menu still lists bookmarks that are gone')
        self.assertFalse(self._clear_action().get_enabled())

    def test_a_bookmark_is_listed_after_them(self):
        self._bookmark(3)
        self.assertEqual(len(self._sections()), 2)
        self.assertIn('(3 / 20)', self._sections()[1][0])

    def test_the_list_follows_the_store(self):
        self._bookmark(3, '/tmp/one.cbz')
        self.assertEqual(len(self._sections()[1]), 1)
        self._bookmark(7, '/tmp/two.cbz')
        self.assertEqual(len(self._sections()[1]), 2)

    def test_editing_twice_raises_the_dialog_that_is_open(self):
        """Each dialog holds the list as the store had it when it
        opened and writes that order back on the way out, so two of them
        are two copies of a list being edited."""
        self.menu._edit_activated()
        pump()
        first = self.menu._dialog
        self.assertIsNotNone(first)
        self.menu._edit_activated()
        pump()
        self.assertIs(self.menu._dialog, first)
        self.assertEqual(
            len([window for window in Gtk.Window.list_toplevels()
                 if isinstance(window, bookmark_dialog._BookmarksDialog)]), 1)

    def test_closing_the_dialog_lets_the_next_edit_open_another(self):
        self.menu._edit_activated()
        pump()
        first = self.menu._dialog
        first._close()
        pump()
        self.assertIsNone(self.menu._dialog)
        self.menu._edit_activated()
        pump()
        self.assertIsNotNone(self.menu._dialog)
        self.assertIsNot(self.menu._dialog, first)
        self.menu._dialog._close()
        pump()

    def test_opening_a_bookmark_loads_it(self):
        self._bookmark(3)
        self.menu._actions.lookup_action('open').activate(GLib.Variant('i', 0))
        self.assertEqual(self.window.filehandler.opened, [('/tmp/book.cbz', 3)])

    def test_a_middle_click_opens_a_bookmark_in_an_mcomix_of_its_own(self):
        """The book being read stays where it is, which is what the
        middle button means everywhere it opens something."""
        self._bookmark(3)
        launched = []
        with unittest.mock.patch.object(
                process, 'launch_mcomix',
                side_effect=lambda path, page=0: launched.append((path, page))):
            widgets._menu_button_pressed(Gdk.BUTTON_MIDDLE)
            self.menu._actions.lookup_action('open').activate(
                GLib.Variant('i', 0))
        self.assertEqual(launched, [('/tmp/book.cbz', 3)])
        self.assertEqual(self.window.filehandler.opened, [],
                         'the bookmark was opened here as well')

    def test_a_middle_click_is_not_remembered_for_the_next_one(self):
        """An item activated from the keyboard has no press of its own."""
        self._bookmark(3)
        widgets._menu_button_pressed(Gdk.BUTTON_MIDDLE)
        open_action = self.menu._actions.lookup_action('open')
        with unittest.mock.patch.object(process, 'launch_mcomix'):
            open_action.activate(GLib.Variant('i', 0))
        open_action.activate(GLib.Variant('i', 0))
        self.assertEqual(self.window.filehandler.opened, [('/tmp/book.cbz', 3)])

    def test_adding_needs_a_file_to_be_open(self):
        add = self.menu._actions.lookup_action('add')
        self.menu.set_sensitive(False)
        self.assertFalse(add.get_enabled())
        self.menu.set_sensitive(True)
        self.assertTrue(add.get_enabled())

    def _accelerators(self):
        """The key each fixed entry shows, or None."""
        link = self.menu.model.get_item_link(0, 'section')
        values = [link.get_item_attribute_value(index, 'accel')
                  for index in range(link.get_n_items())]
        return [None if value is None else value.get_string()
                for value in values]

    def test_the_fixed_entries_show_the_keys_they_answer_to(self):
        """The keys belong to the keybinding manager, so that the
        Shortcuts tab can change them; the menu shows what it is told."""
        self.assertEqual(['<Control>D', '<Control>B', None],
                         self._accelerators())

    def test_a_changed_key_shows_once_the_menu_is_refreshed(self):
        self.ui.accelerators['add_bookmark'] = '<Alt>a'
        self.menu.refresh()
        self.assertEqual(['<Alt>a', '<Control>B', None],
                         self._accelerators())

    def test_the_key_adds_a_bookmark_while_a_book_is_open(self):
        self.menu.set_sensitive(True)
        self.menu.activate('add')
        self.assertEqual([3], [bookmark._page
                               for bookmark in self.store.get_bookmarks()])

    def test_the_key_adds_nothing_while_no_book_is_open(self):
        """set_sensitive() disables adding with no book open, and the key
        has to leave it alone as the menu item does."""
        self.menu.set_sensitive(False)
        self.menu.activate('add')
        self.assertEqual([], self.store.get_bookmarks())


class BookmarkInTheOpenBookTest(MComixTest):

    """Loading a bookmark into a window that has its book open already.

    Opening the book again closes it first, and closing a book forgets
    the pages picked out of it and the changes that could be undone, so
    a bookmark into the open book only turns the page.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.terminate_program()
            self.window.destroy()
            main.set_main_window(None)
        pump()
        super().tearDown()

    def _open(self, path, pages):
        self.window = main.MainWindow(open_path=path)
        main.set_main_window(self.window)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == pages,
            seconds=20))

    def _folder(self):
        """A folder of three loose images, opened at the first."""
        folder = os.path.join(self.tmp_dir, 'book')
        os.makedirs(folder)
        for number in (1, 2, 3):
            shutil.copy(get_testfile_path('images', '03-PNG-RGB.png'),
                        os.path.join(folder, 'page%d.png' % number))
        self._open(os.path.join(folder, 'page1.png'), 3)

    def _load(self, path, page, archive_type=None):
        """Load a bookmark of <path> at <page>, and say whether the book
        was opened again to do it."""
        bookmark = bookmark_menu_item._Bookmark(
            self.window, self.window.filehandler, 'book', path, page, 3,
            archive_type, datetime.datetime.now())
        with unittest.mock.patch.object(
                self.window.filehandler, 'open_file',
                wraps=self.window.filehandler.open_file) as open_file:
            bookmark.load()
            pump()
        return open_file.called

    def test_a_bookmark_in_the_open_folder_only_turns_the_page(self):
        """A folder's bookmark names the file of its page, and it was
        compared with the folder itself, so it never matched."""
        self._folder()
        self.window.selected_pages = {1}
        path = self.window.imagehandler.get_path_to_page(3)
        self.assertFalse(self._load(path, 3), 'the folder was opened again')
        self.assertEqual(3, self.window.imagehandler.get_current_page())
        self.assertEqual({1}, self.window.selected_pages)

    def test_the_page_in_a_folder_is_found_by_its_file(self):
        """The folder may have changed since the bookmark was made, and
        the file is what the bookmark was made of."""
        self._folder()
        path = self.window.imagehandler.get_path_to_page(3)
        self.assertFalse(self._load(path, 2))
        self.assertEqual(3, self.window.imagehandler.get_current_page())

    def test_a_bookmark_in_the_open_archive_only_turns_the_page(self):
        self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'), 4)
        path = self.window.imagehandler.get_real_path()
        self.window.selected_pages = {1}
        self.assertFalse(self._load(path, 3, constants.ZIP),
                         'the archive was opened again')
        self.assertEqual(3, self.window.imagehandler.get_current_page())
        self.assertEqual({1}, self.window.selected_pages)

    def test_a_bookmark_in_another_folder_opens_it(self):
        self._folder()
        other = os.path.join(self.tmp_dir, 'other.png')
        shutil.copy(get_testfile_path('images', 'blue.png'), other)
        self.assertTrue(self._load(other, 1))

# vim: expandtab:sw=4:ts=4
