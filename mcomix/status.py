"""status.py - Statusbar for main window."""

from gi.repository import Gdk, Gio, GLib, Gtk

from mcomix import i18n
from mcomix import constants
from mcomix.preferences import prefs
from mcomix.i18n import _

from typing import Any

class Statusbar(Gtk.EventBox):

    SPACING = 5

    def __init__(self) -> None:
        super(Statusbar, self).__init__()

        self._loading = True

        # Status text, page number, file number, resolution, path, filename, filesize
        self.status = Gtk.Statusbar()
        self.add(self.status)

        # Create popup menu for enabling/disabling status boxes.
        self.tooltipstatus = TooltipStatusHelper(statusbar=self.status)
        self._fields_menu = self._create_fields_menu()

        # Hook mouse release event
        self.connect('button-release-event', self._button_released)
        self.set_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK)

        # Default status information
        self._page_info = ''
        self._file_info = ''
        self._resolution = ''
        self._root = ''
        self._filename = ''
        self._filesize = ''
        self._update_sensitivity()
        self.show_all()

        self._loading = False

    def set_message(self, message):
        """Set a specific message (such as an error message) on the statusbar,
        replacing whatever was there earlier.
        """
        self.status.pop(0)
        self.status.push(0, " " * Statusbar.SPACING + message)

    def set_page_number(self, page, total, this_screen):
        """Update the page number."""
        page_info = ""
        for i in range(this_screen):
            page_info += '%d' % (page + i)
            if i < this_screen - 1:
                page_info +=','
        page_info += ' / %d' % total
        self._page_info = page_info

    def get_page_number(self):
        """Returns the bar's page information."""
        return self._page_info

    def set_file_number(self, fileno, total):
        """Updates the file number (i.e. number of current file/total
        files loaded)."""
        if total > 0:
            self._file_info = '(%d / %d)' % (fileno, total)
        else:
            self._file_info = ''

    def get_file_number(self):
        """ Returns the bar's file information."""
        return self._file_info

    def set_resolution(self, dimensions): # 2D only
        """Update the resolution data.

        Takes an iterable of tuples, (x, y, scale, distorted), describing the
        original resolution of an image as well as the currently displayed
        scale and whether scaling was done irrespective of aspect ratio,
        resulting in a distorted image.
        """
        resolution = ""
        for i in range(len(dimensions)):
            d = dimensions[i]
            resolution += '%dx%d (%.1f%%%s)' % (d[0], d[1], d[2] * 100.0,
                "*" if d[3] else "")
            if i < len(dimensions) - 1:
                resolution += ', '
        self._resolution = resolution

    def set_root(self, root):
        """Set the name of the root (directory or archive)."""
        self._root = i18n.to_display_string(i18n.to_unicode(root))

    def set_filename(self, filename):
        """Update the filename."""
        self._filename = i18n.to_display_string(i18n.to_unicode(filename))

    def set_filesize(self, size):
        """Update the filesize."""
        if size is None:
            size = ""
        self._filesize = size

    def update(self) -> None:
        """Set the statusbar to display the current state."""

        space = " " * Statusbar.SPACING
        text = (space + "|" + space).join(self._get_status_text())
        self.status.pop(0)
        self.status.push(0, space + text)

    def push(self, context_id, message):
        """ Compatibility with Gtk.Statusbar. """
        assert context_id >= 0
        self.status.push(context_id + 1, message)

    def pop(self, context_id):
        """ Compatibility with Gtk.Statusbar. """
        assert context_id >= 0
        self.status.pop(context_id + 1)

    def _get_status_text(self):
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

    def _create_fields_menu(self) -> Any:
        """Build the right-click menu that picks which fields are shown."""
        self._field_actions = Gio.SimpleActionGroup()
        model = Gio.Menu()
        for name, label, bit in self.FIELDS:
            action = Gio.SimpleAction.new_stateful(
                name, None, GLib.Variant('b', bool(prefs['statusbar fields'] & bit)))
            action.connect('change-state', self.toggle_status_visibility, bit)
            self._field_actions.add_action(action)
            model.append(label, 'statusbar.%s' % name)
        self.insert_action_group('statusbar', self._field_actions)
        menu = Gtk.Menu.new_from_model(model)
        menu.attach_to_widget(self, None)
        return menu

    def toggle_status_visibility(self, action: Any, value: Any, bit: int) -> None:
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

    def _button_released(self, widget, event, *args):
        """ Triggered when a mouse button is released to open the context
        menu. """
        if event.button == 3:
            self._fields_menu.popup(None, None, None, None,
                                    event.button, event.time)

    def _update_sensitivity(self) -> None:
        """ Brings the popup's ticks in line with the preferences. """
        for name, label, bit in self.FIELDS:
            self._field_actions.lookup_action(name).set_state(
                GLib.Variant('b', bool(prefs['statusbar fields'] & bit)))


class TooltipStatusHelper(object):
    """ Provides statusbar tooltips when selecting menu items. """

    def __init__(self, statusbar: Any = None) -> None:
        self._statusbar = statusbar

    def attach_to_menu(self, menu: Any, tooltips: dict) -> None:
        """ Show the <tooltips> for a menu built from a Gio.Menu model.

        A UI manager announced every proxy widget it built, along with the
        action behind it.  A menu model announces nothing, and the items
        it produces keep their action to themselves - Gtk.Actionable
        reports None for them - so <tooltips> is keyed by the item's label
        instead, which is the only thing the two ends share.

        Note that GTK4 has no place to hang this at all: menus are
        popovers of buttons there, with no select and deselect to listen
        for.
        """
        for item in menu.get_children():
            if not isinstance(item, Gtk.MenuItem):
                continue
            submenu = item.get_submenu()
            if submenu is not None:
                self.attach_to_menu(submenu, tooltips)
            tooltip = tooltips.get(item.get_label())
            if tooltip:
                item.connect('select', self._on_item_select, tooltip)
                item.connect('deselect', self._on_item_deselect)

    def _on_item_select(self, menuitem, tooltip):
        self._statusbar.push(0, " " * Statusbar.SPACING + tooltip)

    def _on_item_deselect(self, menuitem):
        self._statusbar.pop(0)

# vim: expandtab:sw=4:ts=4
