"""widgets.py - Small helpers for widgets whose API changed in GTK4."""

from gi.repository import Gdk, Gio, Gtk

from typing import Any


class Chooser(Gtk.DropDown):

    """One of a fixed set of values, picked from a dropdown.

    This is what a Gtk.ComboBox over a two-column Gtk.ListStore was,
    both of which GTK deprecated in 4.10 along with the
    Gtk.CellRendererText that drew the labels.  The store held the label
    in one column and the value in another, and every caller had to walk
    a Gtk.TreeIter to read the value back; the labels are a
    Gtk.StringList here and the values a plain Python list beside it.
    """

    __gtype_name__ = 'MComixChooser'

    def __init__(self, options: Any, chosen: Any = None) -> None:
        """Offer <options>, pairs of label and value, with <chosen> set."""
        labels = Gtk.StringList()
        self._values = []
        for label, value in options:
            labels.append(label)
            self._values.append(value)
        super(Chooser, self).__init__(model=labels)
        self.set_value(chosen)

    def get_value(self) -> Any:
        """The value that is picked, or None if there are no options."""
        position = self.get_selected()
        if position == Gtk.INVALID_LIST_POSITION:
            return None
        return self._values[position]

    def set_value(self, value: Any) -> None:
        """Pick <value>.

        A Gtk.DropDown always shows one of its options, where a
        Gtk.ComboBox could show none of them, so a value that is not on
        offer leaves the first option showing rather than an empty box -
        and the preference it came from is left alone until the user
        picks something.
        """
        if value in self._values:
            self.set_selected(self._values.index(value))

    def connect_changed(self, changed: Any) -> None:
        """Call <changed> with this chooser whenever the pick changes."""
        self.connect('notify::selected',
                     lambda widget, _param: changed(widget))


def pack(box: Any, child: Any, expand: bool = False, fill: bool = True,
         padding: int = 0, end: bool = False) -> None:
    """Add <child> to <box>, the way Gtk.Box.pack_start/pack_end did.

    GTK4 boxes only append and prepend.  What the old arguments said is
    now said by the child: whether it takes the slack is hexpand or
    vexpand depending on which way the box runs, not filling its share is
    an alignment, and padding is a margin on the two ends that matter.
    """
    # Gtk.CellLayout - tree view columns, combo boxes - has a pack_start()
    # of its own that GTK4 keeps; only boxes lost theirs.
    assert isinstance(box, Gtk.Box), '%r is not a box' % (box,)
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


def set_border(widget: Any, width: int) -> None:
    """Put <width> pixels of space around what <widget> holds.

    Gtk.Container.set_border_width() is gone in GTK4; the space around a
    widget is the widget's own margin there.  A window is the exception:
    its margins fall outside the part of its surface that it paints, so
    they come out as a transparent strip along the edges rather than as
    a border - the space has to go around what it holds instead.
    """
    if isinstance(widget, Gtk.Window):
        widget = widget.get_child()
        if widget is None:
            return
    widget.set_margin_top(width)
    widget.set_margin_bottom(width)
    widget.set_margin_start(width)
    widget.set_margin_end(width)


def chooser_paths(chooser: Any) -> list:
    """The paths of the files selected in <chooser>.

    Gtk.FileChooser.get_filenames() is gone in GTK4; get_files() answers
    with a Gio.ListModel of Gio.Files instead.
    """
    files = chooser.get_files()
    paths = []
    for index in range(files.get_n_items()):
        path = files.get_item(index).get_path()
        if path is not None:
            paths.append(path)
    return paths


def chooser_folder(chooser: Any) -> "str | None":
    """The path of the folder <chooser> is showing, if it is local."""
    folder = chooser.get_current_folder()
    return folder.get_path() if folder is not None else None


def set_chooser_folder(chooser: Any, path: str) -> None:
    """Show <path> in <chooser>; GTK4 takes a Gio.File, not a name."""
    chooser.set_current_folder(Gio.File.new_for_path(path))


def set_chooser_file(chooser: Any, path: str) -> None:
    """Select <path> in <chooser>; set_filename() is gone in GTK4."""
    chooser.set_file(Gio.File.new_for_path(path))


def popup_at(popover: Any, widget: Any, x: float, y: float) -> None:
    """Show <popover> over <widget>, pointing at (<x>, <y>) within it.

    A Gtk.Menu was popped up at the pointer with an event; a
    Gtk.PopoverMenu is parented to a widget and pointed at a rectangle in
    its coordinates.
    """
    if popover.get_parent() is None:
        popover.set_parent(widget)
    area = Gdk.Rectangle()
    area.x, area.y, area.width, area.height = int(x), int(y), 1, 1
    popover.set_pointing_to(area)
    popover.set_has_arrow(False)
    popover.popup()

# vim: expandtab:sw=4:ts=4
