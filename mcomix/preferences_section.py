"""preferences_section.py - Preference dialog section."""

from gi.repository import Gtk

from mcomix import labels

class _PreferenceSection(Gtk.Box):

    """The _PreferenceSection is a convenience class for making one
    "section" of a preference-style dialog, e.g. it has a bold header
    and a number of rows which are indented with respect to that header.
    """

    def __init__(self, header, right_column_width):
        """Contruct a new section with the header set to the text in
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
        self.pack_start(label, False, False, 0)
        self.pack_start(self.contentbox, True, True, 0)

    def new_split_vboxes(self):
        """Return two new VBoxes that are automatically put in the section
        after the previously added items. The right one has a width request
        equal to the right_column_width value passed to the class contructor,
        in order to make it easy for  all "right column items" in a page to
        line up nicely.
        """
        left_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        right_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)

        if self._right_column_width is not None:
            right_box.set_size_request(self._right_column_width, -1)

        hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
        hbox.pack_start(left_box, True, True, 0)
        hbox.pack_start(right_box, False, False, 0)
        self.contentbox.pack_start(hbox, True, True, 0)
        return left_box, right_box

# vim: expandtab:sw=4:ts=4
