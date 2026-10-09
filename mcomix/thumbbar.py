"""thumbbar.py - Thumbnail sidebar for main window."""

import functools
import os

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from mcomix.preferences import prefs

from collections.abc import Sequence
from typing import TYPE_CHECKING
from mcomix import bookmark_backend
from mcomix import image_tools
from mcomix import log
from mcomix import preview
from mcomix import theme
from mcomix import thumbnail_list
from mcomix import tools
from mcomix import widgets

if TYPE_CHECKING:
    from mcomix import main

#: The badge on the thumbnail of a page a bookmark marks.
_BOOKMARK_BADGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'images', 'bookmark-badge.svg')


@functools.lru_cache(maxsize=4)
def _bookmark_badge(height: int) -> Gdk.Texture | None:
    """The bookmark badge, drawn <height> pixels tall from its SVG, or
    None where gdk-pixbuf has no SVG loader to draw it with."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(_BOOKMARK_BADGE_FILE,
                                                        -1, height)
    except GLib.Error as error:
        log.debug('Could not draw %s: %s', _BOOKMARK_BADGE_FILE, error.message)
        return None
    return None if pixbuf is None else image_tools.pixbuf_to_texture(pixbuf)


class ThumbnailSidebar(Gtk.ScrolledWindow, widgets.Releasable):

    """A thumbnail sidebar including scrollbar for the main window."""

    # Thumbnail border width in pixels.
    _BORDER_SIZE = 1

    def __init__(self, window: "main.MainWindow") -> None:
        super().__init__()

        self._window = window
        #: Thumbnail load status
        self._loaded = False
        #: The page being read, whose row is the one selected
        self._selected_page = 1
        #: The files behind the pages whose thumbnails would not load,
        #: which "skip broken pages" leaves out of the list
        self._broken: set[str] = set()

        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        # Setting step and page increments here has no effect: the
        # scrolled window recomputes both from the viewport size whenever
        # it is allocated.  See the note in main.py.
        # An overlay scrollbar is drawn over the thumbnails and appears
        # only while the pointer is near it, so the sidebar's width
        # would change as the pointer moved across it.
        self.props.overlay_scrolling = False

        self._list = thumbnail_list.ThumbnailListView()
        self._list.generate_thumbnail = self._generate_thumbnail
        self._list.style_cell = self._style_cell
        self._list.is_hidden = self._is_hidden
        self._list.set_thumbnail_size(self._pixbuf_size)
        self._list.set_can_focus(False)
        self._list.connect('activate', self._row_activated)

        # Dragging an image out to a file manager.  GTK4 has neither a
        # model drag source nor drag_data_get: a drag source controller
        # asks for the content when the drag starts.
        drag = Gtk.DragSource()
        drag.set_actions(Gdk.DragAction.COPY)
        drag.connect('prepare', self._drag_prepare)
        drag.connect('drag-begin', self._drag_begin)
        self._list.add_controller(drag)

        # A click on a thumbnail turns to that page, as it did when
        # this was a Gtk.TreeView with set_activate_on_single_click():
        # a Gtk.ListView activates a row on the second click unless it
        # is told otherwise, so the sidebar answered every first click
        # with nothing but a highlight.
        self._list.set_single_click_activate(True)

        # Rows are selected on hover as well once they activate on a
        # single click, and the highlight is what says which page is
        # being read, so it goes back there when the pointer leaves.
        motion = Gtk.EventControllerMotion()
        motion.connect('leave', self._pointer_left)
        self._list.add_controller(motion)

        clicks = Gtk.GestureClick()
        clicks.set_button(0)
        clicks.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        clicks.connect('pressed', self._mouse_press_event)
        self._list.add_controller(clicks)

        # A right click on a thumbnail opens the page menu for its page,
        # as one on the page itself does.
        menu_clicks = Gtk.GestureClick()
        menu_clicks.set_button(Gdk.BUTTON_SECONDARY)
        menu_clicks.connect('pressed', self._menu_click)
        self._list.add_controller(menu_clicks)

        self.set_child(self._list)
        self.change_thumbnail_background_color(prefs['thumb bg colour'])
        self.set_visible(True)

        self._window.page_changed += self._on_page_change
        self._window.imagehandler.page_available += self._on_page_available
        self._window.filehandler.file_closed += self._forget_broken
        store = bookmark_backend.BookmarksStore
        store.add_bookmark += self._bookmarks_changed
        store.remove_bookmark += self._bookmarks_changed
        store.replace_bookmark += self._bookmarks_changed
        store.clear_bookmarks += self._bookmarks_changed

    def release(self) -> None:
        """Take the list off the sidebar once the window has closed.

        GTK holds the list as the sidebar's child, which keeps its
        Python wrapper out of the collector's reach, and the wrapper
        holds the sidebar's methods it was handed - and through them
        the window.
        """
        store = bookmark_backend.BookmarksStore
        store.add_bookmark -= self._bookmarks_changed
        store.remove_bookmark -= self._bookmarks_changed
        store.replace_bookmark -= self._bookmarks_changed
        store.clear_bookmarks -= self._bookmarks_changed
        self.set_child(None)

    def toggle_page_numbers_visible(self) -> None:
        """ Enables or disables page numbers on the thumbnail bar. """

        visible = prefs['show page numbers on thumbnails']
        digits = 0
        if visible:
            number_of_pages = self._window.imagehandler.get_number_of_pages()
            digits = tools.number_of_digits(number_of_pages)
        self._list.set_page_numbers_visible(visible, digits)

    def set_visible(self, visible: bool) -> None:
        """Show or hide the ThumbnailSidebar.

        Every change of the sidebar's visibility goes through here, so
        what has to happen either side of one hangs off this.  Note that
        Gtk.Widget.show() and hide() would not: they reach the same C
        function this overrides without passing through the override,
        leaving the widget visible or not but the thumbnail thread as it
        was.  They are deprecated in GTK4 anyway.
        """
        if visible:
            self.load_thumbnails()
            # Before the rows come on screen, not after: the sidebar
            # is loaded while it is hidden - a page change does it - so
            # a stopped view would turn away every thumbnail its cells
            # ask for as they bind.  refresh() rather than only clearing
            # the flag, because hiding the sidebar does not unbind the
            # cells that were on screen: those are asked again here, or
            # nothing would ever ask for them.
            self._list.refresh()
        super().set_visible(visible)
        if not visible:
            self._list.stop_update()

    def clear(self) -> None:
        """Clear the ThumbnailSidebar of any loaded thumbnails."""

        self._loaded = False
        self._list.clear()
        self._selected_page = 1

    def _is_hidden(self, page: int) -> bool:
        """Whether <page> is left out of the list: a page that would not
        load, where the reader has asked to skip those."""
        if not prefs['skip broken pages']:
            return False
        path = self._window.imagehandler.get_path_to_page(page)
        return path is not None and path in self._broken

    def refilter(self) -> None:
        """List or leave out the pages that would not load again, after
        "skip broken pages" has changed."""
        self._list.refilter()
        self._select_page(self._selected_page, scroll=False)

    def _forget_broken(self) -> None:
        """Forget the pages that would not load, with the book they
        were in."""
        self._broken.clear()

    def _found_broken(self, path: str) -> bool:
        """Leave the page behind <path> out, now that its thumbnail has
        turned out to be the picture of one that would not load."""
        if path not in self._broken:
            self._broken.add(path)
            if prefs['skip broken pages']:
                self.refilter()
        return GLib.SOURCE_REMOVE

    def _style_cell(self, picture: Gtk.Picture, row: int) -> None:
        """Outline the thumbnail of a page picked out or marked to swap,
        as the main view outlines the page itself."""
        page = self._list.page_at(row)
        for css_class, marked in (
                (theme.PICKED_OUT_CLASS, page in self._window.selected_pages),
                (theme.MARKED_CLASS,
                 page is not None and page == self._window.swap_page)):
            if marked:
                picture.add_css_class(css_class)
            else:
                picture.remove_css_class(css_class)

    def restyle(self) -> None:
        """Outline again the thumbnails of the pages picked out or marked,
        after either has changed."""
        self._list.restyle()

    def resize(self) -> None:
        """Reload the thumbnails with the size specified by in the
        preferences.
        """
        self.clear()
        self._list.set_thumbnail_size(self._pixbuf_size)
        self.load_thumbnails()

    def change_thumbnail_background_color(
            self, colour: Sequence[float], dynamic: bool = False) -> None:
        """ Changes the background color of the thumbnail bar. """

        self.set_thumbnail_background(colour, dynamic)
        # Force a redraw of the widget.
        self._list.queue_draw()

    def set_thumbnail_background(self, color: Sequence[float],
                                 dynamic: bool = False) -> None:

        color = theme.background(color, dynamic)
        self._list.set_background(
            color, image_tools.text_color_for_background_color(color))

    @property
    def _thumbnail_size(self) -> int:
        """The size a thumbnail is drawn at on this screen.

        The preference was chosen for the screens MComix was written
        for, and is small on a tall one; every preview in MComix follows
        the screen the same way.
        """
        return preview.scaled(prefs['thumbnail size'], self)

    @property
    def _pixbuf_size(self) -> int:
        # Don't forget the extra pixels for the border!
        return self._thumbnail_size + 2 * self._BORDER_SIZE

    def load_thumbnails(self) -> None:
        """Load the thumbnails, if it is appropriate to do so."""

        if (not self._window.filehandler.file_loaded or
                self._window.imagehandler.get_number_of_pages() == 0 or
                self._loaded):
            return

        self.toggle_page_numbers_visible()

        # One row per page, numbered from 1.  The thumbnails themselves
        # are made as their rows come on screen.
        self._list.set_pages(
            range(1, self._window.imagehandler.get_number_of_pages() + 1))

        self._loaded = True
        self._mark_bookmarks()

        # The row for the page on screen, asked of the image handler
        # rather than remembered: clear() drops every row, so it has no
        # selection left to keep, and the sidebar is cleared and loaded
        # again whenever the thumbnail size or the image enhancement
        # changes.  Selecting row 0 there highlighted page 1 and
        # scrolled away from the page being read.
        page = self._window.imagehandler.get_current_page()
        self._select_page(max(page, 1))

    def _generate_thumbnail(self, uid: int) -> "GdkPixbuf.Pixbuf | None":
        """The thumbnail for page <uid>, made on the list's worker thread.

        A page whose file is not out of the archive yet is not waited
        for, since the thread has other rows to fill: the answer is
        None and the row stays empty until the page arrives and
        _on_page_available() below has the list ask again.
        """
        assert isinstance(uid, int)
        page = uid
        size = self._thumbnail_size
        pixbuf = self._window.imagehandler.get_thumbnail(page, size, size,
                                                         nowait=True)
        if pixbuf is not None and image_tools.is_missing_image(pixbuf):
            path = self._window.imagehandler.get_path_to_page(page)
            if path is not None:
                GLib.idle_add(self._found_broken, path)
        if pixbuf is not None:
            pixbuf = self._window.enhancer.enhance(pixbuf)
            pixbuf = image_tools.add_border(pixbuf, self._BORDER_SIZE)

        return pixbuf

    def _bookmarks_changed(self, *args: object) -> None:
        self._mark_bookmarks()

    def _mark_bookmarks(self) -> None:
        """Badge the thumbnails of the pages a bookmark marks, and only
        those."""
        if not self._loaded:
            return
        marked = bookmark_backend.BookmarksStore.pages_marked()
        badge = (_bookmark_badge(max(self._thumbnail_size // 4, 8))
                 if marked else None)
        store = self._list.store
        for position in range(store.get_n_items()):
            item = store.get_item(position)
            assert item is not None
            wanted = badge if item.uid in marked else None
            if item.badge is not wanted:
                item.badge = wanted

    def _select_page(self, page: int, scroll: bool = True) -> None:
        """Select the row of <page>, the page being read.
        If <scroll> is True, the list is automatically
        scrolled to ensure the selected row is visible.  A page left out
        of the list leaves no row selected.
        """
        self._selected_page = page
        self._list.select_row(self._list.row_of(page),
                              scroll=self._loaded and scroll)

    def _get_selected_page(self) -> int | None:
        """The page in the row that is selected."""
        return self._list.page_at(self._list.get_selected_row())

    def _row_activated(self, view: Gtk.ListView, position: int) -> None:
        """Handle events due to changed thumbnail selection."""
        page = self._list.page_at(position)
        if page is None:
            return
        self._select_page(page, scroll=False)
        self._window.set_page(page)

    def _pointer_left(self, controller: Gtk.EventControllerMotion) -> None:
        """Put the highlight back on the page being read."""
        self._select_page(self._selected_page, scroll=False)

    def _mouse_press_event(self, gesture: Gtk.GestureClick, n_press: int,
                           x: float, y: float) -> None:
        if self._window.was_out_of_focus:
            # if the window was out of focus and the user clicks on
            # the thumbbar then do not select that page because they
            # more than likely have many pages open and are simply trying
            # to give mcomix focus again
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _menu_click(self, gesture: Gtk.GestureClick, n_press: int,
                    x: float, y: float) -> None:
        page = self._list.page_at(self._list.position_at(x, y))
        if page is None:
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._window.show_page_menu(self._list, x, y, page)

    def _drag_prepare(self, source: Gtk.DragSource, x: float,
                      y: float) -> "Gdk.ContentProvider | None":
        """Offer the file behind the thumbnail being dragged, so that it
        can be copied (e.g. to a file manager).
        """
        selected = self._get_selected_page()
        if selected is None:
            return None
        path = self._window.imagehandler.get_path_to_page(selected)
        if path is None:
            return None
        # A Gio.File is what the other end reads a text/uri-list from;
        # there is no URI left to spell out by hand.
        return Gdk.ContentProvider.new_for_value(Gio.File.new_for_path(path))

    def _drag_begin(self, source: Gtk.DragSource, drag: Gdk.Drag) -> None:
        """Set the hotspot for the cursor at the top left corner of the
        thumbnail (so that we might actually see where we are dropping!).
        """
        item = self._list.get_item(self._list.get_selected_row())
        if item is None or item.thumbnail is None:
            return
        # A thumbnail is a Gdk.Texture, which is already the kind of
        # paintable a drag icon is made of.  A row of a Gtk.ListView has
        # no drag icon of its own, the way a Gtk.TreeView's had.
        source.set_icon(item.thumbnail, -5, -5)

    def _on_page_change(self) -> None:
        page = self._window.imagehandler.get_current_page()
        if page == self._selected_page:
            return
        self._select_page(page)

    def _on_page_available(self, page: int) -> None:
        """ Called whenever a new page is ready for display. """
        if self.get_visible():
            self._list.refresh()

# vim: expandtab:sw=4:ts=4
