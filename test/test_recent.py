# -*- coding: utf-8 -*-

""" Tests for the Recent menu, which is assembled from Gtk.RecentManager
now that the chooser widget that used to do it is going away. """

import os
import time

from gi.repository import Gtk

from . import MComixTest

from mcomix import recent


class _StubWindow(Gtk.Window):

    """A real window, so the menu's action group has somewhere to live."""

    def __init__(self):
        super(_StubWindow, self).__init__()
        self.opened = []
        self.filehandler = self

    def open_file(self, path):
        self.opened.append(path)
        return True


class RecentFilesMenuTest(MComixTest):

    def setUp(self):
        super(RecentFilesMenuTest, self).setUp()
        # Never the default manager: that one writes to the real
        # recently-used list in the user's home directory.
        self.storage = os.path.join(self.tmp_dir, 'recently-used.xbel')
        self.manager = Gtk.RecentManager(filename=self.storage)
        self.real_get_default = Gtk.RecentManager.get_default
        Gtk.RecentManager.get_default = staticmethod(lambda: self.manager)
        self.window = _StubWindow()

    def tearDown(self):
        Gtk.RecentManager.get_default = self.real_get_default
        super(RecentFilesMenuTest, self).tearDown()

    def _add(self, name, mime_type='application/zip'):
        """Put a file into the recent list, newest last."""
        path = os.path.join(self.tmp_dir, name)
        with open(path, 'w') as handle:
            handle.write('x')
        uri = 'file://' + path
        data = Gtk.RecentData()
        data.display_name = name
        data.mime_type = mime_type
        data.app_name = 'mcomix-test'
        data.app_exec = 'mcomix %u'
        data.is_private = False
        self.manager.add_full(uri, data)
        return path

    def _labels(self, menu):
        """The entries the menu offers, read from its model."""
        model = menu.model
        return [model.get_item_attribute_value(index, 'label').get_string()
                for index in range(model.get_n_items())]

    def test_a_supported_file_is_offered(self):
        self._add('book.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertEqual(self._labels(menu), ['book.cbz'])

    def test_an_unsupported_file_is_not(self):
        self._add('notes.txt', mime_type='text/plain')
        menu = recent.RecentFilesMenu(None, self.window)
        self.assertNotIn('notes.txt', self._labels(menu))

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

    def test_activating_an_entry_opens_it(self):
        path = self._add('book.cbz')
        menu = recent.RecentFilesMenu(None, self.window)
        target = menu.model.get_item_attribute_value(0, 'target')
        menu._actions.lookup_action(
            recent.RecentFilesMenu.OPEN_ACTION).activate(target)
        self.assertEqual(self.window.opened, [path])

    def test_the_menu_follows_the_list(self):
        menu = recent.RecentFilesMenu(None, self.window)
        self._add('book.cbz')
        # The manager coalesces writes and announces them on a timeout,
        # so give the signal a bounded while to arrive.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self._labels(menu) != ['book.cbz']:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.02)
        self.assertEqual(self._labels(menu), ['book.cbz'])

# vim: expandtab:sw=4:ts=4
