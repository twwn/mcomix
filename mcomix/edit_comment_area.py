"""edit_comment_area.py - The area in the editing window that displays comments."""

import os
from gi.repository import Gio, Gdk, Gtk
from mcomix import widgets
from mcomix import tools
from mcomix.i18n import _

from typing import Any


class _CommentArea(Gtk.Box):

    """The area used for displaying and handling non-image files."""

    def __init__(self, edit_dialog):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._edit_dialog = edit_dialog

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        widgets.pack(self, scrolled, True, True, 0)

        info = Gtk.Label(label=_('Please note that the only files that are automatically added to this list are those files in archives that MComix recognizes as comments.'))
        info.set_xalign(0.5)
        info.set_yalign(0.5)
        # Gtk.Label.set_line_wrap() is set_wrap() in GTK4.
        info.set_wrap(True)
        widgets.pack(self, info, False, False, 10)

        # The ListStore layout is (basename, size, full path).
        self._liststore = Gtk.ListStore(str, str, str)
        self._treeview = Gtk.TreeView(model=self._liststore)
        clicks = Gtk.GestureClick()
        clicks.set_button(3)
        clicks.connect('pressed', self._button_press)
        self._treeview.add_controller(clicks)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press)
        self._treeview.add_controller(keys)

        cellrenderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(_('Name'), cellrenderer, text=0)
        column.set_expand(True)
        self._treeview.append_column(column)

        column = Gtk.TreeViewColumn(_('Size'), cellrenderer, text=1)
        self._treeview.append_column(column)
        scrolled.set_child(self._treeview)

        self._popup_menu = self._create_popup_menu()

    def _create_popup_menu(self) -> Any:
        """Build the right-click menu for the comment list."""
        actions = Gio.SimpleActionGroup()
        remove = Gio.SimpleAction.new('remove', None)
        remove.connect('activate', self._remove_file)
        actions.add_action(remove)
        self.insert_action_group('commentarea', actions)

        model = Gio.Menu()
        model.append(_('Remove from archive'), 'commentarea.remove')
        return Gtk.PopoverMenu.new_from_model(model)

    def fetch_comments(self) -> None:
        """Load all comments in the archive."""

        for num in range(1,
          self._edit_dialog.file_handler.get_number_of_comments() + 1):

            path = self._edit_dialog.file_handler.get_comment_name(num)
            size = tools.format_byte_size(os.stat(path).st_size)
            self._liststore.append([os.path.basename(path), size, path])

    def add_extra_file(self, path):
        """Add an extra imported file (at <path>) to the list."""
        size = tools.format_byte_size(os.stat(path).st_size)
        self._liststore.append([os.path.basename(path), size, path])

    def get_file_listing(self):
        """Return a list with the full paths to all the files, in order."""
        file_list = []

        for row in self._liststore:
            file_list.append(row[2])

        return file_list

    def _remove_file(self, *args):
        """Remove the currently selected file from the list."""
        iterator = self._treeview.get_selection().get_selected()[1]

        if iterator is not None:
            self._liststore.remove(iterator)

    def _button_press(self, gesture, n_press, x, y) -> None:
        """Handle mouse button presses on the area."""
        if self._treeview.get_path_at_pos(int(x), int(y)) is None:
            return

        widgets.popup_at(self._popup_menu, self._treeview, x, y)

    def _key_press(self, controller, keyval, keycode, state):
        """Handle key presses on the area."""
        if keyval == Gdk.KEY_Delete:
            self._remove_file()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

# vim: expandtab:sw=4:ts=4
