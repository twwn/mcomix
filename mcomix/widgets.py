"""widgets.py - Small helpers for widgets whose API changed in GTK4."""

import weakref

from gi.repository import Gdk, Gio, GLib, GObject, Graphene, Gtk

from collections.abc import Callable, Iterable, Iterator
from typing import cast


class Chooser[V](Gtk.DropDown):

    """One of a fixed set of values, picked from a dropdown.

    This is what a Gtk.ComboBox over a two-column Gtk.ListStore was,
    both of which GTK deprecated in 4.10 along with the
    Gtk.CellRendererText that drew the labels.  The store held the label
    in one column and the value in another, and every caller had to walk
    a Gtk.TreeIter to read the value back; the labels are a
    Gtk.StringList here and the values a plain Python list beside it.
    """

    __gtype_name__ = 'MComixChooser'

    def __init__(self, options: "Iterable[tuple[str, V]]",
                 chosen: "V | None" = None) -> None:
        """Offer <options>, pairs of label and value, with <chosen> set.

        A value is whatever the preference behind the chooser holds - a
        number, a string, an enumeration member - so the labels are the
        only half of a pair with a type of its own.
        """
        labels = Gtk.StringList()
        self._values: list[V] = []
        for label, value in options:
            labels.append(label)
            self._values.append(value)
        if not self._values:
            raise ValueError('a chooser must have something to choose from')
        super().__init__(model=labels)
        self.set_value(chosen)

    def get_value(self) -> V:
        """The value that is picked.

        A Gtk.DropDown shows one of its options unless it is told to show
        none, which nothing here does, and the constructor above refuses
        a chooser with nothing to offer: there is always an answer.
        """
        position = self.get_selected()
        if position == Gtk.INVALID_LIST_POSITION:
            raise ValueError('nothing is picked')
        return self._values[position]

    def set_value(self, value: "V | None") -> None:
        """Pick <value>.

        A Gtk.DropDown always shows one of its options, where a
        Gtk.ComboBox could show none of them, so a value that is not on
        offer leaves the first option showing rather than an empty box -
        and the preference it came from is left alone until the user
        picks something.
        """
        if value in self._values:
            self.set_selected(self._values.index(value))

    def connect_changed(self,
                        changed: 'Callable[["Chooser[V]"], None]') -> None:
        """Call <changed> with this chooser whenever the pick changes."""
        self.connect('notify::selected',
                     lambda widget, _param: changed(widget))


# pygobject-stubs declares props on GObject.Object and on the
# interface base with signatures that do not match.
class ScaledTexture(GObject.Object, Gdk.Paintable):  # type: ignore[misc, unused-ignore]

    """A picture made with the screen's pixels, where there are more of
    them than the window's, drawn at the window's size: GTK draws a
    texture one of its pixels to one of the window's, so a picture made
    for the window alone was enlarged and blurred."""

    __gtype_name__ = 'MComixScaledTexture'

    def __init__(self, texture: Gdk.Texture, scale: float) -> None:
        super().__init__()
        self.texture = texture
        self._width = max(1, round(texture.get_width() / scale))
        self._height = max(1, round(texture.get_height() / scale))

    def do_get_intrinsic_width(self) -> int:
        return self._width

    def do_get_intrinsic_height(self) -> int:
        return self._height

    def do_snapshot(self, snapshot: Gtk.Snapshot, width: float,
                    height: float) -> None:
        self.texture.snapshot(snapshot, width, height)


def at_scale(texture: Gdk.Texture, scale: float) -> Gdk.Paintable:
    """<texture>, made with <scale> of the screen's pixels to each of the
    window's, as a paintable of the size it is to be shown at."""
    return texture if scale == 1 else ScaledTexture(texture, scale)


def pack(box: Gtk.Box, child: Gtk.Widget, expand: bool = False,
         fill: bool = True, padding: int = 0) -> None:
    """Add <child> after what <box> holds, the way Gtk.Box.pack_start did.

    GTK4 boxes only append and prepend.  What the old arguments said is
    now said by the child: whether it takes the slack is hexpand or
    vexpand depending on which way the box runs, not filling its share is
    an alignment, and padding is a margin on the two ends that matter.
    Children come in the order they are packed: one meant to sit at the
    far end is packed last, after a sibling that takes the slack.
    """
    if expand:
        if box.get_orientation() == Gtk.Orientation.HORIZONTAL:
            child.set_hexpand(True)
        else:
            child.set_vexpand(True)
    if not fill:
        if box.get_orientation() == Gtk.Orientation.HORIZONTAL:
            child.set_halign(Gtk.Align.CENTER)
        else:
            child.set_valign(Gtk.Align.CENTER)
    if padding:
        if box.get_orientation() == Gtk.Orientation.HORIZONTAL:
            child.set_margin_start(padding)
            child.set_margin_end(padding)
        else:
            child.set_margin_top(padding)
            child.set_margin_bottom(padding)
    box.append(child)


def empty(box: Gtk.Box) -> None:
    """Take everything out of <box>.

    Gtk.Container.foreach() is gone in GTK4 and a box has no
    remove_all(): it hands out its children one at a time, and taking
    one out is what makes the next one first.
    """
    child = box.get_first_child()
    while child is not None:
        box.remove(child)
        child = box.get_first_child()


def set_border(widget: Gtk.Widget, width: int) -> None:
    """Put <width> pixels of space around what <widget> holds.

    Gtk.Container.set_border_width() is gone in GTK4; the space around a
    widget is the widget's own margin there.  A window is the exception:
    its margins fall outside the part of its surface that it paints, so
    they come out as a transparent strip along the edges rather than as
    a border - the space has to go around what it holds instead.
    """
    if isinstance(widget, Gtk.Window):
        held = widget.get_child()
        if held is None:
            return
        widget = held
    widget.set_margin_top(width)
    widget.set_margin_bottom(width)
    widget.set_margin_start(width)
    widget.set_margin_end(width)


def chooser_paths(chooser: Gtk.FileChooser) -> list[str]:
    """The paths of the files selected in <chooser>.

    Gtk.FileChooser.get_filenames() is gone in GTK4; get_files() answers
    with a Gio.ListModel of Gio.Files instead.
    """
    files = chooser.get_files()
    paths = []
    for index in range(files.get_n_items()):
        path = cast(Gio.File, files.get_item(index)).get_path()
        if path is not None:
            paths.append(path)
    return paths


def chooser_folder(chooser: Gtk.FileChooser) -> "str | None":
    """The path of the folder <chooser> is showing, if it is local."""
    folder = chooser.get_current_folder()
    return folder.get_path() if folder is not None else None


def set_chooser_folder(chooser: Gtk.FileChooser, path: str) -> None:
    """Show <path> in <chooser>; GTK4 takes a Gio.File, not a name."""
    chooser.set_current_folder(Gio.File.new_for_path(path))


def set_chooser_file(chooser: Gtk.FileChooser, path: str) -> None:
    """Select <path> in <chooser>; set_filename() is gone in GTK4."""
    chooser.set_file(Gio.File.new_for_path(path))


#: The popovers popup_at() has parented, which release() takes off
#: their widgets again.  Weak, so that a popover nothing else holds is
#: nothing this keeps alive.
_parented: "weakref.WeakSet[Gtk.Popover]" = weakref.WeakSet()


def popup_at(popover: Gtk.Popover, widget: Gtk.Widget,
             x: float, y: float) -> None:
    """Show <popover> over <widget>, pointing at (<x>, <y>) within it.

    A Gtk.Menu was popped up at the pointer with an event; a
    Gtk.PopoverMenu is parented to a widget and pointed at a rectangle
    in *that* widget's coordinates, which is not always <widget> - the
    main window's popup is parented to the window and pointed at by the
    layout area inside it - so the point is translated.

    A popover is centred over what it points at and put above it, which
    is right for a bubble and wrong for a menu: it opened with the
    pointer in the middle of it.  RIGHT with its top at the point puts
    its corner where the pointer is, which is where a menu goes.  Not
    BOTTOM, which did the same: GTK lets a popover below its point flip
    above it but not slide, so a menu taller than the room on either
    side of the pointer was cut to the room below and scrolled, however
    much room the screen had.  Beside the point it slides up as far as
    it has to, and flips to the left at the screen's right edge.

    It opens from an idle: GTK adds the lines between a menu's sections
    from an idle of its own, after a menu was built or items were hidden
    or shown, and a menu that opened before them was measured without
    them and scrolled by as much.
    """
    parent = popover.get_parent()
    if parent is None:
        parent = widget
        popover.set_parent(parent)
        _parented.add(popover)
    if widget is not parent:
        found, point = widget.compute_point(parent, Graphene.Point().init(x, y))
        if found:
            x, y = point.x, point.y
    area = Gdk.Rectangle()
    area.x, area.y, area.width, area.height = int(x), int(y), 1, 1
    popover.set_pointing_to(area)
    popover.set_has_arrow(False)
    popover.set_valign(Gtk.Align.START)
    popover.set_position(Gtk.PositionType.RIGHT)

    def open_now() -> bool:
        if popover.get_parent() is not None:
            popover.popup()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(open_now, priority=GLib.PRIORITY_DEFAULT_IDLE + 10)


def focus_where_scrolled(view: Gtk.Widget) -> None:
    """Give the keyboard focus to the entry <view>, a list or a grid,
    was just told to scroll_to() with Gtk.ListScrollFlags.FOCUS, where
    GTK left it behind.

    GTK moves the focus there only in a list it finds with the focus
    within, a state it sets only while the window is the active one; in
    any other window it moves no more than its own note of where the
    focus is to go.  A right click on a window not yet active selected
    one entry and left the focus on another, and Enter afterwards opened
    that other one.  A list grabbing the focus gives it to the entry so
    noted, which is the one scrolled to.  Only where the list has its
    window's focus: elsewhere, as GTK does, it leaves the focus alone.
    """
    if view.get_state_flags() & Gtk.StateFlags.FOCUS_WITHIN:
        return
    root = view.get_root()
    focus = root.get_focus() if root is not None else None
    if focus is not None and (focus is view or focus.is_ancestor(view)):
        view.grab_focus()


def list_item_position(list_item: Gtk.ListItem | None) -> int:
    """Where <list_item> sits in its list now, or -1 while it sits
    nowhere: not yet bound, or unbound."""
    if list_item is None:
        return -1
    position = list_item.get_position()
    if position == Gtk.INVALID_LIST_POSITION:
        return -1
    return position


def menu_key(keyval: int, state: Gdk.ModifierType) -> bool:
    """Whether a key press is the one that asks for a context menu.

    A GTK3 widget was told by its popup-menu signal, which GTK emitted
    for the menu key and for Shift+F10 alike; a GTK4 widget has no such
    signal and hears the key itself.  Both keys are what GTK's own
    widgets bind their menus to, and Shift+F10 is the only way in on a
    keyboard without a menu key.
    """
    modifiers = state & Gtk.accelerator_get_default_mod_mask()
    if keyval == Gdk.KEY_Menu:
        return not modifiers
    return (keyval == Gdk.KEY_F10
            and modifiers == Gdk.ModifierType.SHIFT_MASK)


def display() -> Gdk.Display:
    """The display MComix is running on.

    Gdk.Display.get_default() answers with None before one has been
    opened, and a clipboard, an icon theme, a monitor and a style
    provider all belong to a display in GTK4, so every caller here needs
    a real one rather than a check it cannot carry on from.
    """
    opened = Gdk.Display.get_default()
    if opened is None:
        raise RuntimeError('MComix is running without a display.')
    return opened


def menu_label(text: str) -> str:
    """<text> as a menu item's label, with nothing read as a mnemonic.

    GTK builds every item of a Gio.Menu with use-underline set, so an
    underscore in a name that came from outside - a file name, a
    bookmark, a label the user typed - is swallowed and the letter after
    it underlined instead.  A label MComix writes itself says where its
    mnemonic goes; a name it was handed has none to find.

    Gtk.MenuItem, which GTK4 removes, took a plain label and showed the
    underscore, so nothing needed this before the menus became models.
    """
    return text.replace('_', '__')


def menu_item(label: str, action: str, accelerator: str | None = None,
              target: GLib.Variant | None = None) -> Gio.MenuItem:
    """A Gio.MenuItem for <action>, with <target> as its parameter where
    one is given, under <label>, showing <accelerator> beside it where one
    is given.  The accel attribute only shows the key; what answers it is
    the keybinding manager or a shortcut controller."""
    item = Gio.MenuItem.new(label, None)
    item.set_action_and_target_value(action, target)
    if accelerator:
        item.set_attribute_value('accel', GLib.Variant('s', accelerator))
    return item


class _MenuClickGesture(Gtk.GestureClick):

    """What watch_menu_clicks() leaves on a popover.

    A type of its own so that a popover already being watched can be
    told from one that is not: GTK hands out the controllers a widget
    carries, and there is nowhere on a widget to leave a note.
    """

    __gtype_name__ = 'MComixMenuClickGesture'


#: Whether the menu press GTK is acting on was the middle button.  Read
#: it through take_middle_click(); watch_menu_clicks() sets it.
_middle_click = False


def _menu_popovers(root: Gtk.Widget) -> Iterator[Gtk.PopoverMenu]:
    """Every menu popover in <root>'s widget tree, <root> included."""
    for widget in (root, *_descendants(root)):
        if isinstance(widget, Gtk.PopoverMenu):
            yield widget


def _descendants(root: Gtk.Widget) -> Iterator[Gtk.Widget]:
    """Every widget in <root>'s widget tree, <root> left out."""
    child = root.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def _released(root: Gtk.Widget) -> Iterator[Gtk.Widget]:
    """The widgets in <root>'s tree that release() goes through.

    Everything but the insides of a menu: a Gtk.PopoverMenu or menu bar
    is built by GTK from its model, item by item, and MComix connects
    nothing there but the gestures watch_menu_clicks() adds, whose
    handler refers to nothing.  The main window's menus are 1,000 of its
    1,090 widgets and 1,500 of its 1,630 controllers, and going through
    them took 10 ms each time a window closed.
    """
    child = root.get_first_child()
    while child is not None:
        yield child
        if not isinstance(child, (Gtk.PopoverMenu, Gtk.PopoverMenuBar)):
            yield from _released(child)
        child = child.get_next_sibling()


class Timer:

    """One wait on the main loop at a time, for what hides itself or
    clears away a while after it was shown.

    start() drops a wait still under way, so that the delay counts from
    the last call, and <done> is called once it has gone by.  The wait
    is over by then, and <done> may start another.  stop() drops it, as
    a window that closes has to: GLib holds the wait, and through it
    <done> and whoever made the timer.
    """

    def __init__(self, done: Callable[[], object]) -> None:
        self._done = done
        self._source: int | None = None

    @property
    def running(self) -> bool:
        """Whether a wait is under way."""
        return self._source is not None

    def start(self, milliseconds: int) -> None:
        """Call <done> <milliseconds> from now, and not before then.

        A delay of 0 or less starts no wait at all: what it would have
        ended stays, as "pointer hide delay" at 0 keeps the pointer.
        """
        self.stop()
        if milliseconds > 0:
            self._source = GLib.timeout_add(milliseconds, self._time_up)

    def stop(self) -> None:
        """Drop the wait under way, if there is one."""
        if self._source is not None:
            GLib.source_remove(self._source)
            self._source = None

    def _time_up(self) -> bool:
        self._source = None
        self._done()
        return GLib.SOURCE_REMOVE


class Releasable:

    """A widget that holds more than its handlers of whoever built it.

    release() below hands every one of these in a closed window's tree
    to its release(), which lets go of the rest: the closures a list
    view's factories and sorters hold, the cells still bound to rows.
    """

    def release(self) -> None:
        """Let go of everything that would keep the closed window alive."""


class Selecting:

    """A list, grid or column view whose items are picked out through
    <selection>, the selection model it shows.

    It comes before the Gtk class in the bases, so that a method of
    the same name a later GTK adds does not take the place of its own.
    """

    selection: Gtk.SelectionModel

    def get_selected_positions(self) -> list[int]:
        """Where the selected items are shown, lowest first."""
        selected = self.selection.get_selection()
        return [selected.get_nth(index)
                for index in range(selected.get_size())]

    def select_only(self, position: int) -> None:
        """Select the item at <position> and nothing else."""
        self.selection.select_item(position, True)

    def select_and_focus(self, position: int) -> None:
        """Select the item at <position> alone, scroll to it and give it
        the keyboard focus.

        Enter, the menu key and the arrow keys act on the item with the
        focus, not on the one highlighted, as Gtk.TreeView's cursor
        did: a right click selects without moving the focus, and Enter
        then opened the item clicked before.  The focus moves only
        within a view that has it.
        """
        self.select_only(position)
        flags = Gtk.ListScrollFlags.FOCUS
        if isinstance(self, Gtk.ColumnView):
            # Its scroll_to() also takes the column to scroll to.
            self.scroll_to(position, None, flags, None)
        elif isinstance(self, (Gtk.ListView, Gtk.GridView)):
            self.scroll_to(position, flags, None)
        else:
            raise TypeError(f'{type(self).__name__} is no list, grid or '
                            'column view')
        focus_where_scrolled(self)

    def unselect_all(self) -> None:
        """Leave nothing selected."""
        if isinstance(self.selection, Gtk.SingleSelection):
            # GTK 4.14's Gtk.SingleSelection has no unselect_all() of
            # its own, and the one it inherits goes through
            # set_selection(), which it does not implement either, so
            # it did nothing.  GTK 4.22's is this.
            self.selection.unselect_item(self.selection.get_selected())
        else:
            self.selection.unselect_all()


class DragReorderable:

    """A list view whose entries are put in a different order by
    dragging one onto another, once set_reorderable() allows it.

    Gtk.TreeView and Gtk.IconView did this for themselves; the list
    models' views have no notion of it, so each cell carries a drag
    source and a drop target, added by _add_reorder_controllers(). A
    drag carries the position it started from, as text after
    _REORDER_TYPE, so that a drag from anywhere else is refused.
    A cell is any widget with a <position> attribute.
    """

    #: What a reordering drag carries: the position it started from.
    _REORDER_TYPE: str
    _reorderable = False

    def set_reorderable(self, reorderable: bool) -> None:
        """Let the entries be dragged into a different order."""
        self._reorderable = reorderable

    def _may_reorder(self) -> bool:
        """Whether a drag may start or land now."""
        return True

    def _move_dragged(self, source: int, destination: int) -> bool:
        """Move the entry at <source> to <destination>; whether it moved."""
        raise NotImplementedError

    def _add_reorder_controllers(self, cell: Gtk.Widget
                                 ) -> Gtk.DragSource | None:
        """Make <cell> one a reordering drag can start from and land on,
        and return its drag source; None while reordering is off."""
        if not self._reorderable:
            return None
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect('prepare', self._reorder_prepare, cell)
        cell.add_controller(source)
        target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        target.connect('drop', self._reorder_drop, cell)
        cell.add_controller(target)
        return source

    def _reorder_prepare(self, source: "Gtk.DragSource | None", x: float,
                         y: float, cell: Gtk.Widget
                         ) -> "Gdk.ContentProvider | None":
        # Nothing to carry is how a Gtk.DragSource is told not to start.
        if not self._may_reorder():
            return None
        return Gdk.ContentProvider.new_for_value(
            '%s:%d' % (self._REORDER_TYPE, _position(cell)))

    def _reorder_drop(self, target: "Gtk.DropTarget | None", value: str,
                      x: float, y: float, cell: Gtk.Widget) -> bool:
        prefix = self._REORDER_TYPE + ':'
        if not isinstance(value, str) or not value.startswith(prefix):
            return False
        if not self._may_reorder():
            return False
        try:
            source_position = int(value[len(prefix):])
        except ValueError:
            return False
        return self._move_dragged(source_position, _position(cell))


def _position(cell: Gtk.Widget) -> int:
    """The position a reorderable view's <cell> is drawn at."""
    position = getattr(cell, 'position')
    assert isinstance(position, int)
    return position


def drop_focus_when_closed(window: Gtk.Window) -> None:
    """Take the focus off <window>'s widgets before its surface goes.

    GTK's input method context on Windows (4.24, gtkimcontextime.c)
    starts filtering the window's messages when a text field takes the
    focus, and stops only when the field loses the focus while the
    window still has its surface.  A window destroyed with a text field
    focused left the filter behind, pointing at a context that was then
    freed; the next messages any window received ran it, and Windows
    workers of the test suite died of access violations in DestroyWindow
    and present() (GTK issue 8289 is the same code).  An 'unrealize'
    handler runs before GTK's own, while the surface is still there.
    """
    window.connect('unrealize', _drop_focus)


def _drop_focus(window: Gtk.Window) -> None:
    window.set_focus(None)


def release(window: Gtk.Window) -> None:
    """Let go of what <window>'s widgets hold of MComix, once it is closed.

    GTK 4 does not dispose a destroyed window's widgets:
    gtk_window_destroy() drops GTK's own reference to the window and
    leaves its children where they are.  A child still has a parent, so
    PyGObject holds its wrapper, and with it the handlers connected to
    it; one that is a method of the window, or a closure over it, then
    keeps the window and everything it shows alive for the rest of the
    session.  The same goes for the event controllers the window and
    its widgets hold.

    The popovers go as well: one is parented to the widget it opens
    over, which GTK then finalizes with the menu still on it.

    What goes is every handler connected from Python, which PyGObject
    connects with no user data.  GTK's own handlers nearly all carry
    theirs and stay: cutting those - as disposing the widgets would -
    makes GTK trip over its own shortcut controllers when they are
    finally freed.  The few it connects without (a list view's drop
    target, a file chooser cell's gestures) go too, on widgets that
    have nothing left to do.  The window's own handlers stay, since Python's
    collector can see those, and some of them are still to run.
    """
    widgets = list(_released(window))
    # First, while their handlers are still there to be disconnected
    # by their own ids: a list view unbinding its rows does just that.
    for widget in widgets:
        if isinstance(widget, Releasable):
            widget.release()
    for controller in window.observe_controllers():
        _cut_handlers(controller)
    for widget in widgets:
        cut_handlers(widget)
    # A popover MComix opened is parented to the widget it opened over
    # and stays there once it has been closed, so GTK finalized that
    # widget with the menu still on it: "Finalizing
    # MComixColumnListView, but it still has children left:
    # GtkPopoverMenu".  Nothing is going to open it again in a window
    # that has closed.  Only the ones popup_at() parented: GTK builds
    # popovers of its own inside its file chooser, and taking one of
    # those off its widget leaves the chooser tripping over the parts
    # that are missing.
    for widget in widgets:
        if widget in _parented:
            widget.unparent()


def empty_action_group(group: Gio.SimpleActionGroup) -> None:
    """Take every action out of <group>, for release() to hand on.

    An action's handler is typically a method of whoever built it, and
    PyGObject keeps the handler with the action in C; once nothing in
    Python refers to the action itself, nothing can see that handler to
    collect it, and it holds its owner for as long as the group lives.
    """
    for name in group.list_actions():
        group.remove_action(name)


def _cut_handlers(instance: GObject.Object) -> None:
    """Disconnect every handler Python connected to <instance>."""
    GObject.signal_handlers_disconnect_matched(
        instance, GObject.SignalMatchType.DATA, 0, 0, None, None, None)


def cut_handlers(widget: Gtk.Widget) -> None:
    """Disconnect every handler Python connected to <widget> or to one of
    its event controllers, which is what release() does to every widget
    in a closed window.

    For a widget release() cannot find there: a list view keeps the
    cells it has built but is not showing, outside the tree.
    """
    _cut_handlers(widget)
    for controller in widget.observe_controllers():
        _cut_handlers(controller)


def _menu_button_pressed(button: int) -> None:
    """Remember which mouse <button> a menu was last pressed with."""
    global _middle_click
    _middle_click = button == Gdk.BUTTON_MIDDLE


def watch_menu_clicks(root: Gtk.Widget) -> None:
    """Note which mouse button presses the menus under <root>.

    A Gtk.MenuItem was a widget, so telling a middle click from a left
    one was a matter of connecting to its button-press-event.  A GTK4
    menu is a model: an item carries an action name and a target, the
    action handler is handed the target and nothing else, and GTK
    activates the item on whichever button was pressed.  The press that
    comes before the activation is all that separates the two.

    Every popover is watched separately.  A Gtk.PopoverMenu is a
    Gtk.Native with a surface of its own, so an event in one is
    propagated from that popover down to the item it lands on, passing
    neither the window nor the popover whose item opened it.

    Call this again whenever a menu model is replaced: GTK builds the
    popovers from the model, so a submenu's popover is a new widget
    afterwards.  Popovers already being watched are left alone.
    """
    for popover in _menu_popovers(root):
        if any(isinstance(controller, _MenuClickGesture)
               for controller in popover.observe_controllers()):
            continue
        gesture = _MenuClickGesture()
        # Every button, so that a left click clears what a middle click
        # set, and the capture phase, so that the press is seen before
        # the item under it acts on it.
        gesture.set_button(0)
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect(
            'pressed',
            lambda gesture, presses, x, y:
            _menu_button_pressed(gesture.get_current_button()))
        popover.add_controller(gesture)


def take_middle_click() -> bool:
    """Whether the menu activation being handled came of a middle click.

    The answer is taken rather than read: an item activated from the
    keyboard is preceded by no press at all, and would otherwise be
    handed the answer belonging to the last one.
    """
    global _middle_click
    middle, _middle_click = _middle_click, False
    return middle


def simple_action(actions: Gio.ActionMap, name: str) -> Gio.SimpleAction:
    """The action registered as <name> in <actions>.

    Gio.ActionMap.lookup_action() answers with the Gio.Action interface,
    which can neither be enabled nor given a state, and with None for a
    name that was never added; every caller wants the Gio.SimpleAction
    it put there.
    """
    action = actions.lookup_action(name)
    if not isinstance(action, Gio.SimpleAction):
        raise LookupError('There is no action named %r.' % name)
    return action

# vim: expandtab:sw=4:ts=4
