"""cursor_handler.py - Cursor handler."""

from gi.repository import Gdk, GLib

from mcomix import constants

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


class CursorHandler:

    """What the pointer looks like over the page area.

    In fullscreen the cursor hides itself after a while of not moving, and
    _current_cursor is what was last *asked* for rather than what is drawn:
    the hide timer changes the pointer without going through
    set_cursor_type(), so that a move of the mouse can put back what the
    program wanted rather than the blank one the timer left.
    """

    #: How long the pointer stays visible after it stops moving, in
    #: milliseconds, while it is hiding itself.
    HIDE_DELAY = 2000

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        self._timer_id: int | None = None
        self._auto_hide = False
        self._current_cursor: "int | Gdk.Cursor" = constants.NORMAL_CURSOR
        #: What set_busy() goes back to when the work is done.
        self._cursor_before_busy: "int | Gdk.Cursor" = constants.NORMAL_CURSOR

    def set_cursor_type(self, cursor: "int | Gdk.Cursor") -> None:
        """Draw the pointer as <cursor> over the page area.

        <cursor> is one of the NORMAL_CURSOR, GRAB_CURSOR, WAIT_CURSOR and
        NO_CURSOR constants in mcomix.constants, or a Gdk.Cursor to use as
        it is.  Anything else leaves the pointer as the theme draws it.
        """
        mode: "Gdk.Cursor | None"
        if cursor == constants.NORMAL_CURSOR:
            mode = None
        elif cursor == constants.GRAB_CURSOR:
            mode = Gdk.Cursor.new_from_name('move', None)
        elif cursor == constants.WAIT_CURSOR:
            mode = Gdk.Cursor.new_from_name('wait', None)
        elif cursor == constants.NO_CURSOR:
            mode = self._get_hidden_cursor()
        elif isinstance(cursor, Gdk.Cursor):
            mode = cursor
        else:
            # Not one of the constants above and not a cursor either;
            # the pointer keeps whatever the theme draws it as.
            mode = None

        self._window.set_layout_cursor(mode)

        self._current_cursor = cursor

        if self._auto_hide:

            if cursor == constants.NORMAL_CURSOR:
                self._set_hide_timer()
            else:
                self._kill_timer()

    def set_busy(self, busy: bool) -> None:
        """Show the wait cursor while the program is working, or stop.

        What it goes back to is what was asked for before rather than the
        normal cursor, because the pointer is not always normal when the
        work starts: the magnifying lens hides it, and an archive that
        finishes listing while the lens is up must not bring it back.

        Asking twice over does not lose the cursor to go back to, and
        clearing when nothing is busy does nothing at all, so a caller that
        abandons the work it started can clear unconditionally.
        """
        if busy:
            if self._current_cursor != constants.WAIT_CURSOR:
                self._cursor_before_busy = self._current_cursor
                self.set_cursor_type(constants.WAIT_CURSOR)
        elif self._current_cursor == constants.WAIT_CURSOR:
            self.set_cursor_type(self._cursor_before_busy)

    def auto_hide_on(self) -> None:
        """Signal that the cursor should auto-hide from now on (e.g. that
        we are entering fullscreen).
        """
        self._auto_hide = True

        if self._current_cursor == constants.NORMAL_CURSOR:
            self._set_hide_timer()

    def auto_hide_off(self) -> None:
        """Signal that the cursor should *not* auto-hide from now on."""
        self._auto_hide = False
        self._kill_timer()

        if self._current_cursor == constants.NORMAL_CURSOR:
            self.set_cursor_type(constants.NORMAL_CURSOR)

    def refresh(self) -> None:
        """Refresh the current cursor (i.e. display it and set a new timer in
        fullscreen). Used when we move the cursor.
        """
        if self._auto_hide:
            self.set_cursor_type(self._current_cursor)

    def _on_timeout(self) -> bool:
        mode = self._get_hidden_cursor()
        self._window.set_layout_cursor(mode)
        self._timer_id = None
        return False

    def _set_hide_timer(self) -> None:
        self._kill_timer()
        self._timer_id = GLib.timeout_add(self.HIDE_DELAY, self._on_timeout)

    def _kill_timer(self) -> None:
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _get_hidden_cursor(self) -> "Gdk.Cursor | None":
        # Cursors go by the name the theme knows them under, and 'none'
        # is the blank one.  None comes back for a name the theme does
        # not know, and leaves the pointer as it is rather than hiding it.
        return Gdk.Cursor.new_from_name('none', None)


# vim: expandtab:sw=4:ts=4
