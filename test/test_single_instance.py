"""An MComix started while another runs hands that one its files.

The two find each other on the session bus.  The tests give them a bus
of their own, a dbus-daemon started for each test, and run both sides
as processes that are told its address: the session bus of whoever runs
the suite is never asked, and the name they meet under is one no MComix
uses.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
import unittest.mock

from gi.repository import Gio

from . import MComixTest

from mcomix import i18n
from mcomix import run
from mcomix import single_instance
from mcomix.preferences import prefs

_REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The MComix that is running: it takes the name, says so, and prints
#: one line for everything it is handed until its input is closed.
_FIRST = '''
import json, sys
from gi.repository import GLib
from mcomix import single_instance
instance = single_instance.SingleInstance(sys.argv[1])
print(json.dumps(instance.hand_over([])), flush=True)
loop = GLib.MainLoop()
instance.serve(lambda *call: print(json.dumps(call), flush=True),
               lambda: print(json.dumps('raised'), flush=True))
def closed(channel, condition):
    loop.quit()
    return False
GLib.io_add_watch(GLib.IOChannel.unix_new(0), GLib.IO_HUP | GLib.IO_IN, closed)
GLib.timeout_add_seconds(20, loop.quit)
loop.run()
'''

#: The MComix started after it, with the paths the command line named.
_SECOND = '''
import json, sys
from mcomix import single_instance
instance = single_instance.SingleInstance(sys.argv[1])
print(json.dumps(instance.hand_over(
    sys.argv[4:], int(sys.argv[2]), sys.argv[3] or None)), flush=True)
'''


@unittest.skipIf(sys.platform == 'win32' or not shutil.which('dbus-daemon'),
                 'needs a session bus to start')
class HandOverTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.daemon = subprocess.Popen(
            ['dbus-daemon', '--session', '--nofork', '--print-address=1'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(self._stop, self.daemon)
        self.address = self.daemon.stdout.readline().strip()
        self.assertTrue(self.address)
        self.name = 'io.github.twwn.mcomix.Test%d' % os.getpid()

    @staticmethod
    def _stop(process):
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()
        process.terminate()
        process.wait(timeout=10)

    def _python(self, code, *arguments, address=None, **keywords):
        environment = dict(os.environ, PYTHONPATH=_REPOSITORY,
                           DBUS_SESSION_BUS_ADDRESS=address or self.address)
        return subprocess.Popen(
            [sys.executable, '-c', code, self.name] + list(arguments),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env=environment, **keywords)

    def _first(self):
        """Start the MComix that is running, once it holds the name."""
        first = self._python(_FIRST)
        self.addCleanup(self._stop, first)
        self.assertIs(False, json.loads(first.stdout.readline()),
                      'the first MComix found another')
        return first

    def _second(self, *paths, page=0, member='', **keywords):
        """What the MComix started with <paths> says of handing them
        over."""
        second = self._python(_SECOND, str(page), member, *paths, **keywords)
        self.addCleanup(self._stop, second)
        said = second.stdout.readline()
        self.assertEqual(0, second.wait(timeout=20))
        return json.loads(said)

    def test_the_files_go_to_the_mcomix_that_is_running(self):
        first = self._first()
        elsewhere = os.path.join(self.tmp_dir, 'elsewhere')
        os.mkdir(elsewhere)
        named = os.path.join(self.tmp_dir, 'b.cbz')
        self.assertIs(True, self._second(
            'a.cbz', named, page=3, member='pages/03.jpg', cwd=elsewhere))
        # A path is made absolute where it was typed, not where it is
        # opened.
        self.assertEqual(
            [[os.path.join(elsewhere, 'a.cbz'), named], 3, 'pages/03.jpg'],
            json.loads(first.stdout.readline()))

    def test_no_page_and_no_file_of_it_are_none(self):
        first = self._first()
        self.assertIs(True, self._second(os.path.join(self.tmp_dir, 'a.cbz')))
        self.assertEqual([[os.path.join(self.tmp_dir, 'a.cbz')], 0, None],
                         json.loads(first.stdout.readline()))

    def test_started_with_no_file_it_brings_the_window_forward(self):
        first = self._first()
        self.assertIs(True, self._second())
        self.assertEqual('raised', json.loads(first.stdout.readline()))

    def test_with_none_running_it_starts_as_ever(self):
        self.assertIs(False, self._second(os.path.join(self.tmp_dir, 'a.cbz')))

    def test_without_a_session_bus_it_starts_as_ever(self):
        gone = 'unix:path=%s' % os.path.join(self.tmp_dir, 'no-bus')
        self.assertIs(False, self._second(
            os.path.join(self.tmp_dir, 'a.cbz'), address=gone))


class ServeTest(MComixTest):

    """What the running MComix does with a call, the bus aside."""

    def setUp(self):
        super().setUp()
        self.instance = single_instance.SingleInstance(
            'io.github.twwn.mcomix.Test%d' % os.getpid())
        self.calls = []

    def _serve(self):
        self.instance.serve(lambda *call: self.calls.append(call),
                            lambda: self.calls.append('raised'))

    def _handed(self, hint, *paths):
        self.instance._on_open(
            None, [Gio.File.new_for_path(path) for path in paths],
            len(paths), hint)

    def test_what_arrives_before_the_window_is_built_waits_for_it(self):
        """The name is taken before GTK is loaded, and the window is
        there a second later."""
        book = os.path.join(self.tmp_dir, 'a.cbz')
        self._handed(json.dumps({'page': 2, 'member': None}), book)
        self.instance._on_activate(None)
        self.assertEqual([], self.calls)
        self._serve()
        self.assertEqual([([book], 2, None), 'raised'], self.calls)

    def test_a_hint_that_says_nothing_it_knows_opens_the_files_all_the_same(self):
        book = os.path.join(self.tmp_dir, 'a.cbz')
        self._serve()
        for hint in ('', 'not json', '[]', '{"page": "3", "member": 4}'):
            with self.subTest(hint=hint):
                self.calls.clear()
                self._handed(hint, book)
                self.assertEqual([([book], 0, None)], self.calls)

    def test_no_file_is_nothing_to_open(self):
        self._serve()
        self._handed('')
        self.assertEqual([], self.calls)

    def test_on_windows_it_asks_for_the_bus_glib_starts_itself(self):
        """Windows has no session bus, and GLib looks for none unless
        the address says to start one: under Wine every MComix found
        itself alone until it did."""
        name = 'io.github.twwn.mcomix.Test%d' % os.getpid()
        with unittest.mock.patch.object(sys, 'platform', 'win32'), \
                unittest.mock.patch.dict(os.environ):
            os.environ.pop('DBUS_SESSION_BUS_ADDRESS', None)
            single_instance.SingleInstance(name)
            self.assertEqual('autolaunch:',
                             os.environ['DBUS_SESSION_BUS_ADDRESS'])
            # One that is set is whoever set it's to choose.
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/some/bus'
            single_instance.SingleInstance(name)
            self.assertEqual('unix:path=/some/bus',
                             os.environ['DBUS_SESSION_BUS_ADDRESS'])
        with unittest.mock.patch.object(sys, 'platform', 'linux'), \
                unittest.mock.patch.dict(os.environ):
            os.environ.pop('DBUS_SESSION_BUS_ADDRESS', None)
            single_instance.SingleInstance(name)
            self.assertNotIn('DBUS_SESSION_BUS_ADDRESS', os.environ)

    def test_the_flatpak_goes_by_its_own_name(self):
        with unittest.mock.patch.dict(os.environ, {'FLATPAK_ID': 'io.x.App'}):
            self.assertEqual('io.x.App', single_instance.application_id())
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop('FLATPAK_ID', None)
            self.assertEqual('net.sourceforge.mcomix',
                             single_instance.application_id())


class StartTest(MComixTest):

    """Whether an MComix that is starting asks at all."""

    def _asks(self, *arguments):
        opts, _args = run.parse_arguments(list(arguments))
        return run.single_instance_for(opts) is not None

    def test_it_does_not_ask_unless_the_preference_says_so(self):
        self.assertFalse(prefs['single instance'])
        self.assertFalse(self._asks('/books/a.cbz'))
        prefs['single instance'] = True
        self.assertTrue(self._asks('/books/a.cbz'))

    def test_a_window_of_its_own_can_be_asked_for(self):
        """What a middle click on a bookmark or a cover starts."""
        prefs['single instance'] = True
        self.assertFalse(self._asks('--new-window', '/books/a.cbz'))

    def test_files_handed_over_end_the_start_before_gtk_is_set_up(self):
        """Everything run() sets for the process on its way there is
        kept from this one: the language it installs was the desktop's,
        and stayed for every later test on the worker."""
        prefs['single instance'] = True
        instance = unittest.mock.Mock()
        instance.hand_over.return_value = True
        with unittest.mock.patch.object(sys, 'argv',
                                        ['mcomix', '--page', '4', 'a.cbz']), \
                unittest.mock.patch.object(
                    run.preferences, 'read_preferences_file'), \
                unittest.mock.patch.object(i18n, 'install_gettext'), \
                unittest.mock.patch.object(sys, 'stdout'), \
                unittest.mock.patch.object(run.log, 'setLevel'), \
                unittest.mock.patch.object(run.log, 'log_uncaught_exceptions'), \
                unittest.mock.patch.object(run, 'single_instance_for',
                                           return_value=instance), \
                unittest.mock.patch.object(
                    run, 'setup_dependencies',
                    side_effect=AssertionError('it went on to start')):
            run.run()
        instance.hand_over.assert_called_once_with(['a.cbz'], 4, None)
