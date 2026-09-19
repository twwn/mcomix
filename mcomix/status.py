"""status.py - Statusbar for main window."""

from gi.repository import Gio, GLib, Gtk, Pango

from mcomix import i18n
from mcomix import widgets
from mcomix import constants
from mcomix.preferences import prefs
from mcomix.i18n import _

from collections.abc import Sequence


def format_page_number(pages: Sequence[int], total: int) -> str:
    """"1,2 / 10": the pages on screen out of the whole book.

    <pages> are listed in the order they read in, which is right to
    left in manga mode, so that they line up with the file names and
    the resolutions the same screen is described by.
    """
    return '%s / %d' % (','.join('%d' % page for page in pages), total)


class Statusbar(Gtk.Box):

    """The status bar along the bottom of the window.

    It was a Gtk.EventBox, which existed so that a widget without a window
    of its own could receive button events.  GTK4 has no such thing:
    every widget can take events, through a controller.
    """

    SPACING = 5

    def __init__(self) -> None:
        super().__init__()

        self._loading = True

        # Status text, page number, file number, resolution, path, filename, filesize
        # Gtk.Statusbar is deprecated as of GTK 4.10, and its message stack
        # was never used here: every write popped context 0 and pushed the
        # whole line back. A label says the same thing.
        self.status = Gtk.Label()
        self.status.set_xalign(0)
        self.status.set_hexpand(True)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.append(self.status)

        # Create popup menu for enabling/disabling status boxes.
        #: The action behind each field's tick, by field name.  Kept
        #: rather than looked up again: Gio.ActionMap.lookup_action()
        #: answers with the Gio.Action interface, which has no way to
        #: set a state, and with None for a name that was never added.
        self._field_toggles: dict[str, Gio.SimpleAction] = {}
        self._fields_menu = self._create_fields_menu()

        # Hook mouse release event
        clicks = Gtk.GestureClick()
        clicks.set_button(0)
        clicks.connect('released', self._button_released)
        self.add_controller(clicks)

        # Default status information
        self._page_info = ''
        self._file_info = ''
        self._resolution = ''
        self._root = ''
        self._filename = ''
        self._filesize = ''
        self._update_sensitivity()
        self.set_visible(True)

        self._loading = False

    def set_message(self, message: str) -> None:
        """Set a specific message (such as an error message) on the statusbar,
        replacing whatever was there earlier.
        """
        self.status.set_text(" " * Statusbar.SPACING + message)

    def set_page_number(self, pages: Sequence[int], total: int) -> None:
        """Update the page number, from the pages on screen."""
        self._page_info = format_page_number(pages, total)

    def get_page_number(self) -> str:
        """Returns the bar's page information."""
        return self._page_info

    def set_file_number(self, fileno: int, total: int) -> None:
        """Updates the file number (i.e. number of current file/total
        files loaded)."""
        if total > 0:
            self._file_info = '(%d / %d)' % (fileno, total)
        else:
            self._file_info = ''

    def get_file_number(self) -> str:
        """ Returns the bar's file information."""
        return self._file_info

    def set_resolution(
            self,
            dimensions: Sequence[Sequence[float]]) -> None:  # 2D only
        """Update the resolution data.

        Takes an iterable of tuples, (x, y, scale, distorted), describing the
        original resolution of an image as well as the currently displayed
        scale and whether scaling was done irrespective of aspect ratio,
        resulting in a distorted image.
        """
        self._resolution = ', '.join(
            '%dx%d (%.1f%%%s)' % (width, height, scale * 100.0,
                                  '*' if distorted else '')
            for width, height, scale, distorted in dimensions)

    def set_root(self, root: str) -> None:
        """Set the name of the root (directory or archive)."""
        self._root = i18n.to_display_string(i18n.to_unicode(root))

    def set_filename(self, filename: str) -> None:
        """Update the filename."""
        self._filename = i18n.to_display_string(i18n.to_unicode(filename))

    def set_filesize(self, size: str | None) -> None:
        """Update the filesize."""
        if size is None:
            size = ""
        self._filesize = size

    def update(self) -> None:
        """Set the statusbar to display the current state."""

        space = " " * Statusbar.SPACING
        # Only the fields that have something to say: before a book is
        # open none of them has, and the bar was a row of bare
        # separators; a file whose size is not known left one in the
        # middle of the line.
        text = (space + "|" + space).join(
            field for field in self._get_status_text() if field)
        self.status.set_text(space + text)

    def _get_status_text(self) -> list[str]:
        """ Returns an array of text fields that should be displayed. """
        fields = []

        if prefs['statusbar fields'] & constants.STATUS_PAGE:
            fields.append(self._page_info)
        if prefs['statusbar fields'] & constants.STATUS_FILENUMBER:
            fields.append(self._file_info)
        if prefs['statusbar fields'] & constants.STATUS_RESOLUTION:
            fields.append(self._resolution)
        if prefs['statusbar fields'] & constants.STATUS_PATH:
            fields.append(self._root)
        if prefs['statusbar fields'] & constants.STATUS_FILENAME:
            fields.append(self._filename)
        if prefs['statusbar fields'] & constants.STATUS_FILESIZE:
            fields.append(self._filesize)

        return fields

    #: The fields the popup offers, and the bit each one stands for.
    FIELDS = (('pagenumber', _('Show page numbers'), constants.STATUS_PAGE),
              ('filenumber', _('Show file numbers'), constants.STATUS_FILENUMBER),
              ('resolution', _('Show resolution'), constants.STATUS_RESOLUTION),
              ('rootpath', _('Show path'), constants.STATUS_PATH),
              ('filename', _('Show filename'), constants.STATUS_FILENAME),
              ('filesize', _('Show filesize'), constants.STATUS_FILESIZE))

    def _create_fields_menu(self) -> Gtk.PopoverMenu:
        """Build the right-click menu that picks which fields are shown."""
        self._field_actions = Gio.SimpleActionGroup()
        model = Gio.Menu()
        for name, label, bit in self.FIELDS:
            action = Gio.SimpleAction.new_stateful(
                name, None, GLib.Variant('b', bool(prefs['statusbar fields'] & bit)))
            action.connect('change-state', self.toggle_status_visibility, bit)
            self._field_actions.add_action(action)
            self._field_toggles[name] = action
            model.append(label, 'statusbar.%s' % name)
        self.insert_action_group('statusbar', self._field_actions)
        return Gtk.PopoverMenu.new_from_model(model)

    def toggle_status_visibility(self, action: Gio.SimpleAction,
                                 value: GLib.Variant, bit: int) -> None:
        """ Called when status entries visibility is to be changed. """
        action.set_state(value)

        # Ignore events as long as control is still loading.
        if self._loading:
            return

        if value.get_boolean():
            prefs['statusbar fields'] |= bit
        else:
            prefs['statusbar fields'] &= ~bit

        self.update()

    def _button_released(self, gesture: Gtk.GestureClick, n_press: int,
                         x: float, y: float) -> None:
        """ Triggered when a mouse button is released to open the context
        menu. """
        if gesture.get_current_button() == 3:
            widgets.popup_at(self._fields_menu, self, x, y)

    def _update_sensitivity(self) -> None:
        """ Brings the popup's ticks in line with the preferences. """
        for name, label, bit in self.FIELDS:
            self._field_toggles[name].set_state(
                GLib.Variant('b', bool(prefs['statusbar fields'] & bit)))


# vim: expandtab:sw=4:ts=4
