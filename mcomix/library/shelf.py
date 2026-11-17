"""The library's covers in the main window, while no book is open.

A window with no book in it has nothing to show, and the books to open
are a window away.  The Shelf fills the page area with the covers of
the books last read - of every book, where none has been read yet -
and a click on one opens it.  It is the library window's cover area
with little around it: no collections and no adding, and a search
field only while CTRL+F has opened it.
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
from mcomix.library import control_area as library_control_area

if TYPE_CHECKING:
    from mcomix import main
    from mcomix.library import main_dialog

_CSS_CLASS = 'mcomix-shelf'


@functools.cache
def _paint_black(display: Gdk.Display) -> None:
    """Give <display> the rule that paints the Shelf as the library
    paints its covers' ground, with writing that shows on it, once: the
    provider stays with the display.

    The search field floats over the covers' corner: the bar a search
    field is put in otherwise would lay a strip of the theme's colour
    across them."""
    provider = Gtk.CssProvider()
    provider.load_from_string(
        '.%s { background-color: black; color: white; }'
        '.%s searchbar > revealer > box { background: none;'
        ' border-style: none; box-shadow: none; }'
        '.%s searchbar .close { color: inherit; }'
        % (_CSS_CLASS, _CSS_CLASS, _CSS_CLASS))
    Gtk.StyleContext.add_provider_for_display(
        display, provider, theme.VIEW_COLOUR_PRIORITY)


class Shelf(Gtk.Box):

    """The covers, under a line that says which books they are.

    The cover area asks the library window it is part of for what is
    around it; here it asks the Shelf, which answers for the window,
    for the list of collections and for the search field at once.
    """

    #: Nothing is dragged, dropped or added here, and a letter typed
    #: over the covers is the window's shortcut, not a search.
    manages = False
    #: Every book of the collection is shown, whatever was last read.
    read_state = backend_types.ReadState.ANY
    #: What the cover area would type a search into: nothing, see
    #: manages.
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

        # The search field lies over the covers, so that opening it
        # moves nothing under it.
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay = Gtk.Overlay(child=content, vexpand=True)
        self.append(overlay)

        self._heading = Gtk.Label(xalign=0)
        self._heading.add_css_class('heading')
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(self._heading, 'set_margin_' + side)(6)
        content.append(self._heading)

        #: What the books shown hold in their name or path, as the
        #: search field says; None shows them all.
        self.filter_string: str | None = None
        # Shown by CTRL+F, and gone with Escape: a letter typed over the
        # covers stays the window's shortcut.
        self._search = Gtk.SearchEntry()
        self._search.set_tooltip_text(
            _('Display only those books that have the specified text string '
              'in their full path. The search is not case sensitive.'))
        self._search.set_search_delay(
            library_control_area._ControlArea.SEARCH_DELAY_MS)
        self._search.connect('search-changed', self._search_changed)
        self._search.connect('activate', self._search_changed)
        self._search_bar = Gtk.SearchBar(child=self._search,
                                         show_close_button=True,
                                         halign=Gtk.Align.END,
                                         valign=Gtk.Align.START)
        self._search_bar.connect_entry(self._search)
        self._search_bar.connect('notify::search-mode-enabled',
                                 self._search_mode_changed)
        # The window lets a key typed into the field go by its
        # shortcuts; what the field leaves, such as CTRL+O, comes back
        # up through here and is the window's after all.
        leftover = Gtk.EventControllerKey()
        leftover.connect('key-pressed', self._key_left_by_search)
        self._search_bar.add_controller(leftover)
        overlay.add_overlay(self._search_bar)

        # The cover area takes the library window; what it asks of one
        # is what this class has.
        self.book_area = library_book_area._BookArea(
            cast('main_dialog._LibraryDialog', self))
        self.book_area.set_vexpand(True)
        content.append(self.book_area)

        self._empty = Gtk.Label(
            label=_('The library holds no books yet. '
                    'Add some in the library window.'),
            wrap=True, justify=Gtk.Justification.CENTER)
        self._empty.set_vexpand(True)
        content.append(self._empty)

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
        # A search looks among every book: those last read are a few.
        if self.filter_string is None and recent.get_books():
            self._collection = constants.COLLECTION_RECENT
            self._heading.set_text(_('Recent'))
            books = True
        else:
            self._collection = constants.COLLECTION_ALL
            self._heading.set_text(_('All books'))
            books = self.backend.has_books()
        self._heading.set_visible(books)
        self.book_area.set_visible(books)
        self._empty.set_visible(not books)
        self.book_area.display_covers(self._collection)

    def get_current_collection(self) -> int | None:
        return self._collection

    def search(self) -> None:
        """Open the search field, or go back to it, with the keyboard."""
        self._search_bar.set_search_mode(True)
        self._search.grab_focus()

    def search_has_focus(self) -> bool:
        """Whether the keyboard is on the search field.

        The window takes every key before anything in it, for its
        shortcuts, and a letter typed into the field would toggle
        fullscreen or turn a page as well, and Escape, which closes the
        field, leave fullscreen; while this holds, it lets them go by.
        """
        focus = self.main_window.get_focus()
        return focus is not None and (focus is self._search
                                      or focus.is_ancestor(self._search))

    def _key_left_by_search(self, controller: Gtk.EventControllerKey,
                            keyval: int, keycode: int,
                            state: Gdk.ModifierType) -> bool:
        """A key the search field did not take is the window's."""
        if not self.search_has_focus():
            return Gdk.EVENT_PROPAGATE
        return self.main_window.event_handler.shortcut_key_press(
            controller, keyval, keycode, state)

    def _search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Show the books whose name or path holds what <entry> does,
        among every book; the shelf as it was once it is empty."""
        text = entry.get_text() or None
        if text == self.filter_string:
            return
        self.filter_string = text
        self.show_books()

    def _search_mode_changed(self, bar: Gtk.SearchBar,
                             _param: object) -> None:
        """Closed - by Escape or its button - the search lets go of its
        text, and the covers have the keyboard again."""
        if bar.get_search_mode():
            return
        # The field's text, or its close button, held the keyboard.
        focus = self.main_window.get_focus()
        refocus = focus is None or focus.is_ancestor(bar)
        self._search.set_text('')
        self._search_changed(self._search)
        if refocus:
            self.book_area.focus_covers()

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
