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
import sys

from gi.repository import Gio, GLib, Gtk

from mcomix import archive_packer
from mcomix import bookmark_backend
from mcomix import constants
from mcomix import edit_dialog
from mcomix import file_chooser_simple_dialog
from mcomix import file_mover
from mcomix import i18n
from mcomix import log
from mcomix import message_dialog
from mcomix import page_marks
from mcomix import page_rotations
from mcomix import rename_dialog
from mcomix import tools
from mcomix.dialog import Response
from mcomix.i18n import _
from mcomix.library import backend
from mcomix.preferences import prefs

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


def _same_file_recased(path: str, target: str) -> bool:
    """Whether <target> is <path> itself under a name that differs only
    in case, which is what a file system that ignores case answers."""
    if (os.path.basename(path).casefold()
            != os.path.basename(target).casefold()):
        return False
    try:
        return os.path.samefile(path, target)
    except OSError:
        return False


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
        #: The name the reader has given a page, by the path of the
        #: file behind it.  A page keeps the name it is given until the
        #: book is written, where the packer writes it under that name
        #: instead of the numbered one it would make up.
        self._page_names: dict[str, str] = {}
        #: Whether the offer to write the book out before it closes has
        #: been answered.  The offer is made once per set of changes:
        #: an answer of "not now" has to close the book rather than be
        #: asked again by every step of the close.
        self._close_offer_answered = False
        #: The close waiting for that answer while the offer is out.
        self._waiting_close: "Callable[[], None] | None" = None

    def forget_changes(self) -> None:
        """Drop the undo stack, which belongs to the book that is going."""
        self._undone.clear()
        self._redone.clear()
        self._page_names.clear()
        self._close_offer_answered = False
        self._waiting_close = None

    def page_names(self) -> dict[str, str]:
        """The name each renamed page is to be written under, by path."""
        return dict(self._page_names)

    def name_typed(self, page: int, name: str) -> "str | None":
        """What <name>, typed for <page>, would call it, or None where
        it would call it nothing it is not called already.

        The rule is the one every file in a book is renamed by, in
        rename_dialog.read(): the last part of what was typed, with the
        old extension where none was typed.
        """
        return rename_dialog.read(self.page_name(page), name)

    def page_called(self, name: str, other_than: int) -> "int | None":
        """The page called <name>, if a page other than <other_than> is.

        The names the reader sees, which are the names the book is
        written under: the name of the file behind a page counts as
        much as one the reader has given it, both being what that page
        would be called in the archive.
        """
        for number in range(
                1, len(self._window.imagehandler.get_image_files()) + 1):
            if number != other_than and self.page_name(number) == name:
                return number
        return None

    def rename_page(self, page: int, name: str) -> "str | None":
        """Call the page at <page> <name>, and answer with the name it
        took, or None if it took none.

        The name replaces the whole of the old one.  A name typed with
        a folder in front of it is read as the last part of it, a page
        being a file inside the book rather than a path, and a name
        typed without an extension keeps the old one, since what MComix
        and every other reader take for a page is decided by that.

        The book in the window is what changes: the page is written
        under this name when the archive is saved, and the archive on
        disk is not touched until then.
        """
        listing = self._window.imagehandler.get_image_files()
        if not 1 <= page <= len(listing):
            return None
        path = listing[page - 1]
        typed = self.name_typed(page, name)
        if typed is None:
            return None
        name = typed
        if self._window.filehandler.archive_type is None:
            return self._rename_on_disk(page, path, name)
        self._give_name(path, name)
        self._close_offer_answered = False
        self.offer_to_save()
        return name

    def _give_name(self, path: str, name: str) -> None:
        """Write down that the page whose file is <path> is called <name>.

        A page named what the file in the archive is called already is
        written down as nothing at all: there is then nothing for the
        packer to do differently, and a name kept here would count as a
        change waiting to be written.
        """
        if name == os.path.basename(path):
            self._page_names.pop(path, None)
        else:
            self._page_names[path] = name

    def swap_page_names(self, page: int, name: str) -> bool:
        """Call <page> <name> and the page that holds <name> what <page>
        was called, and say whether both were.

        One of the two answers to a name that is taken: two pages whose
        names are the wrong way round are put right in one step, rather
        than one of them having to be called something else first.
        """
        typed = self.name_typed(page, name)
        holder = None if typed is None else self.page_called(typed, page)
        if typed is None or holder is None:
            return False
        if self._window.filehandler.archive_type is None:
            return self._swap_names_on_disk(page, holder, typed)
        listing = self._window.imagehandler.get_image_files()
        held = self.page_name(page)
        self._give_name(listing[page - 1], typed)
        self._give_name(listing[holder - 1], held)
        self._close_offer_answered = False
        self.offer_to_save()
        return True

    def replace_page_named(self, page: int, name: str) -> bool:
        """Call <page> <name>, and take the page that held <name> out of
        the book; say whether that was done.

        The other answer to a name that is taken, and the one a file
        manager gives: the page that had the name goes, as the file
        written over goes.  Two pages cannot both be called one name,
        so there is nothing in between.  The last page of a book is not
        taken out, a book with no pages being no book.
        """
        typed = self.name_typed(page, name)
        holder = None if typed is None else self.page_called(typed, page)
        if typed is None or holder is None:
            return False
        if self._window.filehandler.archive_type is None:
            return self._replace_on_disk(page, holder, typed)
        path = self._window.imagehandler.get_image_files()[page - 1]
        if not self.remove_pages({holder}):
            return False
        self._give_name(path, typed)
        self._close_offer_answered = False
        self.offer_to_save()
        return True

    def _swap_names_on_disk(self, page: int, holder: int,
                            name: str) -> bool:
        """Swap the names of two pages that are files of their own.

        Through a name neither file has: a rename onto a name that is
        taken writes over the file that has it, which is what swapping
        the two names is there to avoid.
        """
        listing = self._window.imagehandler.get_image_files()
        path, other = listing[page - 1], listing[holder - 1]
        held = os.path.basename(path)
        aside = other + '.mcomix-swap'
        target = os.path.join(os.path.dirname(path), name)
        other_target = os.path.join(os.path.dirname(other), held)
        try:
            os.rename(other, aside)
        except OSError as error:
            log.error('Could not rename %s: %r', other, error)
            return False
        try:
            os.rename(path, target)
            os.rename(aside, other_target)
        except OSError as error:
            log.error('Could not swap the names of %s and %s: %s',
                      path, other, error)
            # The file taken out of the way goes back under its own
            # name, whichever of the two renames failed: a page whose
            # file is called something no listing knows is a page that
            # has gone missing from the book.  Last move first: when
            # only the last failed, the page's file holds the other's
            # name, and has to leave it before that can go back.
            for source, back in ((target, path), (aside, other)):
                if os.path.lexists(source) and not os.path.lexists(back):
                    os.rename(source, back)
            return False
        self._paths_changed(listing, {path: target, other: other_target})
        self._show_pages(listing,
                         self._window.imagehandler.get_current_page())
        return True

    def _replace_on_disk(self, page: int, holder: int, name: str) -> bool:
        """Write the file of <page> over the file of <holder>.

        A book read as a folder of images has no archive to write, so
        replacing a page happens on disk at once: the file that had the
        name is gone, and the page it was leaves the book with it.
        """
        listing = self._window.imagehandler.get_image_files()
        path = listing[page - 1]
        target = os.path.join(os.path.dirname(path), name)
        if not self.remove_pages({holder}):
            return False
        try:
            os.replace(path, target)
        except OSError as error:
            log.error('Could not rename %s: %r', path, error)
            # The page that was taken out to make room for the name is
            # put back, the name having gone nowhere.
            self.undo()
            return False
        listing = self._window.imagehandler.get_image_files()
        self._paths_changed(listing, {path: target})
        self._show_pages(listing,
                         self._window.imagehandler.get_current_page())
        return True

    def _paths_changed(self, listing: list[str],
                       moved: dict[str, str]) -> None:
        """Follow each file of <moved> from its old path to its new one
        through <listing> and through every listing the undo stack is
        keeping.

        <listing> is the book the caller is about to draw - the window
        hands out a copy of its own, so the one that is drawn is the
        one that has to be changed - and the kept ones would otherwise
        bring a page back under the name it no longer has.  All of them
        in one pass, because two files that change names with each
        other would otherwise be followed one into the other.
        """
        for kept in [listing] + self._undone + self._redone:
            for index, held in enumerate(kept):
                if held in moved:
                    kept[index] = moved[held]

    def _rename_on_disk(self, page: int, path: str,
                        name: str) -> "str | None":
        """Rename the file of a page that is a file: a book read as a
        folder of images has no archive to write, so the rename happens
        at once, and is what the window shows from then on.

        A name that is taken is refused rather than written over:
        MComix is renaming one page of a book here, not moving a file
        about, and the file of that name may be another page of the
        same book.  Where the file system ignores case, as Windows' and
        macOS' do, the name a change of case asks for is taken by the
        file itself, which is no reason to refuse it.
        """
        target = os.path.join(os.path.dirname(path), name)
        if os.path.lexists(target) and not _same_file_recased(path, target):
            dialog = message_dialog.MessageDialog(
                self._window, buttons=Gtk.ButtonsType.CLOSE)
            dialog.set_text(_('A file of that name is there already.'))
            dialog.run_async(lambda response: None)
            return None
        try:
            os.rename(path, target)
        except OSError as error:
            # Not translated, as image_handler's own failures are not:
            # what it says is a file system error to whoever reads the
            # log, and the reader has been told by the page not moving.
            log.error('Could not rename %s: %r', path, error)
            return None
        listing = self._window.imagehandler.get_image_files()
        self._paths_changed(listing, {path: target})
        self._show_pages(listing,
                         self._window.imagehandler.get_current_page())
        return name

    def rename_popup_page(self, *args: object) -> None:
        """Ask what to call the page the right-click menu was opened over.

        The page under the pointer, as Save As and Delete page act on,
        or the page being read where the menu was opened on the
        background around the pages.
        """
        page = self._window.popup_page
        if page is None:
            page = self._window.imagehandler.get_current_page()
        if page:
            self.rename_page_dialog(page)

    def rename_page_being_read(self, *args: object) -> None:
        """Ask what to call the page on screen.

        What the rename key means, a key press carrying no pointer
        position to read a page off: the menu's own rename acts on the
        page the menu was opened over, and there is no menu here.  In
        double page mode the page being read is the first of the two,
        as it is for everything else that names one page.
        """
        page = self._window.imagehandler.get_current_page()
        if page:
            self.rename_page_dialog(page)

    def rename_page_dialog(self, page: int,
                           parent: "Gtk.Window | None" = None,
                           when_done: "Callable[[], None] | None" = None
                           ) -> None:
        """Ask what to call <page>, and give it the answer.

        <parent> is the window the dialog belongs to, which is the
        archive editor when the rename was asked for there, and
        <when_done> is called once a name has been given, so that
        whatever shows the name can show the new one.
        """
        if not self._window.filehandler.file_loaded:
            return

        def clash(typed: str) -> "rename_dialog.Clash | None":
            """The page that holds what has been typed, if one does."""
            name = self.name_typed(page, typed)
            holder = None if name is None else self.page_called(name, page)
            if holder is None or name is None:
                return None
            return rename_dialog.Clash(
                _('Page %(number)d is called "%(name)s" already.')
                % {'number': holder, 'name': name}, True)

        rename_dialog.ask(
            parent or self._window,
            title=_('Rename page?'),
            prompt=_('Please enter a new name for this page.'),
            name=self.page_name(page), clash=clash,
            answered=lambda response, typed: self._rename_answered(
                response, page, typed, when_done))

    def _rename_answered(self, response: int, page: int, name: str,
                         when_done: "Callable[[], None] | None" = None
                         ) -> None:
        """Do what was answered with the name that was typed."""
        if response == Response.OK:
            done = self.rename_page(page, name) is not None
        elif response == rename_dialog.SWAP:
            done = self.swap_page_names(page, name)
        elif response == rename_dialog.REPLACE:
            done = self.replace_page_named(page, name)
        else:
            done = False
        if done and when_done is not None:
            when_done()

    def page_name(self, page: int) -> str:
        """What the page at <page> is called: the name it was given, or
        the name of the file it was read from."""
        listing = self._window.imagehandler.get_image_files()
        if not 1 <= page <= len(listing):
            return ''
        path = listing[page - 1]
        return self._page_names.get(path, os.path.basename(path))

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

    def swap_pages(self, first: int, second: int) -> bool:
        """Put the page at <first> where <second> is, and say whether it
        went.

        The book in the window is what changes, as a removal does: the
        archive on disk is not written until it is saved, and the swap
        can be undone.  A page swapped with itself, or with a page that
        is not there, is no swap at all.

        A page that is picked out is picked out for its file rather than
        for its number, so a mark on one of the two goes with it.
        """
        listing = self._window.imagehandler.get_image_files()
        if first == second or not (1 <= first <= len(listing)
                                   and 1 <= second <= len(listing)):
            return False
        self._undone.append(list(listing))
        self._redone.clear()
        listing[first - 1], listing[second - 1] = \
            listing[second - 1], listing[first - 1]
        selected = self._window.selected_pages
        if (first in selected) != (second in selected):
            self._window.selected_pages = selected ^ {first, second}
        self._show_pages(listing,
                         self._window.imagehandler.get_current_page())
        self.offer_to_save()
        return True

    def _show_pages(self, listing: list[str], page: int) -> None:
        """Draw the book as <listing>, standing on <page>."""
        # Every change to the pages comes through here, and a change
        # made after the book was let off being written is a change the
        # reader has not been asked about yet.
        self._close_offer_answered = False
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

    def has_unsaved_changes(self) -> bool:
        """Whether the book on screen differs from the archive on disk.

        The pages themselves, in their order, and the names the reader
        has given them: any of it is a change the archive does not hold
        until it is written again.  A book that cannot be written back
        over its own archive has nothing to save, and neither has one
        whose changes have all been taken back - the first listing the
        undo stack kept is the book as it was opened, and the stack is
        empty once everything has been undone.
        """
        if self.writeable_archive_type() is None:
            return False
        if self._page_names:
            return True
        return bool(self._undone) and \
            self._window.imagehandler.get_image_files() != self._undone[0]

    def before_closing(self, then: "Callable[[], None]") -> None:
        """Offer to write the book out if it has changes, then run <then>.

        Closing a book throws away everything that has not been written
        to its archive, and the offer made at the change itself may
        have been turned down by a reader who meant to go on editing.
        So the question is put once more on the way out - when the book
        is closed, when another is opened over it and when MComix
        quits - and the close waits for the answer.

        The archive editor is asked about first, and is the one
        question on the way out that can stop the close: what it holds
        cannot be written from anywhere else once the book has gone.

        Both offers are made once for a set of changes: the answer
        stands for the whole of the close that follows it, which
        reaches here more than once, and the next change to the book
        asks again.

        A close asked for while the offer is out waits for the same
        answer, in place of the one that asked: a Next archive pressed
        twice, or a key held down, came in ahead of an answer that is
        delivered from the main loop, and closed the book under the
        question.  The answer then wrote whichever book was open by
        then - the next archive, half listed - and the book it was
        asked about lost its changes.
        """
        if self._waiting_close is not None:
            self._waiting_close = then
            return
        if self._close_offer_answered:
            then()
            return
        self._close_offer_answered = True
        self._waiting_close = then

        def go_on_editing() -> None:
            """The close is off, and the next one asks again."""
            self._close_offer_answered = False
            self._waiting_close = None

        edit_dialog.ask_before_closing(
            self._window,
            closing=lambda: self._write_before_closing(self._close_now),
            keeping=go_on_editing)

    def _close_now(self) -> None:
        """Run the close that waited for the offer to be answered."""
        then = self._waiting_close
        self._waiting_close = None
        if then is not None:
            then()

    def _write_before_closing(self, then: "Callable[[], None]") -> None:
        """Offer to write the book out if it has changes, then close."""
        if not self.has_unsaved_changes():
            then()
            return
        path = self._window.filehandler.get_path_to_base()
        assert path is not None  # has_unsaved_changes() answered for it
        dialog = message_dialog.MessageDialog(
            self._window, modal=True, buttons=Gtk.ButtonsType.NONE)
        dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.SAVE_EDITED_ARCHIVE)
        dialog.set_text(
            _('Write "%s" again before closing it?') % os.path.basename(path),
            _('The book has changes that the archive on disk does not '
              'hold. They are lost when it closes.'))
        dialog.add_button(_('_Close without saving'), Response.NO)
        dialog.add_button(_('_Save'), Response.YES)
        # The other way round from the offer made at the change itself,
        # where Enter must not overwrite an archive: here it is the
        # answer that leaves the archive alone which throws work away,
        # and the reader has already said what they wanted the book to
        # look like.  So Enter saves, and the button that does not is
        # drawn as the destructive one.
        dialog.set_default_response(Response.YES)
        closes = dialog.get_widget_for_response(Response.NO)
        if closes is not None:
            closes.add_css_class('destructive-action')
        dialog.run_async(lambda response: self._closing_answered(response,
                                                                 then))

    def _closing_answered(self, response: int,
                          then: "Callable[[], None]") -> None:
        """Write the book out if that is the answer, then close it."""
        if response == Response.YES:
            self.save_archive()
        then()

    def offer_to_save(self) -> None:
        """Ask whether to write the book back over its own archive.

        Asked after every change to the pages - one removed, two
        swapped, one renamed - until the reader ticks "Do not ask
        again", which is how every other prompt with a lasting answer
        works.
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
              'stands: the pages it holds now, in the order and under '
              'the names it shows.'))
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
            carried_files = self._window.filehandler.get_other_files()
            self._window.filehandler.release_archive()
            archive_packer.write_archive(
                path, image_files, comment_files,
                carried_files=carried_files,
                archive_type=archive_type, permissions_from=path,
                page_names=self._page_names)
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

    def open_containing_folder(self, *args: object) -> None:
        """Show the open file in the file manager: the archive, or the
        picture being read where the book is a folder of them."""
        self._show_in_folder(self._window.imagehandler.get_real_path())

    def open_popup_containing_folder(self, *args: object) -> None:
        """Show the file the right-click menu was opened over.

        A page of an archive has no file of its own to show, so the
        archive is what is shown.  In a folder of pictures it is the
        page the menu stands on, and the page being read where the menu
        was opened on the background.
        """
        page = self._window.popup_page
        if page is None or self._window.filehandler.archive_type is not None:
            self.open_containing_folder()
            return
        self._show_in_folder(self._window.imagehandler.get_path_to_page(page))

    def _show_in_folder(self, path: "str | None") -> None:
        if path is None:
            # The menu entry is insensitive without a file open.
            return
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
        launcher.open_containing_folder(
            self._window, None,
            lambda _source, result: self._shown_in_folder(launcher, result))

    def _shown_in_folder(self, launcher: Gtk.FileLauncher,
                         result: Gio.AsyncResult) -> None:
        try:
            launcher.open_containing_folder_finish(result)
        except GLib.Error as error:
            # Where a portal asks which program to use, turning the
            # question down is an answer, not a failure.
            if any(error.matches(Gtk.dialog_error_quark(), code)
                   for code in (Gtk.DialogError.DISMISSED,
                                Gtk.DialogError.CANCELLED)):
                return
            self._window.osd.show(_('Could not show the folder: %s')
                                  % error.message)

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
        cannot be written to, or one that has no room left, would
        otherwise leave the reader with a dialog that had closed and no
        page where they had asked for one.
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
        if tools.trash_refuses(current_file):
            # Offering the trash for a file it will not take only puts
            # a second question after the first, once the book has
            # already been closed: the question is the one Shift+Delete
            # asks, as a file browser asks it, saying why.
            self._ask_to_delete_permanently(
                current_file,
                _('There is no trash for this folder, so it cannot be '
                  'restored.'))
            return
        dialog = message_dialog.MessageDialog(
                self._window, modal=True, buttons=Gtk.ButtonsType.NONE)
        dialog.set_should_remember_choice(
                message_dialog.RememberedDialog.DELETE_OPENED_FILE)
        dialog.set_text(
                _('Delete "%s"?') % os.path.basename(current_file),
                _('The file is moved to the trash.'))
        dialog.add_button(_('_Cancel'), Response.CANCEL)
        dialog.add_button(_('_Move to Trash'), Response.OK)
        # Enter must not delete a file, so a confirmation defaults to
        # the answer that changes nothing.  What can be taken back out
        # of the trash is drawn as the suggested action, apart from the
        # destructive red of deleting for good.
        dialog.set_default_response(Response.CANCEL)
        trashes = dialog.get_widget_for_response(Response.OK)
        if trashes is not None:
            trashes.add_css_class('suggested-action')
        dialog.run_async(lambda response: self._delete_answered(response, current_file))

    def delete_permanently(self, *args: object) -> None:
        """Delete as delete() does, except that the file does not go to
        the trash.

        Shift+Delete, as in a file browser.  Pages picked out are taken
        out of the book as Delete takes them: they are not files of
        their own until the book is written, and taking them out can be
        undone.  The question has no "Do not ask again", and Enter
        keeps the file.
        """
        if self._window.selected_pages:
            self.delete_page()
            return

        current_file = self._window.imagehandler.get_real_path()
        if current_file is None:
            return
        self._ask_to_delete_permanently(
            current_file,
            _('It does not go to the trash and cannot be restored.'))

    def _ask_to_delete_permanently(self, path: str, why: str) -> None:
        """Ask whether to delete <path> for good, saying <why> it does
        not go to the trash, and delete it if the answer is yes."""
        dialog = message_dialog.MessageDialog(
            self._window, modal=True, buttons=Gtk.ButtonsType.NONE)
        dialog.set_text(
            _('Delete "%s" permanently?') % os.path.basename(path), why)
        self.add_delete_permanently_buttons(dialog)
        dialog.run_async(lambda response: self._delete_answered(
            response, path, self._remove_permanently))

    def _remove_permanently(self, path: str,
                            then: "Callable[[], None]") -> None:
        """Delete <path> for good, then run <then>."""
        if os.path.isfile(path):
            self.delete_files_permanently([path])
        then()

    def _delete_answered(
            self, result: int, current_file: str,
            remove: "Callable[[str, Callable[[], None]], None] | None" = None
    ) -> None:
        """Delete <current_file> if the confirmation came back positive.

        <remove> takes the file away and then runs what it is given;
        moving it to the trash, unless another is named.  The book is
        left only once its file is gone: where the trash refuses it and
        the reader turns down deleting it for good, they are still
        reading it, on the page they were on.
        """
        if result != Response.OK:
            return
        remove = remove or self._trash
        if sys.platform == 'win32':
            # Windows neither trashes nor deletes a file that is open,
            # and the extractor holds the archive open until every
            # member is out.
            self._window.filehandler.release_archive()
        remove(current_file, lambda: self._leave_deleted(current_file))

    def _leave_deleted(self, path: str) -> None:
        """Go on from the book whose file was at <path>, if it is gone:
        to the file nearest to it in its folder, the next or else the
        one before, or nowhere where there is none."""
        if os.path.exists(path):
            return
        # Whatever was waiting to be written into the file went with
        # it: nothing is to offer to write the book back over it.
        self.forget_changes()
        nearest = self._window.filehandler.nearest_in_folder(
            os.path.abspath(path))
        if nearest is None:
            self._window.filehandler.close_file()
        else:
            self._window.filehandler.open_file(nearest, keep_fileprovider=True)
        self._file_deleted(path)

    def _file_deleted(self, path: str) -> None:
        """Forget <path> wherever MComix kept it, if it is gone."""
        if not os.path.exists(path):
            # A file that has been deleted can never be opened
            # again, and the recent files went on offering it.
            self._window.uimanager.recent.remove_path(path)
            self._forget_deleted_book(path)
            self._offer_to_remove_bookmarks(path)

    def _trash(self, path: str, then: "Callable[[], None]") -> None:
        """Move <path> to the trash, then run <then>.

        Where the trash will not take the file, the reader is offered to
        delete it permanently instead, and <then> runs once that has
        been answered.  delete() asks that up front wherever
        tools.trash_refuses() foresees the refusal, so this is for one
        it did not, such as a mount whose trash folder cannot be made.
        """
        if not os.path.isfile(path):
            then()
            return
        try:
            tools.move_to_trash(path)
        except GLib.Error as error:
            log.error('Could not move %s to the trash: %s', path, error.message)
            self.offer_to_delete_permanently(
                {path: error.message}, lambda deleted: then())
            return
        then()

    def offer_to_delete_permanently(
            self, refused: "Mapping[str, str]",
            then: "Callable[[list[str]], None]",
            parent: "Gtk.Window | None" = None) -> None:
        """Offer to delete the files the trash refused, then run <then>
        with those that were deleted.

        <refused> holds each file with the reason the trash gave.  GLib
        keeps no trash on a mount it counts as internal to the system,
        and that takes in every mount whose root is not "/": a folder
        bind-mounted from another partition, a tmpfs.  A file browser
        offers to delete such a file at once, and the reader, who has
        just said the file is to go, expects the same.  The file is
        never deleted for good without being asked, and Enter keeps it.
        """
        dialog = message_dialog.MessageDialog(
            parent or self._window, modal=True,
            buttons=Gtk.ButtonsType.NONE)
        if len(refused) == 1:
            title = _('Could not move "%s" to the trash') % \
                os.path.basename(next(iter(refused)))
        else:
            title = i18n.get_translation().ngettext(
                '%d book could not be moved to the trash.',
                '%d books could not be moved to the trash.',
                len(refused)) % len(refused)
        question = i18n.get_translation().ngettext(
            'Delete it permanently instead? It cannot be restored.',
            'Delete them permanently instead? They cannot be restored.',
            len(refused))
        reasons = '\n'.join(dict.fromkeys(refused.values()))
        dialog.set_text(title, '%s\n\n%s' % (reasons, question))
        self.add_delete_permanently_buttons(dialog)

        def answered(response: int) -> None:
            deleted = []
            if response == Response.OK:
                deleted = self.delete_files_permanently(list(refused), parent)
            then(deleted)

        dialog.run_async(answered)

    @staticmethod
    def add_delete_permanently_buttons(
            dialog: message_dialog.MessageDialog) -> None:
        """Cancel, the default, and the destructive Delete Permanently."""
        dialog.add_button(_('_Cancel'), Response.CANCEL)
        dialog.add_button(_('_Delete Permanently'), Response.OK)
        dialog.set_default_response(Response.CANCEL)
        deletes = dialog.get_widget_for_response(Response.OK)
        if deletes is not None:
            deletes.add_css_class('destructive-action')

    def delete_files_permanently(self, paths: "Iterable[str]",
                                 parent: "Gtk.Window | None" = None
                                 ) -> list[str]:
        """Delete <paths> for good, say which could not be, and return
        those that were."""
        deleted = []
        failed: dict[str, str] = {}
        for path in paths:
            try:
                os.remove(path)
            except OSError as error:
                log.error(_('! Could not remove %(file)s: %(error)s'),
                          {'file': path, 'error': error.strerror or error})
                failed[path] = str(error.strerror or error)
            else:
                deleted.append(path)
        if failed:
            dialog = message_dialog.MessageDialog(
                parent or self._window, buttons=Gtk.ButtonsType.CLOSE)
            first = next(iter(failed))
            if len(failed) == 1:
                reasons = failed[first]
            else:
                reasons = '\n'.join('%s: %s' % (os.path.basename(path), reason)
                                    for path, reason in failed.items())
            dialog.set_text(
                _('Could not delete "%s"') % os.path.basename(first), reasons)
            dialog.run_async(lambda response: None)
        return deleted

    def _offer_to_remove_bookmarks(self, path: str) -> None:
        """Ask whether the bookmarks in the deleted file should go too.

        Asked rather than done: a bookmark is a page the reader marked,
        not a record MComix keeps of a file, so it is the one thing a
        delete does not take with it unasked.  The answer can be given
        for good, and taken back under "Prompts answered for good" in
        the preferences, as every other standing answer can.
        """
        bookmarks = bookmark_backend.BookmarksStore.bookmarks_for_path(path)
        if not bookmarks:
            return
        dialog = message_dialog.MessageDialog(
            self._window, buttons=Gtk.ButtonsType.YES_NO)
        dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.REMOVE_BOOKMARKS_OF_DELETED_FILE)
        message = i18n.get_translation().ngettext(
            'The file is gone, and its %d bookmark cannot be opened any more.',
            'The file is gone, and its %d bookmarks cannot be opened any more.',
            len(bookmarks))
        dialog.set_text(
            _('Remove the bookmarks in "%s"?') % os.path.basename(path),
            message % len(bookmarks))
        dialog.set_default_response(Response.NO)

        def answered(response: int) -> None:
            if response == Response.YES:
                bookmark_backend.BookmarksStore.remove_for_path(path)

        dialog.run_async(answered)

    @staticmethod
    def _forget_deleted_book(path: str) -> None:
        """Take the book at <path> out of the library, the file being gone.

        Without a word: what the library holds about a book is a record
        of a file, and the library itself offers "Clean up", which
        "Removes no longer existent books from the collection", so the
        entry is on its way out either way.  Leaving it meant a library
        that went on offering a book MComix had just deleted, and
        cleaning up by hand to be rid of it.
        """
        library = backend.LibraryBackend()
        book = library.get_book_by_path(path)
        if book is not None and book.id is not None:
            library.remove_book(book.id)

    def move_current_file(self, directory: str) -> None:
        """Move the open file, or the archive it is a page of, into
        <directory>, and go on reading it where it has landed.

        The book is not closed and opened again at its first page: the
        page being read is the page that comes back, which is what makes
        this different from moving the file from outside and opening it
        afresh.  Where the old path is recorded it is brought forward -
        the library holds one, and so do the bookmarks, the store of
        last read pages, and the turns and marks given to single pages.
        """
        current_file = self._window.imagehandler.get_real_path()
        if current_file is None:
            # The menu entries are insensitive without a file open.
            return
        in_archive = self._window.filehandler.archive_type is not None
        page = self._window.imagehandler.get_current_page()
        self._window.filehandler.release_archive()
        try:
            target = file_mover.move_file(current_file, directory)
        except OSError as error:
            self._move_failed(current_file, directory, error)
            return

        self._window.uimanager.move_to.remember(directory)
        backend.LibraryBackend().update_book_path(current_file, target)
        bookmark_backend.BookmarksStore.update_path(current_file, target)
        # The turns and the marks the reader gave its pages are kept by
        # the book's path as well.
        old, new = os.path.abspath(current_file), os.path.abspath(target)
        page_rotations.follow(old, new)
        page_marks.follow(old, new)
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
