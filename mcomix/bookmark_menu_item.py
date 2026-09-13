"""bookmark_menu_item.py - A signle bookmark item."""

from mcomix import i18n
from mcomix import icons

#: The pixel size Gtk.IconSize.MENU stands for.
_MENU_ICON_SIZE = 16


class _Bookmark(object):

    """_Bookmark represents one bookmark.

    It used to be the menu item as well, extending Gtk.ImageMenuItem so it
    could be put straight into the bookmarks menu.  A menu model holds
    entries rather than widgets, so this is just the bookmark now and the
    menu makes its own entry out of it.
    """

    def __init__(self, window, file_handler, name, path, page, numpages, archive_type, date_added):

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

    def __str__(self):
        return '%s, (%d / %d)' % (self._name, self._page, self._numpages)

    def load(self, *args):
        """Open the file and page the bookmark represents."""

        if self._file_handler._base_path != self._path:
            self._file_handler.open_file(self._path, self._page)
        else:
            self._window.set_page(self._page)

    def same_path(self, path):
        """Return True if the bookmark is for the file <path>."""
        return path == self._path

    def same_page(self, page):
        """Return True if the bookmark is for the same page."""
        return page == self._page

    def to_row(self):
        """Return a tuple corresponding to one row in the _BookmarkDialog's
        ListStore.
        """
        pixbuf = icons.load_pixbuf(self.get_icon_name(), _MENU_ICON_SIZE)
        page = '%d / %d' % (self._page, self._numpages)
        date = self._date_added.strftime("%x %X")

        return (pixbuf, self._name, page, i18n.to_display_string(self._path),
            date, self)

    def pack(self):
        """Return a tuple suitable for pickling. The bookmark can be fully
        re-created using the values in the tuple.
        """
        return (self._name, self._path, self._page, self._numpages,
            self._archive_type, self._date_added)

    def __eq__(self, other):
        """ Equality comparison for Bookmark items. """
        if isinstance(other, _Bookmark):
            return self._path == other._path and self._page == other._page
        else:
            return False

    def __hash__(self):
        """ Hash for this object. """
        return hash(self._path) | hash(self._page)

# vim: expandtab:sw=4:ts=4
