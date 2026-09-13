""" Tests for the bookmarks menu, which is a Gio.Menu model now. """

import os

from gi.repository import GLib, Gtk

from . import MComixTest, pump

from mcomix import bookmark_backend
from mcomix import bookmark_menu_item
from mcomix import constants
from mcomix import bookmark_menu


class _StubImageHandler:

    page = 3
    path = '/tmp/book.cbz'

    def get_pretty_current_filename(self):
        return 'book'

    def get_real_path(self):
        return self.path

    def get_current_page(self):
        return self.page

    def get_number_of_pages(self):
        return 20


class _StubFileHandler:

    archive_type = None
    _base_path = None

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

    """Stands in for MainUI, which is where accelerators are registered."""

    def __init__(self):
        self.shortcuts = []

    def add_shortcut(self, accelerator, action):
        self.shortcuts.append((accelerator, action))


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

    def tearDown(self):
        # Anything left on screen would be answered by the next test that
        # goes looking for a dialog.
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, Gtk.MessageDialog) and window.get_visible():
                window.destroy()
        pump()
        super().tearDown()

    def test_a_bookmark_in_the_open_file_leaves_the_tool_bar_alone(self):
        """Loading a bookmark that is already the open file only turns the
        page. It used to hide and immediately show the tool bar, which is
        a redraw of nothing that ends with the bar visible - so it came
        back for anyone who had turned it off."""
        self.window.toolbar.set_visible(False)
        self.window.filehandler._base_path = _StubImageHandler.path
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

    def test_the_fixed_entries_are_always_there(self):
        self.assertEqual(self._sections(),
                         [['Add _Bookmark', '_Edit Bookmarks...']])

    def test_a_bookmark_is_listed_after_them(self):
        self._bookmark(3)
        self.assertEqual(len(self._sections()), 2)
        self.assertIn('(3 / 20)', self._sections()[1][0])

    def test_the_list_follows_the_store(self):
        self._bookmark(3, '/tmp/one.cbz')
        self.assertEqual(len(self._sections()[1]), 1)
        self._bookmark(7, '/tmp/two.cbz')
        self.assertEqual(len(self._sections()[1]), 2)

    def test_opening_a_bookmark_loads_it(self):
        self._bookmark(3)
        self.menu._actions.lookup_action('open').activate(GLib.Variant('i', 0))
        self.assertEqual(self.window.filehandler.opened, [('/tmp/book.cbz', 3)])

    def test_adding_needs_a_file_to_be_open(self):
        add = self.menu._actions.lookup_action('add')
        self.menu.set_sensitive(False)
        self.assertFalse(add.get_enabled())
        self.menu.set_sensitive(True)
        self.assertTrue(add.get_enabled())

    def test_the_accelerators_name_their_actions(self):
        # They are registered against the action rather than the menu item,
        # because the items are rebuilt whenever a bookmark changes.
        self.assertEqual(self.ui.shortcuts,
                         [('<Control>D', 'bookmarks.add'),
                          ('<Control>B', 'bookmarks.edit')])

# vim: expandtab:sw=4:ts=4
