"""library_book_area.py - The window of the library that displays the covers of books."""

import os
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk
import PIL.Image as Image
import PIL.ImageDraw as ImageDraw

from mcomix.preferences import prefs
from mcomix import thumbnail_view
from mcomix import file_chooser_library_dialog
from mcomix import image_tools
from mcomix import constants
from mcomix import preview
from mcomix import icons
from mcomix import widgets
from mcomix import i18n
from mcomix import log
from mcomix import message_dialog
from mcomix import tools
from mcomix.library.pixbuf_cache import get_pixbuf_cache
from mcomix.i18n import _

from typing import Any

_dialog = None

# The "All books" collection is not a real collection stored in the library, but is represented by this ID in the
# library's TreeModels.
_COLLECTION_ALL = -1


class _BookArea(Gtk.ScrolledWindow):

    """The _BookArea is the central area in the library where the book
    covers are displayed.
    """

    # Thumbnail border width in pixels.
    _BORDER_SIZE = 1

    #: The class the covers' black background is written against.
    _BLACK_CSS_CLASS = 'mcomix-library-covers'

    def __init__(self, library):
        super(_BookArea, self).__init__()

        self._library = library
        self._cache = get_pixbuf_cache()

        self._library.backend.book_added_to_collection += self._new_book_added

        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # Store Cover, book ID, book path, book size, date added to library,
        # is thumbnail loaded?

        # The SORT_ constants must correspond to the correct column here,
        # i.e. SORT_SIZE must be 3, since 3 is the size column in the ListStore.
        self._liststore = Gtk.ListStore(GdkPixbuf.Pixbuf,
                GObject.TYPE_INT, GObject.TYPE_STRING, GObject.TYPE_INT64,
                GObject.TYPE_STRING, GObject.TYPE_BOOLEAN)
        self._liststore.set_sort_func(constants.SORT_NAME, self._sort_by_name, None)
        self._liststore.set_sort_func(constants.SORT_PATH, self._sort_by_path, None)
        self.set_sort_order()
        self._liststore.connect('row-inserted', self._icon_added)
        self._iconview = thumbnail_view.ThumbnailIconView(
            self._liststore,
            1, # UID
            0, # pixbuf
            5, # status
        )
        self._iconview.generate_thumbnail = self._get_pixbuf
        self._iconview.connect('item_activated', self._book_activated)
        self._iconview.connect('selection_changed', self._selection_changed)
        clicks = Gtk.GestureClick()
        clicks.set_button(3)
        clicks.connect('pressed', self._button_press)
        self._iconview.add_controller(clicks)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press)
        self._iconview.add_controller(keys)
        # Covers are shown on black, whatever base colour the theme has.
        # A style provider belongs to a display rather than to a widget,
        # so the view carries a class for the rule to single it out.
        self._iconview.add_css_class(self._BLACK_CSS_CLASS)
        self._black_background = Gtk.CssProvider()
        self._black_background.load_from_string(
            '.%s { background-color: black; }' % self._BLACK_CSS_CLASS)
        Gtk.StyleContext.add_provider_for_display(
            self._iconview.get_display(), self._black_background,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # Books drag out to the collection area, and files drop in from
        # a file manager.  GTK4 has neither a model drag source nor a
        # model drag destination; controllers do both, and a drop target
        # answers for one type - so the files come to one of their own.
        drag = Gtk.DragSource()
        drag.set_actions(Gdk.DragAction.MOVE)
        drag.connect('prepare', self._drag_prepare)
        drag.connect('drag-begin', self._drag_begin)
        self._iconview.add_controller(drag)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect('drop', self._drag_data_received)
        self._iconview.add_controller(drop)
        self._iconview.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.set_child(self._iconview)

        self._iconview.set_margin(0)
        self._iconview.set_row_spacing(0)
        self._iconview.set_column_spacing(0)

        self._popup_actions = Gio.SimpleActionGroup()
        self._book_menu = self._create_popup_menu()

    #: The popup's plain entries: action name, label, tooltip, handler.
    def _menu_entries(self) -> tuple:
        return (
            ('open', _('_Open'),
             _('Opens the selected books for viewing.'),
             self.open_selected_book),
            ('open-keep-library', _('Open _without closing library'),
             _('Opens the selected books, but keeps the library window open.'),
             self.open_selected_book_noclose),
            ('add', _('_Add...'),
             _('Add more books to the library.'),
             lambda *args: file_chooser_library_dialog.open_library_filechooser_dialog(
                 self._library)),
            ('remove-from-collection', _('Remove from this _collection'),
             _('Removes the selected books from the current collection.'),
             self._remove_books_from_collection),
            ('remove-from-library', _('Remove from the _library'),
             _('Completely removes the selected books from the library.'),
             self._remove_books_from_library),
            ('completely-remove', _('_Remove and delete from disk'),
             _('Deletes the selected books from disk.'),
             self._completely_remove_book),
            ('copy-to-clipboard', _('_Copy'),
             _("Copies the selected book's path to clipboard."),
             self._copy_selected),
        )

    def _create_popup_menu(self) -> Any:
        """Build the right-click menu for the book list."""
        for name, label, tooltip, handler in self._menu_entries():
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', handler)
            self._popup_actions.add_action(action)

        # An item bound to an action that is never enabled, which is what
        # the heading was before.
        title = Gio.SimpleAction.new('title', None)
        title.set_enabled(False)
        self._popup_actions.add_action(title)

        # The three radio groups become one stateful action each, holding
        # the value the group used to carry on its members.
        for name, state, handler in (
                ('sort-key', prefs['lib sort key'], self._sort_key_changed),
                ('sort-order', prefs['lib sort order'], self._sort_order_changed),
                ('cover-size', self._current_cover_size(), self._book_size_changed)):
            action = Gio.SimpleAction.new_stateful(
                name, GLib.VariantType.new('i'), GLib.Variant('i', state))
            action.connect('change-state', handler)
            self._popup_actions.add_action(action)
        self.insert_action_group('books', self._popup_actions)

        def radio(menu: Any, entries: tuple, action_name: str) -> None:
            for label, value in entries:
                item = Gio.MenuItem.new(label, None)
                item.set_action_and_target_value('books.' + action_name,
                                                 GLib.Variant('i', value))
                menu.append_item(item)

        model = Gio.Menu()
        heading = Gio.Menu()
        heading.append(_('Library books'), 'books.title')
        model.append_section(None, heading)

        entries = self._menu_entries()
        for group in (entries[0:2], entries[2:3], entries[3:6], entries[6:7]):
            section = Gio.Menu()
            for name, label, tooltip, handler in group:
                section.append(label, 'books.' + name)
            model.append_section(None, section)

        sort_menu = Gio.Menu()
        by = Gio.Menu()
        radio(by, ((_('Book name'), constants.SORT_NAME),
                   (_('Full path'), constants.SORT_PATH),
                   (_('File size'), constants.SORT_SIZE),
                   (_('Date added'), constants.SORT_LAST_MODIFIED)), 'sort-key')
        sort_menu.append_section(None, by)
        order = Gio.Menu()
        radio(order, ((_('Ascending'), constants.SORT_ASCENDING),
                      (_('Descending'), constants.SORT_DESCENDING)), 'sort-order')
        sort_menu.append_section(None, order)

        size_menu = Gio.Menu()
        sizes = Gio.Menu()
        radio(sizes, ((_('Huge') + '  (%dpx)' % constants.SIZE_HUGE, constants.SIZE_HUGE),
                      (_('Large') + '  (%dpx)' % constants.SIZE_LARGE, constants.SIZE_LARGE),
                      (_('Normal') + '  (%dpx)' % constants.SIZE_NORMAL, constants.SIZE_NORMAL),
                      (_('Small') + '  (%dpx)' % constants.SIZE_SMALL, constants.SIZE_SMALL),
                      (_('Tiny') + '  (%dpx)' % constants.SIZE_TINY, constants.SIZE_TINY)),
              'cover-size')
        size_menu.append_section(None, sizes)
        custom = Gio.Menu()
        radio(custom, ((_('Custom...'), 0),), 'cover-size')
        size_menu.append_section(None, custom)

        submenus = Gio.Menu()
        submenus.append_submenu(_('_Sort'), sort_menu)
        submenus.append_submenu(_('Cover si_ze'), size_menu)
        model.append_section(None, submenus)

        menu = Gtk.PopoverMenu.new_from_model(model)
        return menu

    @staticmethod
    def _current_cover_size() -> int:
        """The cover size as the menu states it: 0 stands for "custom"."""
        size = prefs['library cover size']
        return size if size in (constants.SIZE_HUGE, constants.SIZE_LARGE,
                                constants.SIZE_NORMAL, constants.SIZE_SMALL,
                                constants.SIZE_TINY) else 0

    def close(self) -> None:
        """Run clean-up tasks for the _BookArea prior to closing."""

        self.stop_update()

        # We must unselect all or we will trigger selection_changed events
        # when closing with multiple books selected.
        self._iconview.unselect_all()
        # We must (for some reason) explicitly clear the ListStore in
        # order to not leak memory.
        self._liststore.clear()

    def display_covers(self, collection_id):
        """Display the books in <collection_id> in the IconView."""

        adjustment = self.get_vadjustment()
        if adjustment:
            adjustment.set_value(0)

        self.stop_update()
        # Temporarily detach model to speed up updates
        self._iconview.set_model(None)
        self._liststore.clear()

        collection = self._library.backend.get_collection_by_id(collection_id)
        books = collection.get_books(self._library.filter_string)
        self.add_books(books)

        # Re-attach model here
        GLib.idle_add(self._iconview.set_model, self._liststore)

    def stop_update(self) -> None:
        """Signal that the updating of book covers should stop."""
        self._iconview.stop_update()

    def add_books(self, books):
        """ Adds new book covers to the icon view.
        @param books: List of L{_Book} instances. """
        filler = self._get_empty_thumbnail()

        for book in books:
            # Fill the liststore with a filler pixbuf.
            self._liststore.append([filler, book.id,
                                    book.path,
                                    book.size, book.added, False])

        self._iconview.draw_thumbnails_on_screen()

    def _new_book_added(self, book, collection):
        """ Callback function for L{LibraryBackend.book_added}. """
        if collection is None:
            collection = _COLLECTION_ALL

        if (collection == self._library.collection_area.get_current_collection() or
            self._library.collection_area.get_current_collection() == _COLLECTION_ALL):
            # Make sure not to show a book twice when COLLECTION_ALL is selected
            # and the book is added to another collection, triggering this event.
            if self.is_book_displayed(book):
                return

            # If the current view is filtered, only draw new books that match the filter
            if not (self._library.filter_string and
                    self._library.filter_string.lower() not in book.name.lower()):
                self.add_books([book])

    def is_book_displayed(self, book):
        """ Returns True when the current view contains the book passed.
        @param book: L{_Book} instance. """
        if not book:
            return False

        for row in self._liststore:
            if row[1] == book.id:
                return True

        return False

    def remove_book_at_path(self, path):
        """Remove the book at <path> from the ListStore (and thus from
        the _BookArea).
        """
        iterator = self._liststore.get_iter(path)
        filepath = self._liststore.get_value(iterator, 2)
        self._liststore.remove(iterator)
        self._cache.invalidate(filepath)

    def get_book_at_path(self, path):
        """Return the book ID corresponding to the IconView <path>."""
        iterator = self._liststore.get_iter(path)
        return self._liststore.get_value(iterator, 1)

    def get_book_path(self, book):
        """Return the <path> to the book from the ListStore.
        """
        return self._liststore.get_iter(book)

    def open_selected_book(self, *args):
        """Open the currently selected book."""
        selected = self._iconview.get_selected_items()
        if not selected:
            return
        self._book_activated(self._iconview, selected, False)

    def open_selected_book_noclose(self, *args):
        """Open the currently selected book, keeping the library open."""
        selected = self._iconview.get_selected_items()
        if not selected:
            return
        self._book_activated(self._iconview, selected, True)

    def set_sort_order(self) -> None:
        """ Orders the list store based on the key passed in C{sort_key}.
        Should be one of the C{SORT_} constants from L{constants}.
        """
        if prefs['lib sort order'] == constants.SORT_ASCENDING:
            sortorder = Gtk.SortType.ASCENDING
        else:
            sortorder = Gtk.SortType.DESCENDING

        self._liststore.set_sort_column_id(prefs['lib sort key'], sortorder)

    def _sort_key_changed(self, action: Any, value: Any) -> None:
        """ Called when the field the library sorts on changes. """
        action.set_state(value)
        prefs['lib sort key'] = value.get_int32()
        self.set_sort_order()

    def _sort_order_changed(self, action: Any, value: Any) -> None:
        """ Called when the direction the library sorts in changes. """
        action.set_state(value)
        prefs['lib sort order'] = value.get_int32()
        self.set_sort_order()

    def _sort_by_name(self, treemodel, iter1, iter2, user_data):
        """ Compares two books based on their file name without the
        path component. """
        path1 = self._liststore.get_value(iter1, 2)
        path2 = self._liststore.get_value(iter2, 2)

        # Catch None values from liststore
        if path1 is None:
            return 1
        elif path2 is None:
            return -1

        name1 = os.path.split(path1)[1].lower()
        name2 = os.path.split(path2)[1].lower()

        return tools.cmp(tools.AlphanumericSortKey(name1), tools.AlphanumericSortKey(name2))

    def _sort_by_path(self, treemodel, iter1, iter2, user_data):
        """ Compares two books based on their full path, in natural order. """
        path1 = self._liststore.get_value(iter1, 2)
        path2 = self._liststore.get_value(iter2, 2)
        return tools.cmp(tools.AlphanumericSortKey(path1), tools.AlphanumericSortKey(path2))

    def _icon_added(self, model, path, iter, *args):
        """ Justifies the alignment of all cell renderers when new data is
        added to the model. """
        width, height = self._pixbuf_size()
        preview.draw_cells_at(self._iconview, max(width, height))
        for cell in self._iconview.get_cells():
            cell.set_fixed_size(width, height)
            cell.set_alignment(0.5, 0.5)

    def load_covers(self) -> None:
        self._cache.invalidate_all()
        collection = self._library.collection_area.get_current_collection()
        GLib.idle_add(self.display_covers, collection)

    def _book_size_changed(self, action: Any, value: Any) -> None:
        """ Called when library cover size changes.

        The state carries the size in pixels, with 0 standing for the
        custom size the dialog below asks for. """
        action.set_state(value)
        old_size = prefs['library cover size']
        chosen = value.get_int32()
        if chosen:
            prefs['library cover size'] = chosen
        else:
            dialog = message_dialog.MessageDialog(self._library, Gtk.DialogFlags.DESTROY_WITH_PARENT,
                Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK)
            dialog.set_auto_destroy(False)
            dialog.set_text(_('Set library cover size'))

            # Add adjustment scale
            adjustment = Gtk.Adjustment.new(prefs['library cover size'], 20,
                    constants.MAX_LIBRARY_COVER_SIZE, 10, 25, 0)
            cover_size_scale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL,
                                             adjustment)
            cover_size_scale.set_size_request(200, -1)
            cover_size_scale.set_digits(0)
            cover_size_scale.set_draw_value(True)
            cover_size_scale.set_value_pos(Gtk.PositionType.LEFT)
            for mark in (constants.SIZE_HUGE, constants.SIZE_LARGE,
                    constants.SIZE_NORMAL, constants.SIZE_SMALL,
                    constants.SIZE_TINY):
                cover_size_scale.add_mark(mark, Gtk.PositionType.TOP, None)

            widgets.pack(dialog.get_message_area(), cover_size_scale, True, True, 0, end=True)

            def size_chosen(response: int) -> None:
                # The dialog was told not to destroy itself, so that the
                # scale can still be read once the answer is in.
                if response == Gtk.ResponseType.OK:
                    prefs['library cover size'] = int(adjustment.get_value())
                dialog.destroy()
                if prefs['library cover size'] != old_size:
                    self.load_covers()

            dialog.run_async(size_chosen)
            return

        if prefs['library cover size'] != old_size:
            self.load_covers()

    def _pixbuf_size(self, border_size=_BORDER_SIZE):
        # Don't forget the extra pixels for the border!
        # The ratio (0.67) is just above the normal aspect ratio for books.
        size = preview.scaled(prefs['library cover size'], self)
        return (int(0.67 * size) + 2 * border_size,
                size + 2 * border_size)

    def _get_pixbuf(self, uid):
        """ Get or create the thumbnail for the selected book <uid>. """
        assert isinstance(uid, int)
        book = self._library.backend.get_book_by_id(uid)
        # One lookup rather than exists() plus get(): another worker thread
        # may evict the entry in between, and get() would then return None.
        pixbuf = self._cache.get(book.path)
        if pixbuf is None:
            width, height = self._pixbuf_size(border_size=0)
            try:
                pixbuf = self._library.backend.get_book_thumbnail(book.path) or image_tools.missing_image_icon()
            except Exception:
                pixbuf = image_tools.missing_image_icon()
            pixbuf = image_tools.fit_in_rectangle(pixbuf, width, height, scale_up=True)
            self._cache.add(book.path, pixbuf)

        pixbuf = self._library._window.enhancer.enhance(pixbuf);
        pixbuf = image_tools.add_border(pixbuf, 1, 0xFFFFFFFF)

        # Display indicator of having finished reading the book.
        # This information isn't cached in the pixbuf cache, as it changes frequently.

        # Anything smaller than 50px means that the status icon will not fit
        if prefs['library cover size'] < 50:
            return pixbuf

        last_read_page = book.get_last_read_page()
        if last_read_page is None or last_read_page != book.pages:
            return pixbuf

        # Composite icon on the lower right corner of the book cover pixbuf.
        book_pixbuf = icons.load_pixbuf('object-select-symbolic', 24)
        translation_x = pixbuf.get_width() - book_pixbuf.get_width() - 1
        translation_y = pixbuf.get_height() - book_pixbuf.get_height() - 1
        book_pixbuf.composite(pixbuf, translation_x, translation_y,
                              book_pixbuf.get_width(), book_pixbuf.get_height(),
                              translation_x, translation_y,
                              1.0, 1.0, GdkPixbuf.InterpType.NEAREST, 0xFF)

        return pixbuf

    def _get_empty_thumbnail(self):
        """ Create an empty filler pixmap. """
        width, height = self._pixbuf_size()
        pixbuf = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                      has_alpha=True,
                                      bits_per_sample=8,
                                      width=width, height=height)

        # Make the pixbuf transparent.
        pixbuf.fill(0)

        return pixbuf

    def _book_activated(self, iconview, paths, keep_library_open=False):
        """Open the book at the (liststore) <path>."""
        if not isinstance(paths, list):
            paths = [ paths ]

        if not keep_library_open:
            # Necessary to prevent a deadlock at exit when trying to "join" the
            # worker thread.
            self.stop_update()
        books = [ self.get_book_at_path(path) for path in paths ]
        self._library.open_book(books, keep_library_open=keep_library_open)

    def _selection_changed(self, iconview):
        """Update the displayed info in the _ControlArea when a new book
        is selected.
        """
        selected = iconview.get_selected_items()
        self._library.control_area.update_info(selected)

    def _remove_books_from_collection(self, *args):
        """Remove the currently selected books from the current collection,
        and thus also from the _BookArea.
        """
        collection = self._library.collection_area.get_current_collection()
        if collection == _COLLECTION_ALL:
            return
        selected = self._iconview.get_selected_items()
        self._library.backend.begin_transaction()
        for path in selected:
            book = self.get_book_at_path(path)
            self._library.backend.remove_book_from_collection(book, collection)
            self.remove_book_at_path(path)
        self._library.backend.end_transaction()

        coll_name = self._library.backend.get_collection_name(collection)
        message = i18n.get_translation().ngettext(
                "Removed %(num)d book from '%(collection)s'.",
                "Removed %(num)d books from '%(collection)s'.",
                len(selected))
        self._library.set_status_message(
            message % {'num': len(selected), 'collection': coll_name})

    def _remove_books_from_library(self, *args):
        """Remove the currently selected books from the library, and thus
        also from the _BookArea.
        """

        selected = self._iconview.get_selected_items()
        self._library.backend.begin_transaction()

        for path in selected:
            book = self.get_book_at_path(path)
            self._library.backend.remove_book(book)
            self.remove_book_at_path(path)

        self._library.backend.end_transaction()

        msg = i18n.get_translation().ngettext(
            'Removed %d book from the library.',
            'Removed %d books from the library.',
            len(selected))
        self._library.set_status_message(msg % len(selected))

    def _completely_remove_book(self, request_response=True, *args):
        """Remove the currently selected books from the library and the
        hard drive.
        """

        if request_response:

            choice_dialog = message_dialog.MessageDialog(self._library, 0,
                Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO)
            choice_dialog.set_default_response(Gtk.ResponseType.YES)
            choice_dialog.set_should_remember_choice('library-remove-book-from-disk',
                (Gtk.ResponseType.YES,))
            choice_dialog.set_text(
                _('Remove books from the library?'),
                _('The selected books will be removed from the library and '
                  'permanently deleted. Are you sure that you want to continue?')
            )
            choice_dialog.run_async(self._remove_answered)
            return

        self._remove_answered(Gtk.ResponseType.YES)

    def _remove_answered(self, response: int) -> None:
        """Delete the selected books once the confirmation has come back."""
        # the user has told us they definitely want to delete the book
        if response == Gtk.ResponseType.YES:

            # get the array of currently selected books in the book window
            selected_books = self._iconview.get_selected_items()
            book_ids = [ self.get_book_at_path(book) for book in selected_books ]
            paths = [ self._library.backend.get_book_path(book_id) for book_id in book_ids ]

            # Remove books from library
            self._remove_books_from_library()

            # Remove from the harddisk
            for book_path in paths:
                try:
                    # try to delete the book.
                    # this can throw an exception if the path points to folder instead
                    # of a single file
                    os.remove(book_path)
                except Exception:
                    log.error(_('! Could not remove file "%s"'), book_path)

    def _copy_selected(self, *args):
        """ Copies the currently selected item to clipboard. """
        paths = self._iconview.get_selected_items()
        if len(paths) == 1:
            model = self._iconview.get_model()
            iter = model.get_iter(paths[0])
            path = model.get_value(iter, 2).decode('utf-8')
            pixbuf = model.get_value(iter, 0)

            self._library._window.clipboard.copy(path, pixbuf)

    def _button_press(self, gesture, n_press, x, y) -> None:
        """Handle mouse button presses on the _BookArea."""
        iconview = self._iconview
        path = iconview.get_path_at_pos(int(x), int(y))

        if path and not iconview.path_is_selected(path):
            iconview.unselect_all()
            iconview.select_path(path)

        self._popup_book_menu()

    def _popup_book_menu(self) -> None:
        """ Shows the book panel popup menu. """

        selected = self._iconview.get_selected_items()
        books_selected = len(selected) > 0
        collection = self._library.collection_area.get_current_collection()
        is_collection_all = collection == _COLLECTION_ALL

        for action in ('open', 'open-keep-library', 'remove-from-library',
                       'completely-remove'):
            self._set_sensitive(action, books_selected)

        self._set_sensitive('add', collection is not None)
        self._set_sensitive('remove-from-collection',
                            books_selected and not is_collection_all)
        self._set_sensitive('copy-to-clipboard', len(selected) == 1)

        widgets.popup_at(self._book_menu, self, 0, 0)

    def _set_sensitive(self, action, sensitive):
        """ Enables the popup menu action <action> based on <sensitive>. """

        self._popup_actions.lookup_action(action).set_enabled(sensitive)

    def _key_press(self, controller, keyval, keycode, state):
        """Handle key presses on the _BookArea."""
        if keyval == Gdk.KEY_Delete:
            self._remove_books_from_collection()
            return Gdk.EVENT_STOP
        # Gtk.Widget::popup-menu, which the menu key used to reach, is
        # not a signal in GTK4.
        if keyval == Gdk.KEY_Menu:
            self._popup_book_menu()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _drag_prepare(self, source, x, y):
        """Offer the books being dragged, as the paths of their icons."""
        paths = self._iconview.get_selected_items()
        if not paths:
            return None
        return Gdk.ContentProvider.new_for_value(
            '%s:%s' % (constants.LIBRARY_DRAG_BOOKS,
                       ','.join(path.to_string() for path in paths)))

    def _drag_begin(self, source, drag):
        """Create a cursor image for drag-n-drop from the library.

        This method relies on implementation details regarding PIL's
        drawing functions and default font to produce good looking results.
        If those are changed in a future release of PIL, this method might
        produce bad looking output (e.g. non-centered text).

        """
        iconview = self._iconview
        icon_path = iconview.get_cursor()[1]
        num_books = len(iconview.get_selected_items())
        book = self.get_book_at_path(icon_path)

        cover: GdkPixbuf.Pixbuf = self._library.backend.get_book_cover(book)
        if cover is None:
            cover = image_tools.missing_image_icon()

        cover = cover.scale_simple(max(0, cover.get_width() // 2),
            max(0, cover.get_height() // 2), prefs['scaling quality'])
        cover = image_tools.add_border(cover, 1, 0xFFFFFFFF)
        cover = image_tools.add_border(cover, 1)

        if num_books > 1:
            cover_width = cover.get_width()
            cover_height = cover.get_height()
            pointer = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                           has_alpha=True, bits_per_sample=8,
                                           width=max(30, cover_width + 15),
                                           height=max(30, cover_height + 10))
            pointer.fill(0x00000000)
            cover.composite(pointer, 0, 0, cover_width, cover_height, 0, 0,
            1, 1, prefs['scaling quality'], 255)
            im = Image.new('RGBA', (30, 30), 0x00000000)
            draw = ImageDraw.Draw(im)
            draw.polygon(
                (8, 0, 20, 0, 28, 8, 28, 20, 20, 28, 8, 28, 0, 20, 0, 8),
                fill=(0, 0, 0), outline=(0, 0, 0))
            draw.polygon(
                (8, 1, 20, 1, 27, 8, 27, 20, 20, 27, 8, 27, 1, 20, 1, 8),
                fill=(128, 0, 0), outline=(255, 255, 255))
            text = str(num_books)
            draw.text((15 - (6 * len(text) // 2), 9), text,
                fill=(255, 255, 255))
            circle = image_tools.pil_to_pixbuf(im)
            circle.composite(pointer, max(0, cover_width - 15),
                max(0, cover_height - 20), 30, 30, max(0, cover_width - 15),
                max(0, cover_height - 20), 1, 1, prefs['scaling quality'], 255)
        else:
            pointer = cover

        source.set_icon(Gdk.Texture.new_for_pixbuf(pointer), -5, -5)

    def _drag_data_received(self, target, value, x, y) -> bool:
        """Handle files dropped on the book area (i.e. from external
        apps like the file manager).
        """
        # A Gdk.FileList carries the files themselves.  What stood here
        # unquoted URIs by hand and then called .decode('utf-8') on the
        # str that came back, which has raised AttributeError ever since
        # the move to Python 3.
        paths = [path for path in
                 (dropped.get_path() for dropped in value.get_files())
                 if path is not None]
        if not paths:
            return False

        collection = self._library.collection_area.get_current_collection()
        collection_name = self._library.backend.get_collection_name(collection)
        self._library.add_books(paths, collection_name)
        return True


# vim: expandtab:sw=4:ts=4
