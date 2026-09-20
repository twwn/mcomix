"""file_actions.py - What the reader can do to the files of the open book.

Saving a page out of the book, deleting one, moving the book itself,
writing the archive again after a change, and the undo stack all of that
is taken back through.  This is a collaborator of MainWindow rather than
more of it: the window is drawing, layout and navigation, and these are
the methods that touch the files on disk.  They reach the window for the
book that is open, for the pages picked out of it and for the page a
popup menu was opened over, and for nothing else.
"""

import errno
import os
import shutil

from gi.repository import Gtk

from mcomix import archive_packer
from mcomix import bookmark_backend
from mcomix import constants
from mcomix import file_chooser_simple_dialog
from mcomix import file_mover
from mcomix import i18n
from mcomix import log
from mcomix import message_dialog
from mcomix import tools
from mcomix.dialog import Response
from mcomix.i18n import _
from mcomix.library import backend
from mcomix.preferences import prefs

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


class FileActions:

    """The file operations MainWindow offers, and their undo stack."""

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        #: What the pages were before each change made from the window,
        #: and what they were before each undo.  Deleting a page from
        #: the book being read has to be as easy to take back as it was
        #: to do.
        self._undone: list[list[str]] = []
        self._redone: list[list[str]] = []

    def forget_changes(self) -> None:
        """Drop the undo stack, which belongs to the book that is going."""
        self._undone.clear()
        self._redone.clear()

    def delete_page(self, page: "int | None" = None) -> bool:
        """Take pages out of the book being read, and say whether any went.

        <page>, or every page that is picked out where none is named.
        The book in the window is what changes; the archive on disk is
        not written until it is saved, and the last page of a book is
        not removed, a book with no pages being no book.
        """
        if not self.remove_pages({page} if page is not None
                                  else self._window.selected_pages):
            return False
        self.offer_to_save()
        return True

    def remove_pages(self, numbers: "Iterable[int]") -> bool:
        """Take the pages at <numbers> out, and say whether any went."""
        listing = self._window.imagehandler.get_image_files()
        going = {number for number in numbers if 1 <= number <= len(listing)}
        if not going or len(listing) <= len(going):
            return False
        self._undone.append(list(listing))
        self._redone.clear()
        # Highest first: removing one moves every page after it up, so
        # taking them in the other order would take the wrong ones.
        for number in sorted(going, reverse=True):
            del listing[number - 1]
        # What is left picked out has moved up by however many of the
        # pages that went stood in front of it.
        self._window.selected_pages = {
            number - sum(1 for gone in going if gone < number)
            for number in self._window.selected_pages - going}
        self._show_pages(listing, min(min(going), len(listing)))
        return True

    def _show_pages(self, listing: list[str], page: int) -> None:
        """Draw the book as <listing>, standing on <page>."""
        self._window.selected_pages = {number for number in self._window.selected_pages
                               if number <= len(listing)}
        self._window.pages_replaced(listing, page)

    # -- Writing the book back over the archive it came from --------------

    def writeable_archive_type(self) -> "int | None":
        """The format the open book can be written back over itself as.

        None where it cannot be.  Writing in place keeps the name the
        file has, so it has to keep the format that name says: a book
        MComix cannot write - a PDF, or a RAR on a machine without the
        rar program - has nothing that can be written over it, and a
        format other than ZIP is only written where the reader has asked
        for the format to be kept, since otherwise a save would put a
        ZIP inside a file still called .cbt.
        """
        archive_type = self._window.filehandler.archive_type
        if archive_type is None or not archive_packer.can_write(archive_type):
            return None
        if archive_type in (constants.ZIP, constants.ZIP_EXTERNAL) \
                or prefs['keep archive format when saving']:
            return archive_type
        return None

    def offer_to_save(self) -> None:
        """Ask whether to write the book back over its own archive.

        Asked after every page removed, until the reader ticks "Do not
        ask again", which is how every other prompt with a lasting
        answer works.
        """
        archive_type = self.writeable_archive_type()
        path = self._window.filehandler.get_path_to_base()
        if archive_type is None or path is None:
            return
        dialog = message_dialog.MessageDialog(
            self._window, modal=True, buttons=Gtk.ButtonsType.NONE)
        dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.SAVE_EDITED_ARCHIVE)
        dialog.set_text(
            _('Write "%s" again now?') % os.path.basename(path),
            _('The archive on disk will be replaced by the book as it '
              'stands, without the pages that were removed.'))
        dialog.add_button(_('_Not now'), Response.NO)
        dialog.add_button(_('_Save'), Response.YES)
        # Enter must not overwrite an archive.  A confirmation defaults
        # to the answer that changes nothing.
        dialog.set_default_response(Response.NO)
        dialog.run_async(self._save_answered)

    def _save_answered(self, response: int) -> None:
        if response == Response.YES:
            self.save_archive()

    def save_archive(self) -> bool:
        """Write the open book over the archive it came from.

        Every page is waited for first: one that is not out of the
        archive yet cannot be written into the new one, and once the old
        archive has been replaced the name it would have been read under
        is no longer in it.
        """
        archive_type = self.writeable_archive_type()
        path = self._window.filehandler.get_path_to_base()
        if archive_type is None or path is None:
            return False
        # Through the cursor handler rather than set_layout_cursor(): the
        # pointer hides itself after a couple of seconds of not moving,
        # and a cursor set straight on the window is replaced by the
        # hidden one part way through a save that takes longer than that.
        self._window.cursor_handler.set_busy(True)
        try:
            image_files = self._window.imagehandler.get_image_files()
            comment_files = [self._window.filehandler.get_comment_name(number)
                             for number in range(
                                 1, self._window.filehandler
                                 .get_number_of_comments() + 1)]
            # Both lists, not just the pages: a comment is extracted
            # like anything else in the archive, and the packer reads
            # its size before it writes it, so saving before it was out
            # raised FileNotFoundError and refused the save.
            self._window.filehandler.wait_for_files(image_files + comment_files)
            archive_packer.write_archive(
                path, image_files, comment_files,
                carried_files=self._window.filehandler.get_other_files(),
                archive_type=archive_type, permissions_from=path)
        except OSError as error:
            log.error(_('! Could not save the archive %(archivefile)s: '
                        '%(error)s'),
                      {'archivefile': path, 'error': error})
            dialog = message_dialog.MessageDialog(
                self._window, buttons=Gtk.ButtonsType.CLOSE)
            dialog.set_text(_("The new archive could not be saved!"),
                            _("The original files have not been removed."))
            dialog.run_async(lambda response: None)
            return False
        finally:
            # Anything that gets out of the block above, and not only the
            # OSError it answers, would otherwise leave the whole program
            # pointing at a wait cursor.
            self._window.cursor_handler.set_busy(False)
        return True

    def undo(self, *args: object) -> bool:
        """Put the pages back as they were before the last change."""
        if not self._undone:
            return False
        self._redone.append(self._window.imagehandler.get_image_files())
        # The pages an undo brings back were never picked out, and every
        # number after them has moved: there is nothing to carry over.
        self._window.selected_pages = set()
        listing = self._undone.pop()
        self._show_pages(listing, min(self._window.imagehandler.get_current_page(),
                                      len(listing)))
        return True

    def redo(self, *args: object) -> bool:
        """Make the last undone change again."""
        if not self._redone:
            return False
        self._undone.append(self._window.imagehandler.get_image_files())
        self._window.selected_pages = set()
        listing = self._redone.pop()
        self._show_pages(listing, min(self._window.imagehandler.get_current_page(),
                                      len(listing)))
        return True

    def can_undo(self) -> bool:
        return bool(self._undone)

    def can_redo(self) -> bool:
        return bool(self._redone)

    def extract_page(self, *args: object) -> None:
        """Save the pages on screen to disk."""
        self._save_pages(self._window.displayed_pages())

    def extract_popup_page(self, *args: object) -> None:
        """Save the page the right-click menu was opened over.

        In double page mode two pages stand side by side and the menu is
        opened on one of them; opened on the background around them
        there is no one page to mean, so both are offered, which is what
        the menu bar's own Save As does.
        """
        page = self._window.popup_page
        self._save_pages([page] if page is not None
                         else self._window.displayed_pages())

    def delete_popup_page(self, *args: object) -> None:
        """Take the page the right-click menu was opened over out.

        The one the menu stands on rather than the one picked out: the
        menu was opened on a page, which says which page is meant as
        plainly as picking one out does.  Opened on the background there
        is no one page to mean, and the page picked out, if any, is what
        is left.
        """
        self.delete_page(self._window.popup_page)

    def _save_pages(self, pages: "Iterable[int]") -> None:
        """Ask where each of <pages> should go, and put it there.

        A number is appended to the name offered where a file of that
        name is in the target directory already.
        """
        for page in pages:
            file_path = self._window.imagehandler.get_path_to_page(page)
            if not file_path:
                return
            file_name = os.path.split(file_path)[-1]

            if self._window.filehandler.archive_type is not None:
                # Prepend the archive base name to the filename being displayed
                archive_name = self._window.filehandler.get_pretty_current_filename()
                file_name = (
                    os.path.splitext(archive_name)[0] + '_' + file_name)

            target_dir = prefs['path of last saved in filechooser']
            suggest_name = i18n.to_unicode(file_name)
            attempt = 1
            while os.path.exists(os.path.join(target_dir, suggest_name)):
                suggest_name = tools.append_number_to_filename(
                    file_name, number=attempt)
                attempt += 1

            # MComix' own chooser, as the archive editor's Save As and
            # every Open in the program use.  A Gtk.FileDialog asks the
            # desktop for the chooser instead, which is drawn by the
            # file chooser portal where one is installed - another
            # program, which MComix' colour scheme does not reach.
            save_dialog = file_chooser_simple_dialog.SimpleFileChooserDialog(
                Gtk.FileChooserAction.SAVE, self._window, folder=target_dir)
            save_dialog.set_title(_('Save page as'))
            save_dialog.set_save_name(suggest_name)

            # Both pages of a double page get a dialog of their own, and
            # they stand at the same time: each answer needs the page it
            # was asked about, not whichever one the loop ended on.
            def saved(paths: list[str], file_path: str = file_path,
                      dialog: file_chooser_simple_dialog.SimpleFileChooserDialog
                      = save_dialog) -> None:
                dialog.destroy()
                if paths:
                    self._save_page_to(file_path, paths[0])

            save_dialog.run_async(saved)

    def _save_page_to(self, file_path: str, target: str) -> None:
        """Copy the page at <file_path> to <target>.

        Where it went is where the next save starts from, which is not
        the folder the chooser opened in: the user may have walked out
        of it.  A save that failed went nowhere, so it neither says
        where the next one starts nor passes in silence: a folder that
        cannot be written to, or one that has no room left, used to
        leave the reader with a dialog that had closed and no page
        where they had asked for one.
        """
        target = i18n.to_unicode(target)
        try:
            shutil.copy2(file_path, target)
        except OSError as error:
            self._save_failed(file_path, target, error)
            return

        prefs['path of last saved in filechooser'] = \
            os.path.dirname(target) \
            if prefs['store last saved in directory'] \
            else constants.HOME_DIR

    def _save_failed(self, file_path: str, target: str,
                     error: OSError) -> None:
        """Say why the page at <file_path> did not become <target>."""
        log.error(_('! Could not save %(file)s to %(directory)s: %(error)s'),
                  {'file': file_path, 'directory': os.path.dirname(target),
                   'error': error})
        if error.errno == errno.ENOSPC:
            reason = (_('There is not enough room there: the file is %s.')
                      % tools.format_byte_size(os.path.getsize(file_path)))
        else:
            reason = str(error)
        dialog = message_dialog.MessageDialog(
            self._window, buttons=Gtk.ButtonsType.CLOSE)
        dialog.set_text(_('Could not save "%(file)s" to "%(directory)s"')
                        % {'file': os.path.basename(target),
                           'directory': os.path.dirname(target)},
                        reason)
        dialog.run_async(lambda response: None)

    def delete(self, *args: object) -> None:
        """Delete the page that is picked out, or else the whole file.

        Delete acts on a selection wherever there is one, which is how
        every list in the program reads the key; a page is picked out
        only by Ctrl and a click on it, and it is drawn outlined while
        it is, so nothing is picked out by accident.  With nothing
        picked out the key means what it always meant, and asks before
        it removes the file from disk.
        """
        if self._window.selected_pages:
            self.delete_page()
            return

        current_file = self._window.imagehandler.get_real_path()
        if current_file is None:
            # The menu entry is insensitive without a file open.
            return
        dialog = message_dialog.MessageDialog(
                self._window, modal=True, buttons=Gtk.ButtonsType.NONE)
        dialog.set_should_remember_choice(
                message_dialog.RememberedDialog.DELETE_OPENED_FILE)
        dialog.set_text(
                _('Delete "%s"?') % os.path.basename(current_file),
                _('The file will be deleted from your harddisk.'))
        dialog.add_button(_('_Cancel'), Response.CANCEL)
        dialog.add_button(_('_Delete'), Response.OK)
        # Enter must not delete a file.  A confirmation defaults to the
        # answer that changes nothing, and the one that does not is
        # drawn as the destructive action it is.
        dialog.set_default_response(Response.CANCEL)
        deletes = dialog.get_widget_for_response(Response.OK)
        if deletes is not None:
            deletes.add_css_class('destructive-action')
        dialog.run_async(lambda response: self._delete_answered(response, current_file))

    def _delete_answered(self, result: int, current_file: str) -> None:
        """Delete <current_file> if the confirmation came back positive."""
        if result == Response.OK:
            # Go to next page/archive, and delete current file
            if self._window.filehandler.archive_type is not None:
                self._window.filehandler.last_read_page.clear_page(current_file)

                next_opened = self._window.filehandler.open_next_archive()
                if not next_opened:
                    next_opened = self._window.filehandler.open_previous_archive()
                if not next_opened:
                    self._window.filehandler.close_file()

                if os.path.isfile(current_file):
                    os.unlink(current_file)
            else:
                if self._window.imagehandler.get_number_of_pages() > 1:
                    # Open the next/previous file
                    if self._window.imagehandler.get_current_page() >= self._window.imagehandler.get_number_of_pages():
                        self._window.flip_page(-1)
                    else:
                        self._window.flip_page(+1)
                    # Unlink the desired file
                    if os.path.isfile(current_file):
                        os.unlink(current_file)
                    # Refresh the directory
                    self._window.filehandler.refresh_file()
                else:
                    self._window.filehandler.close_file()
                    if os.path.isfile(current_file):
                        os.unlink(current_file)

            if not os.path.exists(current_file):
                # A file that has been deleted can never be opened
                # again, and the recent files went on offering it.
                self._window.uimanager.recent.remove_path(current_file)

    def move_current_file(self, directory: str) -> None:
        """Move the open file, or the archive it is a page of, into
        <directory>, and go on reading it where it has landed.

        The book is not closed and opened again at its first page: the
        page being read is the page that comes back, which is what makes
        this different from moving the file from outside and opening it
        afresh.  Where the old path is recorded it is brought forward -
        the library holds one, and so does the store of last read pages.
        """
        current_file = self._window.imagehandler.get_real_path()
        if current_file is None:
            # The menu entries are insensitive without a file open.
            return
        in_archive = self._window.filehandler.archive_type is not None
        page = self._window.imagehandler.get_current_page()
        try:
            target = file_mover.move_file(current_file, directory)
        except OSError as error:
            self._move_failed(current_file, directory, error)
            return

        self._window.uimanager.move_to.remember(directory)
        backend.LibraryBackend().update_book_path(current_file, target)
        bookmark_backend.BookmarksStore.update_path(current_file, target)
        # The book is about to be opened where it landed, which records
        # that; the entry for where it was would open nothing.
        self._window.uimanager.recent.remove_path(current_file)
        # A loose image works out its own page from the file it is
        # opened on; only an archive has to be told which one to show.
        self._window.filehandler.open_file(target, page if in_archive else 0)
        # Opening the book closed it first, which wrote the page being
        # read back under the path the file no longer has.
        self._window.filehandler.last_read_page.clear_page(current_file)

    def _move_failed(self, current_file: str, directory: str,
                     error: OSError) -> None:
        """Say why <current_file> did not move into <directory>.

        Nothing has moved when this is called, so what the message has
        to say is why, and it says it in the terms the reader can act
        on: a name that is taken, or a disk without the room.
        """
        log.error(_('! Could not move %(file)s to %(directory)s: %(error)s'),
                  {'file': current_file, 'directory': directory,
                   'error': error})
        if error.errno == errno.EEXIST:
            reason = _('A file of that name is there already.')
        elif error.errno == errno.ENOSPC:
            reason = (_('There is not enough room there: the file is %s.')
                      % tools.format_byte_size(os.path.getsize(current_file)))
        else:
            reason = str(error)
        dialog = message_dialog.MessageDialog(
            self._window, buttons=Gtk.ButtonsType.CLOSE)
        dialog.set_text(_('Could not move "%(file)s" to "%(directory)s"')
                        % {'file': os.path.basename(current_file),
                           'directory': directory},
                        reason)
        dialog.run_async(lambda response: None)

# vim: expandtab:sw=4:ts=4
