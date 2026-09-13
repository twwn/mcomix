"""preferences_section.py - Preference dialog section."""

from gi.repository import Gtk

from mcomix import labels
from mcomix import widgets


class _PreferenceSection(Gtk.Box):

    """The _PreferenceSection is a convenience class for making one
    "section" of a preference-style dialog, e.g. it has a bold header
    and a number of rows which are indented with respect to that header.
    """

    def __init__(self, header: str,
                 right_column_width: int | None) -> None:
        """Construct a new section with the header set to the text in
        <header>, and the width request of the (possible) right columns
        set to that of <right_column_width>.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._right_column_width = right_column_width
        self.contentbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        self.contentbox.set_margin_start(9)
        label = labels.BoldLabel(header)
        label.set_xalign(0)
        label.set_yalign(0.5)
        widgets.pack(self, label, False, False, 0)
        widgets.pack(self, self.contentbox, True, True, 0)

    def new_split_boxes(self) -> tuple[Gtk.Box, Gtk.Box]:
        """Return the two vertical boxes of a new row, left and right,
        put in the section after the items added so far.

        The right one has the width request the section was constructed
        with, which is what lines the "right column items" of a page up
        with one another.
        """
        left_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        right_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)

        if self._right_column_width is not None:
            right_box.set_size_request(self._right_column_width, -1)

        hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
        widgets.pack(hbox, left_box, True, True, 0)
        widgets.pack(hbox, right_box, False, False, 0)
        widgets.pack(self.contentbox, hbox, True, True, 0)
        return left_box, right_box

# vim: expandtab:sw=4:ts=4
