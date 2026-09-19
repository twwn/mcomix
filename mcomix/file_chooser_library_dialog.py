"""file_chooser_library_dialog.py - Custom FileChooserDialog implementations."""


from mcomix.preferences import prefs
from mcomix import file_chooser_base_dialog
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library import main_dialog

_library_filechooser_dialog: "_LibraryFileChooserDialog | None" = None


class _LibraryFileChooserDialog(file_chooser_base_dialog._BaseFileChooserDialog):

    """The filechooser dialog used when adding books to the library."""

    # The library files archives, and nothing but.
    _offers_all_files = False

    def __init__(self, library: "main_dialog._LibraryDialog") -> None:
        super().__init__(parent=library)
        self.set_title(_('Add books'))

        self._library = library

        self.filechooser.set_select_multiple(True)
        self.add_archive_filters()
        self.add_pending_filters()

        filters = self.list_filters()
        index = prefs['last filter in library filechooser'] - 1
        self.filechooser.set_filter(
            filters[index] if 0 <= index < len(filters) else filters[0])

        # Buttons that make more sense here than Open.  Gtk.Dialog has
        # no action area to empty in GTK4; place_buttons() puts the row
        # back wherever it went the first time.
        self.place_buttons((_('_Cancel'), Response.CANCEL,
                            _('_Add'), Response.OK))

    def should_open_recursive(self) -> bool:
        return True

    def files_chosen(self, paths: list[str]) -> None:
        if paths:
            # There is nothing to remember while the chooser is showing
            # everything, which is what it does with no filter set.
            # The preference counts from 1, as it did when "All files"
            # came first here: its default, 1, is "All archives", and so
            # is the value every preferences file holds that was written
            # with the default in it.
            chosen = self.filechooser.get_filter()
            filters = self.list_filters()
            if chosen in filters:
                prefs['last filter in library filechooser'] = \
                    filters.index(chosen) + 1

            close_library_filechooser_dialog()
            self._library.add_books(paths, None)

        else:
            close_library_filechooser_dialog()


def open_library_filechooser_dialog(
        library: "main_dialog._LibraryDialog") -> None:
    """Open the library filechooser dialog."""
    global _library_filechooser_dialog

    if _library_filechooser_dialog is None:
        _library_filechooser_dialog = _LibraryFileChooserDialog(library)
    else:
        _library_filechooser_dialog.present()


def close_library_filechooser_dialog(*args: object) -> None:
    """Close the library filechooser dialog."""
    global _library_filechooser_dialog

    if _library_filechooser_dialog is not None:
        _library_filechooser_dialog.destroy()
        _library_filechooser_dialog = None


# vim: expandtab:sw=4:ts=4
