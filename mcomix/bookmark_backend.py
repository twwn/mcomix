"""bookmark_backend.py - Bookmarks handler."""

import os
import pickle
import operator
import datetime
import time

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
        #: Modification date of bookmarks file
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
                bookmark._window = window
                bookmark._file_handler = window.filehandler

    def add_bookmark_by_values(self, name: str, path: str, page: int, numpages: int,
                               archive_type: int | None,
                               date_added: datetime.datetime) -> None:
        """Create a bookmark and add it to the list."""
        bookmark = bookmark_menu_item._Bookmark(self._window, self._file_handler,
            i18n.to_display_string(name), path, page, numpages, archive_type, date_added)

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
                archive_type, date_added)

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

    def clear_bookmarks(self) -> None:
        """Remove all bookmarks from the list."""

        while not self.is_empty():
            self.remove_bookmark(self._bookmarks[-1])

    def get_bookmarks(self) -> list[bookmark_menu_item._Bookmark]:
        """Return all the bookmarks in the list."""
        if not self.file_was_modified():
            return self._bookmarks
        else:
            self._bookmarks, self._bookmarks_mtime = self.load_bookmarks()
            return self._bookmarks

    def is_empty(self) -> bool:
        """Return True if the bookmark list is empty."""
        return len(self._bookmarks) == 0

    def load_bookmarks(self) -> tuple[list[bookmark_menu_item._Bookmark], int]:
        """ Loads persisted bookmarks from a local file.
        @return: Tuple of (bookmarks, file mtime)
        """

        path = constants.BOOKMARK_PICKLE_PATH
        bookmarks: list[bookmark_menu_item._Bookmark] = []
        mtime = 0

        if os.path.isfile(path):
            try:
                mtime = int(os.stat(path).st_mtime)
                with open(path, 'rb') as fd:
                    pickle.load(fd)  # Version record, no longer used.
                    packs = pickle.load(fd)

                for pack in packs:
                    # Handle old bookmarks without date_added attribute
                    if len(pack) == 5:
                        pack = pack + (datetime.datetime.now(),)

                    bookmark = bookmark_menu_item._Bookmark(self._window,
                            self._file_handler, *pack)
                    bookmarks.append(bookmark)

            except Exception:
                log.error(_('! Could not parse bookmarks file %s'), path)

        return bookmarks, mtime

    def file_was_modified(self) -> bool:
        """ Checks the bookmark store's mtime to see if it has been modified
        since it was last read. """
        path = constants.BOOKMARK_PICKLE_PATH
        if os.path.isfile(path):
            try:
                mtime = int(os.stat(path).st_mtime)
            except OSError:
                mtime = 0

            if mtime > self._bookmarks_mtime:
                return True
            else:
                return False
        else:
            return True

    def write_bookmarks_file(self) -> None:
        """Store relevant bookmark info in the mcomix directory."""

        # Merge changes in case file was modified from within other instances
        if self.file_was_modified():
            new_bookmarks, new_mtime = self.load_bookmarks()
            self._bookmarks = list(set(self._bookmarks + new_bookmarks))

        with tools.atomic_write(constants.BOOKMARK_PICKLE_PATH, binary=True) as fd:
            pickle.dump(constants.VERSION, fd, pickle.HIGHEST_PROTOCOL)

            packs = [bookmark.pack() for bookmark in self._bookmarks]
            pickle.dump(packs, fd, pickle.HIGHEST_PROTOCOL)

        self._bookmarks_mtime = int(time.time())


    def show_replace_bookmark_dialog(self,
                                     old_bookmarks: list[bookmark_menu_item._Bookmark],
                                     new_page: int,
                                     on_response: Callable[[int], None]) -> None:
        """ Present a confirmation dialog to replace old bookmarks.

        Calls <on_response> with RESPONSE_YES to replace the bookmarks,
        RESPONSE_NO to create a new one alongside them, and anything else
        to abort creating one at all. """
        dialog = message_dialog.MessageDialog(self._window, modal=True)
        dialog.add_buttons(_('_Yes'), Response.YES,
             _('_No'), Response.NO,
             _('_Cancel'), Response.CANCEL)
        dialog.set_default_response(Response.YES)
        dialog.set_should_remember_choice('replace-existing-bookmark',
            (Response.YES, Response.NO))

        pages = list(map(str, sorted(map(operator.attrgetter('_page'), old_bookmarks))))
        dialog.set_text(
            i18n.get_translation().ngettext(
                'Replace existing bookmark on page %s?',
                'Replace existing bookmarks on pages %s?',
                len(pages)
            ) % ", ".join(pages),

            _('The current book already contains marked pages. '
              'Do you want to replace them with a new bookmark on page %d?') % new_page +
              '\n\n' +
            _('Selecting "No" will create a new bookmark without affecting the other bookmarks.'))

        dialog.run_async(on_response)


# Singleton instance of the bookmarks store.
BookmarksStore = _BookmarksStore()

# vim: expandtab:sw=4:ts=4
