"""bookmark_menu_item.py - A single bookmark item."""

import datetime
import os
from typing import TYPE_CHECKING

from mcomix import column_list
from mcomix import i18n
from mcomix import process

if TYPE_CHECKING:
    from mcomix import file_handler
    from mcomix import main


class _Bookmark:

    """_Bookmark represents one bookmark.

    It used to be the menu item as well, extending Gtk.ImageMenuItem so it
    could be put straight into the bookmarks menu.  A menu model holds
    entries rather than widgets, so this is just the bookmark now and the
    menu makes its own entry out of it.
    """

    def __init__(self, window: 'main.MainWindow | None',
                 file_handler: 'file_handler.FileHandler | None',
                 name: str, path: str, page: int, numpages: int,
                 archive_type: int | None,
                 date_added: datetime.datetime,
                 member: str | None = None) -> None:

        self._name = name
        self._path = path
        self._page = page
        self._numpages = numpages
        self._window = window
        self._archive_type = archive_type
        self._file_handler = file_handler
        self._date_added = date_added
        #: The name within the archive of the file of the page, which
        #: finds the page wherever a change of sort order has put it;
        #: None for a loose image, whose path is its file, and for a
        #: bookmark made before this was kept.
        self._member = member

    def attach(self, window: 'main.MainWindow') -> None:
        """Open in <window> from now on.

        For a bookmark read from disk before there was a window to open
        it in, which is when the store loads them.
        """
        self._window = window
        self._file_handler = window.filehandler

    def get_label(self) -> str:
        """The text the menu shows for this bookmark."""
        return str(self)

    def get_icon_name(self) -> str:
        """The icon that goes with it: an archive, or a loose image."""
        return ('mcomix-archive' if self._archive_type is not None
                else 'mcomix-image')

    def __str__(self) -> str:
        return '%s, (%d / %d)' % (self._name, self._page, self._numpages)

    def load(self, *args: object) -> None:
        """Open the file and page the bookmark represents.

        Where that book is open already, only the page is turned:
        opening it again would close it first, and closing a book
        forgets the pages picked out of it and the changes that could be
        undone.  A bookmark in a folder of images names the file of its
        page, so the open folder is recognised by holding that file, and
        the page is found by it rather than by the number, which the
        folder may have moved since.  An archive is recognised by its
        own path, and its page is found by the name of its file within
        it where the bookmark knows that, since the archive may be
        sorted another way since.
        """

        if self._file_handler is None or self._window is None:
            raise ValueError('The bookmark has no window to open in.')
        if self._file_handler.archive_type is None:
            files = self._window.imagehandler.get_image_files()
            if self._path in files:
                self._window.set_page(files.index(self._path) + 1)
                return
        elif self._file_handler.get_path_to_base() == self._path:
            page = (self._file_handler.page_of_member(self._member)
                    if self._member is not None else None)
            self._window.set_page(page or self._page)
            return
        self._file_handler.open_file(self._path, self._page,
                                     start_member=self._member)

    def open_in_new_instance(self) -> None:
        """Open the file and page in an MComix of its own.

        The book being read stays where it is, which is what the middle
        button means everywhere it opens something: a window of its own
        rather than this one's contents replaced.
        """
        process.launch_mcomix(self._path, self._page)

    def get_directory(self) -> str:
        """The directory the bookmarked file is in."""
        return os.path.dirname(self._path)

    def same_path(self, path: str) -> bool:
        """Return True if the bookmark is for the file <path>."""
        return path == self._path

    def same_page(self, page: int) -> bool:
        """Return True if the bookmark is for the same page."""
        return page == self._page

    def to_row(self) -> column_list.Row:
        """Return the row the bookmarks dialog shows this bookmark as."""
        return column_list.Row(
            icon=self.get_icon_name(),
            name=self._name,
            page='%d / %d' % (self._page, self._numpages),
            path=i18n.to_display_string(self._path),
            added=self._date_added.strftime("%x %X"),
            bookmark=self)

    def get_member(self) -> str | None:
        """The name within the archive of the file of the page, if known.

        Kept beside pack()'s tuple rather than in it: an older MComix
        builds a bookmark from the tuple as it is, and one field more
        cost it every bookmark in the file.
        """
        return self._member

    def pack(self) -> tuple[str, str, int, int, int | None, datetime.datetime]:
        """Return a tuple suitable for pickling. The bookmark can be fully
        re-created using the values in the tuple.
        """
        return (self._name, self._path, self._page, self._numpages,
                self._archive_type, self._date_added)

    def __eq__(self, other: object) -> bool:
        """ Equality comparison for Bookmark items. """
        if isinstance(other, _Bookmark):
            return self._path == other._path and self._page == other._page
        else:
            return False

    def __hash__(self) -> int:
        """ Hash for this object.  What __eq__ compares, and no more. """
        return hash((self._path, self._page))

# vim: expandtab:sw=4:ts=4
