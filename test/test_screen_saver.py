"""The request that keeps the screen on while a slideshow runs."""

import ctypes
import sys
import unittest
import unittest.mock

from gi.repository import GLib

from . import MComixTest

from mcomix import screen_saver


class _Bus:

    """A session bus that records what it is asked and answers when
    told to, as the real one answers from the main loop."""

    def __init__(self, refuses=False):
        self.calls = []
        self._refuses = refuses
        self._waiting = []

    def call(self, name, path, interface, method, parameters, reply_type,
             flags, timeout, cancellable, callback, *user_data):
        self.calls.append((name, path, interface, method,
                           parameters.unpack() if parameters else None))
        if callback is not None:
            self._waiting.append(callback)

    def call_finish(self, result):
        if self._refuses:
            raise GLib.Error('No such interface')
        return GLib.Variant('(o)', (result,))

    def answer(self):
        """Deliver the answers the portal owes."""
        waiting, self._waiting = self._waiting, []
        for number, callback in enumerate(waiting):
            callback(self, '/org/freedesktop/portal/desktop/request/1_1/t%d'
                     % (len(self.calls) + number))

    def methods(self):
        return [call[3] for call in self.calls]


@unittest.skipIf(sys.platform == 'win32', 'Windows has no session bus')
class PortalTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.bus = _Bus()
        self._connect = []
        patcher = unittest.mock.patch.object(
            screen_saver, '_session_bus', self._connect.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hold = screen_saver.ScreenHold('Slideshow')

    def _connected(self, bus='the bus'):
        """Hand over the bus, as the main loop does once it is there."""
        waiting, self._connect[:] = list(self._connect), []
        for ready in waiting:
            ready(self.bus if bus == 'the bus' else bus)

    def test_holding_asks_the_portal_to_keep_the_session_from_idling(self):
        self.hold.hold()
        # Nothing waits for the bus: it answers from the main loop.
        self.assertEqual([], self.bus.calls)
        self.assertTrue(self.hold.is_held())
        self._connected()
        self.assertEqual([(
            'org.freedesktop.portal.Desktop',
            '/org/freedesktop/portal/desktop',
            'org.freedesktop.portal.Inhibit', 'Inhibit',
            ('', 8, {'reason': 'Slideshow'}))], self.bus.calls)

    def test_releasing_closes_the_request_the_portal_answered_with(self):
        self.hold.hold()
        self._connected()
        self.bus.answer()
        self.hold.release()
        self.assertFalse(self.hold.is_held())
        name, path, interface, method, parameters = self.bus.calls[-1]
        self.assertEqual(('org.freedesktop.portal.Desktop',
                          'org.freedesktop.portal.Request', 'Close', None),
                         (name, interface, method, parameters))
        self.assertTrue(path.startswith(
            '/org/freedesktop/portal/desktop/request/'), path)
        # Once: a second release has nothing left to close.
        self.hold.release()
        self.assertEqual(['Inhibit', 'Close'], self.bus.methods())

    def test_held_twice_it_asks_once(self):
        self.hold.hold()
        self.hold.hold()
        self._connected()
        self.bus.answer()
        self.hold.hold()
        self.assertEqual(['Inhibit'], self.bus.methods())
        self.assertEqual([], self._connect)

    def test_released_before_the_bus_is_there_nothing_is_asked(self):
        self.hold.hold()
        self.hold.release()
        self._connected()
        self.assertEqual([], self.bus.calls)

    def test_released_before_the_portal_answers_the_answer_is_closed(self):
        """The slideshow stopped while the request was on its way: left
        open, it would have kept the screen on until MComix quit."""
        self.hold.hold()
        self._connected()
        self.hold.release()
        self.assertEqual(['Inhibit'], self.bus.methods())
        self.bus.answer()
        self.assertEqual(['Inhibit', 'Close'], self.bus.methods())

    def test_held_again_while_the_request_is_on_its_way_it_is_kept(self):
        """A changed delay stops and starts the slideshow at once."""
        self.hold.hold()
        self._connected()
        self.hold.release()
        self.hold.hold()
        self.bus.answer()
        self.assertEqual(['Inhibit'], self.bus.methods())
        self.assertEqual([], self._connect)
        self.hold.release()
        self.assertEqual(['Inhibit', 'Close'], self.bus.methods())

    def test_held_again_after_a_release_it_asks_again(self):
        self.hold.hold()
        self._connected()
        self.bus.answer()
        self.hold.release()
        self.hold.hold()
        self._connected()
        self.assertEqual(['Inhibit', 'Close', 'Inhibit'], self.bus.methods())

    def test_without_a_session_bus_nothing_fails_and_it_can_ask_again(self):
        self.hold.hold()
        self._connected(None)
        self.hold.release()
        self.hold.hold()
        self.assertEqual(1, len(self._connect))

    def test_a_desktop_without_the_portal_is_left_alone(self):
        self.bus = _Bus(refuses=True)
        self.hold.hold()
        self._connected()
        self.bus.answer()
        self.hold.release()
        self.assertEqual(['Inhibit'], self.bus.methods())
        # And asked again by the next slideshow.
        self.hold.hold()
        self.assertEqual(1, len(self._connect))


@unittest.skipUnless(sys.platform == 'win32', 'SetThreadExecutionState')
class WindowsTest(MComixTest):

    def _state(self):
        """The thread's execution state: setting one answers with the
        one before, so set what release() sets and read the answer."""
        return ctypes.windll.kernel32.SetThreadExecutionState(
            ctypes.c_uint(0x80000000)) & 0xffffffff

    def test_holding_requires_the_display_and_releasing_lets_it_go(self):
        hold = screen_saver.ScreenHold('Slideshow')
        hold.hold()
        self.assertEqual(0x80000002, self._state())
        hold.hold()
        hold.release()
        self.assertEqual(0x80000000, self._state())


# vim: expandtab:sw=4:ts=4
