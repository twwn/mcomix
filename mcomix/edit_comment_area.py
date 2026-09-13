"""edit_comment_area.py - The area in the editing window that displays comments."""

import os
from gi.repository import Gio, Gdk, Gtk
from mcomix import column_list
from mcomix import widgets
from mcomix import tools
from mcomix.i18n import _

from typing import Any


class _CommentArea(Gtk.Box):

    """The area used for displaying and handling non-image files."""

    def __init__(self, edit_dialog: Any) -> None:
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

        # A row carries the basename, the size as it is written out,
        # and the full path the archive is built from.
        self._list = column_list.ColumnListView()
        self._list.add_text_column(_('Name'), 'name', expand=True)
        self._list.add_text_column(_('Size'), 'size')
        clicks = Gtk.GestureClick()
        clicks.set_button(3)
        clicks.connect('pressed', self._button_press)
        self._list.add_controller(clicks)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press)
        self._list.add_controller(keys)
        scrolled.set_child(self._list)

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

            self.add_extra_file(
                self._edit_dialog.file_handler.get_comment_name(num))

    def add_extra_file(self, path: str) -> None:
        """Add an extra imported file (at <path>) to the list."""
        self._list.append_row(column_list.Row(
            name=os.path.basename(path),
            size=tools.format_byte_size(os.stat(path).st_size),
            path=path))

    def get_file_listing(self) -> list[str]:
        """Return a list with the full paths to all the files, in order."""
        return [row.path for row in self._list.each_row()]

    def _remove_file(self, *args: Any) -> None:
        """Remove the currently selected file from the list."""
        row = self._list.get_selected_row()
        if row is not None:
            self._list.remove_row(row)

    def _button_press(self, gesture: Gtk.GestureClick, n_press: int,
                      x: float, y: float) -> None:
        """Handle mouse button presses on the area."""
        if self._list.row_at(x, y) is None:
            return

        widgets.popup_at(self._popup_menu, self._list, x, y)

    def _key_press(self, controller: Gtk.EventControllerKey, keyval: int,
                   keycode: int, state: Gdk.ModifierType) -> bool:
        """Handle key presses on the area."""
        if keyval == Gdk.KEY_Delete:
            self._remove_file()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

# vim: expandtab:sw=4:ts=4
