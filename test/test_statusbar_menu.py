# -*- coding: utf-8 -*-

""" Tests for the status bar's right-click menu, which picks the fields
it shows. """

from gi.repository import GLib, Gtk

from . import MComixTest

from mcomix import constants
from mcomix import status
from mcomix.preferences import prefs


class StatusbarFieldsMenuTest(MComixTest):

    def setUp(self):
        super(StatusbarFieldsMenuTest, self).setUp()
        prefs['statusbar fields'] = (constants.STATUS_PAGE |
                                     constants.STATUS_FILENAME)
        self.bar = status.Statusbar()
        self.window = Gtk.Window()
        self.window.add(self.bar)

    def tearDown(self):
        self.window.destroy()
        super(StatusbarFieldsMenuTest, self).tearDown()

    def _ticks(self):
        return {item.get_label(): item.get_active()
                for item in self.bar._fields_menu.get_children()}

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
