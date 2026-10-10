"""book_area.py - The grid of book covers in the library window.

A Gtk.GridView of thumbnails, one per book in the collection that is
selected, filled by display_covers() and sorted by whichever of the
book's columns the sort preferences name.  The covers themselves are
drawn by a thumbnailing thread and arrive one at a time; the grid also
carries the popup menu that acts on a selection, and the drag source
that hands books to the collection tree.
"""

import functools
import os
import weakref
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk
import PIL.Image as Image
import PIL.ImageDraw as ImageDraw

from mcomix.preferences import prefs
from mcomix import thumbnail_list
from mcomix import file_chooser_library_dialog
from mcomix import image_tools
from mcomix import constants
from mcomix import preview
from mcomix import process
from mcomix import icons
from mcomix import theme
from mcomix import widgets
from mcomix import bookmark_backend
from mcomix import i18n
from mcomix import log
from mcomix import message_dialog
from mcomix import tools
from mcomix.library.pixbuf_cache import get_pixbuf_cache
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from mcomix.library import backend_types
    from mcomix.library import main_dialog


@functools.cache
def _paint_black(display: Gdk.Display, css_class: str) -> None:
    """Give <display> the rule that paints <css_class> black, once.

    The provider stays with the display for as long as the display
    lasts, and every library window opened after the first finds it
    there; one per window would pile up, closed windows' and all.
    """
    provider = Gtk.CssProvider()
    provider.load_from_string('.%s { background-color: black; }' % css_class)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, theme.VIEW_COLOUR_PRIORITY)


class _BookItem(thumbnail_list.ThumbnailItem):

    """One cover in the view, and what the sorters compare."""

    __gtype_name__ = 'MComixLibraryBookItem'

    def __init__(self, book: 'backend_types._Book') -> None:
        super().__init__(book.id)
        self.path = book.path
        self.size = book.size
        self.added = book.added


class _BookArea(Gtk.ScrolledWindow, widgets.Releasable):

    """The _BookArea is the central area in the library where the book
    covers are displayed.
    """

    # Thumbnail border width in pixels.
    _BORDER_SIZE = 1

    #: The class the covers' black background is written against.
    _BLACK_CSS_CLASS = 'mcomix-library-covers'

    def __init__(self, library: 'main_dialog._LibraryDialog') -> None:
        super().__init__()

        self._library_ref = weakref.ref(library)
        self._cache = get_pixbuf_cache()

        self._library.backend.book_added += self._new_book_in_library
        self._library.backend.book_added_to_collection += self._new_book_added

        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # A cover's uid is the book id, which is what _get_pixbuf()
        # takes; the rest of what the sorters compare rides along on the
        # item.
        self._covers = thumbnail_list.ThumbnailGridView()
        self._covers.generate_thumbnail = self._get_pixbuf
        self.set_thumbnail_size()
        self.set_sort_order()
        self._covers.connect('activate', self._book_activated)
        self._covers.selection.connect('selection-changed',
                                       self._selection_changed)
        clicks = Gtk.GestureClick()
        clicks.set_button(3)
        clicks.connect('pressed', self._button_press)
        self._covers.add_controller(clicks)

        middle_clicks = Gtk.GestureClick()
        middle_clicks.set_button(Gdk.BUTTON_MIDDLE)
        middle_clicks.connect('pressed', self._middle_click)
        self._covers.add_controller(middle_clicks)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press)
        self._covers.add_controller(keys)
        # Covers are shown on black, whatever base colour the theme has.
        # A style provider belongs to a display rather than to a widget,
        # so the view carries a class for the rule to single it out.
        self._covers.add_css_class(self._BLACK_CSS_CLASS)
        _paint_black(self._covers.get_display(), self._BLACK_CSS_CLASS)
        # Books drag out to the collection area, and files drop in from
        # a file manager.  GTK4 has neither a model drag source nor a
        # model drag destination; controllers do both, and a drop target
        # answers for one type - so the files come to one of their own.
        drag = Gtk.DragSource()
        # CTRL while dragging copies the books into a collection rather
        # than moving them there; GTK narrows the actions to COPY then.
        drag.set_actions(Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        drag.connect('prepare', self._drag_prepare)
        drag.connect('drag-begin', self._drag_begin)
        self._covers.add_controller(drag)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect('drop', self._drag_data_received)
        self._covers.add_controller(drop)
        self.set_child(self._covers)

        self._popup_actions = Gio.SimpleActionGroup()
        self._book_menu = self._create_popup_menu()

    def release(self) -> None:
        """Take the book popup actions out, once the window is closed.

        GTK holds an inserted action group, and each action holds a
        handler that is a method of this area: a cycle through C that
        Python's collector cannot see, which kept the area - and the
        covers it shows - alive after the window had gone.
        """
        self.insert_action_group('books', None)
        # And the cover grid: it holds a method of this area in turn, which
        # makes another such cycle for as long as the area is its parent.
        self.set_child(None)
        widgets.empty_action_group(self._popup_actions)

    @property
    def _library(self) -> 'main_dialog._LibraryDialog':
        """The library window this area is part of.

        Held weakly: GTK holds the area for as long as the window's
        widgets stand, which is for good once the window is closed,
        and a plain reference would keep the window alive with it.
        """
        library = self._library_ref()
        assert library is not None, 'the library window is gone'
        return library

    #: The popup's plain entries: action name, label, tooltip, handler.
    def _menu_entries(self) -> "tuple[tuple[str, str, str, Callable[..., None]], ...]":  # type: ignore[explicit-any]  # the menu items differ in what their handlers take
        return (
            ('open', _('_Open'),
             _('Opens the selected books for viewing.'),
             self.open_selected_book),
            ('open-keep-library', _('Open _without closing library'),
             _('Opens the selected books, but keeps the library window open.'),
             self.open_selected_book_noclose),
            ('mark-read', _('_Mark as read'),
             _('Marks the selected books as read to the end.'),
             self._mark_read),
            ('mark-unread', _('Mark as u_nread'),
             _('Forgets the page the selected books were left at.'),
             self._mark_unread),
            ('add', _('_Add...'),
             _('Add more books to the library.'),
             lambda *args: file_chooser_library_dialog.open_library_filechooser_dialog(
                 self._library)),
            ('remove-from-collection', _('Remove _from this collection'),
             _('Removes the selected books from the current collection.'),
             self._remove_books_from_collection),
            ('remove-from-library', _('Remove from the _library'),
             _('Completely removes the selected books from the library.'),
             self._remove_books_from_library),
            ('completely-remove', _('_Remove and move to the trash'),
             _('Deletes the selected books from disk.'),
             self._completely_remove_book),
            ('cleanup', _('Clean _up'),
             _('Removes no longer existent books from the collection.'),
             self._clean_up),
            ('copy-to-clipboard', _('_Copy'),
             _("Copies the selected book's path to clipboard."),
             self._copy_selected),
        )

    def _create_popup_menu(self) -> Gtk.PopoverMenu:
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

        # Each of the three radio groups is one stateful action, whose
        # state is the value picked in it.
        for name, state, handler in (
                ('sort-key', prefs['lib sort key'], self._sort_key_changed),
                ('sort-order', prefs['lib sort order'], self._sort_order_changed),
                ('cover-size', self._current_cover_size(), self._book_size_changed)):
            action = Gio.SimpleAction.new_stateful(
                name, GLib.VariantType.new('i'), GLib.Variant('i', state))
            action.connect('change-state', handler)
            self._popup_actions.add_action(action)
        self.insert_action_group('books', self._popup_actions)

        def radio(menu: Gio.Menu, entries: "tuple[tuple[str, int], ...]",
                  action_name: str) -> None:
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
        for group in (entries[0:2], entries[2:4], entries[4:5], entries[5:9],
                      entries[9:10]):
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
        # The backend outlives the library window, and holds the area
        # only weakly - but a closed area is not collected, and one left
        # listening would put a cover in its grid for every book filed
        # from then on.
        self._library.backend.book_added -= self._new_book_in_library
        self._library.backend.book_added_to_collection -= self._new_book_added

        # Unselect first, or closing with several books selected sends a
        # selection-changed for each one that goes.
        self._covers.unselect_all()
        self._covers.clear()

    def display_covers(self, collection_id: int) -> None:
        """Display the books that make up <collection_id>."""

        adjustment = self.get_vadjustment()
        if adjustment:
            adjustment.set_value(0)

        collection = self._library.backend.get_collection_by_id(collection_id)
        if collection is None:
            # The collection went between being asked for and being
            # drawn, which the idle this runs from leaves room for.
            self._covers.set_items(())
            return
        books = collection.get_books(self._library.filter_string)
        self._covers.set_items(_BookItem(book) for book in books)
        # Nothing is selected in a collection just shown, and the info
        # box speaks for the books on show.
        self._library.control_area.update_info(
            self._covers.get_selected_positions())

    def stop_update(self) -> None:
        """Signal that the updating of book covers should stop."""
        self._covers.stop_update()

    def add_books(self, books: Iterable['backend_types._Book']) -> None:
        """ Adds a cover to the grid for each of <books>. """
        for book in books:
            self._covers.append_item(_BookItem(book))

    def _new_book_in_library(self, book: 'backend_types._Book') -> None:
        """Bound to the backend's book_added: draws the cover of <book>,
        which the library did not have before, where "All books" is on
        show.

        A book filed in no collection is announced only here, and is in
        "All books" all the same; one filed in a collection is announced
        again for that, and is not drawn twice.
        """
        self._new_book_added(book, None)

    def _new_book_added(self, book: 'backend_types._Book',
                        collection: int | None) -> None:
        """ Bound to the backend's book_added_to_collection: draws
        the cover of <book> when <collection> is the one on show or one
        under it, or when all books are, and the filter does not hide it.  A book
        filed in no collection counts as being in "All books". """
        if collection is None:
            collection = constants.COLLECTION_ALL

        # The covers of a collection include the books of every
        # collection under it, as display_covers() draws them.
        if self._library.backend.collection_is_within(
                collection,
                self._library.collection_area.get_current_collection()):
            # Make sure not to show a book twice when COLLECTION_ALL is selected
            # and the book is added to another collection, triggering this event.
            if self.is_book_displayed(book):
                return

            # Under a filter, only a book it lets through: by name or by
            # path, and without regard to case, as the covers drawn from
            # the database are chosen.
            wanted = (self._library.filter_string or '').lower()
            if (wanted in book.name.lower()
                    or wanted in book.path.lower()):
                self.add_books([book])

    def is_book_displayed(self, book: 'backend_types._Book | None') -> bool:
        """ Returns True when <book> is one of the covers on show.
        None, which is what a lookup that found no book gives back,
        never is. """
        if not book:
            return False

        for item in self._each_item():
            if item.uid == book.id:
                return True

        return False

    def _item_at(self, position: int) -> _BookItem | None:
        """The cover shown at <position>, or None if none is.

        Everything this view holds is a _BookItem; the view itself only
        promises the ThumbnailItem every view has.
        """
        return cast('_BookItem | None', self._covers.get_item(position))

    def _each_item(self) -> Iterable[_BookItem]:
        """Every cover, in the order they are shown."""
        return cast('Iterable[_BookItem]', self._covers.each_item())

    def _selected_items(self) -> list[_BookItem]:
        """Every selected cover, in the order they are shown."""
        return cast('list[_BookItem]', self._covers.get_selected_items())

    def get_book_at_path(self, position: int) -> int | None:
        """Return the book ID of the cover shown at <position>."""
        item = self._item_at(position)
        return None if item is None else item.uid

    def shown_ids(self) -> list[int]:
        """The id of every book shown, in the order shown."""
        return [item.uid for item in self._each_item()]

    def shown_paths(self) -> list[str]:
        """The path of every book shown, in the order shown."""
        return [item.path for item in self._each_item()]

    def remove_books(self, book_ids: Iterable[int]) -> None:
        """Remove the books with <book_ids> from the _BookArea."""
        wanted = set(book_ids)
        items = [item for item in self._each_item()
                 if item.uid in wanted]
        self._covers.remove_items(items)
        for item in items:
            self._cache.invalidate(item.path)

    def _open_books(self, keep_library_open: bool) -> None:
        books = [item.uid for item in self._selected_items()]
        if not books:
            return
        self._library.open_book(books, keep_library_open=keep_library_open)

    def open_selected_book(self, *args: object) -> None:
        """Open the currently selected book."""
        self._open_books(False)

    def open_selected_book_noclose(self, *args: object) -> None:
        """Open the currently selected book, keeping the library open."""
        self._open_books(True)

    def _mark_read(self, *args: object) -> None:
        """Store the last page as where the selected books were left,
        which is what puts the tick on a cover."""
        self._mark_books(True)

    def _mark_unread(self, *args: object) -> None:
        """Forget where the selected books were left, tick and all."""
        self._mark_books(False)

    def _mark_books(self, read: bool) -> None:
        """Mark the selected books read to the end, or not read at all
        (upstream feature request 59).  A book whose pages were never
        counted has no last page to store, and is left as it is."""
        selected = self._selected_items()
        backend = self._library.backend
        with backend.transaction():
            for item in selected:
                book = backend.get_book_by_id(item.uid)
                if book is None:
                    continue
                if not read:
                    book.set_last_read_page(None)
                elif book.pages > 0:
                    book.set_last_read_page(book.pages)
        for item in selected:
            self._covers.redraw_item(item)

    def set_sort_order(self) -> None:
        """ Orders the covers by the "lib sort key" and "lib sort
        order" preferences. """
        key = prefs['lib sort key']
        ascending = prefs['lib sort order'] == constants.SORT_ASCENDING

        # Through the class, not self: GTK keeps the sort function where
        # Python's collector cannot see it, and a closure over the area
        # would keep the area alive once the library window is closed.
        def compare(left: _BookItem, right: _BookItem, _data: object) -> int:
            answer = _BookArea._compare_books(key, left, right)
            return answer if ascending else -answer

        self._covers.set_sorter(Gtk.CustomSorter.new(compare))

    @staticmethod
    def _compare_books(key: int, left: _BookItem, right: _BookItem) -> int:
        """Order two covers by <key>, one of the SORT_ constants: the
        name of the file, its size, the date the book was added, or else
        the whole path.

        Covers the key cannot tell apart - books added in one go, each
        series' "Volume 1" - are put in order by their paths, rather than
        left in whatever order the view held them in.
        """
        answer = 0
        if key == constants.SORT_NAME:
            answer = tools.cmp(
                tools.AlphanumericSortKey(os.path.basename(left.path).lower()),
                tools.AlphanumericSortKey(os.path.basename(right.path).lower()))
        elif key == constants.SORT_SIZE:
            answer = tools.cmp(left.size, right.size)
        elif key == constants.SORT_LAST_MODIFIED:
            answer = tools.cmp(left.added, right.added)
        if answer:
            return answer
        return tools.cmp(tools.AlphanumericSortKey(left.path),
                         tools.AlphanumericSortKey(right.path))

    def _sort_key_changed(self, action: Gio.SimpleAction,
                          value: GLib.Variant) -> None:
        """ Called when the field the library sorts on changes. """
        action.set_state(value)
        prefs['lib sort key'] = value.get_int32()
        self.set_sort_order()

    def _sort_order_changed(self, action: Gio.SimpleAction,
                            value: GLib.Variant) -> None:
        """ Called when the direction the library sorts in changes. """
        action.set_state(value)
        prefs['lib sort order'] = value.get_int32()
        self.set_sort_order()

    def set_thumbnail_size(self) -> None:
        """Draw the covers at the size the preference asks for."""
        self._covers.set_thumbnail_size(*self._pixbuf_size())

    def load_covers(self) -> None:
        self._cache.invalidate_all()
        self.set_thumbnail_size()
        collection = self._library.collection_area.get_current_collection()
        GLib.idle_add(self.display_covers, collection)

    def _book_size_changed(self, action: Gio.SimpleAction,
                           value: GLib.Variant) -> None:
        """ Called when library cover size changes.

        The state carries the size in pixels, with 0 standing for the
        custom size the dialog below asks for. """
        action.set_state(value)
        old_size = prefs['library cover size']
        chosen = value.get_int32()
        if chosen:
            prefs['library cover size'] = chosen
        else:
            dialog = message_dialog.MessageDialog(
                self._library, buttons=Gtk.ButtonsType.OK,
                destroy_with_parent=True)
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

            widgets.pack(dialog.get_content_area(), cover_size_scale, True, True, 0, end=True)

            def size_chosen(response: int) -> None:
                # The adjustment is not the scale: it is a plain object
                # the closure holds, and reading it owes nothing to the
                # dialog run_async() has already taken down.
                if response == Response.OK:
                    prefs['library cover size'] = int(adjustment.get_value())
                # "Custom..." was ticked when it was picked, before this
                # was answered; the menu says what the size came to.
                action.set_state(GLib.Variant('i', self._current_cover_size()))
                if prefs['library cover size'] != old_size:
                    self.load_covers()

            dialog.run_async(size_chosen)
            return

        if prefs['library cover size'] != old_size:
            self.load_covers()

    def _pixbuf_size(self, border_size: int = _BORDER_SIZE) -> tuple[int, int]:
        # Don't forget the extra pixels for the border!
        # The ratio (0.67) is just above the normal aspect ratio for books.
        size = preview.scaled(prefs['library cover size'], self)
        return (int(0.67 * size) + 2 * border_size,
                size + 2 * border_size)

    @functools.cached_property
    def _finished_mark(self) -> GdkPixbuf.Pixbuf | None:
        """The tick drawn on the cover of a book read to the end.

        A symbolic icon is a shape in whatever colour the icon theme
        drew it, which GTK recolours for the widget it stands in; loaded
        as a pixbuf it keeps that colour, and Adwaita's dark grey all
        but vanished on a dark cover.  So only the icon's shape is used,
        in dark grey on a light disc, which shows on any cover under
        any theme.

        Made once: the icon is an SVG file, and loading it cost about
        5 ms, fifty times what the rest of a cached cover costs, for
        every finished book each time the covers were drawn.  It is only
        read from then on, so the worker threads can share it; two of
        them may both make it the first time, which does no harm.
        """
        tick = icons.load_pixbuf('object-select-symbolic', 16)
        if tick is None:
            return None
        # Drawn four times over and scaled down, which smooths the edge
        # that ImageDraw leaves jagged.
        mark = Image.new('RGBA', (96, 96), (0, 0, 0, 0))
        ImageDraw.Draw(mark).ellipse((0, 0, 95, 95),
                                     fill=(255, 255, 255, 230))
        mark = mark.resize((24, 24), Image.Resampling.LANCZOS)
        shape = image_tools.pixbuf_to_pil(tick).convert('RGBA')
        mark.paste((46, 52, 54, 255), (4, 4), mask=shape.getchannel('A'))
        return image_tools.pil_to_pixbuf(mark)

    def _get_pixbuf(self, uid: int) -> GdkPixbuf.Pixbuf:
        """ Get or create the thumbnail for the selected book <uid>. """
        assert isinstance(uid, int)
        book = self._library.backend.get_book_by_id(uid)
        if book is None:
            # The book went while its cover was being drawn.
            return image_tools.missing_image_icon(
                *self._pixbuf_size(border_size=0))
        # One lookup rather than exists() plus get(): another worker thread
        # may evict the entry in between, and get() would then return None.
        pixbuf = self._cache.get(book.path)
        if pixbuf is None:
            width, height = self._pixbuf_size(border_size=0)
            try:
                thumbnail = self._library.backend.get_book_thumbnail(book.path)
            except Exception:
                thumbnail = None
            if thumbnail is None:
                # Drawn at this size already, and not composited, so
                # that the library shows through its rounded corners.
                pixbuf = image_tools.missing_image_icon(width, height)
            else:
                # Turned as the cover is shown when the book is read.
                pixbuf = image_tools.fit_in_rectangle(
                    image_tools.turned_as_shown(thumbnail, book.path),
                    width, height, scale_up=True)
            self._cache.add(book.path, pixbuf)

        pixbuf = self._library.main_window.enhancer.enhance(pixbuf)
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
        book_pixbuf = self._finished_mark
        if book_pixbuf is None:
            return pixbuf
        translation_x = pixbuf.get_width() - book_pixbuf.get_width() - 1
        translation_y = pixbuf.get_height() - book_pixbuf.get_height() - 1
        book_pixbuf.composite(pixbuf, translation_x, translation_y,
                              book_pixbuf.get_width(), book_pixbuf.get_height(),
                              translation_x, translation_y,
                              1.0, 1.0, GdkPixbuf.InterpType.NEAREST, 0xFF)

        return pixbuf

    def _book_activated(self, covers: thumbnail_list.ThumbnailGridView,
                        position: int) -> None:
        """Open the book whose cover is shown at <position>."""
        book = self.get_book_at_path(position)
        if book is None:
            return
        self._library.open_book([book], keep_library_open=False)

    def _selection_changed(self, selection: Gtk.MultiSelection,
                           position: int, count: int) -> None:
        """Update the displayed info in the _ControlArea when a new book
        is selected.
        """
        self._library.control_area.update_info(
            self._covers.get_selected_positions())

    def _remove_books_from_collection(self, *args: object) -> None:
        """Remove the currently selected books from the current collection,
        and thus also from the _BookArea.
        """
        collection = self._library.collection_area.get_current_collection()
        if collection is None or collection == constants.COLLECTION_ALL:
            # There is no one collection to take the books out of.
            return
        selected = self._selected_items()
        # The connection stays in transactional mode until it is told
        # otherwise, so a failure anywhere in here would leave every
        # later write waiting for a commit that never comes; the context
        # manager commits on the way out either way.
        with self._library.backend.transaction():
            for item in selected:
                self._library.backend.remove_book_from_collection(item.uid,
                                                                  collection)
            # The covers are those of every collection under this one as
            # well, so a book that is also filed in one of those is still
            # among them and keeps its cover.
            shown = self._library.backend.get_collection_by_id(collection)
            still_here = ({book.id for book in shown.get_books()}
                          if shown is not None else set())
            gone = [item for item in selected if item.uid not in still_here]
            self._covers.remove_items(gone)
            for item in gone:
                self._cache.invalidate(item.path)

        coll_name = self._library.backend.get_collection_name(collection)
        message = i18n.get_translation().ngettext(
                "Removed %(num)d book from '%(collection)s'.",
                "Removed %(num)d books from '%(collection)s'.",
                len(selected))
        self._library.set_status_message(
            message % {'num': len(selected), 'collection': coll_name})

    def _remove_books_from_library(self, *args: object) -> None:
        """Remove the currently selected books from the library, and thus
        also from the _BookArea.
        """

        selected = self._selected_items()
        # As above: the mode has to be put back whatever happens, or the
        # library stops committing anything for the rest of the session.
        with self._library.backend.transaction():
            for item in selected:
                self._library.backend.remove_book(item.uid)

            self._covers.remove_items(selected)
            for item in selected:
                self._cache.invalidate(item.path)

        msg = i18n.get_translation().ngettext(
            'Removed %d book from the library.',
            'Removed %d books from the library.',
            len(selected))
        self._library.set_status_message(msg % len(selected))

    def _completely_remove_book(self, *args: object) -> None:
        """Remove the currently selected books from the library and the
        hard drive, once the reader has said yes.

        Where the trash will not take one of them, as GLib's will not
        from a folder bind-mounted from another partition, the question
        says so before anything is done, and asks to delete for good:
        the answer to that is never remembered.
        """
        permanently = any(tools.trash_refuses(item.path)
                          for item in self._selected_items())
        if permanently:
            choice_dialog = message_dialog.MessageDialog(
                self._library, buttons=Gtk.ButtonsType.NONE)
            self._library.main_window.file_actions \
                .add_delete_permanently_buttons(choice_dialog)
            choice_dialog.set_text(
                _('Remove books from the library?'),
                _('The selected books will be removed from the library. '
                  'Any in a folder with no trash is deleted permanently '
                  'and cannot be restored.'))
            choice_dialog.run_async(lambda response: self._remove_answered(
                Response.YES if response == Response.OK else Response.NO,
                permanently=True))
            return
        choice_dialog = message_dialog.MessageDialog(
            self._library, buttons=Gtk.ButtonsType.YES_NO)
        # These books are deleted from the disk, so Enter must not be
        # what does it.  They go to the trash, from where they can be
        # restored, so the button that does it is the suggested action
        # rather than the destructive red of deleting for good.
        choice_dialog.set_default_response(Response.NO)
        deletes = choice_dialog.get_widget_for_response(Response.YES)
        if deletes is not None:
            deletes.add_css_class('suggested-action')
        choice_dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.LIBRARY_REMOVE_BOOK_FROM_DISK)
        choice_dialog.set_text(
            _('Remove books from the library?'),
            _('The selected books will be removed from the library and '
              'moved to the trash.')
        )
        choice_dialog.run_async(self._remove_answered)

    def _remove_answered(self, response: int,
                         permanently: bool = False) -> None:
        """Delete the selected books once the confirmation has come back.

        <permanently> says the reader was asked to delete for good the
        books the trash will not take, and those are not offered to the
        trash first.
        """
        # the user has told us they definitely want to delete the book
        if response == Response.YES:

            # The paths have to be read before the books go: removing
            # them from the library takes their rows with them.
            paths = [item.path for item in self._selected_items()]

            # Remove books from library
            self._remove_books_from_library()

            file_actions = self._library.main_window.file_actions
            kept: list[str] = []
            if permanently:
                for_good = [path for path in paths
                            if tools.trash_refuses(path)]
                deleted = file_actions.delete_files_permanently(
                    for_good, parent=self._library)
                kept = [path for path in for_good if path not in deleted]
                trashed = [path for path in paths if path not in for_good]
            else:
                trashed = paths

            # Into the trash.  A file that will not go - one on a file
            # system with no trash, inside a directory that cannot be
            # written to - was logged and nothing more, and the book had
            # left the library by then, so the reader was told the file
            # was gone while it was still there.  It is offered to be
            # deleted permanently instead, as the window's delete does.
            refused: dict[str, str] = {}
            for book_path in trashed:
                try:
                    tools.move_to_trash(book_path)
                except GLib.Error as error:
                    refused[book_path] = error.message
                    log.error(_('! Could not remove %(file)s: %(error)s'),
                              {'file': book_path, 'error': error.message})
            if not refused:
                self._books_deleted([path for path in paths
                                     if path not in kept])
                return

            def answered(deleted: list[str]) -> None:
                not_trashed = [path for path in refused
                               if path not in deleted]
                if not_trashed:
                    message = i18n.get_translation().ngettext(
                        '%d book could not be moved to the trash.',
                        '%d books could not be moved to the trash.',
                        len(not_trashed))
                    self._library.set_status_message(
                        message % len(not_trashed))
                self._books_deleted([path for path in paths
                                     if path not in kept + not_trashed])

            file_actions.offer_to_delete_permanently(
                refused, answered, parent=self._library)

    def _books_deleted(self, gone: "Sequence[str]") -> None:
        """Forget the books at <gone>, whose files have been deleted."""
        # A file that has been deleted can never be opened again, so
        # the recent files forget it, as they do after the window's
        # own delete.
        main_window = self._library.main_window
        for path in gone:
            main_window.uimanager.recent.remove_path(path)
        # The book on screen may be one of them, and whatever was
        # waiting to be written into it went with its file: closing
        # it is not to offer to write the archive back where it was
        # just deleted from.  The window's own delete forgets the
        # changes the same way.
        open_book = main_window.filehandler.get_path_to_base()
        if open_book is not None and os.path.abspath(open_book) in [
                os.path.abspath(path) for path in gone]:
            main_window.file_actions.forget_changes()
        self._offer_to_remove_bookmarks(gone)

    def _offer_to_remove_bookmarks(self, paths: "Sequence[str]") -> None:
        """Ask whether the bookmarks in the deleted books should go too.

        Asked rather than done, as the window's own delete asks: a
        bookmark is a page the reader marked, not a record MComix keeps
        of a file, and it is the same remembered prompt, so a reader who
        has answered it once is not asked again here.
        """
        store = bookmark_backend.BookmarksStore
        marked = [path for path in paths if store.bookmarks_for_path(path)]
        if not marked:
            return
        dialog = message_dialog.MessageDialog(
            self._library, buttons=Gtk.ButtonsType.YES_NO)
        dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.REMOVE_BOOKMARKS_OF_DELETED_FILE)
        # Named rather than positional, so that a language whose
        # singular form covers 21 and 31 as well can carry the number
        # in it: a mapping leaves a format string that does not use the
        # key alone, where a bare %d would raise.
        message = i18n.get_translation().ngettext(
            'Remove the bookmarks in the deleted book?',
            'Remove the bookmarks in the %(count)d deleted books?',
            len(marked))
        dialog.set_text(message % {'count': len(marked)})
        dialog.set_default_response(Response.NO)

        def answered(response: int) -> None:
            if response == Response.YES:
                for path in marked:
                    store.remove_for_path(path)

        dialog.run_async(answered)

    def _copy_selected(self, *args: object) -> None:
        """ Copies the currently selected item to clipboard. """
        selected = self._selected_items()
        if len(selected) == 1:
            item = selected[0]
            # The cover as a pixbuf, which is what the clipboard takes;
            # the cell holds it as a texture.  _get_pixbuf() answers
            # from the cache, so this costs nothing that was not
            # already paid.
            self._library.main_window.clipboard.copy(item.path,
                                                 self._get_pixbuf(item.uid))

    def _middle_click(self, gesture: Gtk.GestureClick, n_press: int,
                      x: float, y: float) -> None:
        """Open the book under the pointer in an MComix of its own.

        The middle button means here what it means in the recent and
        bookmark menus: what it opens goes into a program of its own,
        leaving both the book being read and the library as they are.
        It acts on the cover under the pointer rather than on the
        selection, and leaves the selection alone, so a reader can send
        off one book without losing the several they had picked.
        """
        position = self._covers.position_at(x, y)
        if position < 0:
            return
        book = self.get_book_at_path(position)
        if book is None:
            return
        path = self._library.backend.get_book_path(book)
        if path is None:
            return
        process.launch_mcomix(path)

    def _button_press(self, gesture: Gtk.GestureClick, n_press: int,
                      x: float, y: float) -> None:
        """Handle mouse button presses on the _BookArea."""
        position = self._covers.position_at(x, y)

        if position >= 0 \
                and position not in self._covers.get_selected_positions():
            self._covers.select_only(position)

        self._popup_book_menu(gesture.get_widget() or self._covers, x, y)

    def _popup_book_menu(self, over: "Gtk.Widget | None" = None,
                         x: float = 0, y: float = 0) -> None:
        """ Shows the book panel popup menu, pointing at (<x>, <y>) in
        <over>: where a click was made, or the corner of the panel for the
        menu key, which has no position. """

        selected = self._selected_items()
        books_selected = bool(selected)
        collection = self._library.collection_area.get_current_collection()
        is_collection_all = collection == constants.COLLECTION_ALL

        for action in ('open', 'open-keep-library', 'mark-read',
                       'mark-unread', 'remove-from-library',
                       'completely-remove'):
            self._set_sensitive(action, books_selected)

        self._set_sensitive('add', collection is not None)
        self._set_sensitive('cleanup', collection is not None)
        self._set_sensitive('remove-from-collection',
                            books_selected and not is_collection_all)
        self._set_sensitive('copy-to-clipboard', len(selected) == 1)

        widgets.popup_at(self._book_menu, over or self, x, y)

    def _clean_up(self, *args: object) -> None:
        """Take the books of the collection on show whose files have
        gone out of the library, as the collection's own menu does."""
        collection = self._library.collection_area.get_current_collection()
        if collection is None:
            return
        self._library.collection_area.clean_collection(
            None if collection == constants.COLLECTION_ALL else collection)

    def _set_sensitive(self, action: str, sensitive: bool) -> None:
        """ Enables the popup menu action <action> based on <sensitive>. """

        widgets.simple_action(self._popup_actions, action).set_enabled(sensitive)

    def _key_press(self, controller: Gtk.EventControllerKey,
                   keyval: int, keycode: int,
                   state: Gdk.ModifierType) -> bool:
        """Handle key presses on the _BookArea."""
        if keyval == Gdk.KEY_Delete:
            self._remove_books_from_collection()
            return Gdk.EVENT_STOP
        # A GTK4 widget has no popup-menu signal, so the keys that
        # asked for a menu through it are heard here.
        if widgets.menu_key(keyval, state):
            self._popup_book_menu()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _drag_prepare(self, source: Gtk.DragSource, x: float,
                      y: float) -> "Gdk.ContentProvider | None":
        """Offer the books being dragged, as the positions of their covers."""
        positions = self._covers.get_selected_positions()
        if not positions:
            return None
        return Gdk.ContentProvider.new_for_value(
            '%s:%s' % (constants.LIBRARY_DRAG_BOOKS,
                       ','.join(str(position) for position in positions)))

    def _drag_begin(self, source: Gtk.DragSource, drag: Gdk.Drag) -> None:
        """Create a cursor image for drag-n-drop from the library.

        This method relies on implementation details regarding PIL's
        drawing functions and default font to produce good looking results.
        If those are changed in a future release of PIL, this method might
        produce bad looking output (e.g. non-centered text).

        """
        selected = self._selected_items()
        if not selected:
            return
        num_books = len(selected)
        book = selected[0].uid

        cover = self._library.backend.get_book_cover(book) \
            or image_tools.missing_image_icon(constants.MAX_LIBRARY_COVER_SIZE,
                                              constants.MAX_LIBRARY_COVER_SIZE)

        halved = cover.scale_simple(max(0, cover.get_width() // 2),
                                    max(0, cover.get_height() // 2),
                                    image_tools.scaling_quality_preference())
        assert halved is not None, 'the drag cursor could not be scaled'
        cover = image_tools.add_border(halved, 1, 0xFFFFFFFF)
        cover = image_tools.add_border(cover, 1)

        if num_books > 1:
            cover_width = cover.get_width()
            cover_height = cover.get_height()
            pointer = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                           has_alpha=True, bits_per_sample=8,
                                           width=max(30, cover_width + 15),
                                           height=max(30, cover_height + 10))
            assert pointer is not None, 'the drag cursor could not be allocated'
            pointer.fill(0x00000000)
            cover.composite(pointer, 0, 0, cover_width, cover_height, 0, 0,
                            1, 1, image_tools.scaling_quality_preference(), 255)
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
                             max(0, cover_height - 20), 1, 1,
                             image_tools.scaling_quality_preference(), 255)
        else:
            pointer = cover

        source.set_icon(image_tools.pixbuf_to_texture(pointer), -5, -5)

    def _drag_data_received(self, target: Gtk.DropTarget, value: Gdk.FileList,
                            x: float, y: float) -> bool:
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

        self._library.add_books(
            paths, self._library.collection_area.get_current_collection())
        return True


# vim: expandtab:sw=4:ts=4
