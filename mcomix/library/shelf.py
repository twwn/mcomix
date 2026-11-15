"""The library's covers in the main window, while no book is open.

A window with no book in it has nothing to show, and the books to open
are a window away.  The Shelf fills the page area with the covers of
the books last read - of every book, where none has been read yet -
and a click on one opens it.  It is the library window's cover area
with nothing around it: no collections, no search, no adding.
"""

import functools
import weakref
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

from gi.repository import Gdk, GLib, Gtk

from mcomix import constants
from mcomix import theme
from mcomix.i18n import _
from mcomix.library import backend as library_backend
from mcomix.library import backend_types
from mcomix.library import book_area as library_book_area

if TYPE_CHECKING:
    from mcomix import main
    from mcomix.library import main_dialog

_CSS_CLASS = 'mcomix-shelf'


@functools.cache
def _paint_black(display: Gdk.Display) -> None:
    """Give <display> the rule that paints the Shelf as the library
    paints its covers' ground, with writing that shows on it, once: the
    provider stays with the display."""
    provider = Gtk.CssProvider()
    provider.load_from_string(
        '.%s { background-color: black; color: white; }' % _CSS_CLASS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, theme.VIEW_COLOUR_PRIORITY)


class Shelf(Gtk.Box):

    """The covers, under a line that says which books they are.

    The cover area asks the library window it is part of for what is
    around it; here it asks the Shelf, which answers for the window,
    for the list of collections and for the search field at once.
    """

    #: Nothing is dragged, dropped, added or searched for here.
    manages = False
    #: Every book of the collection is shown.
    filter_string: str | None = None
    read_state = backend_types.ReadState.ANY
    #: There is no search field to type into.
    search_entry = None

    def __init__(self, window: 'main.MainWindow') -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = weakref.ref(window)
        self.backend = library_backend.LibraryBackend()
        self._collection: int = constants.COLLECTION_ALL
        self._closed = False
        # Whatever colour the pages' ground has, and whatever the theme
        # writes in.
        self.add_css_class(_CSS_CLASS)
        _paint_black(self.get_display())

        self._heading = Gtk.Label(xalign=0)
        self._heading.add_css_class('heading')
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(self._heading, 'set_margin_' + side)(6)
        self.append(self._heading)

        # The cover area takes the library window; what it asks of one
        # is what this class has.
        self.book_area = library_book_area._BookArea(
            cast('main_dialog._LibraryDialog', self))
        self.book_area.set_vexpand(True)
        self.append(self.book_area)

        self._empty = Gtk.Label(
            label=_('The library holds no books yet. '
                    'Add some in the library window.'),
            wrap=True, justify=Gtk.Justification.CENTER)
        self._empty.set_vexpand(True)
        self.append(self._empty)

    @property
    def main_window(self) -> 'main.MainWindow':
        """The window the covers are shown in.

        Held weakly: GTK holds the Shelf for as long as the window's
        widgets stand, and a plain reference would keep the window
        alive with it once it is closed.
        """
        window = self._window()
        assert window is not None
        return window

    @property
    def window(self) -> Gtk.Window:
        """The window the covers' questions are asked over."""
        return self.main_window

    @property
    def collection_area(self) -> 'Shelf':
        return self

    @property
    def control_area(self) -> 'Shelf':
        return self

    def show_books(self) -> None:
        """Show the books last read, or every book where none has been
        read, as the library now holds them."""
        if self._closed:
            return
        recent = self.backend.get_recent_collection()
        if recent.get_books():
            self._collection = constants.COLLECTION_RECENT
            self._heading.set_text(_('Recent'))
            books = True
        else:
            self._collection = constants.COLLECTION_ALL
            self._heading.set_text(_('All books'))
            books = bool(self.backend.get_books_in_collection(None))
        self._heading.set_visible(books)
        self.book_area.set_visible(books)
        self._empty.set_visible(not books)
        self.book_area.display_covers(self._collection)

    def get_current_collection(self) -> int | None:
        return self._collection

    def clean_collection(self, collection: int | None) -> None:
        """Take the books of <collection> whose files have gone out of
        the library, every such book where it is None."""
        if self.backend.clean_collection(collection):
            GLib.idle_add(self.show_books)

    def update_info(self, selected: Sequence[int]) -> None:
        """There is no box that tells of the books selected."""

    def set_status_message(self, message: str) -> None:
        """There is no line for the library's messages."""

    def add_books(self, paths: Sequence[str],
                  collection: int | None = None) -> None:
        """Nothing is added from here."""

    def open_book(self, books: Sequence[int],
                  keep_library_open: bool = False) -> None:
        """Open the books whose ids are in <books>: one among the books
        shown, which Next and Previous book then walk; several as one
        book of their pages."""
        paths = [path for path in map(self.backend.get_book_path, books)
                 if path is not None]
        handler = self.main_window.filehandler
        if len(paths) > 1:
            handler.open_file(paths)
        elif paths:
            handler.open_file(paths[0], listed=self.book_area.shown_paths())

    def close(self) -> None:
        """Stop the cover area's work, before the window goes."""
        if not self._closed:
            self._closed = True
            self.book_area.close()
            self.book_area.release()

# vim: expandtab:sw=4:ts=4
