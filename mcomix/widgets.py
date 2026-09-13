"""widgets.py - Small helpers for widgets whose API changed in GTK4."""

from gi.repository import Gdk, Gio, Graphene, Gtk

from collections.abc import Callable, Iterable
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


def pack(box: Gtk.Box, child: Gtk.Widget, expand: bool = False,
         fill: bool = True, padding: int = 0, end: bool = False) -> None:
    """Add <child> to <box>, the way Gtk.Box.pack_start/pack_end did.

    GTK4 boxes only append and prepend.  What the old arguments said is
    now said by the child: whether it takes the slack is hexpand or
    vexpand depending on which way the box runs, not filling its share is
    an alignment, and padding is a margin on the two ends that matter.
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
    pointer in the middle of it.  START and BOTTOM put its corner where
    the pointer is, which is where a menu goes.
    """
    parent = popover.get_parent()
    if parent is None:
        parent = widget
        popover.set_parent(parent)
    if widget is not parent:
        found, point = widget.compute_point(parent, Graphene.Point().init(x, y))
        if found:
            x, y = point.x, point.y
    area = Gdk.Rectangle()
    area.x, area.y, area.width, area.height = int(x), int(y), 1, 1
    popover.set_pointing_to(area)
    popover.set_has_arrow(False)
    popover.set_halign(Gtk.Align.START)
    popover.set_position(Gtk.PositionType.BOTTOM)
    popover.popup()


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
