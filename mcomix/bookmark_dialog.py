"""bookmark_dialog.py - Bookmarks dialog handler."""

from gi.repository import Gdk, Gtk

from mcomix.dialog import Dialog
from mcomix.preferences import prefs
from mcomix import column_list
from mcomix import tools
from mcomix import widgets
from mcomix import constants
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import bookmark_backend
    from mcomix import bookmark_menu_item
    from mcomix import main


class _BookmarksDialog(Dialog):

    """_BookmarksDialog lets the user remove or rearrange bookmarks."""

    def __init__(self, window: "main.MainWindow",
                 bookmarks_store: "bookmark_backend._BookmarksStore") -> None:
        super().__init__(
            title=_('Edit Bookmarks'), transient_for=window,
            destroy_with_parent=True)
        self.add_buttons(_('C_lear bookmarks...'), constants.RESPONSE_CLEAR,
                         _('_Remove'), constants.RESPONSE_REMOVE,
                         _('_Close'), Response.CLOSE)
        clears = self.get_widget_for_response(constants.RESPONSE_CLEAR)
        assert clears is not None
        clears.add_css_class('destructive-action')
        self._clear_button = clears

        self._bookmarks_store = bookmarks_store

        self.set_resizable(True)
        self.set_default_response(Response.CLOSE)
        # No margin around what the window holds, so that the list of
        # bookmarks reaches its edges; the button row below the content
        # area brings its own spacing.
        widgets.set_border(self, 0)

        scrolled = Gtk.ScrolledWindow()
        widgets.set_border(scrolled, 0)
        # Gtk.ShadowType is gone; the frame comes from the theme.
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        widgets.pack(self.get_content_area(), scrolled, True, True, 0)

        self._list = column_list.ColumnListView()
        self._list.set_reorderable(True)
        # search by typing first few letters of name
        self._list.set_search_attribute('name')
        scrolled.set_child(self._list)

        self._icon_col = self._list.add_icon_column(
            _('Type'), 'icon', sort_key=self._sort_key('_archive_type',
                                                       '_name', '_page'))
        self._name_col = self._list.add_text_column(
            _('Name'), 'name', expand=True,
            sort_key=self._sort_key('_name', '_page', '_path'))
        self._page_col = self._list.add_text_column(
            _('Page'), 'page',
            sort_key=self._sort_key('_page', '_numpages', '_name'))
        self._path_col = self._list.add_text_column(
            _('Location'), 'path', sort_key=lambda row: row.path)
        # TRANSLATORS: "Added" as in "Date Added"
        self._date_add_col = self._list.add_text_column(
            _('Added'), 'added', sort_key=self._sort_key('_date_added'))

        # Right-clicking any heading offers the rest; Location starts
        # out hidden because there is rarely room for it beside the
        # others, not because it is not worth having.
        self._list.offer_column_chooser(
            hidden=prefs['hidden bookmark columns'],
            changed=self._remember_columns)

        self.set_default_size(600, 450)

        # Only 'response': Dialog turns the window's close button into
        # one of those, so connecting to 'close-request' as well ran
        # the closing twice over, once through each.
        self.connect('response', self._response)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press_event)
        self._list.add_controller(keys)
        self._list.connect('activate', self._bookmark_activated)
        self._list.selection.connect('selection-changed',
                                     self._selection_changed)

        for bookmark in self._bookmarks_store.get_bookmarks():
            self._add_bookmark(bookmark)
        self._store_changed()

        # What the store's own docstring promises: a change to it shows
        # in the menu and in the dialog alike.  Adding a bookmark with
        # Ctrl+D, or a second window removing one, used to leave the
        # dialog listing what the store held when it opened.
        self._bookmarks_store.add_bookmark += self._bookmark_added
        self._bookmarks_store.remove_bookmark += self._bookmark_removed
        self._bookmarks_store.clear_bookmarks += self._bookmarks_cleared

        self.set_visible(True)

    @staticmethod
    def _remember_columns(hidden: list[str]) -> None:
        """Keep the chosen columns for the next dialog.

        The window is built again every time it is opened, so what the
        headings' menu was told has to outlive it.
        """
        prefs['hidden bookmark columns'] = hidden

    @staticmethod
    def _sort_key(*fields: str) -> \
            "Callable[[column_list.Row], tools.SupportsLessThan]":
        """Order the rows by <fields> of the bookmark, in turn.

        The fields go into a tuple rather than being compared one at a
        time as they were, which needs them all to be orderable against
        their own kind: _archive_type is None for a loose image and a
        number for an archive, and comparing the two raised a TypeError
        the moment the Type heading was clicked on a mixed list.  A None
        sorts before every number here.
        """
        def key(row: column_list.Row) -> "tuple[tuple[bool, Any], ...]":  # type: ignore[explicit-any]  # a bookmark field read by a run-time name
            # Any, because a field read by a name worked out at run time
            # is whatever that field of a bookmark holds.
            values = []
            for field in fields:
                value = getattr(row.bookmark, field)
                values.append((value is not None, value))
            return tuple(values)
        return key

    def _add_bookmark(self,
                      bookmark: "bookmark_menu_item._Bookmark") -> None:
        """Add the <bookmark> to the dialog, newest first."""
        self._list.insert_row(0, bookmark.to_row())

    def _row_for(self, bookmark: "bookmark_menu_item._Bookmark") \
            -> "column_list.Row | None":
        """The row standing for <bookmark>, if it is listed.

        By the bookmark rather than by the row: a store that has been
        read again from the file holds bookmarks that are equal to the
        listed ones without being the same objects, and a row is found
        in the list by identity.
        """
        return next((row for row in self._list.each_stored_row()
                     if row.bookmark == bookmark), None)

    def _bookmark_added(self,
                        bookmark: "bookmark_menu_item._Bookmark") -> None:
        """List a bookmark added while the dialog is open."""
        if self._row_for(bookmark) is None:
            self._add_bookmark(bookmark)
        self._store_changed()

    def _bookmark_removed(self,
                          bookmark: "bookmark_menu_item._Bookmark") -> None:
        """Drop a bookmark removed while the dialog is open."""
        row = self._row_for(bookmark)
        if row is not None:
            self._list.remove_row(row)
        self._store_changed()

    def _bookmarks_cleared(self) -> None:
        """Empty the list, the store having been emptied."""
        self._list.clear()
        self._store_changed()

    def _store_changed(self) -> None:
        """Follow the store's contents with the buttons that act on it."""
        self._clear_button.set_sensitive(
            not self._bookmarks_store.is_empty())
        self._selection_changed()

    def _selection_changed(self, *args: object) -> None:
        """Only a bookmark that is selected can be removed.

        A Gtk.SingleSelection starts with nothing selected here, so the
        button starts insensitive rather than being one that does
        nothing when it is pressed - which is what the "open with"
        editor's own Remove does.
        """
        self.set_response_sensitive(constants.RESPONSE_REMOVE,
                                    self._list.get_selected_row() is not None)

    def _remove_selected(self) -> None:
        """Remove the selected bookmark from the dialog and the store.

        Whatever takes its place is selected next, or the row above it
        if it was the last, so that Delete works down a run of
        bookmarks: a Gtk.SingleSelection leaves nothing selected when
        what was selected goes, where a Gtk.TreeView moved the
        selection on.
        """

        row = self._list.get_selected_row()

        if row is not None:
            position = self._list.get_selected_positions()[0]
            self._bookmarks_store.remove_bookmark(row.bookmark)
            left = self._list.store.get_n_items()
            if left:
                self._list.select_only(min(position, left - 1))

    def _clear_all(self) -> None:
        """Remove every bookmark, once the reader has confirmed it."""
        self._bookmarks_store.show_clear_bookmarks_dialog(self._clear_answered)

    def _clear_answered(self, response: int) -> None:
        if response != Response.YES:
            return
        # The rows go with it, through _bookmarks_cleared().
        self._bookmarks_store.clear_bookmarks()

    def _bookmark_activated(self, view: Gtk.ListView, position: int,
                            *args: object) -> None:
        """ Open the activated bookmark. """

        row = self._list.get_row(position)
        if row is None:
            return

        self._close()
        row.bookmark.load()

    def _response(self, dialog: Dialog, response: int) -> None:

        if response == constants.RESPONSE_REMOVE:
            self._remove_selected()

        elif response == constants.RESPONSE_CLEAR:
            self._clear_all()

        else:
            # Close, escape and the window's close button all mean the
            # same thing here, and now do the same thing: escape threw
            # away a reordering that either of the others kept.
            self._close()

    def _key_press_event(self, controller: Gtk.EventControllerKey,
                         keyval: int, keycode: int,
                         state: Gdk.ModifierType) -> bool:

        if keyval == Gdk.KEY_Delete:
            self._remove_selected()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _close(self, *args: object) -> None:
        """Close the dialog, leaving the store in the order it holds.

        The order the list holds, not the one it is drawing: a heading
        that is sorting draws an order of its own, and writing that
        back made looking at the bookmarks by date reorder them for
        good.  It is the held order a reordering drag moves a row in,
        which is why the drag is refused while a heading sorts.  The
        list shows the newest bookmark first and the store keeps it
        last, so the one is the other reversed.
        """
        self._bookmarks_store.add_bookmark -= self._bookmark_added
        self._bookmarks_store.remove_bookmark -= self._bookmark_removed
        self._bookmarks_store.clear_bookmarks -= self._bookmarks_cleared

        ordering = [row.bookmark for row in self._list.each_stored_row()]
        ordering.reverse()
        self._bookmarks_store.set_bookmark_order(ordering)
        self.destroy()


# vim: expandtab:sw=4:ts=4
