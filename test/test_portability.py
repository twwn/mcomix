# -*- coding: utf-8 -*-

""" The parts of portability.py that differ between desktops. """

import os
import unittest.mock

from gi.repository import Gio, GLib

from . import MComixTest

from mcomix import constants
from mcomix import portability


class _Answer(object):

    """Stands in for what a Gio.DBusConnection call answers with."""

    def __init__(self, value):
        self._value = value

    def unpack(self):
        return (self._value,)


class _Connection(object):

    def __init__(self, answers):
        #: What call_sync() answers, by method name; a GLib.Error to raise.
        self._answers = answers
        self.asked = []

    def call_sync(self, _name, _path, _interface, method, *args):
        self.asked.append(method)
        answer = self._answers.get(method)
        if isinstance(answer, GLib.Error):
            raise answer
        return _Answer(answer)


class DefaultLocaleTest(MComixTest):

    """What the environment says the user's language is."""

    def _locale(self, name):
        with unittest.mock.patch.dict(os.environ, {'LANGUAGE': name}):
            return portability.get_default_locale()

    def test_a_locale_name_is_spelled_out_in_full(self):
        self.assertEqual('de_DE', self._locale('de'))
        self.assertEqual('he_IL', self._locale('he_IL.UTF-8'))

    def test_the_first_of_several_languages_wins(self):
        self.assertEqual('en_GB', self._locale('en_GB:en:de'))

    def test_a_name_python_cannot_parse_falls_back_on_c(self):
        # locale.normalize() has no entry for a BCP 47 shaped name, and
        # answers with ValueError rather than a locale.
        self.assertEqual('C', self._locale('zh_Hans_CN'))

    def test_the_c_locale_is_reported_as_c(self):
        self.assertEqual('C', self._locale('C'))


class ColourSchemeTest(MComixTest):

    def _detect(self, connection):
        with unittest.mock.patch.object(Gio, 'bus_get_sync',
                                        return_value=connection):
            return portability.is_system_ui_dark_themed()

    def test_the_portal_saying_dark_is_dark(self):
        self.assertEqual(self._detect(_Connection({'ReadOne': 1})),
                         constants.SystemThemeLightness.DARK)

    def test_the_portal_saying_light_is_light(self):
        self.assertEqual(self._detect(_Connection({'ReadOne': 2})),
                         constants.SystemThemeLightness.LIGHT)

    def test_no_preference_is_unknown(self):
        self.assertEqual(self._detect(_Connection({'ReadOne': 0})),
                         constants.SystemThemeLightness.UNKNOWN)

    def test_a_variant_is_unwrapped(self):
        # Read() wraps the value one deeper than ReadOne() does.
        self.assertEqual(
            self._detect(_Connection({'ReadOne': GLib.Variant('u', 1)})),
            constants.SystemThemeLightness.DARK)

    def test_a_portal_without_read_one_is_asked_for_read(self):
        connection = _Connection({
            'ReadOne': GLib.Error.new_literal(Gio.io_error_quark(), 'no', 0),
            'Read': 1})
        self.assertEqual(self._detect(connection),
                         constants.SystemThemeLightness.DARK)
        self.assertEqual(connection.asked, ['ReadOne', 'Read'])

    def test_no_portal_at_all_is_unknown(self):
        connection = _Connection({
            'ReadOne': GLib.Error.new_literal(Gio.io_error_quark(), 'no', 0),
            'Read': GLib.Error.new_literal(Gio.io_error_quark(), 'no', 0)})
        self.assertEqual(self._detect(connection),
                         constants.SystemThemeLightness.UNKNOWN)

    def test_no_session_bus_is_unknown(self):
        error = GLib.Error.new_literal(Gio.io_error_quark(), 'no bus', 0)
        with unittest.mock.patch.object(Gio, 'bus_get_sync', side_effect=error):
            self.assertEqual(portability.is_system_ui_dark_themed(),
                             constants.SystemThemeLightness.UNKNOWN)

# vim: expandtab:sw=4:ts=4
