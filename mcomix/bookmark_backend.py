"""bookmark_backend.py - Bookmarks handler."""

import os
import pickle
import operator
import datetime

from gi.repository import Gtk

from mcomix import constants
from mcomix import log
from mcomix import bookmark_menu_item
from mcomix import callback
from mcomix import i18n
from mcomix import message_dialog
from mcomix import tools
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import file_handler as file_handler_module
    from mcomix import image_handler as image_handler_module
    from mcomix import main


class _BookmarksStore:

    """The _BookmarksStore is a backend for both the bookmarks menu and dialog.
    Changes in the _BookmarksStore are mirrored in both.
    """

    def __init__(self) -> None:
        self._initialized = False
        #: All three are filled in by initialize(), which the main window
        #: calls once it has built the handlers.
        self._window: 'main.MainWindow | None' = None
        self._file_handler: 'file_handler_module.FileHandler | None' = None
        self._image_handler: 'image_handler_module.ImageHandler | None' = None

        bookmarks, mtime = self.load_bookmarks()

        #: List of bookmarks
        self._bookmarks = bookmarks
        #: Modification time of the bookmarks file, in nanoseconds, as
        #: it was when this instance last read or wrote it
        self._bookmarks_mtime = mtime

    def initialize(self, window: 'main.MainWindow') -> None:
        """ Initializes references to the main window and file/image handlers. """
        if not self._initialized:
            self._window = window
            self._file_handler = window.filehandler
            self._image_handler = window.imagehandler
            self._initialized = True

            # Update already loaded bookmarks with window and file handler information
            for bookmark in self._bookmarks:
                bookmark.attach(window)

    def forget(self, window: 'main.MainWindow') -> None:
        """Let go of <window>, which has closed, and of its handlers.

        The store is one for the process, so whatever it holds lives as
        long as the process: it held the first window ever opened, and
        its bookmarks went on opening in that one.  The next window to
        call initialize() is the one they open in.
        """
        if self._window is not window:
            return
        self._window = None
        self._file_handler = None
        self._image_handler = None
        self._initialized = False
        for bookmark in self._bookmarks:
            bookmark.detach()

    def add_bookmark_by_values(self, name: str, path: str, page: int, numpages: int,
                               archive_type: int | None,
                               date_added: datetime.datetime,
                               member: str | None = None) -> None:
        """Create a bookmark and add it to the list."""
        bookmark = bookmark_menu_item._Bookmark(self._window, self._file_handler,
                                                i18n.to_display_string(name), path, page, numpages, archive_type, date_added,
                                                member=member)

        self.add_bookmark(bookmark)

    @callback.Callback
    def add_bookmark(self, bookmark: bookmark_menu_item._Bookmark) -> None:
        """Add the <bookmark> to the list."""
        self._bookmarks.append(bookmark)
        self.write_bookmarks_file()

    @callback.Callback
    def remove_bookmark(self, bookmark: bookmark_menu_item._Bookmark) -> None:
        """Remove the <bookmark> from the list."""
        self._bookmarks.remove(bookmark)
        self.write_bookmarks_file()

    @callback.Callback
    def replace_bookmark(self, old: bookmark_menu_item._Bookmark,
                         new: bookmark_menu_item._Bookmark) -> None:
        """Put <new> where <old> stands in the list."""
        self._bookmarks[self._bookmarks.index(old)] = new
        self.write_bookmarks_file()

    def bookmarks_for_path(self, path: str
                           ) -> list[bookmark_menu_item._Bookmark]:
        """Every bookmark that marks a page of the file at <path>."""
        return [bookmark for bookmark in self._bookmarks
                if bookmark.same_path(path)]

    def remove_for_path(self, path: str) -> None:
        """Remove every bookmark that marks a page of the file at <path>.

        One at a time, through remove_bookmark(), so that the menu and
        an open bookmarks dialog hear about each of them as they would
        about any other removal.
        """
        for bookmark in self.bookmarks_for_path(path):
            self.remove_bookmark(bookmark)

    def update_path(self, old_path: str, new_path: str) -> None:
        """Follow a book that has been moved to <new_path>.

        A bookmark holds the path of the file it marks, and one left at
        the old path would point at a file that is not there.  The
        library and the store of last read pages are brought forward the
        same way when a book moves.
        """
        for bookmark in self.bookmarks_for_path(old_path):
            name, _path, page, numpages, archive_type, added = bookmark.pack()
            self.replace_bookmark(bookmark, bookmark_menu_item._Bookmark(
                self._window, self._file_handler, name, new_path, page,
                numpages, archive_type, added, member=bookmark.get_member()))

    @callback.Callback
    def set_bookmark_order(self,
                           order: list[bookmark_menu_item._Bookmark]) -> None:
        """Put the stored bookmarks into <order>.

        A bookmark in <order> that is no longer stored is dropped from
        it, and one that is stored but not in <order> keeps its place
        after the rest, so that a dialog writing back the order it was
        showing can neither bring back a bookmark another window has
        removed - which raised a ValueError out of remove_bookmark()
        while this was a loop of remove and add - nor lose one added
        since it opened.

        What is kept is the stored bookmark rather than the one handed
        in: the two are equal when they mark the same page of the same
        file, which leaves the name, the page count and the date free
        to differ.
        """
        unplaced = {bookmark: bookmark for bookmark in self._bookmarks}
        ordered = []
        for bookmark in order:
            stored = unplaced.pop(bookmark, None)
            if stored is not None:
                ordered.append(stored)
        ordered.extend(bookmark for bookmark in self._bookmarks
                       if bookmark in unplaced)

        # One write for the whole order, and none at all for an order
        # that is already the stored one: this was a remove and an add
        # per bookmark, and each of those re-pickled and fsynced the
        # whole file and rebuilt the bookmarks menu.
        if ordered != self._bookmarks:
            self._bookmarks = ordered
            self.write_bookmarks_file()

    def add_current_to_bookmarks(self) -> None:
        """Add the currently viewed page to the list."""
        if self._image_handler is None or self._file_handler is None:
            raise ValueError('The bookmarks store has no handlers yet.')
        name = self._image_handler.get_pretty_current_filename()
        path = self._image_handler.get_real_path()
        if path is None:
            # The menu entry is insensitive without a file open, so this
            # is only reached if something bypasses it.
            return
        page = self._image_handler.get_current_page()
        numpages = self._image_handler.get_number_of_pages()
        archive_type = self._file_handler.archive_type
        member = self._file_handler.page_member(page)
        date_added = datetime.datetime.now()

        same_file_bookmarks = []

        for bookmark in self._bookmarks:
            if bookmark.same_path(path):
                if bookmark.same_page(page):
                    # Do not create identical bookmarks
                    return
                else:
                    same_file_bookmarks.append(bookmark)

        def add() -> None:
            self.add_bookmark_by_values(name, path, page, numpages,
                                        archive_type, date_added, member)

        # If the same file was already bookmarked, ask to replace
        # the existing bookmarks before deleting them.
        if not same_file_bookmarks:
            add()
            return

        def replace_answered(response: int) -> None:
            # Delete old bookmarks
            if response == Response.YES:
                for bookmark in same_file_bookmarks:
                    self.remove_bookmark(bookmark)
            # Perform no action
            elif response not in (Response.YES, Response.NO):
                return
            add()

        self.show_replace_bookmark_dialog(same_file_bookmarks, page,
                                          replace_answered)

    @callback.Callback
    def clear_bookmarks(self) -> None:
        """Remove every bookmark, this instance's and the file's.

        One write and one notification, rather than one of each per
        bookmark: removing them one at a time re-pickled and fsynced the
        whole store for every bookmark, and rebuilt the menu as many
        times.  The write does not merge, either - what the reader was
        told is that all stored bookmarks will be removed, so a bookmark
        another instance has added since is one of them.
        """
        self._bookmarks = []
        self.write_bookmarks_file(merge=False)

    def get_bookmarks(self) -> list[bookmark_menu_item._Bookmark]:
        """Return all the bookmarks in the list."""
        if not self.file_was_modified():
            return self._bookmarks
        else:
            self._bookmarks, self._bookmarks_mtime = self.load_bookmarks()
            return self._bookmarks

    def is_empty(self) -> bool:
        """Return True if the bookmark list is empty."""
        return not self._bookmarks

    def load_bookmarks(self) -> tuple[list[bookmark_menu_item._Bookmark], int]:
        """Read the stored bookmarks, and return them with the file's mtime.

        The mtime comes back with them, in nanoseconds, because that is
        what file_was_modified() compares against later to tell another
        instance's write from this one's own.

        A file that is not there, or one that cannot be unpickled, gives
        back an empty list or however much of it was read: a damaged
        bookmarks file should cost the bookmarks, not the session.
        """

        path = constants.BOOKMARK_PICKLE_PATH
        bookmarks: list[bookmark_menu_item._Bookmark] = []
        mtime = 0

        if os.path.isfile(path):
            try:
                mtime = os.stat(path).st_mtime_ns
                with open(path, 'rb') as fd:
                    pickle.load(fd)  # Version record, no longer used.
                    packs = pickle.load(fd)
                    # The name within its archive of each bookmark's
                    # page, in a record of its own after the bookmarks,
                    # which an older MComix stops short of.  A file one
                    # of those wrote has none.
                    try:
                        members = pickle.load(fd)
                    except EOFError:
                        members = []
                if (not isinstance(members, list)
                        or len(members) != len(packs)):
                    members = [None] * len(packs)

                for pack, member in zip(packs, members):
                    # Handle old bookmarks without date_added attribute
                    if len(pack) == 5:
                        pack = pack + (datetime.datetime.now(),)

                    name, book_path, page, numpages, archive_type, added = pack
                    bookmark = bookmark_menu_item._Bookmark(
                        self._window, self._file_handler, name, book_path, page,
                        numpages, archive_type, added,
                        member=member if isinstance(member, str) else None)
                    bookmarks.append(bookmark)

            except Exception:
                log.error(_('! Could not parse bookmarks file %s'), path)

        return bookmarks, mtime

    def file_was_modified(self) -> bool:
        """Whether the store's file has been written since it was read.

        A file that is not there has not been written by anyone, so the
        answer is no.  Were it yes, get_bookmarks() would re-read nothing
        over the bookmarks it holds: deleting the file under a running
        MComix would empty its list, and the next bookmark added would
        write that empty list back over what the reader had.
        """
        path = constants.BOOKMARK_PICKLE_PATH
        if not os.path.isfile(path):
            return False
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = 0
        # Compared whole, and for any difference rather than for a later
        # time: in whole seconds, as it was, a write by another instance
        # within the second of this one's own went unseen, and the next
        # write here put the file back without what it had added.
        return mtime != self._bookmarks_mtime

    def write_bookmarks_file(self, merge: bool = True) -> None:
        """Store relevant bookmark info in the mcomix directory.

        <merge> takes in what another instance has written since the
        file was last read, which is what every change to a single
        bookmark wants.  Only clear_bookmarks() passes False: it is
        meant to empty the file, not to leave another instance's
        bookmarks standing in it.
        """

        # Another instance may have written the file since it was last
        # read, so merge what is in it back in before overwriting it.
        # dict.fromkeys() rather than a set: two bookmarks are the same
        # when they mark the same page of the same file, but the order of
        # the list is the order the menu and the dialog show, so it has
        # to survive the merge.  Ours keep their places and the other
        # instance's newcomers follow, in the order it wrote them.
        if merge and self.file_was_modified():
            new_bookmarks, _mtime = self.load_bookmarks()
            self._bookmarks = list(dict.fromkeys(self._bookmarks +
                                                 new_bookmarks))

        with tools.atomic_write(constants.BOOKMARK_PICKLE_PATH, binary=True) as fd:
            pickle.dump(constants.VERSION, fd, pickle.HIGHEST_PROTOCOL)

            packs = [bookmark.pack() for bookmark in self._bookmarks]
            pickle.dump(packs, fd, pickle.HIGHEST_PROTOCOL)
            pickle.dump([bookmark.get_member()
                         for bookmark in self._bookmarks],
                        fd, pickle.HIGHEST_PROTOCOL)

        # The file's own time rather than the clock's, which is what the
        # next file_was_modified() compares with.
        try:
            self._bookmarks_mtime = os.stat(
                constants.BOOKMARK_PICKLE_PATH).st_mtime_ns
        except OSError:
            self._bookmarks_mtime = 0

    def show_replace_bookmark_dialog(self,
                                     old_bookmarks: list[bookmark_menu_item._Bookmark],
                                     new_page: int,
                                     on_response: Callable[[int], None]) -> None:
        """ Present a confirmation dialog to replace old bookmarks.

        Calls <on_response> with Response.YES to replace the bookmarks,
        Response.NO to create a new one alongside them, and anything else
        to abort creating one at all. """
        dialog = message_dialog.MessageDialog(self._window, modal=True)
        dialog.add_buttons(_('_Yes'), Response.YES,
                           _('_No'), Response.NO,
                           _('_Cancel'), Response.CANCEL)
        dialog.set_default_response(Response.YES)
        dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.REPLACE_EXISTING_BOOKMARK)

        pages = list(map(str, sorted(map(operator.attrgetter('_page'), old_bookmarks))))
        dialog.set_text(
            i18n.get_translation().ngettext(
                'Replace existing bookmark on page %s?',
                'Replace existing bookmarks on pages %s?',
                len(pages)
            ) % ", ".join(pages),

            _('The current book already contains marked pages. '
              'Do you want to replace them with a new bookmark on page %d?')
            % new_page + '\n\n' +
            _('Selecting "No" will create a new bookmark without affecting the other bookmarks.'))

        dialog.run_async(on_response)

    def show_clear_bookmarks_dialog(self,
                                    on_response: Callable[[int], None]) -> None:
        """Ask whether to remove every bookmark.

        Calls <on_response> with Response.YES to go ahead.  The prompt
        offers no "Do not ask again": this is the one bookmark action
        that cannot be undone one step at a time. """
        dialog = message_dialog.MessageDialog(self._window, modal=True,
                                              buttons=Gtk.ButtonsType.YES_NO)
        # Every bookmark goes, so Enter must not be what does it, and the
        # button that does is drawn as the destructive action it is.
        dialog.set_default_response(Response.NO)
        clears = dialog.get_widget_for_response(Response.YES)
        if clears is not None:
            clears.add_css_class('destructive-action')
        dialog.set_text(
            _('Clear all bookmarks?'),
            _('All stored bookmarks will be removed. Are you sure that '
              'you want to continue?'))

        dialog.run_async(on_response)


# Singleton instance of the bookmarks store.
BookmarksStore = _BookmarksStore()

# vim: expandtab:sw=4:ts=4
