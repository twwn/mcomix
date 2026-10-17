""" The parts of portability.py that differ between desktops. """

import os
import sys
import unittest.mock

from gi.repository import Gio, GLib

from . import MComixTest

from mcomix import constants
from mcomix import portability


class _Answer:

    """Stands in for what a Gio.DBusConnection call answers with."""

    def __init__(self, value):
        self._value = value

    def unpack(self):
        return (self._value,)


class _Connection:

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


@unittest.skipIf(sys.platform == 'win32',
                 "Windows' language comes from GetUserDefaultUILanguage()")
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


class WindowsDefaultLocaleTest(MComixTest):

    """What Windows says the user's display language is."""

    def _locale(self, langid):
        kernel32 = unittest.mock.Mock()
        kernel32.GetUserDefaultUILanguage.return_value = langid
        windll = unittest.mock.Mock(kernel32=kernel32)
        with unittest.mock.patch('sys.platform', 'win32'), \
                unittest.mock.patch('ctypes.windll', windll, create=True):
            return portability.get_default_locale()

    def test_a_language_id_is_turned_into_a_locale_name(self):
        self.assertEqual('en_GB', self._locale(0x0809))

    def test_a_language_id_python_does_not_know_falls_back_on_c(self):
        """A language id missing from Python's table stopped MComix with
        KeyError before it had opened a window.

        0x1000 is LOCALE_CUSTOM_UNSPECIFIED, what Windows answers for a
        display language it has no id of its own for, and no Python has
        it.  K'iche' (0x0486) was the example first: Python 3.14 leaves
        it out, and 3.12, the floor, has it.
        """
        self.assertEqual('C', self._locale(0x1000))


class ProcessAgeTest(MComixTest):

    """How long ago Windows says the process was created."""

    def _age(self, created, now, answered=True):
        def process_times(handle, created_at, *others):
            self.assertEqual(-1 & 0xFFFFFFFFFFFFFFFF, handle.value)
            created_at._obj.value = created
            return answered

        def system_time(now_at):
            now_at._obj.value = now

        kernel32 = unittest.mock.Mock()
        kernel32.GetProcessTimes.side_effect = process_times
        kernel32.GetSystemTimeAsFileTime.side_effect = system_time
        windll = unittest.mock.Mock(kernel32=kernel32)
        with unittest.mock.patch('sys.platform', 'win32'), \
                unittest.mock.patch('ctypes.windll', windll, create=True):
            return portability.seconds_since_process_start()

    def test_the_times_are_counted_in_100_ns(self):
        self.assertEqual(90.5, self._age(10**17, 10**17 + 905_000_000))

    def test_a_process_whose_times_cannot_be_read_has_none(self):
        self.assertIsNone(self._age(0, 0, answered=False))

    def test_elsewhere_it_is_not_known(self):
        with unittest.mock.patch('sys.platform', 'linux'):
            self.assertIsNone(portability.seconds_since_process_start())

class RenameOnceClosedTest(MComixTest):

    """A rename Windows refuses because the file is open is tried again."""

    def _refusal(self, winerror):
        error = PermissionError(13, 'Permission denied')
        if winerror is not None:
            error.winerror = winerror
        return error

    def _rename(self, *answers):
        rename = unittest.mock.Mock(side_effect=answers)
        with unittest.mock.patch('time.sleep') as sleep:
            try:
                portability.rename_once_closed(rename, 'a', 'b')
            finally:
                self.calls = rename.call_count
                self.waits = [call.args[0] for call in sleep.call_args_list]

    def test_a_sharing_violation_is_waited_out(self):
        self._rename(self._refusal(32), self._refusal(32), None)
        self.assertEqual(3, self.calls)
        self.assertEqual([0.01, 0.02], self.waits)

    def test_access_denied_over_an_open_file_is_waited_out(self):
        self._rename(self._refusal(5), None)
        self.assertEqual(2, self.calls)

    def test_a_file_that_stays_open_fails_after_a_second_at_most(self):
        with self.assertRaises(PermissionError):
            self._rename(*[self._refusal(32)] * 7)
        self.assertEqual(7, self.calls)
        self.assertLess(sum(self.waits), 1)

    def test_a_refusal_without_a_windows_error_is_not_tried_again(self):
        with self.assertRaises(PermissionError):
            self._rename(self._refusal(None), None)
        self.assertEqual(1, self.calls)

    def test_other_windows_errors_are_not_tried_again(self):
        with self.assertRaises(PermissionError):
            self._rename(self._refusal(1314), None)
        self.assertEqual(1, self.calls)

    def test_other_errors_are_not_tried_again(self):
        with self.assertRaises(FileNotFoundError):
            self._rename(FileNotFoundError(2, 'No such file'), None)
        self.assertEqual(1, self.calls)


@unittest.skipIf(sys.platform == 'win32',
                 "Windows' colour scheme comes from the registry")
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
