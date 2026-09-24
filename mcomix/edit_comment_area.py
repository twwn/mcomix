"""edit_comment_area.py - The area in the editing window that displays comments."""

import os
import weakref
from collections.abc import Sequence
from gi.repository import Gio, Gdk, Gtk
from mcomix import column_list
from mcomix import rename_dialog
from mcomix import widgets
from mcomix import tools
from mcomix.dialog import Response
from mcomix.i18n import _

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import edit_dialog as edit_dialog_module
    from mcomix import main


class _CommentArea(Gtk.Box, widgets.Releasable):

    """The area used for displaying and handling non-image files."""

    def __init__(self, edit_dialog: "edit_dialog_module._EditArchiveDialog",
                 window: "main.MainWindow") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._editor = weakref.ref(edit_dialog)
        self._window = window

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        widgets.pack(self, scrolled, True, True, 0)

        info = Gtk.Label(label=_('Please note that the only files that are automatically added to this list are those files in archives that MComix recognizes as comments.'))
        info.set_xalign(0.5)
        info.set_yalign(0.5)
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

        # A comment file listed before it is out of the archive has its
        # size filled in when the extractor announces it.  'unrealize'
        # rather than 'destroy', which GTK4 emits only when the last
        # reference goes.
        self._window.filehandler.file_available += self._on_file_available
        self.connect('unrealize', self._stop_following)

    def _stop_following(self, *args: object) -> None:
        """Stop hearing about extracted files once the editor is gone."""
        self._window.filehandler.file_available -= self._on_file_available

    def _on_file_available(self, paths: Sequence[str]) -> None:
        """Give the rows of the files in <paths> their sizes."""
        arrived = set(paths)
        for row in self._list.each_row():
            if row.path in arrived and not row.size:
                row.size = self._size_of(row.path)
                row.changed()

    def release(self) -> None:
        """Take the comment area actions out, once the window is closed.

        GTK holds an inserted action group, and each action holds a
        handler that is a method of this area: a cycle through C that
        Python's collector cannot see, which kept the area - and its
        list - alive after the window had gone.
        """
        self.insert_action_group('commentarea', None)

    @property
    def _edit_dialog(self) -> "edit_dialog_module._EditArchiveDialog":
        """The editor this area is part of.

        Held weakly: GTK holds the area for as long as the editor's
        widgets stand, which is for good once the editor is closed, and
        a plain reference would then keep the editor, and every page it
        shows, alive with it.
        """
        editor = self._editor()
        assert editor is not None, 'the editor is gone'
        return editor

    def _create_popup_menu(self) -> Gtk.PopoverMenu:
        """Build the right-click menu for the comment list.

        Undo and redo are the dialog's own Ctrl+Z and Ctrl+Y, and this
        menu is one of the two places the editor has to name them.
        """
        actions = Gio.SimpleActionGroup()
        for name, activated in (('rename', self._rename_file),
                                ('remove', self._remove_file),
                                ('undo', self._undo),
                                ('redo', self._redo)):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', activated)
            actions.add_action(action)
        self.insert_action_group('commentarea', actions)

        model = Gio.Menu()
        removal = Gio.Menu()
        removal.append(_('Re_name file...'), 'commentarea.rename')
        removal.append(_('Remove from archive'), 'commentarea.remove')
        model.append_section(None, removal)
        history = Gio.Menu()
        history.append(_('_Undo'), 'commentarea.undo')
        history.append(_('_Redo'), 'commentarea.redo')
        model.append_section(None, history)
        return Gtk.PopoverMenu.new_from_model(model)

    def _undo(self, *args: object) -> None:
        self._edit_dialog.undo()

    def _redo(self, *args: object) -> None:
        self._edit_dialog.redo()

    def fetch_comments(self) -> None:
        """Show the comment files the archive holds, and nothing else.

        What is there is replaced rather than added to, as the list of
        pages beside this one replaces what it shows: a second fetch
        would otherwise list every comment twice, and the name each is
        written under is read back by the path it came from, which two
        rows for one file cannot answer for.
        """
        handler = self._edit_dialog.file_handler
        self._list.set_rows([
            self._row_for(handler.get_comment_name(number))
            for number in range(1, handler.get_number_of_comments() + 1)])

    def add_extra_file(self, path: str) -> None:
        """Add an extra imported file (at <path>) to the list."""
        self._list.append_row(self._row_for(path))

    @staticmethod
    def _size_of(path: str) -> str:
        """How large the file at <path> is, or nothing while it is not
        there yet."""
        try:
            return tools.format_byte_size(os.stat(path).st_size)
        except FileNotFoundError:
            return ''

    @classmethod
    def _row_for(cls, path: str) -> column_list.Row:
        """The row for the file at <path>: what it is called, how large
        it is written out, and the file itself.

        The editor lists the comments as soon as the book is open, and
        the extractor may not have reached one yet: its size comes when
        it does (_on_file_available).  Reading it here raised
        FileNotFoundError, and the editor opened with no comments listed
        and without the pages picked out in the window.
        """
        return column_list.Row(
            name=os.path.basename(path),
            size=cls._size_of(path),
            path=path)

    def get_file_listing(self) -> list[str]:
        """Return a list with the full paths to all the files, in order."""
        return [row.path for row in self._list.each_row()]

    def file_names(self) -> dict[str, str]:
        """The name each file is written under, by the path it is read
        from: what the list shows, which is the name of its file until
        the reader gives it another."""
        return {row.path: row.name for row in self._list.each_row()}

    def _rename_file(self, *args: object) -> None:
        """Ask what to call the file that is selected.

        The same dialog the pages are renamed through, and the same
        rules: the name replaces the whole of the old one, an extension
        left off is kept, and a name that something else in the archive
        holds is warned about rather than taken.
        """
        row = self._list.get_selected_row()
        if row is None:
            return

        def clash(typed: str) -> "rename_dialog.Clash | None":
            """What holds the name that has been typed, if anything.

            A file of this list can be swapped with or written over,
            both being rows here.  A page cannot: it belongs to the
            list in the other tab, which this one does not touch, so
            the name is warned about and nothing is offered.
            """
            name = rename_dialog.read(row.name, typed)
            if name is None:
                return None
            if self._row_called(name, row) is not None:
                return rename_dialog.Clash(
                    _('Another file in the archive is called "%s" already.')
                    % name, True)
            page = self._window.file_actions.page_called(name, 0)
            if page is not None:
                return rename_dialog.Clash(
                    _('A page of the book is called "%s" already.') % name,
                    False)
            return None

        rename_dialog.ask(
            self._edit_dialog, title=_('Rename file?'),
            prompt=_('Please enter a new name for this file.'),
            name=row.name, clash=clash,
            answered=lambda response, typed: self._rename_answered(
                row, response, typed))

    def _row_called(self, name: str,
                    other_than: column_list.Row) -> "column_list.Row | None":
        """The row called <name>, if one other than <other_than> is."""
        for row in self._list.each_row():
            if row is not other_than and row.name == name:
                return row
        return None

    def _rename_answered(self, row: column_list.Row, response: int,
                         typed: str) -> None:
        """Do what was answered with the name that was typed."""
        name = rename_dialog.read(row.name, typed)
        if name is None:
            return
        other = self._row_called(name, row)
        if response == Response.OK and other is None:
            self._give_name(row, name)
        elif response == rename_dialog.SWAP and other is not None:
            held = row.name
            self._give_name(row, name)
            self._give_name(other, held)
        elif response == rename_dialog.REPLACE and other is not None:
            self._edit_dialog.record_change()
            self._list.remove_row(other)
            row.name = name
            row.changed()

    def _give_name(self, row: column_list.Row, name: str) -> None:
        """Call the file of <row> <name>, and say so on the row.

        Through the editor's undo, as everything else here is: a name
        is as much a change to the archive that will be written as a
        file taken out of it.
        """
        self._edit_dialog.record_change()
        row.name = name
        row.changed()

    def snapshot(self) -> list[column_list.Row]:
        """The rows as they stand, for the dialog's undo."""
        return list(self._list.each_row())

    def restore(self, rows: list[column_list.Row]) -> None:
        """Show <rows>, from a snapshot(), and nothing else."""
        self._list.set_rows(rows)

    def _remove_file(self, *args: object) -> None:
        """Remove the currently selected file from the list."""
        row = self._list.get_selected_row()
        if row is not None:
            self._edit_dialog.record_change()
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
        if keyval == Gdk.KEY_F2:
            # The key a file manager renames with, as in the list of
            # pages beside this one.
            self._rename_file()
            return Gdk.EVENT_STOP
        # As in the page area beside it: the menu key and Shift+F10 open
        # the popup, which a GTK4 widget is not told about by a signal.
        if widgets.menu_key(keyval, state):
            widgets.popup_at(self._popup_menu, self._list, 0, 0)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

# vim: expandtab:sw=4:ts=4
