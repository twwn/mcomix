"""bookmark_menu_item.py - A single bookmark item."""

import datetime
from typing import TYPE_CHECKING

from mcomix import column_list
from mcomix import i18n

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
                 date_added: datetime.datetime) -> None:

        self._name = name
        self._path = path
        self._page = page
        self._numpages = numpages
        self._window = window
        self._archive_type = archive_type
        self._file_handler = file_handler
        self._date_added = date_added

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
        """Open the file and page the bookmark represents."""

        if self._file_handler is None or self._window is None:
            raise ValueError('The bookmark has no window to open in.')
        if self._file_handler._base_path != self._path:
            self._file_handler.open_file(self._path, self._page)
        else:
            self._window.set_page(self._page)

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
