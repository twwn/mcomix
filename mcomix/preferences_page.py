"""preferences_page.py - MComix preference page."""

from gi.repository import Gtk

from mcomix import preferences_section
from mcomix import widgets


class _PreferencePage(Gtk.Box):

    """The _PreferencePage is a conveniece class for making one "page"
    in a preferences-style dialog that contains one or more
    _PreferenceSections.
    """

    def __init__(self, right_column_width):
        """Create a new page where any possible right columns have the
        width request <right_column_width>.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        widgets.set_border(self, 12)
        self._right_column_width = right_column_width
        self._section = None

    def new_section(self, header):
        """Start a new section in the page, with the header text from
        <header>.
        """
        self._section = preferences_section._PreferenceSection(header, self._right_column_width)
        widgets.pack(self, self._section, False, False, 0)

    def add_row(self, left_item, right_item=None):
        """Add a row to the page (in the latest section), containing one
        or two items. If the left item is a label it is automatically
        aligned properly.
        """
        if isinstance(left_item, Gtk.Label):
            left_item.set_xalign(0)
            left_item.set_yalign(0.5)

        if right_item is None:
            widgets.pack(self._section.contentbox, left_item, True, True, 0)
        else:
            left_box, right_box = self._section.new_split_vboxes()
            widgets.pack(left_box, left_item, True, True, 0)
            widgets.pack(right_box, right_item, True, True, 0)

# vim: expandtab:sw=4:ts=4
