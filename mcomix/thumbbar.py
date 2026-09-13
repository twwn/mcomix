"""thumbbar.py - Thumbnail sidebar for main window."""

from gi.repository import Gdk, Gio, Gtk

from mcomix.preferences import prefs

from collections.abc import Sequence
from typing import TYPE_CHECKING
from mcomix import image_tools
from mcomix import preview
from mcomix import theme
from mcomix import thumbnail_list
from mcomix import tools

if TYPE_CHECKING:
    from gi.repository import GdkPixbuf
    from mcomix import main


class ThumbnailSidebar(Gtk.ScrolledWindow):

    """A thumbnail sidebar including scrollbar for the main window."""

    # Thumbnail border width in pixels.
    _BORDER_SIZE = 1

    def __init__(self, window: "main.MainWindow") -> None:
        super(ThumbnailSidebar, self).__init__()

        self._window = window
        #: Thumbnail load status
        self._loaded = False
        #: Selected row in the list
        self._currently_selected_row = 0

        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        # Setting step and page increments here has no effect: the
        # scrolled window recomputes both from the viewport size whenever
        # it is allocated.  See the note in main.py.
        # Disable stupid overlay scrollbars...
        if hasattr(self.props, 'overlay_scrolling'):
            self.props.overlay_scrolling = False

        self._list = thumbnail_list.ThumbnailListView()
        self._list.generate_thumbnail = self._generate_thumbnail
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

        clicks = Gtk.GestureClick()
        clicks.set_button(0)
        clicks.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        clicks.connect('pressed', self._mouse_press_event)
        self._list.add_controller(clicks)

        self.set_child(self._list)
        self.change_thumbnail_background_color(prefs['thumb bg colour'])
        self.set_visible(True)

        self._window.page_changed += self._on_page_change
        self._window.imagehandler.page_available += self._on_page_available

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
        super(ThumbnailSidebar, self).set_visible(visible)
        if not visible:
            self._list.stop_update()

    def clear(self) -> None:
        """Clear the ThumbnailSidebar of any loaded thumbnails."""

        self._loaded = False
        self._list.clear()
        self._currently_selected_row = 0

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

        # Update current image selection in the thumb bar.
        self._set_selected_row(self._currently_selected_row)

    def _generate_thumbnail(self, uid: int) -> "GdkPixbuf.Pixbuf | None":
        """ Generate the pixbuf for C{uid} at demand. """
        assert isinstance(uid, int)
        page = uid
        size = self._thumbnail_size
        pixbuf = self._window.imagehandler.get_thumbnail(page, size, size,
                                                         nowait=True)
        if pixbuf is not None:
            pixbuf = self._window.enhancer.enhance(pixbuf);
            pixbuf = image_tools.add_border(pixbuf, self._BORDER_SIZE)

        return pixbuf

    def _set_selected_row(self, row: int, scroll: bool = True) -> None:
        """Set currently selected row.
        If <scroll> is True, the list is automatically
        scrolled to ensure the selected row is visible.
        """
        self._currently_selected_row = row
        self._list.select_row(row, scroll=self._loaded and scroll)

    def _get_selected_row(self) -> int:
        """Return the index of the currently selected row."""
        return self._list.get_selected_row()

    def _row_activated(self, view: Gtk.ListView, position: int) -> None:
        """Handle events due to changed thumbnail selection."""
        self._set_selected_row(position, scroll=False)
        self._window.set_page(position + 1)

    def _mouse_press_event(self, gesture: Gtk.GestureClick, n_press: int,
                           x: float, y: float) -> None:
        if self._window.was_out_of_focus:
            # if the window was out of focus and the user clicks on
            # the thumbbar then do not select that page because they
            # more than likely have many pages open and are simply trying
            # to give mcomix focus again
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _drag_prepare(self, source: Gtk.DragSource, x: float,
                      y: float) -> "Gdk.ContentProvider | None":
        """Offer the file behind the thumbnail being dragged, so that it
        can be copied (e.g. to a file manager).
        """
        selected = self._get_selected_row()
        path = self._window.imagehandler.get_path_to_page(selected + 1)
        if path is None:
            return None
        # A Gio.File is what the other end reads a text/uri-list from;
        # there is no URI left to spell out by hand.
        return Gdk.ContentProvider.new_for_value(Gio.File.new_for_path(path))

    def _drag_begin(self, source: Gtk.DragSource, drag: Gdk.Drag) -> None:
        """Set the hotspot for the cursor at the top left corner of the
        thumbnail (so that we might actually see where we are dropping!).
        """
        item = self._list.get_item(self._get_selected_row())
        if item is None or item.thumbnail is None:
            return
        # A thumbnail is a Gdk.Texture, which is already the kind of
        # paintable a drag icon is made of.  A row of a Gtk.ListView has
        # no drag icon of its own, the way a Gtk.TreeView's had.
        source.set_icon(item.thumbnail, -5, -5)

    def _on_page_change(self) -> None:
        row = self._window.imagehandler.get_current_page() - 1
        if row == self._currently_selected_row:
            return
        self._set_selected_row(row)

    def _on_page_available(self, page: int) -> None:
        """ Called whenever a new page is ready for display. """
        if self.get_visible():
            self._list.refresh()

# vim: expandtab:sw=4:ts=4
