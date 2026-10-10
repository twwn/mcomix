""" Tests for the Recent menu, which is assembled from Gtk.RecentManager
now that the chooser widget that used to do it is going away. """

import os
import time
import unittest.mock

from gi.repository import Gdk, Gio, GLib, Gtk

from . import MComixTest, pump, session_tmp_dir, wait_for

from mcomix import process
from mcomix import recent
from mcomix import widgets


class _StubWindow(Gtk.Window):

    """A real window, so the menu's action group has somewhere to live."""

    def __init__(self):
        super().__init__()
        self.opened = []
        self.filehandler = self

    def open_file(self, path):
        self.opened.append(path)
        return True


class RecentFilesMenuTest(MComixTest):

    #: The settings and the manager belong to the process, not to a
    #: test.  Gtk.Settings is the one every widget reads, and a
    #: Gtk.RecentManager stays subscribed to it: one built under a
    #: setting is still answering changes to it after the test that
    #: built it is over, from memory Python has since reclaimed, which
    #: takes the process down when the next test sets the setting again.
    #: So both are set up once, and each test only empties the list.
    settings = None
    manager = None

    @classmethod
    def setUpClass(cls):
        # Gtk.RecentManager keeps nothing at all when the desktop has
        # turned file history off - and answers add_full() with True
        # either way - or when it says to keep it for no days, which
        # empties the list on the next reload.  A bare X server has no
        # settings daemon to say otherwise and defaults to both, so say
        # it here: these tests are about MComix' menu, not GTK's gate.
        cls.settings = Gtk.Settings.get_default()
        cls.saved_settings = {
            name: cls.settings.get_property(name)
            for name in ('gtk-recent-files-enabled',
                         'gtk-recent-files-max-age')}
        cls.settings.set_property('gtk-recent-files-enabled', True)
        cls.settings.set_property('gtk-recent-files-max-age', 30)
        # Never the default manager: that one writes to the real
        # recently-used list in the user's home directory.  Nor a
        # directory of a single test's, which is removed when it passes
        # while the manager goes on writing to it.
        cls.storage = os.path.join(session_tmp_dir(), 'recently-used.xbel')
        cls.manager = Gtk.RecentManager(filename=cls.storage)

    @classmethod
    def tearDownClass(cls):
        for name, value in cls.saved_settings.items():
            cls.settings.set_property(name, value)

    def setUp(self):
        super().setUp()
        self.manager.purge_items()
        self.real_get_default = Gtk.RecentManager.get_default
        Gtk.RecentManager.get_default = staticmethod(lambda: self.manager)
        self.window = _StubWindow()
        # A press left over from another test would be handed to the
        # first activation here that asks.
        widgets.take_middle_click()

    def tearDown(self):
        Gtk.RecentManager.get_default = self.real_get_default
        super().tearDown()

    def _add(self, name, mime_type='application/zip'):
        """Put a file into the recent list, newest last."""
        path = os.path.join(self.tmp_dir, name)
        with open(path, 'w') as handle:
            handle.write('x')
        uri = Gio.File.new_for_path(path).get_uri()
        data = Gtk.RecentData()
        data.display_name = name
        data.mime_type = mime_type
        data.app_name = 'mcomix-test'
        data.app_exec = 'mcomix %u'
        data.is_private = False
        self.manager.add_full(uri, data)
        return path

    def _labels(self, menu):
        """The entries the menu offers, read from its model: the files,
        without the section below them that clears the list."""
        model = menu.model
        return [model.get_item_attribute_value(index, 'label').get_string()
                for index in range(model.get_n_items())
                if model.get_item_link(index, Gio.MENU_LINK_SECTION) is None]

    def _clear_entry(self, menu):
        """The label and the action of the entry below the files."""
        model = menu.model
        last = model.get_n_items() - 1
        section = model.get_item_link(last, Gio.MENU_LINK_SECTION)
        self.assertIsNotNone(section, 'no section below the files')
        return (section.get_item_attribute_value(0, 'label').get_string(),
                section.get_item_attribute_value(0, 'action').get_string())

    def test_a_supported_file_is_offered(self):
        self._add('book.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertEqual(self._labels(menu), ['book.cbz'])

    def test_an_unsupported_file_is_not(self):
        self._add('notes.txt', mime_type='text/plain')
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertNotIn('notes.txt', self._labels(menu))

    def test_a_closed_window_s_menu_stops_following_the_list(self):
        """The manager is one for the application: a menu still
        connected to it after its window closed was kept alive by it,
        window and all, and rebuilt for every later change."""
        self.window.present()
        pump()
        menu = recent.RecentFilesMenu(None, self.window)
        rebuilds = []
        menu._rebuild = lambda: rebuilds.append(True)
        self._add('open.cbz')
        wait_for(lambda: rebuilds)
        self.assertTrue(rebuilds, 'the menu does not hear the manager at all')
        self.window.destroy()
        rebuilds.clear()
        # The change is told to a handler of the test's own as well,
        # which says when the menu would have heard of it.
        heard = []
        handler = self.manager.connect('changed', lambda _m: heard.append(True))
        self.addCleanup(self.manager.disconnect, handler)
        self._add('closed.cbz')
        wait_for(lambda: heard)
        self.assertTrue(heard)
        self.assertEqual(rebuilds, [])

    def test_an_empty_list_says_so(self):
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertEqual(len(self._labels(menu)), 1)
        placeholder = menu._actions.lookup_action('nothing')
        self.assertFalse(placeholder.get_enabled(),
                         'the placeholder must not be pickable')

    def test_no_more_than_the_limit_is_shown(self):
        for number in range(recent.RecentFilesMenu._LIMIT + 5):
            self._add('book%02d.cbz' % number)
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertEqual(len(self._labels(menu)),
                         recent.RecentFilesMenu._LIMIT)

    def test_the_most_recent_comes_first(self):
        self._add('older.cbz')
        time.sleep(1.1)  # the list stores whole seconds
        self._add('newer.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertEqual(self._labels(menu)[:2], ['newer.cbz', 'older.cbz'])

    def test_an_underscore_in_a_file_name_is_not_eaten(self):
        """GTK builds a menu model's items with use-underline set, so a
        name shown as it stands loses an underscore to the mnemonic it
        is read as.  Gtk.RecentChooserMenu, and the Gtk.MenuItem the
        menu was made of before the port, showed it."""
        self._add('two_words.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertEqual(self._labels(menu), ['two__words.cbz'])

    def test_a_modification_time_is_a_datetime(self):
        """_modified() used to carry a branch for an int, which is what
        GTK3's Gtk.RecentInfo.get_modified() answered with. GTK4 answers
        with a GLib.DateTime, so that branch could never be taken."""
        self._add('book.cbz')
        info = self.manager.get_items()[0]
        self.assertIsInstance(info.get_modified(), GLib.DateTime)
        self.assertEqual(info.get_modified().to_unix(),
                         recent.RecentFilesMenu._modified(info))

    def test_activating_an_entry_opens_it(self):
        path = self._add('book.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        target = menu.model.get_item_attribute_value(0, 'target')
        menu._actions.lookup_action(
            recent.RecentFilesMenu.OPEN_ACTION).activate(target)
        self.assertEqual(self.window.opened, [path])

    def test_a_middle_click_opens_an_entry_in_an_mcomix_of_its_own(self):
        """The book being read stays where it is, which is what the
        middle button means everywhere it opens something."""
        path = self._add('book.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        target = menu.model.get_item_attribute_value(0, 'target')
        launched = []
        with unittest.mock.patch.object(
                process, 'launch_mcomix',
                side_effect=lambda name, page=0: launched.append((name, page))):
            widgets._menu_button_pressed(Gdk.BUTTON_MIDDLE)
            menu._actions.lookup_action(
                recent.RecentFilesMenu.OPEN_ACTION).activate(target)
        self.assertEqual(launched, [(path, 0)])
        self.assertEqual(self.window.opened, [],
                         'the file was opened here as well')

    def test_a_book_that_will_not_open_leaves_the_list(self):
        """The entry to forget was named by urllib's pathname2url(),
        which escapes the brackets that GTK, keeping every URI the way
        GLib writes it, leaves alone - and from Python 3.14 on begins
        with "file://///" - so no entry was ever found to remove, and a
        book that was gone stayed on the menu."""
        path = os.path.join(self.tmp_dir, 'Batman (2016) #1.cbz')
        # add_full(), which files the entry before it returns;
        # add_item() asks for the file's type first, and the answer
        # comes back through the main loop when it comes.
        data = Gtk.RecentData()
        data.display_name = os.path.basename(path)
        data.mime_type = 'application/zip'
        data.app_name = 'mcomix-test'
        data.app_exec = 'mcomix %u'
        self.manager.add_full(Gio.File.new_for_path(path).get_uri(), data)
        self.assertEqual(1, len(self.manager.get_items()))
        self.window.open_file = lambda path: False
        menu = recent.RecentFilesMenu(None, self.window)
        target = menu.model.get_item_attribute_value(0, 'target')
        menu._actions.lookup_action(
            recent.RecentFilesMenu.OPEN_ACTION).activate(target)
        pump()
        self.assertEqual([], [info.get_uri()
                              for info in self.manager.get_items()])

    def test_clearing_it_leaves_other_programs_files_alone(self):
        """Switching "Store information about recently opened files" to
        "Never" offers to clear the Recent menu, and did it with
        Gtk.RecentManager.purge_items(): the list is the whole desktop's,
        so every program's history went - documents, music, whatever
        else - not just the books and pages the menu offers."""
        notes = self._add('notes.txt', mime_type='text/plain')
        self._add('book.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertEqual(1, menu.count())

        menu.remove_all()

        self.assertEqual(
            [Gio.File.new_for_path(notes).get_uri()],
            [info.get_uri() for info in self.manager.get_items()])
        self.assertEqual(0, menu.count())

    def test_the_list_can_be_cleared_from_the_menu(self):
        """Clearing it took switching "Store information about recently
        opened files" to "Never" and back (a review on SourceForge)."""
        notes = self._add('notes.txt', mime_type='text/plain')
        self._add('book.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        label, action = self._clear_entry(menu)
        self.assertEqual('_Clear List', label)
        self.assertEqual('recent.clear', action)
        clear = menu._actions.lookup_action(recent.RecentFilesMenu.CLEAR_ACTION)
        self.assertTrue(clear.get_enabled())

        clear.activate(None)

        self.assertEqual(
            [Gio.File.new_for_path(notes).get_uri()],
            [info.get_uri() for info in self.manager.get_items()])
        self.assertEqual(0, menu.count())

    def test_an_empty_list_cannot_be_cleared(self):
        menu = recent.RecentFilesMenu(None, self.window)
        self._clear_entry(menu)
        clear = menu._actions.lookup_action(recent.RecentFilesMenu.CLEAR_ACTION)
        self.assertFalse(clear.get_enabled())

    def test_the_menu_follows_the_list(self):
        menu = recent.RecentFilesMenu(None, self.window)
        self._add('book.cbz')
        # The manager coalesces writes and announces them on a timeout,
        # so give the signal a bounded while to arrive.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self._labels(menu) != ['book.cbz']:
            pump()
            time.sleep(0.02)
        self.assertEqual(self._labels(menu), ['book.cbz'])

# vim: expandtab:sw=4:ts=4
