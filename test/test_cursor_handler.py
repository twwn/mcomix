"""What the pointer looks like over the page area, and when.

The wait cursor is the one of the four kinds MComix defines that nothing
ever asked for: set_cursor_type() had a branch for constants.WAIT_CURSOR
and no caller.  It is set while an archive is being listed now, which is
the one stretch where the window has nothing to show and the reader has
no way of telling that anything is happening.
"""

import unittest

from gi.repository import Gdk

from mcomix import constants
from mcomix import cursor_handler


class _StubWindow:

    """The handler asks its window to draw one cursor and nothing else."""

    def __init__(self):
        self.drawn = []

    def set_layout_cursor(self, cursor):
        self.drawn.append(cursor)


class CursorHandlerTest(unittest.TestCase):

    def setUp(self):
        self.window = _StubWindow()
        self.handler = cursor_handler.CursorHandler(self.window)

    def tearDown(self):
        # A hide timer left running would fire into a torn-down handler.
        self.handler.auto_hide_off()

    def test_a_normal_cursor_is_whatever_the_theme_draws(self):
        self.handler.set_cursor_type(constants.NORMAL_CURSOR)
        self.assertEqual([None], self.window.drawn)

    def test_each_named_cursor_reaches_the_window(self):
        for cursor in (constants.GRAB_CURSOR, constants.WAIT_CURSOR,
                       constants.NO_CURSOR):
            self.window.drawn.clear()
            self.handler.set_cursor_type(cursor)
            self.assertEqual(1, len(self.window.drawn))
            self.assertIsInstance(self.window.drawn[0], Gdk.Cursor)

    def test_a_gdk_cursor_is_used_as_it_is(self):
        cursor = Gdk.Cursor.new_from_name('crosshair', None)
        self.handler.set_cursor_type(cursor)
        self.assertEqual([cursor], self.window.drawn)

    def test_something_that_is_no_cursor_at_all_leaves_the_pointer_alone(self):
        self.handler.set_cursor_type(object())
        self.assertEqual([None], self.window.drawn)

    def test_being_busy_shows_the_wait_cursor(self):
        self.handler.set_busy(True)
        self.assertEqual(constants.WAIT_CURSOR, self.handler._current_cursor)

    def test_no_longer_being_busy_puts_the_normal_cursor_back(self):
        self.handler.set_busy(True)
        self.handler.set_busy(False)
        self.assertEqual(constants.NORMAL_CURSOR,
                         self.handler._current_cursor)

    def test_being_busy_goes_back_to_the_cursor_it_interrupted(self):
        """The magnifying lens hides the pointer, and an archive that
        finishes listing while the lens is up must not bring it back."""
        self.handler.set_cursor_type(constants.NO_CURSOR)
        self.handler.set_busy(True)
        self.assertEqual(constants.WAIT_CURSOR, self.handler._current_cursor)
        self.handler.set_busy(False)
        self.assertEqual(constants.NO_CURSOR, self.handler._current_cursor)

    def test_being_told_twice_over_does_not_lose_what_to_go_back_to(self):
        self.handler.set_cursor_type(constants.GRAB_CURSOR)
        self.handler.set_busy(True)
        self.handler.set_busy(True)
        self.handler.set_busy(False)
        self.assertEqual(constants.GRAB_CURSOR, self.handler._current_cursor)

    def test_clearing_when_nothing_is_busy_does_nothing(self):
        """_close() clears unconditionally, including when no listing was
        running, so this must not put a cursor back over the lens."""
        self.handler.set_cursor_type(constants.NO_CURSOR)
        self.window.drawn.clear()
        self.handler.set_busy(False)
        self.assertEqual([], self.window.drawn)
        self.assertEqual(constants.NO_CURSOR, self.handler._current_cursor)

    def test_the_wait_cursor_stops_the_pointer_hiding_itself(self):
        """In fullscreen the pointer hides after HIDE_DELAY of not moving.
        It must not hide while the program is working, or the reader is
        left with no cursor and no sign of progress."""
        self.handler.auto_hide_on()
        self.assertIsNotNone(self.handler._timer_id,
                             'the normal cursor did not arm the hide timer')
        self.handler.set_busy(True)
        self.assertIsNone(self.handler._timer_id,
                          'the wait cursor left the hide timer running')
        self.handler.set_busy(False)
        self.assertIsNotNone(self.handler._timer_id,
                             'the hide timer was not armed again')


class HandSetCursorTest(unittest.TestCase):

    """Why the slow paths have to go through set_busy().

    Saving an archive used to put the wait cursor straight on the window
    with set_layout_cursor(), which the handler knows nothing about.  The
    pointer hides itself after HIDE_DELAY of not moving - auto_hide_on() is
    called from MainWindow.__init__(), so the timer is armed in every mode
    and not only in fullscreen - and the timer then draws the hidden cursor
    over the wait one.  A save that takes longer than two seconds left the
    reader with no pointer at all and no sign that anything was happening.
    """

    def setUp(self):
        self.window = _StubWindow()
        self.handler = cursor_handler.CursorHandler(self.window)
        self.handler.auto_hide_on()

    def tearDown(self):
        self.handler.auto_hide_off()

    def _names(self):
        return [None if cursor is None else cursor.get_name()
                for cursor in self.window.drawn]

    def test_the_hide_timer_replaces_a_cursor_set_behind_the_handler(self):
        """The defect itself, so that the reason for set_busy() is written
        down rather than taken on trust."""
        self.window.set_layout_cursor(Gdk.Cursor.new_from_name('wait', None))
        self.assertEqual('wait', self._names()[-1])

        # What GLib would call when the timer runs out.
        self.handler._on_timeout()

        self.assertEqual('none', self._names()[-1],
                         'the hide timer left the wait cursor alone')

    def test_set_busy_keeps_the_timer_from_running_at_all(self):
        self.handler.set_busy(True)
        self.assertIsNone(self.handler._timer_id,
                          'the wait cursor left the hide timer armed')
        self.assertEqual('wait', self._names()[-1])

    def test_the_timer_is_armed_again_once_the_work_is_done(self):
        self.handler.set_busy(True)
        self.handler.set_busy(False)
        self.assertIsNotNone(self.handler._timer_id)
        self.assertIsNone(self._names()[-1], 'the normal cursor is not back')

# vim: expandtab:sw=4:ts=4
