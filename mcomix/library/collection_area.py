"""collection_area.py - The tree of collections in the library window.

The collections of the library as a tree under a bold "All books" row,
with the popup menu that adds, renames, duplicates, cleans and removes
one.  Selecting a row is what tells the book area which collection to
show.  It is also a drop target twice over: for books dragged from the
book area, and for another collection dragged onto the one it is to sit
under.
"""

import weakref
from xml.sax.saxutils import escape as xmlescape
from gi.repository import Gdk, Gio, GLib, Gtk
from typing import TYPE_CHECKING

from mcomix.preferences import prefs
from mcomix import column_list
from mcomix import widgets
from mcomix import constants
from mcomix import i18n
from mcomix import file_chooser_library_dialog
from mcomix import message_dialog
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Iterator
if TYPE_CHECKING:
    from mcomix.library.main_dialog import _LibraryDialog

#: What a drop handler answers with when it will not take the drop.
_NO_DRAG_ACTION = Gdk.DragAction(0)

#: How wide the sidebar asks to be, in characters of whatever font the
#: desktop is drawn in.  The lower bound is about what "All books" and
#: "Recent" need; the upper one keeps one long collection name from
#: taking the room the books are drawn in, the library window being 500
#: pixels wide by default and the control area under it wanting 350.
_SIDEBAR_MIN_CHARS = 14
_SIDEBAR_MAX_CHARS = 28


class _CollectionArea(Gtk.ScrolledWindow, widgets.Releasable):

    """The _CollectionArea is the sidebar area in the library where
    different collections are displayed in a tree.
    """

    def __init__(self, library: "_LibraryDialog") -> None:
        super().__init__()
        self._library_ref = weakref.ref(library)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # A Gtk.ScrolledWindow asks for its child's *minimum* width, and
        # an ellipsized label is willing to shrink to a single character:
        # the sidebar came out 39 pixels wide, drawing every collection
        # as "...".  A Gtk.TreeView asked for the width its columns
        # wanted, so ask for the natural width here too; the column below
        # is what bounds it, since min-content-width and
        # max-content-width are both ignored while nothing may scroll
        # sideways.
        self.set_propagate_natural_width(True)

        # A row carries the name as it is drawn and the collection id
        # behind it; the collections under a collection are its own
        # children, which is what a Gtk.TreeStore held.
        self._list = column_list.ColumnListView(tree=True)
        self._list.add_text_column('', 'name', expand=True, markup=True,
                                   width_chars=_SIDEBAR_MIN_CHARS,
                                   max_width_chars=_SIDEBAR_MAX_CHARS)
        self._list.set_show_column_separators(False)
        self._list.selection.connect('selection-changed',
                                     self._collection_selected)
        clicks = Gtk.GestureClick()
        clicks.set_button(3)
        clicks.connect('pressed', self._button_press)
        self._list.add_controller(clicks)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press)
        self._list.add_controller(keys)
        self._list.connect('activate', self._expand_or_collapse_row)
        self._list.set_headers_visible(False)
        # Books and collections are both dragged as text saying which
        # they are: GTK4 has no target names to tell them apart by, and a
        # drop target answers for one type.  Preloading is what makes the
        # dragged text readable while it is still only being hovered,
        # which is when the drop has to be accepted or refused.
        self._drop_target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        self._drop_target.set_preload(True)
        self._drop_target.connect('motion', self._drag_motion)
        self._drop_target.connect('drop', self._drag_data_received)
        self._list.add_controller(self._drop_target)

        drag = Gtk.DragSource()
        drag.set_actions(Gdk.DragAction.MOVE)
        drag.connect('prepare', self._drag_prepare)
        drag.connect('drag-begin', self._drag_begin)
        self._list.add_controller(drag)

        self.set_child(self._list)

        self._popup_actions = Gio.SimpleActionGroup()
        self._collection_menu = self._create_popup_menu()

        self.display_collections()

    def release(self) -> None:
        """Take the collection popup actions out, once the window is closed.

        GTK holds an inserted action group, and each action holds a
        handler that is a method of this area: a cycle through C that
        Python's collector cannot see, which kept the area - and its
        tree - alive after the window had gone.
        """
        self.insert_action_group('collections', None)
        # And the list: it holds a method of this area in turn, which
        # makes another such cycle for as long as the area is its parent.
        self.set_child(None)
        widgets.empty_action_group(self._popup_actions)

    @property
    def _library(self) -> "_LibraryDialog":
        """The library window this area is part of.

        Held weakly: GTK holds the area for as long as the window's
        widgets stand, which is for good once the window is closed,
        and a plain reference would keep the window alive with it.
        """
        library = self._library_ref()
        assert library is not None, 'the library window is gone'
        return library

    def _create_popup_menu(self) -> Gtk.PopoverMenu:
        """Build the right-click menu for the collection list."""
        entries = (
            ('add', _('_Add...'),
             _('Add more books to the library.'),
             lambda *args: file_chooser_library_dialog.open_library_filechooser_dialog(
                 self._library)),
            ('new', _('New'),
             _('Add a new empty collection.'), self.add_collection),
            ('rename', _('Re_name'),
             _('Renames the selected collection.'), self._rename_collection),
            ('duplicate', _('_Duplicate'),
             _('Creates a duplicate of the selected collection.'),
             self._duplicate_collection),
            ('cleanup', _('_Clean up'),
             _('Removes no longer existent books from the collection.'),
             self._clean_collection),
            ('remove', _('_Remove'),
             _('Deletes the selected collection.'), self._remove_collection),
        )
        for name, label, tooltip, handler in entries:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', handler)
            self._popup_actions.add_action(action)

        # The heading is an item bound to an action that is never enabled,
        # which is what it was before.  A labelled Gio.Menu section would
        # say the same thing, but Gtk.Menu draws such a section as a bare
        # separator and throws the label away.
        title = Gio.SimpleAction.new('title', None)
        title.set_enabled(False)
        self._popup_actions.add_action(title)
        self.insert_action_group('collections', self._popup_actions)

        model = Gio.Menu()
        heading = Gio.Menu()
        heading.append(_('Library collections'), 'collections.title')
        model.append_section(None, heading)
        adding = Gio.Menu()
        adding.append(entries[0][1], 'collections.add')
        model.append_section(None, adding)
        creating = Gio.Menu()
        for entry in entries[1:4]:
            creating.append(entry[1], 'collections.%s' % entry[0])
        model.append_section(None, creating)
        removing = Gio.Menu()
        for entry in entries[4:]:
            removing.append(entry[1], 'collections.%s' % entry[0])
        model.append_section(None, removing)

        menu = Gtk.PopoverMenu.new_from_model(model)
        return menu

    def _collection_name(self, collection: int | None) -> str:
        """The name of <collection>, or nothing if it has gone.

        The backend answers with None for a collection that no longer
        exists, which the labels and status messages here have nothing
        to say about.
        """
        return self._library.backend.get_collection_name(collection) or ''

    def get_current_collection(self) -> int | None:
        """Return the collection ID for the currently selected collection,
        or None if no collection is selected.
        """
        row = self._list.get_selected_row()
        return row.collection if row is not None else None

    def display_collections(self) -> None:
        """Display the library collections by redrawing them from the
        backend data. Should be called on startup or when the collections
        hierarchy has been changed (e.g. after moving, adding, renaming).
        Any row that was expanded before the call will have it's
        corresponding new row also expanded after the call.
        """

        # The whole hierarchy in one statement: the tree is walked here
        # rather than by a query for the collections under every row and
        # another for each of their names.
        tree = self._library.backend.get_collection_tree()

        def _rows_under(supercoll: int | None) -> list[column_list.Row]:
            return [column_list.Row(name=xmlescape(name), collection=coll,
                                    children=_rows_under(coll))
                    for coll, name in tree.get(supercoll, ())]

        expanded_collections = [row.collection
                                for row in self._list.expanded_rows()]
        rows = [column_list.Row(
            name='<b>%s</b>' % xmlescape(_('All books')),
            collection=constants.COLLECTION_ALL, children=[])]
        rows.extend(_rows_under(None))
        self._list.set_rows(rows)

        def _each_row(rows: list[column_list.Row]) -> Iterator[column_list.Row]:
            for row in rows:
                yield row
                yield from _each_row(row.children)

        for row in list(_each_row(rows)):
            if row.collection == prefs['last library collection']:
                # Reset to trigger update of book area.
                prefs['last library collection'] = None
                self._list.expand_to(row)
                self._list.select_row(row)
            elif row.collection in expanded_collections:
                self._list.expand_to(row)
                self._list.toggle_expanded(row)

    def add_collection(self, *args: object) -> None:
        """Add a new collection to the library, through a dialog."""
        add_dialog = message_dialog.MessageDialog(
            self._library, buttons=Gtk.ButtonsType.OK_CANCEL)
        add_dialog.set_default_response(Response.OK)
        add_dialog.set_text(
            _('Add new collection?'),
            _('Please enter a name for the new collection.')
        )

        # To get nice line-ups with the padding.
        box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.pack(add_dialog.get_content_area(), box, True, True, 0)

        entry = Gtk.Entry()
        entry.set_activates_default(True)
        widgets.pack(box, entry, True, True, 6)
        box.set_visible(True)

        # The entry outlives the dialog, which run_async() takes down
        # before it answers.
        add_dialog.run_async(
            lambda response: self._add_answered(response, entry.get_text()))

    def _add_answered(self, response: int, name: str) -> None:
        """Create the collection the add dialog asked about.

        Spaces around the name are not part of it: typed by accident,
        they made a second "Shelf" beside the first, and spaces alone a
        collection whose name showed as nothing.
        """
        name = name.strip()
        if response == Response.OK and name:
            collection = self._library.backend.add_collection(name)
            if collection is not None:
                prefs['last library collection'] = collection
                self._library.collection_area.display_collections()
            else:
                message = _("Could not add a new collection called '%s'.") % (
                    name)
                if (self._library.backend.get_collection_by_name(name)
                        is not None):
                    message = '%s %s' % (message,
                                         _('A collection by that name already exists.'))
                self._library.set_status_message(message)

    def clean_collection(self, collection: int | None) -> None:
        """ Removes from the library every book in <collection> whose
        file has gone away, or every such book there is when
        <collection> is None, says in the status bar how many went and
        redraws the covers of the collection on show. """

        removed = self._library.backend.clean_collection(collection)

        msg = i18n.get_translation().ngettext(
            'Removed %d book from the library.',
            'Removed %d books from the library.',
            removed)
        self._library.set_status_message(msg % removed)

        if removed > 0:
            collection = self._library.collection_area.get_current_collection()
            GLib.idle_add(self._library.book_area.display_covers, collection)

    def _collection_selected(self, *args: object) -> None:
        """Change the viewed collection (in the _BookArea) to the
        currently selected one in the sidebar, if it has been changed.
        """
        collection = self.get_current_collection()
        if (collection is None or
                collection == prefs['last library collection']):
            return
        prefs['last library collection'] = collection
        GLib.idle_add(self._library.book_area.display_covers, collection)

    def _clean_collection(self, *args: object) -> None:
        """ Menu item hook to clean a collection. """

        collection = self.get_current_collection()

        # The backend expects constants.COLLECTION_ALL to be passed as None
        if collection == constants.COLLECTION_ALL:
            collection = None

        self.clean_collection(collection)

    def _remove_collection(self, *args: object) -> None:
        """Remove the currently selected collection from the library."""
        collection = self.get_current_collection()

        if collection is not None \
                and collection not in (constants.COLLECTION_ALL, constants.COLLECTION_RECENT):
            self._library.backend.remove_collection(collection)
            prefs['last library collection'] = constants.COLLECTION_ALL
            self.display_collections()

    def _rename_collection(self, *args: object) -> None:
        """Rename the currently selected collection, using a dialog."""
        collection = self.get_current_collection()
        if collection is None:
            return
        old_name = self._collection_name(collection)
        rename_dialog = message_dialog.MessageDialog(
            self._library, buttons=Gtk.ButtonsType.OK_CANCEL)
        rename_dialog.set_text(
            _('Rename collection?'),
            _('Please enter a new name for the selected collection.')
        )
        rename_dialog.set_default_response(Response.OK)

        # To get nice line-ups with the padding.
        box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.pack(rename_dialog.get_content_area(), box, True, True, 0)

        entry = Gtk.Entry()
        entry.set_text(old_name)
        entry.set_activates_default(True)
        widgets.pack(box, entry, True, True, 6)
        box.set_visible(True)

        # As in add_collection() above: the entry outlives the dialog.
        rename_dialog.run_async(lambda response: self._rename_answered(
            response, collection, entry.get_text()))

    def _rename_answered(self, response: int, collection: int,
                         new_name: str) -> None:
        """Rename the collection the rename dialog asked about, less any
        spaces around the new name, as add_collection() takes them."""
        new_name = new_name.strip()
        if response == Response.OK and new_name:
            if self._library.backend.rename_collection(collection, new_name):
                self.display_collections()
            else:
                message = _("Could not change the name to '%s'.") % new_name
                if (self._library.backend.get_collection_by_name(new_name)
                        is not None):
                    message = '%s %s' % (message,
                                         _('A collection by that name already exists.'))
                self._library.set_status_message(message)

    def _duplicate_collection(self, *args: object) -> None:
        """Duplicate the currently selected collection."""
        collection = self.get_current_collection()
        if collection is None:
            return
        if self._library.backend.duplicate_collection(collection):
            self.display_collections()
        else:
            self._library.set_status_message(
                _('Could not duplicate collection.'))

    def _button_press(self, gesture: Gtk.GestureClick, n_press: int,
                      x: float, y: float) -> None:
        """Handle mouse button presses on the _CollectionArea."""

        row = self._list.row_at(x, y)
        self._popup_collection_menu(row.collection if row is not None
                                    else None,
                                    gesture.get_widget() or self._list, x, y)

    def _popup_menu(self) -> None:
        """ Called to open the control's popup menu via
        keyboard controls. """

        self._popup_collection_menu(self.get_current_collection())

    def _popup_collection_menu(self, collection: int | None,
                               over: "Gtk.Widget | None" = None,
                               x: float = 0, y: float = 0) -> None:
        """ Shows the collection popup over <collection>, with the
        items that suit it enabled.  Renaming, duplicating and removing
        want a collection of the user's own, so they are off over the
        built-in "All books" and "Recent" rows, and over no collection
        at all - which is what a right click on empty space gives, and
        the only thing adding books and cleaning up are off over.
        Creating a collection is always offered. """

        is_collection_all = collection in (constants.COLLECTION_ALL, constants.COLLECTION_RECENT)

        for name in ('rename', 'duplicate', 'remove'):
            widgets.simple_action(self._popup_actions, name).set_enabled(
                collection is not None and not is_collection_all)

        for name in ('add', 'cleanup'):
            widgets.simple_action(self._popup_actions, name).set_enabled(
                collection is not None)

        # Where the click was, or the corner of the sidebar for the menu
        # key, which has no position.
        widgets.popup_at(self._collection_menu, over or self, x, y)

    def _key_press(self, controller: Gtk.EventControllerKey,
                   keyval: int, keycode: int,
                   state: Gdk.ModifierType) -> bool:
        """Handle key presses on the _CollectionArea."""
        if keyval == Gdk.KEY_Delete:
            self._remove_collection()
            return Gdk.EVENT_STOP
        # A GTK4 widget has no popup-menu signal, so the keys that
        # asked for a menu through it are heard here.
        if widgets.menu_key(keyval, state):
            self._popup_menu()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _expand_or_collapse_row(self, view: column_list.ColumnListView,
                                position: int) -> None:
        """Expand or collapse the activated row."""
        row = self._list.get_row(position)
        if row is not None:
            self._list.toggle_expanded(row)

    def _drag_data_received(self, target: Gtk.DropTarget, value: str,
                            x: float, y: float) -> bool:
        """Move books dragged from the _BookArea to the target collection,
        or move some collection into another collection.
        """
        kind, _separator, payload = value.partition(':')
        self._library.set_status_message('')
        drop = self._drop_row_at(x, y)
        if drop is None:
            return False
        dest_row, pos = drop
        src_collection = self.get_current_collection()
        dest_collection = dest_row.collection
        if kind == constants.LIBRARY_DRAG_COLLECTION:
            if src_collection is None:
                # The payload only exists for a collection that is
                # selected, which is the one being dragged.
                return False
            if pos != self._list.DROP_INTO:
                dest_collection = self._library.backend.get_supercollection(
                    dest_collection)
            self._library.backend.add_collection_to_collection(
                src_collection, dest_collection)
            self.display_collections()
        elif kind == constants.LIBRARY_DRAG_BOOKS:
            # The positions are read before any book is removed: taking
            # one out moves every cover after it, so removing them one
            # at a time by position took the wrong books.
            positions = [int(position) for position in payload.split(',')]
            books = [self._library.book_area.get_book_at_path(position)
                     for position in positions]
            # Books dragged out of "All books" are filed rather than
            # moved, and so are books dragged with no collection shown.
            move_from = (src_collection if src_collection is not None
                         and src_collection != constants.COLLECTION_ALL else None)
            for book in books:
                if book is None:
                    continue
                self._library.backend.add_book_to_collection(book,
                                                             dest_collection)
                if move_from is not None:
                    self._library.backend.remove_book_from_collection(
                        book, move_from)
            if move_from is not None:
                self._library.book_area.remove_books(
                    [book for book in books if book is not None])
        else:
            return False
        return True

    def _drop_row_at(self, x: float, y: float) -> "tuple[column_list.Row, int] | None":
        """The row a drop at (<x>, <y>) lands on, and where on it, or
        None where the list has no rows at all.

        The list itself answers for a point that is on a row.  A point
        below every row is the empty space under the tree, which counts
        as after the last row, so that a collection dragged there is put
        at the root rather than nowhere.
        """
        drop = self._list.drop_at(x, y)
        if drop is not None:
            return drop
        rows = list(self._list.each_row())
        if not rows:
            return None
        return rows[-1], self._list.DROP_AFTER

    def _drag_prepare(self, source: Gtk.DragSource, x: float,
                      y: float) -> "Gdk.ContentProvider | None":
        """Offer the collection being dragged."""
        collection = self.get_current_collection()
        if collection is None:
            return None
        return Gdk.ContentProvider.new_for_value(
            '%s:%d' % (constants.LIBRARY_DRAG_COLLECTION, collection))

    def _drag_motion(self, target: Gtk.DropTarget, x: float,
                     y: float) -> Gdk.DragAction:
        """What dropping what is being dragged at (<x>, <y>) would do.

        Books dragged from the book area and a collection dragged from
        here are both hovered over this list, and each has its own rules
        about where it may land: a collection goes into another one or
        beside it, books only into one.  Where the drop would do
        something, the library's status bar is told what, and the answer
        is the action GTK is to show the cursor for; where it would not,
        the message is cleared and the answer is no action at all.
        """
        value = target.get_value()
        if not isinstance(value, str):
            # Not read yet, or not ours at all.
            return _NO_DRAG_ACTION
        kind, _separator, _payload = value.partition(':')
        drop = self._drop_row_at(x, y)
        src_collection = self.get_current_collection()
        if kind == constants.LIBRARY_DRAG_COLLECTION:  # Moving collection.
            if drop is None:
                return self._refuse_drop()
            dest_row, pos = drop
            src_row = self._list.get_selected_row()
            if src_row is not None and self._list.is_above(src_row, dest_row):
                # No cycles!
                return self._refuse_drop()
            dest_collection = dest_row.collection
            if pos != self._list.DROP_INTO:
                dest_collection = self._library.backend.get_supercollection(
                    dest_collection)
            if (constants.COLLECTION_ALL in (src_collection, dest_collection) or
                    constants.COLLECTION_RECENT in (src_collection, dest_collection) or
                    src_collection == dest_collection):
                return self._refuse_drop()
            src_name = self._collection_name(src_collection)
            if dest_collection is None:
                dest_name = _('Root')
            else:
                dest_name = self._collection_name(dest_collection)
            message = (_("Put the collection '%(subcollection)s' in the collection '%(supercollection)s'.") %
                       {'subcollection': src_name, 'supercollection': dest_name})
        else:  # Moving book(s).
            if drop is None or drop[1] != self._list.DROP_INTO:
                # Books go in a collection, not between two of them.
                return self._refuse_drop()
            dest_row, pos = drop
            dest_collection = dest_row.collection
            if src_collection == dest_collection or dest_collection == constants.COLLECTION_ALL:
                return self._refuse_drop()
            dest_name = self._collection_name(dest_collection)
            if src_collection == constants.COLLECTION_ALL:
                message = _("Add books to '%s'.") % dest_name
            else:
                src_name = self._collection_name(src_collection)
                message = (_("Move books from '%(source collection)s' to '%(destination collection)s'.") %
                           {'source collection': src_name,
                            'destination collection': dest_name})
        self._library.set_status_message(message)
        return Gdk.DragAction.MOVE

    def _refuse_drop(self) -> Gdk.DragAction:
        """Take no drop where the pointer is, and clear the status
        message an acceptable position further back had set."""
        self._library.set_status_message('')
        return _NO_DRAG_ACTION

    def _drag_begin(self, source: Gtk.DragSource, drag: Gdk.Drag) -> None:
        """Drag the selected collection under a picture of its own row.

        The hotspot is put a little above and to the left of the
        picture rather than inside it, so that the row the pointer is
        over stays visible while the drag is in the air; it is the row
        under the pointer, not the picture, that says where the drop
        would land.
        """
        row = self._list.get_selected_row()
        if row is None:
            return
        paintable = self._list.row_paintable(row)
        if paintable is not None:
            source.set_icon(paintable, -5, -5)

# vim: expandtab:sw=4:ts=4
