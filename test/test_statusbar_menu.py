""" Tests for the status bar's right-click menu, which picks the fields
it shows. """

import unittest.mock

from gi.repository import GLib, Gtk

from . import MComixTest

from mcomix import constants
from mcomix import status
from mcomix.preferences import prefs


class StatusbarFieldsMenuTest(MComixTest):

    def setUp(self):
        super().setUp()
        prefs['statusbar fields'] = (constants.STATUS_PAGE |
                                     constants.STATUS_FILENAME)
        self.bar = status.Statusbar()
        self.window = Gtk.Window()
        self.window.set_child(self.bar)

    def tearDown(self):
        self.window.destroy()
        super().tearDown()

    def _ticks(self):
        """What each entry would show, read from the action behind it.

        A Gtk.PopoverMenu keeps no list of items to walk; the state that
        decides the tick is on the action either way.
        """
        return {label: self.bar._field_actions.lookup_action(
                    name).get_state().get_boolean()
                for name, label, bit in status.Statusbar.FIELDS}

    def _set(self, name, ticked):
        self.bar._field_actions.lookup_action(name).change_state(
            GLib.Variant('b', ticked))

    def test_every_field_is_offered(self):
        self.assertEqual(len(self._ticks()), len(status.Statusbar.FIELDS))

    def test_the_ticks_start_from_the_preference(self):
        ticks = self._ticks()
        self.assertTrue(ticks['Show page numbers'])
        self.assertTrue(ticks['Show filename'])
        self.assertFalse(ticks['Show resolution'])

    def test_ticking_a_field_turns_it_on(self):
        self._set('resolution', True)
        self.assertTrue(prefs['statusbar fields'] & constants.STATUS_RESOLUTION)
        self.assertTrue(self._ticks()['Show resolution'])

    def test_unticking_a_field_turns_it_off(self):
        self._set('pagenumber', False)
        self.assertFalse(prefs['statusbar fields'] & constants.STATUS_PAGE)
        self.assertFalse(self._ticks()['Show page numbers'])

    def test_the_other_fields_are_left_alone(self):
        before = prefs['statusbar fields']
        self._set('resolution', True)
        self.assertEqual(prefs['statusbar fields'],
                         before | constants.STATUS_RESOLUTION)

# vim: expandtab:sw=4:ts=4


class StatusbarCopyTest(MComixTest):

    """Copying what the bar knows of the file being read (upstream
    feature request 14)."""

    def setUp(self):
        super().setUp()
        self.bar = status.Statusbar()
        self.window = Gtk.Window()
        self.window.set_child(self.bar)
        self.copied = []
        patcher = unittest.mock.patch.object(
            self.bar, '_put_on_clipboard', self.copied.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.window.destroy()
        super().tearDown()

    def test_the_file_name_is_copied_as_the_bar_shows_it(self):
        self.bar.set_filename('02.jpg, 03.jpg')
        self.bar._field_actions.activate_action('copy-filename', None)
        self.assertEqual(['02.jpg, 03.jpg'], self.copied)

    def test_the_path_is_the_whole_one(self):
        self.bar.set_path('/books/Some Book.cbz')
        self.bar._field_actions.activate_action('copy-path', None)
        self.assertEqual(['/books/Some Book.cbz'], self.copied)

    def test_nothing_to_copy_leaves_the_entry_insensitive(self):
        self.bar.set_filename('01.jpg')
        gesture = unittest.mock.Mock()
        gesture.get_current_button.return_value = 3
        with unittest.mock.patch('mcomix.widgets.popup_at'):
            self.bar._button_released(gesture, 1, 0, 0)
        actions = self.bar._field_actions
        self.assertTrue(actions.lookup_action('copy-filename').get_enabled())
        self.assertFalse(actions.lookup_action('copy-path').get_enabled())
