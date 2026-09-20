"""edit_dialog.py - The dialog for the archive editing window."""

import os
from gi.repository import Gio, GLib, Gtk
import re

from mcomix.preferences import prefs
from mcomix.dialog import Dialog
from mcomix import archive_packer
from mcomix import file_chooser_simple_dialog
from mcomix import image_tools
from mcomix import log
from mcomix import column_list
from mcomix import edit_image_area
from mcomix import edit_comment_area
from mcomix import thumbnail_list
from mcomix import tools
from mcomix import widgets
from mcomix import constants
from mcomix import message_dialog
from mcomix import preview
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from mcomix import main

_dialog: "_EditArchiveDialog | None" = None

#: Both of the editor's listings at one moment: the pages, and the files
#: that came with them.  What an undo puts back.
_EditState = tuple[list[thumbnail_list.ThumbnailItem],
                   list[column_list.Row]]


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
        super().__init__(
            title=_('Edit archive'), transient_for=window, modal=True)
        self.add_buttons(_('_Cancel'), Response.CANCEL)

        self._accept_changes_button = self.add_button(_('A_pply'), Response.APPLY)

        self.file_handler = window.filehandler
        self._window = window
        #: What the two listings were before each change, and what they
        #: were before each undo.  A snapshot is the entries themselves,
        #: so nothing a page carries - its thumbnail above all - is made
        #: again when it comes back.
        self._undone: list[_EditState] = []
        self._redone: list[_EditState] = []

        self._save_button = self.add_button(_('Save _As'), constants.RESPONSE_SAVE_AS)

        self._import_button = self.add_button(_('_Import'), constants.RESPONSE_IMPORT)

        widgets.set_border(self, 4)
        # As large on this screen as 750x600 was on the ones MComix
        # was written for; the pages inside follow the screen too.
        self.set_default_size(*_fit_on_screen(preview.scaled(750, self),
                                              preview.scaled(600, self)))

        self.connect('response', self._response)

        # An editor that removes and reorders pages needs a way back.
        # The keys are registered here, on the dialog, so that they work
        # whichever of its two lists has the focus; both lists name them
        # in their right-click menus, which is all the menu there is.
        shortcuts = Gtk.ShortcutController()
        # The unbound methods, handed the editor GTK hands over: GTK
        # holds these where Python's collector cannot see them, and a
        # bound method would keep the editor alive once it is closed.
        for accelerator, step in (('<Control>z', _EditArchiveDialog.undo),
                                  ('<Control>y', _EditArchiveDialog.redo),
                                  ('<Control><Shift>z', _EditArchiveDialog.redo)):
            shortcuts.add_shortcut(Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string(accelerator),
                Gtk.CallbackAction.new(
                    lambda widget, args, step=step:
                    step(cast(_EditArchiveDialog, widget)))))
        self.add_controller(shortcuts)

        self._image_area = edit_image_area._ImageArea(self, window)
        self._comment_area = edit_comment_area._CommentArea(self, window)

        notebook = Gtk.Notebook()
        widgets.set_border(notebook, 6)
        notebook.append_page(self._image_area, Gtk.Label(label=_('Images')))
        notebook.append_page(self._comment_area, Gtk.Label(label=_('Comment files')))
        widgets.pack(self.get_content_area(), notebook, True, True, 0)

        self.set_visible(True)

        # The editor is about the files of one book: its two lists are
        # that book's pages and comment files, extracted to a temporary
        # directory that goes when the book does.  So the editor goes
        # with it, rather than standing over a book that is no longer
        # there - where its save fails on files that have been cleaned
        # up, and Apply would hand the window a listing of them.
        self.file_handler.file_closed += self._on_book_close
        # 'unrealize' rather than 'destroy', which GTK4 emits only when
        # the last reference to the window goes.
        self.connect('unrealize', self._stop_following)

        GLib.idle_add(self._load_original_files)

    def _on_book_close(self) -> None:
        """Close the editor, the book it lists having gone.

        From the idle queue rather than here and now: this runs inside
        the file handler's own call round its listeners, and closing
        takes the editor out of that list while it is being walked,
        which would step over whoever subscribed after it.
        """
        GLib.idle_add(self._close_with_the_book)

    def _close_with_the_book(self) -> bool:
        _forget_dialog(self)
        self.destroy()
        return False

    def _stop_following(self, *args: object) -> None:
        """Stop hearing about the book once the editor has closed.

        A destroyed dialog is not collected - the handlers on its own
        widgets hold it - so one left listening would answer the close
        of every book opened after it.
        """
        self.file_handler.file_closed -= self._on_book_close

    def _load_original_files(self) -> bool:
        """Load the original files from the archive or directory into
        the edit dialog.
        """
        self._save_button.set_sensitive(False)
        self._import_button.set_sensitive(False)
        self._window.cursor_handler.set_busy(True)
        try:
            self._image_area.fetch_images()
            self._comment_area.fetch_comments()
            # The pages the reader picked out in the window are the ones
            # the editor was opened to do something about, so they are
            # picked out here too; what is picked out when it closes
            # goes back the same way.
            self._image_area.select_paths(self._window.selected_page_paths())
        finally:
            # The cursor belongs to the main window rather than to this
            # dialog: whatever gets out of the two calls above, the
            # program must not be left pointing at a wait cursor over an
            # editor that can neither save nor import.
            self._window.cursor_handler.set_busy(False)
            self._save_button.set_sensitive(True)
            self._import_button.set_sensitive(True)

        return False

    def _save_format(self) -> tuple[int, str]:
        """Which format a save writes, and the extension that goes with it.

        A CBZ, as it always was, unless the reader has asked for the
        archive to come back in the format it was opened in and that is
        one MComix can write: a RAR is read with a program that cannot
        make one, a PDF is not a format a book of pages goes back into,
        and a 7z needs 7-Zip installed.
        """
        archive_type = self.file_handler.archive_type
        if (prefs['keep archive format when saving']
                and archive_type is not None
                and archive_packer.can_write(archive_type)):
            source = self.file_handler.get_path_to_base() or ''
            extension = os.path.splitext(source)[1]
            if extension:
                return archive_type, extension
        return constants.ZIP, '.cbz'

    def _pack_archive(self, archive_path: str) -> None:
        """Write the chosen files out as an archive at <archive_path>."""
        self.set_sensitive(False)
        self._window.cursor_handler.set_busy(True)

        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

        # Neither list the editor shows holds what the archive had
        # besides its pages and its comments, and a new archive written
        # without that is not the archive that was opened: it has lost
        # its metadata.
        images = self._image_area.get_file_listing()
        comments = self._comment_area.get_file_listing()
        # The packer reads each file's size before it writes it, so a
        # page or a comment still inside the archive it came from would
        # raise FileNotFoundError and lose the save.
        self.file_handler.wait_for_files(images + comments)

        saved = False
        try:
            archive_packer.write_archive(
                archive_path,
                images,
                comments,
                carried_files=self.file_handler.get_other_files(),
                archive_type=self._save_format()[0],
                permissions_from=self.file_handler.get_path_to_base()
                if self.file_handler.archive_type is not None else None,
                # A page renamed in the window is renamed in whatever
                # the editor writes as well: the two are the same book.
                page_names=self._window.file_actions.page_names(),
                # A comment file is renamed in this editor and nowhere
                # else, so the list itself says what each is called.
                comment_names=self._comment_area.file_names())
            saved = True
        except OSError as error:
            log.error(_('! Could not save the archive %(archivefile)s: '
                        '%(error)s'),
                      {'archivefile': archive_path, 'error': error})
        finally:
            self._window.cursor_handler.set_busy(False)

        if saved:
            _close_dialog()
            return

        dialog = message_dialog.MessageDialog(
            self._window, buttons=Gtk.ButtonsType.CLOSE)
        dialog.set_text(
            _("The new archive could not be saved!"),
            _("The original files have not been removed."))
        dialog.run_async(lambda response: self.set_sensitive(True))

    # -- Taking a change back ---------------------------------------------

    def _state(self) -> "_EditState":
        """Both listings as they stand."""
        return (self._image_area.snapshot(), self._comment_area.snapshot())

    def _restore(self, state: "_EditState") -> None:
        images, comments = state
        self._image_area.restore(images)
        self._comment_area.restore(comments)

    def record_change(self) -> None:
        """Remember both listings, before something changes one of them.

        Called by whatever is about to make the change, so that the
        state remembered is the one an undo has to put back.  A fresh
        change is the end of whatever was undone before it: there is no
        longer a redo to arrive at.
        """
        self._undone.append(self._state())
        self._redone.clear()

    def undo(self) -> bool:
        """Put the listings back as they were before the last change."""
        if not self._undone:
            return False
        self._redone.append(self._state())
        self._restore(self._undone.pop())
        return True

    def redo(self) -> bool:
        """Make the last undone change again."""
        if not self._redone:
            return False
        self._undone.append(self._state())
        self._restore(self._redone.pop())
        return True

    # -- Adding files -----------------------------------------------------

    def _import_files(self, paths: list[str]) -> None:
        """Add the chosen <paths> to the archive being edited."""
        # The extensions are read as text, not as a pattern: see
        # FileHandler.update_comment_extensions().
        comment_re = re.compile(
            r'\.' + tools.fixed_strings_regex(prefs['comment extensions'])
            + r'\s*$', re.I)

        images = [path for path in paths if image_tools.is_image_file(path)]
        comments = [path for path in paths
                    if path not in images and os.path.isfile(path)
                    and comment_re.search(path)]
        if not images and not comments:
            return

        # One change, however many files were chosen, so that a single
        # undo takes the whole import back.
        self.record_change()
        for path in images:
            self._image_area.add_extra_image(path)
        for path in comments:
            self._comment_area.add_extra_file(path)

    def _response(self, dialog: Dialog, response: int) -> None:

        if response == constants.RESPONSE_SAVE_AS:

            # There is an archive to save under another name whenever
            # this dialog is open at all.
            src_path = self.file_handler.get_path_to_base() or ''
            archive_type, extension = self._save_format()

            chooser = file_chooser_simple_dialog.SimpleFileChooserDialog(
                Gtk.FileChooserAction.SAVE, self,
                folder=os.path.dirname(src_path))

            chooser.set_save_name('%s%s' % (os.path.splitext(
                os.path.basename(src_path))[0], extension))
            # The note says what a save writes whatever was opened.  It
            # is left off only where the reader has asked for the format
            # to be kept and it is being kept: there it says nothing
            # that the name above it does not.
            if (archive_type != self.file_handler.archive_type
                    or not prefs['keep archive format when saving']):
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

            picked_out = self._image_area.selected_paths()
            self._window.pages_replaced(self._image_area.get_file_listing())
            self._window.select_page_paths(picked_out)

        else:
            _close_dialog()

    def destroy(self) -> None:
        # What is picked out here is picked out in the window when the
        # editor closes, whether the listing was applied or not: a
        # selection is not a change to the book, and carrying it back is
        # what lets the two be used together.
        self._window.select_page_paths(self._image_area.selected_paths())
        self._image_area.cleanup()
        # The snapshots hold the pages' entries, thumbnails and all, and
        # a closed editor is never collected (see _ImageArea.cleanup()).
        self._undone.clear()
        self._redone.clear()
        Dialog.destroy(self)


def open_dialog(action: Gio.SimpleAction, window: "main.MainWindow") -> None:
    global _dialog

    if _dialog is None:
        _dialog = _EditArchiveDialog(window)
    else:
        _dialog.present()


def _close_dialog(*args: object) -> None:
    global _dialog

    if _dialog is not None:
        _dialog.destroy()
        _dialog = None


def _forget_dialog(dialog: "_EditArchiveDialog") -> None:
    """Let go of <dialog> if it is the one the menu entry opens.

    An editor that closes itself has to say so here, or the menu would
    go on presenting the window that has gone.
    """
    global _dialog

    if _dialog is dialog:
        _dialog = None

# vim: expandtab:sw=4:ts=4
