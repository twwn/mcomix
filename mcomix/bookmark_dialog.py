"""bookmark_dialog.py - Bookmarks dialog handler."""

from gi.repository import Gdk, Gtk

from mcomix.dialog import Dialog
from mcomix import column_list
from mcomix import widgets
from mcomix import constants
from mcomix.i18n import _

from typing import Any

class _BookmarksDialog(Dialog):

    """_BookmarksDialog lets the user remove or rearrange bookmarks."""

    def __init__(self, window, bookmarks_store):
        super(_BookmarksDialog, self).__init__(
            title=_('Edit Bookmarks'), transient_for=window,
            destroy_with_parent=True)
        self.add_buttons(_('_Remove'), constants.RESPONSE_REMOVE,
                         _('_Close'), Gtk.ResponseType.CLOSE)

        self._bookmarks_store = bookmarks_store

        self.set_resizable(True)
        self.set_default_response(Gtk.ResponseType.CLOSE)
        # scroll area fill to the edge (TODO window should not really be a dialog)
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

        # FIXME Hide extra columns. Needs UI controls to enable these.
        self._path_col.set_visible(False)

        self.set_default_size(600, 450)

        self.connect('response', self._response)
        self.connect('close-request', self._close)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press_event)
        self._list.add_controller(keys)
        self._list.connect('activate', self._bookmark_activated)

        for bookmark in self._bookmarks_store.get_bookmarks():
            self._add_bookmark(bookmark)

        self.set_visible(True)

    @staticmethod
    def _sort_key(*fields: str) -> "Any":
        """Order the rows by <fields> of the bookmark, in turn.

        The fields go into a tuple rather than being compared one at a
        time as they were, which needs them all to be orderable against
        their own kind: _archive_type is None for a loose image and a
        number for an archive, and comparing the two raised a TypeError
        the moment the Type heading was clicked on a mixed list.  A None
        sorts before every number here.
        """
        def key(row: column_list.Row) -> tuple:
            values = []
            for field in fields:
                value = getattr(row.bookmark, field)
                values.append((value is not None, value))
            return tuple(values)
        return key

    def _add_bookmark(self, bookmark):
        """Add the <bookmark> to the dialog, newest first."""
        self._list.insert_row(0, bookmark.to_row())

    def _remove_selected(self) -> None:
        """Remove the currently selected bookmark from the dialog and from
        the store."""

        row = self._list.get_selected_row()

        if row is not None:
            self._list.remove_row(row)
            self._bookmarks_store.remove_bookmark(row.bookmark)

    def _bookmark_activated(self, view, position, *args):
        """ Open the activated bookmark. """

        row = self._list.get_row(position)
        if row is None:
            return

        self._close()
        row.bookmark.load()

    def _response(self, dialog, response):

        if response == Gtk.ResponseType.CLOSE:
            self._close()

        elif response == constants.RESPONSE_REMOVE:
            self._remove_selected()

        else:
            self.destroy()

    def _key_press_event(self, controller, keyval, keycode, state):

        if keyval == Gdk.KEY_Delete:
            self._remove_selected()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _close(self, *args):
        """Close the dialog and update the _BookmarksStore with the new
        ordering."""

        ordering: list = []

        for row in self._list.each_row():
            ordering.insert(0, row.bookmark)

        for bookmark in ordering:
            self._bookmarks_store.remove_bookmark(bookmark)
            self._bookmarks_store.add_bookmark(bookmark)

        self.destroy()


# vim: expandtab:sw=4:ts=4
