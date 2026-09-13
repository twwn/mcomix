"""canvas.py - The scrolling area the pages are laid out on."""

from collections.abc import Callable

from gi.repository import Gdk, GLib, GObject, Graphene, Gtk


class PageCanvas(Gtk.Widget):

    """A canvas children are placed on at a position of their own, and
    scrolled over by a pair of adjustments.

    This is what Gtk.Layout was up to GTK3, and GTK4 dropped it: nothing
    else replaces it here.  Gtk.Fixed keeps the positioning but has no
    adjustments; Gtk.ScrolledWindow owns its adjustments and scrolls by
    itself, while MComix drives its own scroll bars and does all of its
    scrolling by hand.
    """

    __gtype_name__ = 'MComixPageCanvas'

    __gsignals__ = {
        # The room the pages have to be drawn in has changed.  GTK4 has
        # no size-allocate signal to watch, and a window's default size
        # is what it asked for rather than what it was given, so the
        # canvas says so itself.
        'resized': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__()
        #: Children, as (widget, x, y) in the canvas' own coordinates.
        self._children: "list[tuple[Gtk.Widget, int, int]]" = []
        #: The size of the canvas, which is what the pages need rather
        #: than what is on screen.
        self._size = (0, 0)
        #: What draws over the pages, by name.
        self._overlays: dict[str, Callable[[Gtk.Snapshot], None]] = {}
        self._hadjustment = Gtk.Adjustment()
        self._vadjustment = Gtk.Adjustment()
        for adjustment in (self._hadjustment, self._vadjustment):
            adjustment.connect('value-changed', self._scrolled)
        #: Set while size_allocate() is configuring the adjustments, so
        #: that the value they emit does not ask for another allocation.
        self._allocating = False
        self._pointer: tuple[float, float] = (0.0, 0.0)
        #: The last size announced through 'resized'.
        self._allocated = (0, 0)
        # A page larger than the window must not be drawn over the rest
        # of it; the scrolling window Gtk.Layout drew into clipped it.
        self.set_overflow(Gtk.Overflow.HIDDEN)
        # Gtk.Layout.get_pointer() came from the same GdkWindow, which
        # GTK4 does not have; a controller is the way to ask now.
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._moved)
        self.add_controller(motion)

    def get_hadjustment(self) -> Gtk.Adjustment:
        return self._hadjustment

    def get_vadjustment(self) -> Gtk.Adjustment:
        return self._vadjustment

    def get_content_size(self) -> tuple[int, int]:
        """Return the size of the canvas, not of what is on screen.

        Not get_size(): Gtk.Widget has one of its own, which takes an
        orientation and answers with the allocation along it, so a
        canvas holding a 5000 pixel wide page would have said 5000 here
        and its own width there.
        """
        return self._size

    def set_content_size(self, width: int, height: int) -> None:
        """Set the size of the canvas, i.e. the range to scroll over."""
        if (width, height) == self._size:
            return
        self._size = (width, height)
        self.queue_allocate()

    def put(self, child: Gtk.Widget, x: int, y: int) -> None:
        """Place <child> on the canvas at (<x>, <y>)."""
        self._children.append((child, x, y))
        child.set_parent(self)
        self.queue_allocate()

    def move(self, child: Gtk.Widget, x: int, y: int) -> None:
        """Move <child>, already on the canvas, to (<x>, <y>)."""
        for index, (widget, at_x, at_y) in enumerate(self._children):
            if widget is child:
                if (at_x, at_y) != (x, y):
                    self._children[index] = (child, x, y)
                    self.queue_allocate()
                return
        raise ValueError('%r is not on the canvas' % (child,))

    def remove(self, child: Gtk.Widget) -> None:
        """Take <child> off the canvas."""
        for index, entry in enumerate(self._children):
            if entry[0] is child:
                del self._children[index]
                child.unparent()
                self.queue_allocate()
                return
        raise ValueError('%r is not on the canvas' % (child,))

    def set_overlay(self, name: str,
                    draw: "Callable[[Gtk.Snapshot], None] | None") -> None:
        """Draw over the pages with <draw>, or take an overlay away.

        <draw> is called with a Gtk.Snapshot, in canvas coordinates -
        the ones the OSD and the lens were drawing in when they had
        Gtk.Layout's scrolling window to draw onto.  Passing None for it
        takes the overlay called <name> away again.
        """
        if draw is None:
            if self._overlays.pop(name, None) is None:
                return
        else:
            self._overlays[name] = draw
        self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        # The pages themselves, as any widget draws its children.
        Gtk.Widget.do_snapshot(self, snapshot)
        if not self._overlays:
            return
        snapshot.save()
        snapshot.translate(Graphene.Point().init(
            -float(self._hadjustment.get_value()),
            -float(self._vadjustment.get_value())))
        for draw in list(self._overlays.values()):
            draw(snapshot)
        snapshot.restore()

    def get_pointer(self) -> tuple[float, float]:
        """Return where the pointer last was, in canvas coordinates."""
        return self._pointer

    def _moved(self, _controller: Gtk.EventControllerMotion, x: float,
               y: float) -> None:
        self._pointer = (x, y)

    def _scrolled(self, _adjustment: Gtk.Adjustment) -> None:
        if not self._allocating:
            self.queue_allocate()

    def do_measure(self, orientation: Gtk.Orientation,
                   for_size: int) -> tuple[int, int, int, int]:
        # Nothing, the way Gtk.Layout asked for nothing: the canvas is
        # whatever room is left over, and scrolls for the rest.
        return 0, 0, -1, -1

    def do_size_allocate(self, width: int, height: int,
                         baseline: int) -> None:
        if (width, height) != self._allocated:
            self._allocated = (width, height)
            # Not from inside the allocation itself: whoever listens is
            # going to want to lay the pages out again.
            GLib.idle_add(self._announce_resize)
        self._allocating = True
        try:
            self._configure(self._hadjustment, width, self._size[0])
            self._configure(self._vadjustment, height, self._size[1])
        finally:
            self._allocating = False
        x_offset = int(round(self._hadjustment.get_value()))
        y_offset = int(round(self._vadjustment.get_value()))
        allocation = Gdk.Rectangle()
        for child, x, y in self._children:
            request = child.get_preferred_size()[1]
            allocation.x = x - x_offset
            allocation.y = y - y_offset
            allocation.width = request.width
            allocation.height = request.height
            child.size_allocate(allocation, baseline)

    def _announce_resize(self) -> bool:
        self.emit('resized')
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _configure(adjustment: Gtk.Adjustment, viewport: int, content: int) -> None:
        # Gtk.Layout took the upper bound to be whichever of the canvas
        # and the window was larger, so that a page smaller than the
        # window leaves nothing to scroll; scroll() reads it back.
        upper = max(content, viewport)
        value = min(adjustment.get_value(), upper - viewport)
        adjustment.configure(max(0, value), 0, upper,
                             viewport * 0.1, viewport * 0.9, viewport)

    def do_dispose(self) -> None:
        # A GTK4 widget has to be rid of its children before it goes.
        for child, _x, _y in self._children:
            child.unparent()
        self._children = []
        # Gtk.Widget.do_dispose is put there by PyGObject for a widget
        # that overrides it, so the stubs do not describe it.
        Gtk.Widget.do_dispose(self)  # type: ignore[attr-defined]

# vim: expandtab:sw=4:ts=4
