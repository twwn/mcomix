"""file_chooser_main_dialog.py - Custom FileChooserDialog implementations."""


from gi.repository import Gio, Gtk

from mcomix.preferences import prefs
from mcomix import file_chooser_base_dialog
from mcomix import file_provider

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main

_main_filechooser_dialog: "_MainFileChooserDialog | None" = None


class _MainFileChooserDialog(file_chooser_base_dialog._BaseFileChooserDialog):

    """The normal filechooser dialog used with the "Open" menu item."""

    def __init__(self, window: "main.MainWindow") -> None:
        super().__init__(parent=window)
        self._window = window
        self.filechooser.set_select_multiple(True)
        self.add_archive_filters()
        self.add_image_filters()
        self.add_pending_filters()
        filters = self.list_filters()
        try:
            # The remembered filter is an index into the list, and the
            # list is built afresh from what MComix can open: an index
            # written by a build with more formats in it names nothing
            # here, and the first filter, "All files", stands in.
            self.filechooser.set_filter(filters[
                prefs['last filter in main filechooser']])
        except IndexError:
            self.filechooser.set_filter(filters[0])

    def folder_opens_as_itself(self, folder: str,
                               ffilter: "Gtk.FileFilter | None") -> bool:
        """A folder chosen by itself is opened as the folder, as one
        named on the command line is: the book is listed afresh as it
        is read, a page turn past its end walks on to the folder beside
        it, and the folders in it are read with it where the
        preferences say so.

        Only where that opens what the chooser showed: the filter hides
        none of the files that make the book, the folder's pictures or,
        where it has none, its archives.  Otherwise the files it does
        show are opened, and no others.
        """
        try:
            provider = file_provider.OrderedFileProvider(folder)
        except ValueError:
            # Gone since it was chosen.
            return False
        for mode in (file_provider.FileProvider.IMAGES,
                     file_provider.FileProvider.ARCHIVES):
            book = provider.list_files(mode)
            if book:
                return all(self._matches(ffilter, path) for path in book)
        return False

    def files_chosen(self, paths: list[str]) -> None:
        if paths:
            # There is nothing to remember while the chooser is showing
            # everything, which is what it does with no filter set.
            chosen = self.filechooser.get_filter()
            filters = self.list_filters()
            if chosen in filters:
                prefs['last filter in main filechooser'] = filters.index(chosen)
            _close_main_filechooser_dialog()

            # If more than one file is selected, restrict opening
            # further files to the selection.
            files: "str | list[str]" = paths if len(paths) > 1 else paths[0]

            self._window.filehandler.open_file(files)
        else:
            _close_main_filechooser_dialog()


def open_main_filechooser_dialog(action: Gio.SimpleAction,
                                 window: "main.MainWindow") -> None:
    """Open the main filechooser dialog."""
    global _main_filechooser_dialog
    if _main_filechooser_dialog is None:
        _main_filechooser_dialog = _MainFileChooserDialog(window)
    else:
        _main_filechooser_dialog.present()


def _close_main_filechooser_dialog(*args: object) -> None:
    """Close the main filechooser dialog."""
    global _main_filechooser_dialog
    if _main_filechooser_dialog is not None:
        _main_filechooser_dialog.destroy()
        _main_filechooser_dialog = None

# vim: expandtab:sw=4:ts=4
