"""book_properties.py - The properties of the books selected in the library.

The main window's Properties describe the book being read.  These
describe the books picked out among the library's covers, which need
not be open: what the library holds of each - its pages, its format,
when it was added and read, the collections it is filed in - and what
the file system knows of its file, in the rows the main window uses.
Several books are described together, as a file manager describes a
selection: how many, how many pages and bytes, how far they were read.
"""

import os

from gi.repository import GdkPixbuf, Gtk

from mcomix import archive_tools
from mcomix import i18n
from mcomix import image_tools
from mcomix import properties_dialog
from mcomix import properties_page
from mcomix import tools
from mcomix import widgets
from mcomix.dialog import Dialog, Response
from mcomix.i18n import _
from mcomix.library import backend_types

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library import backend


#: How dates are written on the page, as the main window's Properties
#: write a file's.
_DATE = '%Y-%m-%d, %H:%M:%S'


class BookPropertiesDialog(Dialog):

    """The properties of <books>, one or more books of the library."""

    def __init__(self, parent: "Gtk.Window | None",
                 library: "backend._LibraryBackend",
                 books: "Sequence[backend_types._Book]",
                 cover: "GdkPixbuf.Pixbuf | None" = None,
                 scale: float = 1) -> None:
        """<cover> is the picture the library shows for a single book,
        drawn with <scale> of the screen's pixels to each of the
        window's; a book's cover is not read again for this."""
        super().__init__(title=_('Properties'), transient_for=parent,
                         destroy_with_parent=True)
        self.add_buttons(_('_Close'), Response.CLOSE)
        self.set_default_response(Response.CLOSE)
        self.set_default_size(500, 430)
        self.set_resizable(True)
        widgets.set_border(self, 4)

        self.page = properties_page._Page()
        widgets.set_border(self.page, 6)
        widgets.pack(self.get_content_area(), self.page, True, True, 0)
        if len(books) == 1:
            self._describe_book(books[0], cover, scale)
        else:
            self._describe_books(library, books)
        self.connect('response', lambda dialog, response: dialog.destroy())
        self.set_visible(True)

    def _describe_book(self, book: "backend_types._Book",
                       cover: "GdkPixbuf.Pixbuf | None",
                       scale: float) -> None:
        """One book: its cover, name, pages and format, then what the
        library and the file system know of it."""
        page = self.page
        if cover is not None:
            side = int(round(128 * scale))
            page.set_thumbnail(image_tools.fit_in_rectangle(
                cover, side, side), scale)
        page.set_filename(book.name)
        ngettext = i18n.get_translation().ngettext
        page.set_main_info((
            ngettext('%d page', '%d pages', book.pages) % book.pages,
            archive_tools.describe(book.path, book.format),
        ))
        rows = properties_dialog.file_rows(book.path)
        if not os.path.exists(book.path):
            # What the library recorded, the file being gone.
            rows.append((_('Size'), tools.format_byte_size(book.size)))
        rows.append((_('Date added'), _written(book.added)))
        last_page = book.get_last_read_page()
        last_date = book.get_last_read_date()
        if last_page is not None and last_date is not None:
            rows.append((_('Last read'), '%s %d/%d, %s' % (
                _('Page'), last_page, book.pages, last_date.strftime(_DATE))))
        names = [collection.name for collection in book.get_collections()
                 if collection.id is not None]
        if names:
            rows.append((_('Collection'), ', '.join(sorted(
                names, key=i18n.to_unicode))))
        page.set_secondary_info(rows)

    def _describe_books(self, library: "backend._LibraryBackend",
                        books: "Sequence[backend_types._Book]") -> None:
        """Several books: how many, their pages and bytes together, the
        folder they share, and how far they were read."""
        page = self.page
        ngettext = i18n.get_translation().ngettext
        page.set_filename(ngettext('%d book', '%d books', len(books))
                          % len(books))
        pages = sum(book.pages for book in books)
        # In the words the library's own summary of the books on show
        # uses, under the covers.
        stats = library.reading_statistics(
            book.id for book in books if book.id is not None)
        read = [_('Pages read: %d') % stats.pages_read]
        if stats.last_read is not None:
            read.append(_('last read on %(date)s, %(time)s') % {
                'date': stats.last_read.strftime('%x'),
                'time': stats.last_read.strftime('%X')})
        page.set_main_info((
            ngettext('%d page', '%d pages', pages) % pages,
            tools.format_byte_size(sum(book.size for book in books)),
            _('Started: %(started)d, finished: %(finished)d') % {
                'started': stats.started, 'finished': stats.finished},
            ', '.join(read),
        ))
        folders = {os.path.dirname(book.path) for book in books}
        if len(folders) == 1:
            page.set_secondary_info([(_('Location'), i18n.to_display_string(
                i18n.to_unicode(folders.pop())))])


def _written(text: str) -> str:
    """A time the library keeps as text, as the page writes dates; the
    text itself where it is not one."""
    try:
        return backend_types.parse_time(text).strftime(_DATE)
    except (TypeError, ValueError):
        return text

# vim: expandtab:sw=4:ts=4
