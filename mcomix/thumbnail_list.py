"""thumbnail_list.py - Thumbnails that are made as their rows come on screen."""

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango

from mcomix import image_tools
from mcomix.preferences import prefs
from mcomix.worker_thread import WorkerThread

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, cast


class ThumbnailItem(GObject.Object):

    """One entry of a thumbnail view.

    <uid> is whatever the view's generate_thumbnail() takes: a page
    number for the sidebar, a path or a book id elsewhere.  The
    thumbnail is a property rather than a plain attribute so that a row
    which is already on screen redraws itself when the worker thread
    that was making one finishes.
    """

    __gtype_name__ = 'MComixThumbnailItem'

    thumbnail = GObject.Property(type=Gdk.Texture)

    def __init__(self, uid: Any, label: str = '', tooltip: str = '') -> None:
        super(ThumbnailItem, self).__init__()
        self.uid = uid
        #: What the view writes beside or under the thumbnail.
        self.label = label
        #: What it says when the pointer rests on it.
        self.tooltip = tooltip


class _ThumbnailCell(Gtk.Box):

    """The widget one entry of a thumbnail view is built out of.

    A class of its own rather than a Gtk.Box with attributes set on it:
    PyGObject is free to drop the Python wrapper of a plain Gtk.Box that
    only GTK still holds, and to build a new one without them when the
    row comes back.
    """

    __gtype_name__ = 'MComixThumbnailCell'

    def __init__(self, orientation: Gtk.Orientation) -> None:
        super(_ThumbnailCell, self).__init__(orientation=orientation)
        self.label = Gtk.Label()
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        if orientation == Gtk.Orientation.HORIZONTAL:
            self.label.set_xalign(1.0)
            self.picture.set_hexpand(True)
            self.append(self.label)
            self.append(self.picture)
        else:
            self.picture.set_vexpand(True)
            self.append(self.picture)
            self.append(self.label)
        #: The notify::thumbnail handler while this cell is bound.
        self.handler: int | None = None
        #: The position this cell is showing, for a reordering drag.
        self.position = 0


class _ThumbnailViewBase(object):

    """What a thumbnail view is made of, whatever shape it has.

    This is what a Gtk.TreeView or Gtk.IconView of
    Gtk.CellRendererPixbufs became, all of which GTK deprecated in 4.10.
    The change is not only a rename.  Those views had to be *asked*
    which of their rows were on screen, and answered None until they had
    been laid out - neither being mapped nor their adjustment settling
    was late enough - so the code that fed them carried a timer which
    asked again up to forty times before giving up.  A Gtk.ListView or
    Gtk.GridView binds a row exactly when it comes on screen and unbinds
    it when it leaves, so 'bind' *is* that answer, and it cannot arrive
    too early.
    """

    #: How the label sits next to the picture in one cell.
    CELL_ORIENTATION = Gtk.Orientation.HORIZONTAL
    #: The CSS class set_background() writes its rule against.
    CSS_CLASS = 'mcomix-thumbnail-view'

    #: Built by the view classes below, which know which kind of
    #: selection they want.  <store> holds the entries; <model> is what
    #: the view shows, which is the store itself unless something sorts
    #: it; <selection> wraps <model>.
    store: "Gio.ListStore[ThumbnailItem]"
    model: "Gio.ListModel[ThumbnailItem]"
    selection: Gtk.SelectionModel

    def _init_thumbnails(self) -> None:
        #: Replaced by whoever knows how to make a thumbnail for a uid.
        self.generate_thumbnail: Callable[[Any], GdkPixbuf.Pixbuf | None] | None = None
        #: The size a thumbnail is drawn at, and whether the label is
        #: drawn with it.  A cover is taller than it is wide, so the two
        #: are kept apart.
        self._thumbnail_width = 0
        self._thumbnail_height = 0
        self._labels_visible = False
        self._label_width = 0
        #: The items whose cells are on screen right now.
        self._bound: set[ThumbnailItem] = set()
        #: Ignore thumbnails that arrive after stop_update().
        self._updates_stopped = True
        self._thread = WorkerThread(self._thumbnail_worker,
                                    name='thumbview',
                                    unique_orders=True,
                                    max_threads=prefs['max threads'])
        #: The style provider carrying the background colour.
        self._colour_provider: Gtk.CssProvider | None = None

    def _make_factory(self) -> Gtk.SignalListItemFactory:
        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._setup_cell)
        factory.connect('bind', self._bind_cell)
        factory.connect('unbind', self._unbind_cell)
        return factory

    # -- The cells --------------------------------------------------------

    def _setup_cell(self, factory: Gtk.SignalListItemFactory,
                    list_item: Gtk.ListItem) -> None:
        """Build an empty cell: a label, and the thumbnail itself."""
        cell = _ThumbnailCell(self.CELL_ORIENTATION)
        self._size_cell(cell)
        self._decorate_cell(cell)
        list_item.set_child(cell)

    def _decorate_cell(self, cell: _ThumbnailCell) -> None:
        """Add whatever this view wants on every cell. Nothing, by default."""

    def _bind_cell(self, factory: Gtk.SignalListItemFactory,
                   list_item: Gtk.ListItem) -> None:
        """Show <list_item>'s thumbnail, and ask for it if it has none.

        A cell is bound when it comes on screen, so this is where the
        view says what has to be made.
        """
        cell = cast(_ThumbnailCell, list_item.get_child())
        item = cast(ThumbnailItem, list_item.get_item())
        cell.position = list_item.get_position()
        cell.label.set_text(item.label)
        cell.set_tooltip_text(item.tooltip or None)
        cell.picture.set_paintable(item.thumbnail)
        cell.handler = item.connect('notify::thumbnail',
                                    self._thumbnail_arrived, cell)
        self._bound.add(item)
        if item.thumbnail is None:
            self._ask_for(item)

    def _unbind_cell(self, factory: Gtk.SignalListItemFactory,
                     list_item: Gtk.ListItem) -> None:
        """Let go of the item a cell off the screen was showing."""
        cell = cast(_ThumbnailCell, list_item.get_child())
        item = cast(ThumbnailItem, list_item.get_item())
        if cell.handler is not None:
            item.disconnect(cell.handler)
            cell.handler = None
        self._bound.discard(item)
        cell.picture.set_paintable(None)

    def _thumbnail_arrived(self, item: ThumbnailItem,
                           parameter: GObject.ParamSpec,
                           cell: _ThumbnailCell) -> None:
        cell.picture.set_paintable(item.thumbnail)

    def _size_cell(self, cell: _ThumbnailCell) -> None:
        cell.picture.set_size_request(self._thumbnail_width,
                                      self._thumbnail_height)
        cell.label.set_visible(self._labels_visible)
        if self._label_width:
            cell.label.set_width_chars(self._label_width)

    def _each_cell(self) -> Iterator[_ThumbnailCell]:
        """The cell widget of every list item that has one right now."""
        child = cast(Gtk.Widget, self).get_first_child()
        while child is not None:
            cell = child.get_first_child()
            if isinstance(cell, _ThumbnailCell):
                yield cell
            child = child.get_next_sibling()

    # -- What the cells look like -----------------------------------------

    def set_thumbnail_size(self, width: int, height: int | None = None) -> None:
        """Draw the thumbnails <width> by <height> pixels from now on.

        <height> defaults to <width>, which is what a square thumbnail
        wants; the library's covers are not square.
        """
        if height is None:
            height = width
        if (width, height) == (self._thumbnail_width, self._thumbnail_height):
            return
        self._thumbnail_width = width
        self._thumbnail_height = height
        for cell in self._each_cell():
            self._size_cell(cell)

    def set_labels_visible(self, visible: bool, width: int = 0) -> None:
        """Show or hide the label that goes with each thumbnail."""
        self._labels_visible = visible
        self._label_width = width
        for cell in self._each_cell():
            self._size_cell(cell)

    def set_background(self, colour: Sequence[float],
                       text_colour: Gdk.RGBA) -> None:
        """Paint the view on <colour>, with its labels in <text_colour>.

        <colour> is a sequence of red, green, blue and alpha between 0
        and 1.  This was two properties of two cell renderers; a view
        built from widgets says it in CSS instead.
        """
        widget = cast(Gtk.Widget, self)
        provider = self._colour_provider
        if provider is None:
            provider = self._colour_provider = Gtk.CssProvider()
            widget.add_css_class(self.CSS_CLASS)
            Gtk.StyleContext.add_provider_for_display(
                widget.get_display(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        provider.load_from_string(
            '.%(name)s, .%(name)s > child, .%(name)s > row'
            ' { background: %(background)s; color: %(text)s; }'
            % {'name': self.CSS_CLASS,
               'background': Gdk.RGBA(*colour).to_string(),
               'text': text_colour.to_string()})

    # -- The entries themselves -------------------------------------------

    def set_items(self, items: Iterable[ThumbnailItem]) -> None:
        """Show <items>, replacing whatever was there."""
        self.stop_update()
        items = list(items)
        # Before the splice, not after it: the cells that fit on screen
        # are bound from inside it, and a stopped view turns away every
        # thumbnail those cells ask for.
        self._updates_stopped = False
        self.store.splice(0, self.store.get_n_items(), items)

    def append_item(self, item: ThumbnailItem) -> None:
        """Add one entry to the end."""
        self._updates_stopped = False
        self.store.append(item)

    def clear(self) -> None:
        """Drop every entry."""
        self.stop_update()
        self._bound.clear()
        self.store.remove_all()

    def stop_update(self) -> None:
        """Stop making thumbnails, and ignore the ones still coming."""
        self._updates_stopped = True
        self._thread.stop()

    def refresh(self) -> None:
        """Ask again for the thumbnails the cells on screen are missing.

        A page that has not been extracted yet answers with nothing, so
        the cells showing it have to be asked again once it has been.
        Only the bound cells are asked: those are the ones on screen.
        """
        self._updates_stopped = False
        for item in tuple(self._bound):
            if item.thumbnail is None:
                self._ask_for(item)

    def _ask_for(self, item: ThumbnailItem) -> None:
        if self.generate_thumbnail is None or self._updates_stopped:
            return
        with self._thread:
            self._thread.append_order(item)

    def _thumbnail_worker(self, item: ThumbnailItem) -> None:
        """Run by a worker thread to make one thumbnail."""
        generate = self.generate_thumbnail
        pixbuf = generate(item.uid) if generate is not None else None
        if pixbuf is not None:
            GLib.idle_add(self._thumbnail_finished, item, pixbuf)

    def _thumbnail_finished(self, item: ThumbnailItem,
                            pixbuf: GdkPixbuf.Pixbuf) -> bool:
        if not self._updates_stopped:
            item.thumbnail = image_tools.pixbuf_to_texture(pixbuf)
        return GLib.SOURCE_REMOVE

    # -- The entries, by position -----------------------------------------

    def get_item(self, position: int) -> "ThumbnailItem | None":
        """The ThumbnailItem shown at <position>, or None if none is.

        Positions are the ones the view shows, which is not the order
        the store holds them in once a sorter is set.
        """
        if not 0 <= position < self.model.get_n_items():
            return None
        return cast(ThumbnailItem, self.model.get_item(position))

    def each_item(self) -> Iterator[ThumbnailItem]:
        """Every entry, in the order they are shown."""
        for position in range(self.model.get_n_items()):
            yield cast(ThumbnailItem, self.model.get_item(position))

    def remove_items(self, items: Iterable[ThumbnailItem]) -> None:
        """Drop <items>, wherever the store happens to hold them."""
        for item in items:
            found, position = self.store.find(item)
            if found:
                self.store.remove(position)


class ThumbnailListView(Gtk.ListView, _ThumbnailViewBase):

    """A vertical list of thumbnails, one per row, as the sidebar shows."""

    CELL_ORIENTATION = Gtk.Orientation.HORIZONTAL
    CSS_CLASS = 'mcomix-thumbnail-list'

    #: One row at a time, and the sidebar follows the page rather than
    #: leading it, so nothing may be selected.
    selection: Gtk.SingleSelection

    def __init__(self) -> None:
        self.store = Gio.ListStore.new(ThumbnailItem)
        self.selection = Gtk.SingleSelection(model=self.store)
        # A page is selected because the viewer moved to it, so the list
        # must be able to start with nothing selected and to follow the
        # page rather than lead it.
        self.selection.set_autoselect(False)
        self.selection.set_can_unselect(True)
        _ThumbnailViewBase._init_thumbnails(self)
        super(ThumbnailListView, self).__init__(
            model=self.selection, factory=self._make_factory())

    def set_pages(self, uids: Iterable[int]) -> None:
        """Show one row per page number in <uids>."""
        self.set_items(ThumbnailItem(uid, label=str(uid)) for uid in uids)

    def set_page_numbers_visible(self, visible: bool, digits: int = 0) -> None:
        """Show or hide the page number beside each thumbnail."""
        self.set_labels_visible(visible, digits + 1 if digits else 0)

    def get_selected_row(self) -> int:
        """The row that is selected, or 0 if none is."""
        position = self.selection.get_selected()
        if position == Gtk.INVALID_LIST_POSITION:
            return 0
        return position

    def select_row(self, row: int, scroll: bool = True) -> None:
        """Select <row>, scrolling it into view unless told not to."""
        if not 0 <= row < self.store.get_n_items():
            return
        self.selection.set_selected(row)
        if scroll:
            self.scroll_to(row, Gtk.ListScrollFlags.NONE, None)


class ThumbnailGridView(Gtk.GridView, _ThumbnailViewBase):

    """A grid of thumbnails, as the library and the archive editor show.

    This is what a Gtk.IconView was.  Selecting more than one is the
    Gtk.MultiSelection the model is wrapped in; reordering by dragging,
    which Gtk.IconView did for itself, is set_reorderable() below.
    """

    CELL_ORIENTATION = Gtk.Orientation.VERTICAL
    CSS_CLASS = 'mcomix-thumbnail-grid'

    #: What a reordering drag carries: the position it started from.
    _REORDER_TYPE = 'application/x-mcomix-thumbnail-position'

    def __init__(self) -> None:
        self.store = Gio.ListStore.new(ThumbnailItem)
        # Always a sort model, with no sorter until one is set: it costs
        # nothing when it passes the store straight through, and it is
        # what lets the library reorder its covers without the entries
        # themselves moving.
        self._sort_model = Gtk.SortListModel(model=self.store)
        self.model = self._sort_model
        self.selection = Gtk.MultiSelection(model=self.model)
        _ThumbnailViewBase._init_thumbnails(self)
        self._reorderable = False
        super(ThumbnailGridView, self).__init__(
            model=self.selection, factory=self._make_factory())
        self.set_max_columns(64)

    def set_sorter(self, sorter: "Gtk.Sorter | None") -> None:
        """Show the entries in the order <sorter> puts them in.

        None shows them in the order they were added, which is what the
        archive editor wants: there, the order *is* the thing being
        edited.
        """
        self._sort_model.set_sorter(sorter)

    # -- Reordering -------------------------------------------------------

    def set_reorderable(self, reorderable: bool) -> None:
        """Let the entries be dragged into a different order."""
        self._reorderable = reorderable

    def _decorate_cell(self, cell: _ThumbnailCell) -> None:
        if not self._reorderable:
            return
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect('prepare', self._reorder_prepare, cell)
        source.connect('drag-begin', self._reorder_begin, cell)
        cell.add_controller(source)
        target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        target.connect('drop', self._reorder_drop, cell)
        cell.add_controller(target)

    def _reorder_prepare(self, source: Gtk.DragSource, x: float, y: float,
                         cell: _ThumbnailCell) -> Gdk.ContentProvider:
        return Gdk.ContentProvider.new_for_value(
            '%s:%d' % (self._REORDER_TYPE, cell.position))

    def _reorder_begin(self, source: Gtk.DragSource, drag: Gdk.Drag,
                       cell: _ThumbnailCell) -> None:
        paintable = cell.picture.get_paintable()
        if paintable is not None:
            source.set_icon(paintable, 0, 0)

    def _reorder_drop(self, target: Gtk.DropTarget, value: str, x: float,
                      y: float, cell: _ThumbnailCell) -> bool:
        prefix = self._REORDER_TYPE + ':'
        if not isinstance(value, str) or not value.startswith(prefix):
            return False
        try:
            source_position = int(value[len(prefix):])
        except ValueError:
            return False
        return self.move_item(source_position, cell.position)

    def move_item(self, source: int, destination: int) -> bool:
        """Move the entry at <source> so that it sits at <destination>.

        Only meaningful while no sorter is set; with one, the sorter
        decides the order and this would be undone at once.
        """
        count = self.store.get_n_items()
        if source == destination or not 0 <= source < count \
                or not 0 <= destination < count:
            return False
        item = cast(ThumbnailItem, self.store.get_item(source))
        self.store.remove(source)
        self.store.insert(destination, item)
        return True

    # -- Selection --------------------------------------------------------

    def get_selected_positions(self) -> list[int]:
        """Every selected position, lowest first."""
        selected = self.selection.get_selection()
        return [selected.get_nth(index)
                for index in range(selected.get_size())]

    def get_selected_items(self) -> list[ThumbnailItem]:
        """Every selected entry, in the order they are shown."""
        return [cast(ThumbnailItem, self.model.get_item(position))
                for position in self.get_selected_positions()]

    def select_only(self, position: int) -> None:
        """Make <position> the one selected entry."""
        self.selection.select_item(position, True)

    def unselect_all(self) -> None:
        self.selection.unselect_all()

    def remove_positions(self, positions: Iterable[int]) -> None:
        """Drop the entries shown at <positions>.

        The items are collected before any of them goes, because
        removing one moves everything after it.
        """
        self.remove_items([item for item in
                           (self.get_item(position) for position in positions)
                           if item is not None])

    def position_at(self, x: float, y: float) -> int:
        """The position of the entry under (<x>, <y>), or -1 if none is."""
        picked = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while picked is not None and not isinstance(picked, _ThumbnailCell):
            picked = picked.get_parent()
        if picked is None:
            return -1
        return picked.position

# vim: expandtab:sw=4:ts=4
