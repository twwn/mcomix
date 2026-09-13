"""cursor_handler.py - Cursor handler."""

from gi.repository import Gdk, GLib

from mcomix import constants

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main

class CursorHandler:

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        self._timer_id: int | None = None
        self._auto_hide = False
        self._current_cursor: "int | Gdk.Cursor" = constants.NORMAL_CURSOR

    def set_cursor_type(self, cursor: "int | Gdk.Cursor") -> None:
        """Set the cursor to type <cursor>. Supported cursor types are
        available as constants in this module. If <cursor> is not one of the
        cursor constants above, it must be a Gdk.Cursor.
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
        self._timer_id = GLib.timeout_add(2000, self._on_timeout)

    def _kill_timer(self) -> None:
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _get_hidden_cursor(self) -> "Gdk.Cursor | None":
        # Gdk.CursorType is gone in GTK4; cursors go by the name the
        # theme knows them under, and 'none' is the blank one.
        return Gdk.Cursor.new_from_name('none', None)


# vim: expandtab:sw=4:ts=4
