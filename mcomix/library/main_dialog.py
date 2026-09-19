"""main_dialog.py - The library window itself.

The window that holds the other three areas of the library - the
collection tree, the grid of covers and the control strip - in a grid,
and owns the backend they all read through.  It is also what adds books
to the library, through the progress dialog, and what opens one in the
main window.
"""

import os
from gi.repository import Gdk, Gio, Gtk

from mcomix.preferences import prefs
from mcomix import i18n
from mcomix import tools
from mcomix import file_chooser_library_dialog
from mcomix import status
from mcomix import widgets
from mcomix.library import backend as library_backend
from mcomix.library import book_area as library_book_area
from mcomix.library import collection_area as library_collection_area
from mcomix.library import control_area as library_control_area
from mcomix.library import add_progress_dialog as library_add_progress_dialog
from mcomix.i18n import _

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import file_handler as file_handler_module
    from mcomix import main
    from mcomix.library import backend_types

_dialog: "_LibraryDialog | None" = None


class _LibraryDialog(Gtk.Window):

    """The library window, and the backend the areas in it read through.

    Opening one opens the library database: LibraryBackend() hands out
    the one connection there is, and close() closes it again.
    """

    def __init__(self, window: "main.MainWindow",
                 file_handler: "file_handler_module.FileHandler") -> None:
        super().__init__()

        self.main_window = window

        self.set_default_size(prefs['lib window width'],
                              prefs['lib window height'])
        self.set_title(_('Library'))
        self.connect('close-request', self.close)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press_event)
        self.add_controller(keys)
        # As every MComix dialog does: GTK never disposes a closed
        # window's widgets, and what they hold would keep this one alive.
        self.connect_after('unrealize', widgets.release)

        self.filter_string: str | None = None
        self._file_handler = file_handler
        # Gtk.Statusbar is deprecated as of GTK 4.10; the one message this
        # ever shows is a label's worth.
        self._statusbar = Gtk.Label()
        self._statusbar.set_xalign(0)
        self.backend = library_backend.LibraryBackend()
        self.book_area = library_book_area._BookArea(self)
        self.control_area = library_control_area._ControlArea(self)
        self.collection_area = library_collection_area._CollectionArea(self)

        self.backend.watchlist.new_files_found += self._new_files_found
        self.backend.watchlist.scan_finished += self._scan_finished
        #: How many scans are walking the watch list right now.  The
        #: watch list dialog can start one while the one the library
        #: opened with is still running, and the pointer goes back to
        #: normal when the last of them is over, not the first.
        self._scans_running = 0

        grid = Gtk.Grid()
        for child, column, row, width, height, hexpand, vexpand in (
                (self.collection_area, 0, 0, 1, 1, False, True),
                (self.book_area,       1, 0, 1, 1, True,  True),
                (self.control_area,    0, 1, 2, 1, True,  False),
        ):
            child.set_hexpand(hexpand)
            child.set_vexpand(vexpand)
            grid.attach(child, column, row, width, height)

        if prefs['show statusbar']:
            self._statusbar.set_hexpand(False)
            self._statusbar.set_vexpand(False)
            grid.attach(self._statusbar, 0, 2, 2, 1)

        self.set_child(grid)
        self.set_visible(True)
        self.present()

    def open_book(self, books: Sequence[int],
                  keep_library_open: bool = False) -> None:
        """Open the books whose ids are in <books>, in the main window.

        More than one is opened as a book of its own pages, in the order
        given.  The library window hides itself unless
        <keep_library_open> says otherwise.
        """

        # get_book_path() answers None for a book that is no longer in
        # the library, which is nothing to hand the file handler.
        paths = [path for path in map(self.backend.get_book_path, books)
                 if path is not None]

        if not keep_library_open:
            self.set_visible(False)

        self.main_window.present()

        if len(paths) > 1:
            self._file_handler.open_file(paths)
        elif len(paths) == 1:
            self._file_handler.open_file(paths[0])

    def scan_for_new_files(self) -> None:
        """ Start scanning for new files from the watch list. """

        if self.backend.watchlist.get_watchlist():
            self.set_status_message(_("Scanning for new books..."))
            self._scans_running += 1
            self.set_busy(True)
            self.backend.watchlist.scan_for_new_files()

    def _scan_finished(self) -> None:
        """Bound to the watch list's scan_finished: a walk is over.

        Whether it found anything is _new_files_found()'s business; this
        is only about the pointer, which has been saying the library is
        working since the scan started and may not stop while a second
        scan is still going.
        """
        self._scans_running = max(0, self._scans_running - 1)
        if not self._scans_running:
            self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        """Show the wait pointer over the library window, or stop.

        The main window has a cursor handler, but it draws on the page
        area of that window, which a reader looking at the library is
        not looking at.  A pointer over this window is this window's to
        set, and it goes back to inheriting whatever the widget under it
        asks for rather than to a cursor of its own.
        """
        self.set_cursor(Gdk.Cursor.new_from_name('wait', None)
                        if busy else None)

    def _new_files_found(self, filelist: Sequence[str],
                         watchentry: "backend_types._WatchListEntry") -> None:
        """ Called after the scan for new files finished. """

        if filelist:
            # A watch list entry that has been removed keeps its
            # directory but no longer names a collection.
            collection = watchentry.collection
            if collection is not None and collection.id is not None:
                collection_name = collection.name
            else:
                collection_name = None

            self.add_books(filelist, collection_name)

            if len(filelist) == 1:
                message = _("Added new book '%(bookname)s' "
                            "from directory '%(directory)s'.")
            else:
                message = _("Added %(count)d new books "
                            "from directory '%(directory)s'.")

            self.set_status_message(message % {'directory': watchentry.directory,
                                               'count': len(filelist), 'bookname': os.path.basename(filelist[0])})
        else:
            self.set_status_message(
                _("No new books found in directory '%s'.") % watchentry.directory)

    def set_status_message(self, message: str) -> None:
        """Set a specific message on the statusbar, replacing whatever was
        there earlier.
        """
        self._statusbar.set_text(
            ' ' * status.Statusbar.SPACING + '%s' % i18n.to_unicode(message))

    def close(self, *args: object) -> None:
        """Close the library and do required cleanup tasks."""
        if self.get_width() and self.get_height():
            prefs['lib window width'] = self.get_width()
            prefs['lib window height'] = self.get_height()
        self.backend.watchlist.new_files_found -= self._new_files_found
        self.backend.watchlist.scan_finished -= self._scan_finished
        self.book_area.stop_update()
        self.book_area.close()
        file_chooser_library_dialog.close_library_filechooser_dialog()
        _close_dialog()

    def add_books(self, paths: Sequence[str],
                  collection_name: str | None = None) -> None:
        """Add the books at <paths> to the library. If <collection_name>
        is not None, it is the name of a (new or existing) collection the
        books should be put in.
        """
        if collection_name is None:
            collection_id = self.collection_area.get_current_collection()
        else:
            collection = self.backend.get_collection_by_name(collection_name)

            if collection is not None:
                collection_id = collection.id
            else:
                # Collection by that name doesn't exist.  add_collection()
                # answers None if it could not add one either, and the
                # books then go into no collection rather than nowhere.
                collection_id = self.backend.add_collection(collection_name)

        library_add_progress_dialog._AddLibraryProgressDialog(self, paths, collection_id)

        if collection_id is not None:
            prefs['last library collection'] = collection_id

    def _key_press_event(self, controller: Gtk.EventControllerKey,
                         keyval: int, keycode: int,
                         state: Gdk.ModifierType) -> bool:
        """ Handle key press events for closing the library on Escape press. """

        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE


def open_dialog(action: Gio.SimpleAction, window: "main.MainWindow") -> None:
    """ Shows the library window. """
    global _dialog

    if _dialog is None:
        _dialog = _LibraryDialog(window, window.filehandler)
    else:
        _dialog.present()

    if prefs['scan for new books on library startup']:
        _dialog.scan_for_new_files()


def _close_dialog(*args: object) -> None:
    global _dialog

    if _dialog is not None:
        _dialog.destroy()
        _dialog = None
        tools.garbage_collect()

# vim: expandtab:sw=4:ts=4
