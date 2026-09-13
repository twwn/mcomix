"""edit_dialog.py - The dialog for the archive editing window."""

import os
import tempfile
from gi.repository import Gdk, Gio, GLib, Gtk
import re

from mcomix.preferences import prefs
from mcomix.dialog import Dialog
from mcomix import archive_packer
from mcomix import file_chooser_simple_dialog
from mcomix import image_tools
from mcomix import edit_image_area
from mcomix import edit_comment_area
from mcomix import widgets
from mcomix import constants
from mcomix import message_dialog
from mcomix import preview
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main

_dialog: "_EditArchiveDialog | None" = None

def _fit_on_screen(width: int, height: int) -> tuple[int, int]:
    """Return (<width>, <height>), trimmed to fit on the monitor."""
    monitors = widgets.display().get_monitors()
    monitor = monitors.get_item(0) if monitors.get_n_items() else None
    if monitor is None:
        return width, height
    geometry = monitor.get_geometry()
    return (min(geometry.width - 50, width), min(geometry.height - 50, height))


class _EditArchiveDialog(Dialog):

    """The _EditArchiveDialog lets users edit archives (or directories) by
    reordering images and removing and adding images or comment files. The
    result can be saved as a ZIP archive.
    """

    def __init__(self, window: "main.MainWindow") -> None:
        super(_EditArchiveDialog, self).__init__(
            title=_('Edit archive'), transient_for=window, modal=True)
        self.add_buttons(_('_Cancel'), Response.CANCEL)

        self._accept_changes_button = self.add_button(_('_Apply'), Response.APPLY)

        self.kill = False # Dialog is killed.
        self.file_handler = window.filehandler
        self._window = window
        self._imported_files: list[str] = []

        self._save_button = self.add_button(_('Save _As'), constants.RESPONSE_SAVE_AS)

        self._import_button = self.add_button(_('_Import'), constants.RESPONSE_IMPORT)

        widgets.set_border(self, 4)
        # Gdk.Screen is gone in GTK4; a display has monitors, and a
        # window asks for a size rather than being given one.
        # As large on this screen as 750x600 was on the ones MComix
        # was written for; the pages inside follow the screen too.
        self.set_default_size(*_fit_on_screen(preview.scaled(750, self),
                                              preview.scaled(600, self)))

        self.connect('response', self._response)

        self._image_area = edit_image_area._ImageArea(self, window)
        self._comment_area = edit_comment_area._CommentArea(self)

        notebook = Gtk.Notebook()
        widgets.set_border(notebook, 6)
        notebook.append_page(self._image_area, Gtk.Label(label=_('Images')))
        notebook.append_page(self._comment_area, Gtk.Label(label=_('Comment files')))
        widgets.pack(self.get_content_area(), notebook, True, True, 0)

        self.set_visible(True)

        GLib.idle_add(self._load_original_files)

    def _load_original_files(self) -> bool:
        """Load the original files from the archive or directory into
        the edit dialog.
        """
        self._save_button.set_sensitive(False)
        self._import_button.set_sensitive(False)
        self._window.set_layout_cursor(Gdk.Cursor.new_from_name('wait', None))
        self._image_area.fetch_images()

        if self.kill: # fetch_images() allows pending events to be handled.
            return False

        self._comment_area.fetch_comments()
        self._window.set_layout_cursor(None)
        self._save_button.set_sensitive(True)
        self._import_button.set_sensitive(True)

        return False

    def _pack_archive(self, archive_path: str) -> None:
        """Create a new archive with the chosen files."""
        self.set_sensitive(False)
        self._window.set_layout_cursor(Gdk.Cursor.new_from_name('wait', None))

        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

        image_files = self._image_area.get_file_listing()
        comment_files = self._comment_area.get_file_listing()

        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix='.%s' % os.path.basename(archive_path),
                prefix='tmp.', dir=os.path.dirname(archive_path))
            # Close open tempfile handle (writing is handled by the packer)
            os.close(fd)
            fail = False

        except:
            fail = True

        if not fail:
            packer = archive_packer.Packer(image_files, comment_files, tmp_path,
                os.path.splitext(os.path.basename(archive_path))[0])
            packer.pack()
            packing_success = packer.wait()

            if packing_success:
                # Preserve permissions if currently edited files come from an archive
                base_path = self._window.filehandler.get_path_to_base()
                if (self._window.filehandler.archive_type is not None
                        and base_path is not None
                        and os.path.exists(base_path)):
                    mode = os.stat(base_path).st_mode
                else:
                    mode = os.stat(tmp_path).st_mode

                # Remove existing file (Win32 fails on rename otherwise)
                if os.path.exists(archive_path):
                    os.unlink(archive_path)

                os.rename(tmp_path, archive_path)
                os.chmod(archive_path, mode)

                _close_dialog()
            else:
                fail = True
        
        self._window.set_layout_cursor(None)
        if fail:
            dialog = message_dialog.MessageDialog(
                self._window, buttons=Gtk.ButtonsType.CLOSE)
            dialog.set_text(
                _("The new archive could not be saved!"),
                _("The original files have not been removed."))
            dialog.run_async(lambda response: self.set_sensitive(True))

    def _import_files(self, paths: list[str]) -> None:
        """Add the chosen <paths> to the archive being edited."""
        exts = '|'.join(prefs['comment extensions'])
        comment_re = re.compile(r'\.(%s)\s*$' % exts, re.I)

        for path in paths:

            if image_tools.is_image_file(path):
                self._imported_files.append( path )
                self._image_area.add_extra_image(path)

            elif os.path.isfile(path):

                if comment_re.search( path ):
                    self._imported_files.append( path )
                    self._comment_area.add_extra_file(path)

    def _response(self, dialog: Dialog, response: int) -> None:

        if response == constants.RESPONSE_SAVE_AS:

            # There is an archive to save under another name whenever
            # this dialog is open at all.
            src_path = self.file_handler.get_path_to_base() or ''

            chooser = file_chooser_simple_dialog.SimpleFileChooserDialog(
                Gtk.FileChooserAction.SAVE, self,
                folder=os.path.dirname(src_path))

            chooser.set_save_name('%s.cbz' % os.path.splitext(
                os.path.basename(src_path))[0])
            chooser.set_note(_('Archives are stored as ZIP files.'))
            chooser.add_archive_filters()

            def save_as_chosen(paths: list[str]) -> None:
                chooser.destroy()
                if paths:
                    self._pack_archive(paths[0])

            chooser.run_async(save_as_chosen)

        elif response == constants.RESPONSE_IMPORT:

            chooser = file_chooser_simple_dialog.SimpleFileChooserDialog(parent=self)
            chooser.add_image_filters()

            def import_chosen(paths: list[str]) -> None:
                chooser.destroy()
                self._import_files(paths)

            chooser.run_async(import_chosen)

        elif response == Response.APPLY:

            old_image_array = self._window.imagehandler._image_files or []

            new_image_array = self._image_area.get_file_listing()

            new_positions = []

            end_index = len(old_image_array) - 1

            for image_path in old_image_array:

                try:
                    new_position = new_image_array.index( image_path )
                    new_positions.append(new_position)
                except ValueError:
                    # the path was not found in the new array so that means it was deleted
                    new_positions.append(end_index)
                    end_index -= 1

            self._window.imagehandler.set_image_files(new_image_array)
            self._window.imagehandler._raw_pixbufs = {}
            self._window.imagehandler.do_cacheing()
            self._window.thumbnailsidebar.clear()
            self._window.set_page(1)
            self._window.thumbnailsidebar.load_thumbnails()

        else:
            _close_dialog()
            self.kill = True

    def destroy(self) -> None:
        self._image_area.cleanup()
        Dialog.destroy(self)

def open_dialog(action: Gio.SimpleAction, window: "main.MainWindow") -> None:
    global _dialog

    if _dialog is None:
        _dialog = _EditArchiveDialog(window)
    else:
        _dialog.present()


def _close_dialog(*args: Any) -> None:
    global _dialog

    if _dialog is not None:
        _dialog.destroy()
        _dialog = None

# vim: expandtab:sw=4:ts=4
