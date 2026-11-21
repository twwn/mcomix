"""thumbnail_list.py - Thumbnails that are made as their rows come on screen."""

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Graphene, Gtk, Pango

from mcomix import image_tools
from mcomix import theme
from mcomix import tools
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix.worker_thread import WorkerThread

from collections.abc import Callable, Iterable, Iterator, Sequence
import bisect
import weakref
from typing import Any, cast


class ThumbnailItem(GObject.Object):

    """One entry of a thumbnail view.

    <uid> is whatever the view's generate_thumbnail() takes: a page
    number for the sidebar, a path or a book id elsewhere.  The
    thumbnail is a property rather than a plain attribute so that a row
    which is already on screen redraws itself when the worker thread
    that was making one finishes.  So is the badge drawn on it, which
    comes and goes without the thumbnail being made again.
    """

    __gtype_name__ = 'MComixThumbnailItem'

    thumbnail = GObject.Property(type=Gdk.Texture)
    badge = GObject.Property(type=Gdk.Texture)

    def __init__(self, uid: Any, label: str = '', tooltip: str = '') -> None:  # type: ignore[explicit-any]  # the view does not care what a uid is
        super().__init__()
        self.uid = uid
        #: How many of the screen's pixels the thumbnail has to each of
        #: the window's: the view's device_scale when it was made.
        self.scale = 1.0
        #: What the view writes beside or under the thumbnail.
        self.label = label
        #: What it says when the pointer rests on it.
        self.tooltip = tooltip


# pygobject-stubs declares props on GObject.Object and on the
# interface base with signatures that do not match.
class _Badged(GObject.Object, Gdk.Paintable):  # type: ignore[misc, unused-ignore]

    """A thumbnail with a badge hanging from its top edge, at the right.

    Drawn over the thumbnail rather than into it, so that the badge
    comes and goes without the thumbnail being made again.  A paintable
    rather than a widget laid over the cell: a thumbnail narrower than
    its cell is drawn in the middle of it, and the badge goes on the
    corner of the picture, not of the cell.
    """

    __gtype_name__ = 'MComixBadgedThumbnail'

    def __init__(self, thumbnail: Gdk.Paintable, badge: Gdk.Texture) -> None:
        super().__init__()
        self.thumbnail = thumbnail
        self.badge = badge

    def do_get_intrinsic_width(self) -> int:
        return self.thumbnail.get_intrinsic_width()

    def do_get_intrinsic_height(self) -> int:
        return self.thumbnail.get_intrinsic_height()

    def do_snapshot(self, snapshot: Gtk.Snapshot, width: float,
                    height: float) -> None:
        self.thumbnail.snapshot(snapshot, width, height)
        # Never more than a third of the picture's width, which only a
        # picture far wider than it is tall leaves it short of.
        scale = min(1.0, width / 3 / self.badge.get_width())
        badge_width = self.badge.get_width() * scale
        badge_height = self.badge.get_height() * scale
        snapshot.save()
        snapshot.translate(Graphene.Point().init(
            width - badge_width * 1.25, 0))
        self.badge.snapshot(snapshot, badge_width, badge_height)
        snapshot.restore()


def _shown(item: ThumbnailItem) -> Gdk.Paintable | None:
    """What a cell draws for <item>: its thumbnail, at the window's size
    whatever the screen's pixels it was made with, and its badge on it."""
    texture = cast("Gdk.Texture | None", item.thumbnail)
    if texture is None:
        return None
    thumbnail = widgets.at_scale(texture, item.scale)
    badge = cast("Gdk.Texture | None", item.badge)
    if badge is None:
        return thumbnail
    return _Badged(thumbnail, badge)


class _ThumbnailCell(Gtk.Box):

    """The widget one entry of a thumbnail view is built out of.

    A class of its own rather than a Gtk.Box with attributes set on it:
    PyGObject is free to drop the Python wrapper of a plain Gtk.Box that
    only GTK still holds, and to build a new one without them when the
    row comes back.
    """

    __gtype_name__ = 'MComixThumbnailCell'

    def __init__(self, orientation: Gtk.Orientation) -> None:
        super().__init__(orientation=orientation)
        self.label = Gtk.Label()
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.picture = Gtk.Picture()
        # Never larger than it is: a thumbnail is made at the size it is
        # shown at, and one smaller than that is a picture that small,
        # which CONTAIN blew up to fill the cell - a 3 by 3 page drawn
        # 27 times over.  A Gtk.TreeView drew it at its own size.
        self.picture.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        if orientation == Gtk.Orientation.HORIZONTAL:
            self.label.set_xalign(1.0)
            self.picture.set_hexpand(True)
            self.append(self.label)
            self.append(self.picture)
        else:
            self.picture.set_vexpand(True)
            self.append(self.picture)
            self.append(self.label)
        #: The handler of the item's notify while this cell is bound.
        self.handler: int | None = None
        #: The list item this cell is the child of, which is what knows
        #: where it sits.  Set once, when the cell is built: a list item
        #: keeps its child for as long as it has one.
        self.list_item: Gtk.ListItem | None = None

    @property
    def position(self) -> int:
        """Where this cell sits now, or -1 while it sits nowhere.

        Asked of the list item rather than remembered from the last
        bind, because GTK keeps a list item's position up to date as the
        model changes under it and a bind is not repeated for a cell
        that stays on screen.  The archive editor removes pages from the
        middle of the grid, so a remembered number would name whatever
        moved into that place: a right click landed on the entry that
        many places along, and so did a reordering drag.
        """
        return widgets.list_item_position(self.list_item)


class _ThumbnailViewBase(widgets.Releasable):

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
    #: Milliseconds refresh_soon() waits before it refreshes.
    REFRESH_DELAY = 50

    #: Built by the view classes below, which know which kind of
    #: selection they want.  <store> holds the entries; <model> is what
    #: the view shows, which is the store itself unless something sorts
    #: or filters it; <selection> wraps <model>.
    store: "Gio.ListStore[ThumbnailItem]"
    model: "Gio.ListModel[ThumbnailItem]"
    selection: Gtk.SelectionModel

    def _init_thumbnails(self) -> None:
        #: Replaced by whoever knows how to make a thumbnail for a uid.
        self.generate_thumbnail: "Callable[..., GdkPixbuf.Pixbuf | None] | None" = None  # type: ignore[explicit-any]  # the view does not care what a uid is
        #: Replaced by whoever can hand some thumbnails over at once:
        #: called on the main thread with an entry whose cell is being
        #: bound and that has no thumbnail, it answers with one only
        #: where that costs no more than a lookup, and None otherwise,
        #: which leaves the entry to generate_thumbnail().
        self.thumbnail_at_hand: "Callable[[ThumbnailItem], GdkPixbuf.Pixbuf | None] | None" = None
        #: Replaced by whoever marks some rows out: called with a cell's
        #: picture and the row it shows whenever the cell is bound, and
        #: by restyle().
        self.style_cell: "Callable[[Gtk.Picture, int], None] | None" = None
        #: How many of the screen's pixels there are to each of the
        #: window's, which an owner that makes thumbnails at that many
        #: sets; a thumbnail made then is drawn at 1/device_scale its
        #: size.  Read on the worker thread, so set it and then refresh.
        self.device_scale = 1.0
        #: The size a thumbnail is drawn at, and whether the label is
        #: drawn with it.  A cover is taller than it is wide, so the two
        #: are kept apart.
        self._thumbnail_width = 0
        self._thumbnail_height = 0
        self._labels_visible = False
        self._label_width = 0
        #: The items whose cells are on screen right now.
        self._bound: dict[ThumbnailItem, int] = {}
        #: The entries bound since the main loop last turned, whose
        #: thumbnails are to be asked for once it does.
        self._unasked: list[ThumbnailItem] = []
        #: The entries whose thumbnail is to be made again, which were
        #: off screen when that was asked or left it before it was done:
        #: they are asked for when they are next bound.
        self._stale: set[ThumbnailItem] = set()
        #: The entries whose thumbnail has been made and waits for the
        #: main loop to hand it over: out of the workers' queue, and not
        #: on the entry yet, so not to be asked for again.  The sidebar
        #: asks again for every row without one each time a page comes
        #: out of the archive, and made the same page up to ten times
        #: while a book was opened.
        self._coming: set[ThumbnailItem] = set()
        #: The timer refresh_soon() started, or None while none is
        #: pending.
        self._refresh_source: int | None = None
        #: Every cell the factory has built, on screen or kept aside
        #: for rows to come; release() needs the ones kept aside too.
        self._cells: "weakref.WeakSet[_ThumbnailCell]" = weakref.WeakSet()
        #: Ignore thumbnails that arrive after stop_update().
        self._updates_stopped = True
        self._thread = WorkerThread(self._thumbnail_worker,
                                    name='thumbview',
                                    unique_orders=True,
                                    narrow_first=True,
                                    max_threads=tools.thread_count(
                                        prefs['max threads']))
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
        cell.list_item = list_item
        self._cells.add(cell)
        self._size_cell(cell)
        self._decorate_cell(cell)
        list_item.set_child(cell)

    def _decorate_cell(self, cell: _ThumbnailCell) -> None:
        """Add whatever this view wants on every cell. Nothing, by default."""

    def _bind_cell(self, factory: Gtk.SignalListItemFactory,
                   list_item: Gtk.ListItem) -> None:
        """Show <list_item>'s thumbnail, and ask for it if it has none.

        A cell is bound when it comes on screen, so this is where the
        view says what has to be made, once the binding is over.
        """
        cell = cast(_ThumbnailCell, list_item.get_child())
        item = cast(ThumbnailItem, list_item.get_item())
        if (item.thumbnail is None and self.thumbnail_at_hand is not None
                and not self._updates_stopped):
            # Shown in the frame that shows the cell.  Asked for, it came
            # back from a worker a frame or more later, and every cell of
            # a collection drawn again was blank first.
            pixbuf = self.thumbnail_at_hand(item)
            if pixbuf is not None:
                # Before the thumbnail, as _thumbnail_finished() does.
                item.scale = self.device_scale
                item.thumbnail = image_tools.pixbuf_to_texture(pixbuf)
        cell.label.set_text(item.label)
        cell.set_tooltip_text(item.tooltip or None)
        cell.picture.set_paintable(_shown(item))
        # The thumbnail and the badge are the only properties there are.
        cell.handler = item.connect('notify', self._thumbnail_arrived, cell)
        self._bound[item] = list_item.get_position()
        if self.style_cell is not None:
            self.style_cell(cell.picture, list_item.get_position())
        if item.thumbnail is None or item in self._stale:
            self._ask_soon(item)

    def _ask_soon(self, item: ThumbnailItem) -> None:
        """Ask for <item>'s thumbnail once the cells being bound now have
        all been bound.

        GTK binds the cells of some thirty rows in one go on the main
        thread.  Asked for as each was bound, the first thumbnails were
        being made while the rest were still being bound, which the
        worker threads slowed, and those made waited for the binding to
        end to be shown: the first covers of the library came up in
        twice the time.
        """
        if not self._unasked:
            GLib.idle_add(self._ask_for_unasked)
        self._unasked.append(item)

    def _ask_for_unasked(self) -> bool:
        """Ask for the thumbnails of the cells bound since the main loop
        last turned: those on screen first, then the others, nearest
        first.

        GTK binds some thirty rows for the few on screen, and after a
        jump to another part of a long list it binds the rows on screen
        last.  Asked for in the order bound, behind what the cells bound
        before were still waiting for, the covers in view of a library
        scrolled on while its first covers were read came after 900
        others.

        What is still waiting is therefore taken back and sorted in with
        the rest, and left out where its cell has gone.  In one go, not
        as each cell is unbound: with the workers busy, every turn the
        main thread takes at their queue is one it waits for.
        """
        unasked, self._unasked = self._unasked, []
        if self.generate_thumbnail is None or self._updates_stopped:
            return GLib.SOURCE_REMOVE
        wanted: dict[ThumbnailItem, None] = {}
        for item in self._thread.clear_orders():
            if item in self._bound:
                wanted[item] = None
            elif item.thumbnail is not None:
                # It was to be made again: when it is next bound, then.
                self._stale.add(item)
        for item in unasked:
            # Not one that went off screen meanwhile, or whose thumbnail
            # came by another way.
            if item in self._bound and (item in self._stale or (
                    item.thumbnail is None and item not in self._coming)):
                wanted[item] = None
        first, last = self._positions_on_screen()
        bound = self._bound
        # A stable sort: what is as far away stays in the order asked.
        ordered = sorted(wanted, key=lambda item: max(
            first - bound[item], bound[item] - last, 0))
        self._stale.difference_update(ordered)
        self._thread.extend_orders(ordered)
        return GLib.SOURCE_REMOVE

    def _positions_on_screen(self) -> tuple[float, float]:
        """The first and the last position on screen, about: the share
        of the list the scroll bar shows, taken of its entries, which is
        exact where every row is as high as the next.  Where nothing has
        been laid out yet, every position."""
        count = self.model.get_n_items()
        adjustment = cast(Gtk.Scrollable, self).get_vadjustment()
        if adjustment is None:
            return 0, count
        start = adjustment.get_lower()
        length = adjustment.get_upper() - start
        if length <= 0:
            return 0, count
        top = adjustment.get_value() - start
        return (count * top / length,
                count * (top + adjustment.get_page_size()) / length)

    def restyle(self) -> None:
        """Call style_cell() again for every cell on screen, after what it
        marks out has changed."""
        if self.style_cell is None:
            return
        for cell in self._each_cell():
            position = cell.position
            if position >= 0:
                self.style_cell(cell.picture, position)

    def _unbind_cell(self, factory: Gtk.SignalListItemFactory,
                     list_item: Gtk.ListItem) -> None:
        """Let go of the item a cell off the screen was showing."""
        cell = cast(_ThumbnailCell, list_item.get_child())
        item = cast(ThumbnailItem, list_item.get_item())
        if cell.handler is not None:
            item.disconnect(cell.handler)
            cell.handler = None
        self._bound.pop(item, None)
        cell.picture.set_paintable(None)

    def _thumbnail_arrived(self, item: ThumbnailItem,
                           parameter: GObject.ParamSpec,
                           cell: _ThumbnailCell) -> None:
        cell.picture.set_paintable(_shown(item))

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
        and 1.  A view built from widgets says it in CSS.
        """
        widget = cast(Gtk.Widget, self)
        provider = self._colour_provider
        if provider is None:
            provider = self._colour_provider = Gtk.CssProvider()
            widget.add_css_class(self.CSS_CLASS)
            Gtk.StyleContext.add_provider_for_display(
                widget.get_display(), provider, theme.VIEW_COLOUR_PRIORITY)
        provider.load_from_string(
            '.%(name)s, .%(name)s > child, .%(name)s > row'
            ' { background: %(background)s; color: %(text)s; }'
            % {'name': self.CSS_CLASS,
               'background': image_tools.rgba(*colour).to_string(),
               'text': text_colour.to_string()})

    # -- The entries themselves -------------------------------------------

    def set_items(self, items: Iterable[ThumbnailItem]) -> None:
        """Show <items>, replacing whatever was there.

        The thumbnails still waiting to be made go with the entries they
        were for.  One being made is not waited for: this runs on the
        main thread, for every letter typed in the library's search box,
        and a cover deep in a solid archive takes seconds.  It finishes
        on an entry that is no longer shown, and its worker then turns
        to the new ones.
        """
        items = list(items)
        waiting = self._thread.clear_orders()
        # An entry shown again may still be due to be made again.
        self._stale.intersection_update(items)
        # Before the splice, not after it: the cells that fit on screen
        # are bound from inside it, and a stopped view turns away every
        # thumbnail those cells ask for.
        self._updates_stopped = False
        self.store.splice(0, self.store.get_n_items(), items)
        # An entry that was on show before and is again keeps its cell,
        # and GTK does not bind it again: what it was waiting for is
        # asked for here, and its place is read anew.
        for cell in self._each_cell():
            if cell.list_item is None:
                continue
            shown = cell.list_item.get_item()
            if isinstance(shown, ThumbnailItem) and shown in self._bound:
                self._bound[shown] = cell.position
        again = [item for item in waiting if item in self._bound]
        if again and self.generate_thumbnail is not None:
            self._thread.extend_orders(again)

    def append_item(self, item: ThumbnailItem) -> None:
        """Add one entry to the end."""
        self._updates_stopped = False
        self.store.append(item)

    def clear(self) -> None:
        """Drop every entry."""
        self.stop_update()
        self._bound.clear()
        self._stale.clear()
        self.store.remove_all()

    def stop_update(self) -> None:
        """Stop making thumbnails, and ignore the ones still coming."""
        self._updates_stopped = True
        self._cancel_refresh()
        self._thread.stop()

    def retire(self) -> None:
        """Stop making thumbnails for good, and ignore the ones still
        coming, without waiting for the one being made.

        For a view whose thumbnails come from something that outlives
        it, such as the library's covers, which the library backend
        reads: the read in flight ends on its own.
        """
        self._updates_stopped = True
        self._cancel_refresh()
        self._thread.retire()

    def release(self) -> None:
        """Stop, unbind every cell and drop the factory, once the window
        is closed.

        The factory's handlers are this view's own methods, and each
        bound entry holds a handler of this view's as well; GTK holds
        both, so the view kept itself, its thumbnails and whatever
        carries it alive after the window had gone.
        """
        self.stop_update()
        view = cast("Gtk.ListView | Gtk.GridView", self)
        view.set_model(None)
        view.set_factory(None)
        for cell in list(self._cells):
            widgets.cut_handlers(cell)

    def position_at(self, x: float, y: float) -> int:
        """The position of the entry under (<x>, <y>), or -1 if none is."""
        picked = cast(Gtk.Widget, self).pick(x, y, Gtk.PickFlags.DEFAULT)
        while picked is not None and not isinstance(picked, _ThumbnailCell):
            picked = picked.get_parent()
        if picked is None:
            return -1
        return picked.position

    def refresh(self) -> None:
        """Ask again for the thumbnails the cells on screen are missing.

        A page that has not been extracted yet answers with nothing, so
        the cells showing it have to be asked again once it has been.
        Only the bound cells are asked: those are the ones on screen.
        """
        self._updates_stopped = False
        for item in tuple(self._bound):
            if item.thumbnail is None and item not in self._coming:
                self._ask_for(item)

    def refresh_soon(self) -> None:
        """refresh() in REFRESH_DELAY milliseconds, once however often
        this is called meanwhile.

        For a page let out of the archive: a book lets out hundreds a
        second, and every refresh hands the worker threads an order for
        each empty row on screen, nearly all of them for pages still in
        the archive.  One refresh per page kept the main thread busy
        for over a second opening a 200-page book.  stop_update() drops
        a refresh still to come.
        """
        if self._refresh_source is None:
            self._refresh_source = GLib.timeout_add(
                self.REFRESH_DELAY, self._refresh_now)

    def _refresh_now(self) -> bool:
        self._refresh_source = None
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _cancel_refresh(self) -> None:
        if self._refresh_source is not None:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = None

    def _ask_for(self, item: ThumbnailItem) -> None:
        if self.generate_thumbnail is None or self._updates_stopped:
            return
        with self._thread:
            self._thread.append_order(item)

    def _thumbnail_worker(self, item: ThumbnailItem) -> None:
        """Run by a worker thread to make one thumbnail."""
        generate = self.generate_thumbnail
        # The scale the owner's generate_thumbnail() reads as well.
        scale = self.device_scale
        pixbuf = generate(item.uid) if generate is not None else None
        if pixbuf is not None:
            # Before the worker gives the order up: until then the queue
            # turns away the same order.
            self._coming.add(item)
            GLib.idle_add(self._thumbnail_finished, item, pixbuf, scale)

    def _thumbnail_finished(self, item: ThumbnailItem,
                            pixbuf: GdkPixbuf.Pixbuf,
                            scale: float = 1.0) -> bool:
        self._coming.discard(item)
        if not self._updates_stopped:
            # Before the thumbnail, whose notification redraws the cell.
            item.scale = scale
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

    def refresh_item(self, item: ThumbnailItem) -> None:
        """Draw <item> again, whatever has changed about it.

        A cell reads the entry when it is bound, so a label or a
        tooltip that changes afterwards is not shown until the store
        says the entry has: this is that word.
        """
        found, position = self.store.find(item)
        if found:
            self.store.items_changed(position, 1, 1)

    def redraw_item(self, item: ThumbnailItem) -> None:
        """Make <item>'s thumbnail again, after something drawn on it
        has changed.  The one on screen stays until the new one comes;
        one that is not on screen is made when it next is."""
        if item in self._bound:
            self._stale.discard(item)
            self._ask_for(item)
        elif item.thumbnail is not None:
            self._stale.add(item)

    def remove_items(self, items: Iterable[ThumbnailItem]) -> None:
        """Drop <items>, wherever the store happens to hold them."""
        for item in items:
            self._stale.discard(item)
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
        #: Replaced by whoever decides that a page is not to be listed.
        self.is_hidden: "Callable[[int], bool] | None" = None
        # Nothing sorts the pages: they are shown in the order they are
        # held, less those is_hidden() leaves out.
        self._filter = Gtk.CustomFilter.new(self._is_shown)
        self.model = Gtk.FilterListModel(model=self.store,
                                         filter=self._filter)
        self.selection = Gtk.SingleSelection(model=self.model)
        # A page is selected because the viewer moved to it, so the list
        # must be able to start with nothing selected and to follow the
        # page rather than lead it.
        self.selection.set_autoselect(False)
        self.selection.set_can_unselect(True)
        _ThumbnailViewBase._init_thumbnails(self)
        super().__init__(model=self.selection, factory=self._make_factory())

    def release(self) -> None:
        _ThumbnailViewBase.release(self)
        # The filter holds this view's method in C, and the model the
        # view keeps holds the filter.
        self._filter.set_filter_func(None)

    def set_pages(self, uids: Iterable[int]) -> None:
        """Show one row per page number in <uids>, which ascend."""
        self.set_items(ThumbnailItem(uid, label=str(uid)) for uid in uids)

    def _is_shown(self, item: GObject.Object) -> bool:
        uid = cast(ThumbnailItem, item).uid
        return self.is_hidden is None or not self.is_hidden(uid)

    def refilter(self) -> None:
        """Ask is_hidden() again about every page, after its answer
        has changed."""
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def row_of(self, uid: int) -> int | None:
        """The row page <uid> is shown in, or None where it is not."""
        rows = self.model.get_n_items()
        row = bisect.bisect_left(
            range(rows), uid,
            key=lambda position: cast(ThumbnailItem,
                                      self.model.get_item(position)).uid)
        if row < rows and self.page_at(row) == uid:
            return row
        return None

    def page_at(self, row: int) -> int | None:
        """The page shown in <row>, or None if there is no such row."""
        item = self.get_item(row)
        return None if item is None else cast(int, item.uid)

    def set_page_numbers_visible(self, visible: bool, digits: int = 0) -> None:
        """Show or hide the page number beside each thumbnail."""
        self.set_labels_visible(visible, digits + 1 if digits else 0)

    def get_selected_row(self) -> int:
        """The row that is selected, or 0 if none is."""
        position = self.selection.get_selected()
        if position == Gtk.INVALID_LIST_POSITION:
            return 0
        return position

    def select_row(self, row: int | None, scroll: bool = True) -> None:
        """Select <row>, scrolling it into view unless told not to;
        None selects nothing."""
        if row is None:
            self.selection.set_selected(Gtk.INVALID_LIST_POSITION)
            return
        if not 0 <= row < self.model.get_n_items():
            return
        self.selection.set_selected(row)
        if scroll:
            self.scroll_to(row, Gtk.ListScrollFlags.NONE, None)


#: The most columns a grid of thumbnails lays its cells out in.
_MOST_COLUMNS = 64


class ThumbnailGridView(Gtk.GridView, _ThumbnailViewBase, widgets.Selecting,
                        widgets.DragReorderable):

    """A grid of thumbnails, as the library and the archive editor show.

    This is what a Gtk.IconView was.  Selecting more than one is the
    Gtk.MultiSelection the model is wrapped in; reordering by dragging,
    which Gtk.IconView did for itself, is set_reorderable() below.
    """

    CELL_ORIENTATION = Gtk.Orientation.VERTICAL
    CSS_CLASS = 'mcomix-thumbnail-grid'

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
        #: Called just before a drag moves an entry, for whoever wants
        #: to remember the order it was in.  The archive editor does,
        #: for its undo.
        self.about_to_reorder: "Callable[[], None] | None" = None
        super().__init__(model=self.selection, factory=self._make_factory())
        # One until the view knows how wide it and its cells are: see
        # do_size_allocate().
        self.set_max_columns(1)

    def do_size_allocate(self, width: int, height: int,
                         baseline: int) -> None:
        """Lay the cells out <width> wide, in as many columns as fit.

        GTK keeps a cell for every entry in some thirty rows of the
        most columns the view may have, on screen or not, and binds
        each: with that left at 64, a library of a thousand books had
        all its covers built and asked for at once, where twenty fit
        in the window.  The most columns is therefore what the width
        holds, and one more, which GTK then lays out as it would have.
        """
        self._fit_columns(width)
        Gtk.GridView.do_size_allocate(self, width, height, baseline)

    def _fit_columns(self, width: int) -> None:
        """Let the view have as many columns as <width> holds cells,
        the cells as wide as the narrowest GTK lays one out."""
        cell = next(self._each_cell(), None)
        if cell is None:
            # Nothing to measure yet: whatever is bound before the
            # view is laid out is one column's worth.
            return
        child = cell.get_parent()
        assert child is not None
        least = child.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        columns = min(_MOST_COLUMNS, width // max(1, least) + 1)
        if columns != self.get_max_columns():
            self.set_max_columns(columns)

    def set_sorter(self, sorter: "Gtk.Sorter | None") -> None:
        """Show the entries in the order <sorter> puts them in.

        None shows them in the order they were added, which is what the
        archive editor wants: there, the order *is* the thing being
        edited.
        """
        self._sort_model.set_sorter(sorter)

    # -- Reordering -------------------------------------------------------

    def _decorate_cell(self, cell: _ThumbnailCell) -> None:
        source = self._add_reorder_controllers(cell)
        if source is not None:
            source.connect('drag-begin', self._reorder_begin, cell)

    def _move_dragged(self, source: int, destination: int) -> bool:
        return self.move_item(source, destination)

    def _reorder_begin(self, source: Gtk.DragSource, drag: Gdk.Drag,
                       cell: _ThumbnailCell) -> None:
        paintable = cell.picture.get_paintable()
        if paintable is not None:
            source.set_icon(paintable, 0, 0)

    def move_item(self, source: int, destination: int) -> bool:
        """Move the entry at <source> so that it sits at <destination>.

        Only meaningful while no sorter is set; with one, the sorter
        decides the order and this would be undone at once.
        """
        count = self.store.get_n_items()
        if source == destination or not 0 <= source < count \
                or not 0 <= destination < count:
            return False
        if self.about_to_reorder is not None:
            self.about_to_reorder()
        item = cast(ThumbnailItem, self.store.get_item(source))
        # The entry that was dragged or clicked holds the keyboard focus,
        # and taking the focused entry out of the model makes GTK focus
        # another and scroll the view to it when it next lays the view
        # out - to the first entry, as often as not.  So the focus is
        # let go of first, and nothing scrolls: the reader dropped the
        # entry on a row they could see.  Once the view has been laid
        # out again, the entry where it has landed gets the focus back.
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        had_focus = focus is not None and focus.is_ancestor(self)
        if had_focus and root is not None:
            root.set_focus(None)
        self.store.remove(source)
        self.store.insert(destination, item)
        if had_focus:
            self._focus_after_layout(item)
        return True

    def _focus_after_layout(self, item: ThumbnailItem) -> None:
        """Give <item> the focus once the view has been laid out again.

        Not from the idle queue: an idle can run before the next frame
        lays the view out, and the cell it focuses is then one that has
        not been moved to where it will be drawn yet - GTK scrolls a row
        up or down to show it.  After the frame has been painted, the
        cells are where the reader sees them.
        """
        clock = self.get_frame_clock()
        if clock is None:
            # Not on screen, so there is no layout to wait for.
            GLib.idle_add(self._focus_entry, item)
            return
        handler = 0

        def painted(clock: Gdk.FrameClock) -> None:
            clock.disconnect(handler)
            self._focus_entry(item)

        handler = clock.connect('after-paint', painted)
        clock.request_phase(Gdk.FrameClockPhase.LAYOUT)

    def _focus_entry(self, item: ThumbnailItem) -> bool:
        """Give the keyboard focus to the cell showing <item>, if one is."""
        for cell in self._each_cell():
            parent = cell.get_parent()
            if (parent is not None and 0 <= cell.position
                    < self.store.get_n_items()
                    and self.store.get_item(cell.position) is item):
                parent.grab_focus()
                break
        return GLib.SOURCE_REMOVE

    # -- Selection --------------------------------------------------------

    def get_selected_items(self) -> list[ThumbnailItem]:
        """Every selected entry, in the order they are shown."""
        return [cast(ThumbnailItem, self.model.get_item(position))
                for position in self.get_selected_positions()]

    def select_positions(self, positions: Iterable[int]) -> None:
        """Select <positions> and nothing else."""
        self.selection.unselect_all()
        for position in positions:
            self.selection.select_item(position, False)

    def select_all(self) -> None:
        self.selection.select_all()

    def remove_positions(self, positions: Iterable[int]) -> None:
        """Drop the entries shown at <positions>.

        The items are collected before any of them goes, because
        removing one moves everything after it.
        """
        self.remove_items([item for item in
                           (self.get_item(position) for position in positions)
                           if item is not None])

# vim: expandtab:sw=4:ts=4
