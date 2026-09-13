"""preferences_page.py - MComix preference page."""

from gi.repository import Gtk

from mcomix import preferences_section
from mcomix import widgets


class _PreferencePage(Gtk.Box):

    """The _PreferencePage is a conveniece class for making one "page"
    in a preferences-style dialog that contains one or more
    _PreferenceSections.
    """

    #: The section rows go into, which new_section() puts there.
    _section: "preferences_section._PreferenceSection | None" = None

    def __init__(self, right_column_width: int | None) -> None:
        """Create a new page where any possible right columns have the
        width request <right_column_width>.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        widgets.set_border(self, 12)
        self._right_column_width = right_column_width

    def _current_section(self) -> "preferences_section._PreferenceSection":
        """The section rows are being added to.

        Every page starts one before it adds a row to it.
        """
        if self._section is None:
            raise RuntimeError('no section has been started on this page')
        return self._section

    def new_section(self, header: str) -> None:
        """Start a new section in the page, with the header text from
        <header>.
        """
        self._section = preferences_section._PreferenceSection(header, self._right_column_width)
        widgets.pack(self, self._section, False, False, 0)

    def add_row(self, left_item: Gtk.Widget,
                right_item: "Gtk.Widget | None" = None) -> None:
        """Add a row to the page (in the latest section), containing one
        or two items. If the left item is a label it is automatically
        aligned properly.
        """
        if isinstance(left_item, Gtk.Label):
            left_item.set_xalign(0)
            left_item.set_yalign(0.5)

        section = self._current_section()
        if right_item is None:
            widgets.pack(section.contentbox, left_item, True, True, 0)
        else:
            left_box, right_box = section.new_split_boxes()
            widgets.pack(left_box, left_item, True, True, 0)
            widgets.pack(right_box, right_item, True, True, 0)

# vim: expandtab:sw=4:ts=4
