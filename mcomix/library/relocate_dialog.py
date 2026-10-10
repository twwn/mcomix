"""relocate_dialog.py - The question of where a folder of books has gone.

The library holds a book by its path, so a folder of them that was
moved or renamed outside MComix leaves every one pointing at a file
that is not there.  This asks which folder the books were in and which
they are in now; _LibraryDialog.relocate_books() is what follows them.
"""

import os
from gi.repository import Gio, GLib, Gtk

from mcomix import message_dialog
from mcomix import tools
from mcomix.dialog import Response
from mcomix.i18n import _

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library import backend as library_backend
    from mcomix.library import main_dialog


def folder_gone(backend: "library_backend._LibraryBackend") -> str:
    """The folder the books whose files are gone were in, or nothing.

    Nothing where no file is gone, and nothing where the folder they
    share still holds a book that is there: relocating takes every book
    under the folder with it, so a folder offered without being asked
    for must be one that has gone whole.
    """
    gone: list[str] = []
    there: list[str] = []
    for _book, path in backend.get_book_paths_in_collection():
        if path:
            (there if os.path.isfile(path) else gone).append(path)
    if not gone:
        return ''
    try:
        folder = os.path.commonpath([os.path.dirname(path) for path in gone])
    except ValueError:
        # On Windows, books on different drives share no folder.
        return ''
    prefix = tools.folder_prefix(folder)
    if folder == os.path.dirname(folder) or any(
            path.startswith(prefix) for path in there):
        return ''
    return folder


class RelocateDialog(message_dialog.MessageDialog):

    """Asks for the folder a shelf of books was in and the one it is in
    now, and has the library follow the books when it is answered OK."""

    def __init__(self, library: "main_dialog._LibraryDialog") -> None:
        super().__init__(library, buttons=Gtk.ButtonsType.OK_CANCEL,
                         modal=True, destroy_with_parent=True)
        self._library = library
        self.set_default_response(Response.OK)
        self.set_text(_('Relocate books?'), self.explanation())
        # Two sentences on one line made the dialog as wide as the line,
        # 1025 pixels; wrapping alone asks for no less.
        self._secondary.set_max_width_chars(60)

        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        self._old = self._folder_entry(grid, 0, _('The books were in:'))
        self._new = self._folder_entry(grid, 1, _('They are now in:'))
        browse = Gtk.Button.new_from_icon_name('folder-open-symbolic')
        browse.set_tooltip_text(_('Select a Folder'))
        browse.connect('clicked', self._browse)
        grid.attach(browse, 2, 1, 1, 1)
        self.get_content_area().append(grid)

        self._old.set_text(folder_gone(library.backend))
        self._folders_changed()
        # The folder to type is the one that is missing.
        (self._new if self._old.get_text() else self._old).grab_focus()
        self.run_async(self._answered)

    @staticmethod
    def explanation() -> str:
        """What relocating does, as the dialog and the menu say it."""
        return _('Tells the library where a folder of books has been moved '
                 'to. The books keep their collections, their bookmarks '
                 'and the pages they were read to.')

    def _folder_entry(self, grid: Gtk.Grid, row: int, text: str) -> Gtk.Entry:
        """A labelled entry for a folder in <row> of <grid>."""
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_width_chars(40)
        entry.set_activates_default(True)
        entry.connect('changed', self._folders_changed)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(entry, 1, row, 1, 1)
        return entry

    def folders(self) -> tuple[str, str]:
        """The folder the books were in and the one they are in now, as
        typed, less the spaces around them and with a leading ~ read as
        the home directory."""
        return (os.path.expanduser(self._old.get_text().strip()),
                os.path.expanduser(self._new.get_text().strip()))

    def _folders_changed(self, *args: object) -> None:
        """Offer OK only for a move there is something to follow by:
        from a folder named in full, into another that is there."""
        old, new = self.folders()
        self.set_response_sensitive(
            Response.OK, os.path.isabs(old) and os.path.isabs(new)
            and os.path.isdir(new)
            and tools.folder_prefix(old) != tools.folder_prefix(new))

    def _browse(self, *args: object) -> None:
        """Pick the folder the books are in now from a file chooser."""
        chooser = Gtk.FileDialog(modal=True, title=_('Select a Folder'))
        new = self.folders()[1]
        if os.path.isdir(new):
            chooser.set_initial_folder(Gio.File.new_for_path(new))
        chooser.select_folder(self, None, self._folder_chosen)

    def _folder_chosen(self, chooser: Gtk.FileDialog,
                       result: Gio.AsyncResult) -> None:
        """Write the folder the file chooser came back with."""
        try:
            chosen = chooser.select_folder_finish(result)
        except GLib.Error:
            # The only thing it fails with is the user closing it.
            return
        path = chosen.get_path() if chosen is not None else None
        if path:
            self._new.set_text(path)

    def _answered(self, response: int) -> None:
        if response == Response.OK:
            self._library.relocate_books(*self.folders())


# vim: expandtab:sw=4:ts=4
