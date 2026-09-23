"""control_area.py - The strip along the bottom of the library window.

What the current selection is - its name, its directory, how far it has
been read and how large it is - beside the button that opens it and the
one that shows the watch list, and the entry that filters the covers
shown down to the books a substring occurs in.
"""

import os
import weakref
from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import Pango

from mcomix import i18n
from mcomix import labels
from mcomix import tools
from mcomix.library.watchlist import WatchListDialog
from mcomix import widgets
from mcomix.i18n import _

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library import main_dialog


class _ControlArea(Gtk.Box):

    """The _ControlArea is the bottom area of the library window where
    information is displayed and controls such as buttons reside.
    """

    def __init__(self, library: "main_dialog._LibraryDialog") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        widgets.set_border(self, 10)

        self._library_ref = weakref.ref(library)

        borderbox = Gtk.Frame()
        borderbox.set_size_request(350, -1)

        infobox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 5)
        widgets.set_border(infobox, 10)
        widgets.pack(self, borderbox, True, True, 0)
        borderbox.set_child(infobox)

        self._namelabel = labels.BoldLabel()
        self._namelabel.set_xalign(0)
        self._namelabel.set_yalign(0.5)
        self._namelabel.set_selectable(True)
        self._namelabel.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        widgets.pack(infobox, self._namelabel, False, False, 0)

        self._filelabel = Gtk.Label()
        self._filelabel.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._filelabel.set_xalign(0)
        self._filelabel.set_yalign(0.5)
        widgets.pack(infobox, self._filelabel, False, False, 0)

        self._dirlabel = Gtk.Label()
        self._dirlabel.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._dirlabel.set_xalign(0)
        self._dirlabel.set_yalign(0.5)
        self._dirlabel.set_selectable(True)
        widgets.pack(infobox, self._dirlabel, False, False, 0)

        vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 10)
        vbox.set_size_request(350, -1)
        widgets.pack(self, vbox, False, False, 0)

        # First line of controls, containing the search box
        hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.pack(vbox, hbox, True, True, 0)

        label = Gtk.Label(label=_('_Search:'))
        label.set_use_underline(True)
        widgets.pack(hbox, label, False, False, 0)
        search_entry = Gtk.Entry()
        search_entry.connect('activate', self._filter_books)
        search_entry.set_tooltip_text(
            _('Display only those books that have the specified text string '
              'in their full path. The search is not case sensitive.'))
        widgets.pack(hbox, search_entry, True, True, 6)
        label.set_mnemonic_widget(search_entry)

        # Last line of controls, containing buttons like 'Open'
        hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
        widgets.pack(vbox, hbox, True, True, 0, end=True)

        watchlist_button = Gtk.Button(label=_("_Watch list"), use_underline=True)
        watchlist_button.connect('clicked',
                                 lambda *args: WatchListDialog(self._library))
        watchlist_button.set_tooltip_text(
            _('Open the watchlist management dialog.'))
        widgets.pack(hbox, watchlist_button, True, True, 0)

        self._open_button = Gtk.Button(label=_("_Open list"), use_underline=True)
        self._open_button.connect('clicked',
                                  self._library.book_area.open_selected_book)
        self._open_button.set_tooltip_text(_('Open the selected book.'))
        self._open_button.set_sensitive(False)
        widgets.pack(hbox, self._open_button, True, True, 0, end=True)

    @property
    def _library(self) -> "main_dialog._LibraryDialog":
        """The library window this area is part of.

        Held weakly: GTK holds the area for as long as the window's
        widgets stand, which is for good once the window is closed,
        and a plain reference would keep the window alive with it.
        """
        library = self._library_ref()
        assert library is not None, 'the library window is gone'
        return library

    def update_info(self, selected: Sequence[int]) -> None:
        """Update the info box using the currently <selected> books from
        the _BookArea.
        """

        book = None
        if selected:
            book_id = self._library.book_area.get_book_at_path(selected[0])
            if book_id is not None:
                book = self._library.backend.get_book_by_id(book_id)

        name = book.name if book else None
        dir_path = os.path.dirname(book.path) if book else None
        pages = book.pages if book else None
        size = book.size if book else None
        last_page = book.get_last_read_page() if book else None
        last_date = book.get_last_read_date() if book else None

        self._open_button.set_sensitive(bool(selected))

        if name is not None:
            self._namelabel.set_text(i18n.to_unicode(name))
            self._namelabel.set_tooltip_text(i18n.to_unicode(name))
        else:
            self._namelabel.set_text('')
            self._namelabel.set_has_tooltip(False)

        infotext = []

        if last_page is not None and pages is not None and last_page != pages:
            infotext.append('%s %d/%d' % (_('Page'), last_page, pages))
        elif pages is not None:
            infotext.append(i18n.get_translation().ngettext(
                '%d page', '%d pages', pages) % pages)

        if size is not None:
            infotext.append(tools.format_byte_size(size))

        if (pages is not None and last_page is not None and
                last_date is not None and last_page == pages):
            infotext.append(_('Finished reading on %(date)s, %(time)s') % {
                'date': last_date.strftime('%x'),
                'time': last_date.strftime('%X')})

        self._filelabel.set_text(', '.join(infotext))

        if dir_path is not None:
            self._dirlabel.set_text(i18n.to_unicode(dir_path))
        else:
            self._dirlabel.set_text('')

    def _filter_books(self, entry: Gtk.Entry, *args: object) -> None:
        """Display only the books in the current collection whose name or
        path contains the string in the Gtk.Entry. The string is not
        case-sensitive.
        """
        self._library.filter_string = entry.get_text()
        if not self._library.filter_string:
            self._library.filter_string = None
        collection = self._library.collection_area.get_current_collection()
        GLib.idle_add(self._library.book_area.display_covers, collection)

# vim: expandtab:sw=4:ts=4
