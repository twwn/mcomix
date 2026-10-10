"""bookmark_menu.py - Bookmarks menu."""

import os

from gi.repository import Gio, GLib, Gtk


from mcomix import bookmark_backend
from mcomix import bookmark_dialog
from mcomix import message_dialog
from mcomix import widgets
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import bookmark_menu_item
    from mcomix import main
    from mcomix import ui as ui_module


class BookmarksMenu:

    """The bookmarks menu: two fixed entries, and one per bookmark.

    What it keeps is a Gio.Menu model, which the menu bar takes.  Opening
    a bookmark goes through one action carrying its position as a target,
    under a prefix of its own.
    """

    #: Where this menu's actions live, as menu items address them.
    ACTION_PREFIX = 'bookmarks'

    #: The permanent entries, and the keybinding actions whose keys reach
    #: them, which the Shortcuts tab can change like any other.  Clearing
    #: gets none: it throws away every bookmark, so it is not something
    #: to be a keystroke away from; nor does removing the open book's,
    #: which asks first anyway.
    FIXED = (('add', _('Add _Bookmark'), 'add_bookmark'),
             ('remove', _("_Remove this book's bookmarks..."), None),
             ('edit', _('_Edit Bookmarks...'), 'edit_bookmarks'),
             ('clear', _('C_lear bookmarks...'), None))

    def __init__(self, ui: "ui_module.MainUI",
                 window: "main.MainWindow") -> None:
        self._window = window
        self._ui = ui
        self._bookmarks_store = bookmark_backend.BookmarksStore
        self._bookmarks_store.initialize(window)
        self._bookmarks: "list[bookmark_menu_item._Bookmark]" = []
        #: The bookmarks dialog, for as long as one is open.
        self._dialog: "bookmark_dialog._BookmarksDialog | None" = None

        self.model = Gio.Menu()

        self._actions = Gio.SimpleActionGroup()
        for name, _label, _binding in self.FIXED:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', getattr(self, '_%s_activated' % name))
            self._actions.add_action(action)
        open_action = Gio.SimpleAction.new('open', GLib.VariantType.new('i'))
        open_action.connect('activate', self._open_activated)
        self._actions.add_action(open_action)
        window.insert_action_group(self.ACTION_PREFIX, self._actions)

        self._rebuild()
        # Methods, which the store holds weakly, and not lambdas, which
        # it would hold - and the window with them - for good.
        store = self._bookmarks_store
        store.add_bookmark += self._changed
        store.remove_bookmark += self._changed
        store.replace_bookmark += self._changed
        store.clear_bookmarks += self._changed
        store.set_bookmark_order += self._changed
        store.set_note += self._changed
        store.relocate += self._changed

    def _changed(self, *args: object) -> None:
        self._rebuild()

    def release(self) -> None:
        """Let go of the closed window: see MainUI.release()."""
        store = self._bookmarks_store
        store.add_bookmark -= self._changed
        store.remove_bookmark -= self._changed
        store.replace_bookmark -= self._changed
        store.clear_bookmarks -= self._changed
        store.set_bookmark_order -= self._changed
        store.set_note -= self._changed
        store.relocate -= self._changed
        widgets.empty_action_group(self._actions)

    def _rebuild(self) -> None:
        """Put the fixed entries and the current bookmarks in the model."""
        self._bookmarks = self._bookmarks_store.get_bookmarks()
        self.model.remove_all()

        fixed = Gio.Menu()
        for name, label, binding in self.FIXED:
            entry = Gio.MenuItem.new(label, '%s.%s' % (self.ACTION_PREFIX, name))
            # The key belongs to the keybinding manager, where the reader
            # may have changed it; the menu only shows it.
            accelerator = self._ui.accelerator(binding) if binding else None
            if accelerator:
                entry.set_attribute_value('accel', GLib.Variant('s', accelerator))
            fixed.append_item(entry)
        self.model.append_section(None, fixed)

        # There is nothing to clear from an empty list, and the entry
        # says so rather than asking a question with only one answer.
        widgets.simple_action(self._actions, 'clear').set_enabled(
            bool(self._bookmarks))
        self._update_remove()

        if self._bookmarks:
            listed = Gio.Menu()
            folders = telling_folders(self._bookmarks)
            for position, bookmark in enumerate(self._bookmarks):
                entry = Gio.MenuItem.new(
                    widgets.menu_label(bookmark.get_label(folders[position])),
                    None)
                entry.set_action_and_target_value(
                    '%s.open' % self.ACTION_PREFIX, GLib.Variant('i', position))
                listed.append_item(entry)
            self.model.append_section(None, listed)

    def _open_activated(self, action: Gio.SimpleAction,
                        target: GLib.Variant) -> None:
        bookmark = self._bookmarks[target.get_int32()]
        if widgets.take_middle_click():
            bookmark.open_in_new_instance()
        else:
            bookmark.load()

    def activate(self, name: str) -> None:
        """Run the fixed entry <name>, as the key bound to it does.

        The keybinding manager calls this.  Gio does not run a disabled
        action, so an entry set_sensitive() has disabled stays inert here
        as it does in the menu.
        """
        self._actions.activate_action(name, None)

    def refresh(self) -> None:
        """Show the keys the fixed entries answer to now."""
        self._rebuild()

    def _add_activated(self, *args: object) -> None:
        """Add the current page to the bookmarks list."""
        self._bookmarks_store.add_current_to_bookmarks()

    def _edit_activated(self, *args: object) -> None:
        """Open the bookmarks dialog, or raise the one already open.

        One at a time, as dialog_handler keeps the dialogs it opens.
        Each dialog lists the bookmarks as the store held them when it
        opened and writes that order back when it closes, so a second
        one is a second copy of a list that is already being edited:
        whichever was closed last decided the order, and a bookmark the
        other had removed was gone from a list still showing it.
        """
        if self._dialog is not None:
            self._dialog.present()
            return
        self._dialog = bookmark_dialog._BookmarksDialog(
            self._window, self._bookmarks_store)
        # 'unrealize' rather than 'destroy', which GTK4 emits when the
        # last reference to the window goes and not when it is
        # destroyed.
        self._dialog.connect('unrealize', self._edit_closed)

    def _edit_closed(self, *args: object) -> None:
        """Forget the dialog, so that the next Edit opens a new one."""
        self._dialog = None

    def _open_book(self) -> str | None:
        """The path the bookmarks of the open book are kept under, or
        None where no book is open."""
        return self._window.imagehandler.get_real_path()

    def _update_remove(self) -> None:
        """Offer to remove the open book's bookmarks only where it has
        some."""
        path = self._open_book()
        widgets.simple_action(self._actions, 'remove').set_enabled(
            path is not None
            and bool(self._bookmarks_store.bookmarks_for_path(path)))

    def _remove_activated(self, *args: object) -> None:
        """Remove the open book's bookmarks, once the reader has said yes.

        Finishing a book left its bookmark behind, to be found in the
        bookmarks dialog and removed there (upstream feature request
        17).
        """
        path = self._open_book()
        if path is None:
            return
        dialog = message_dialog.MessageDialog(
            self._window, buttons=Gtk.ButtonsType.YES_NO)
        dialog.set_text(
            _('Remove the bookmarks in "%s"?') % os.path.basename(path))
        dialog.set_default_response(Response.NO)

        def answered(response: int) -> None:
            if response == Response.YES:
                self._bookmarks_store.remove_for_path(path)

        dialog.run_async(answered)

    def _clear_activated(self, *args: object) -> None:
        """Remove every bookmark, once the reader has confirmed it."""
        self._bookmarks_store.show_clear_bookmarks_dialog(self._clear_answered)

    def _clear_answered(self, response: int) -> None:
        if response == Response.YES:
            self._bookmarks_store.clear_bookmarks()

    def set_sensitive(self, loaded: bool) -> None:
        """Set the sensitivities of menu items as appropriate if <loaded>
        represents whether a file is currently loaded in the main program
        or not.
        """
        widgets.simple_action(self._actions, 'add').set_enabled(loaded)
        self._update_remove()

def telling_folders(
        bookmarks: "Sequence[bookmark_menu_item._Bookmark]") -> list[str]:
    """For each of <bookmarks>, the folders to show before its name.

    Books are named by their file, and a series kept as one folder per
    volume names every chapter alike: the menu listed "chapter_01" for
    each of them (upstream feature request 90).  Where two books of one
    name are in different places, each is given as many of the folders
    it is in, the nearest last, as it takes to tell them apart; any
    other bookmark is given none.  Bookmarks of one book, at different
    pages, are told apart by their pages already.
    """
    folders = [''] * len(bookmarks)
    by_name: dict[str, list[int]] = {}
    for index, bookmark in enumerate(bookmarks):
        by_name.setdefault(bookmark.get_name(), []).append(index)
    for name, indices in by_name.items():
        parents = {}
        for index in indices:
            path = os.path.normpath(bookmarks[index].get_path())
            parts = os.path.dirname(path).split(os.sep)
            # A bookmark in a folder of pictures is named after the
            # folder, which is the last part already.
            if parts and parts[-1] == name:
                parts = parts[:-1]
            parents[index] = [part for part in parts if part]
        if len({tuple(parts) for parts in parents.values()}) < 2:
            continue
        depth = 1
        deepest = max(len(parts) for parts in parents.values())
        while depth < deepest:
            shown = {tuple(parents[index][-depth:]) for index in indices}
            if len(shown) == len({tuple(parts) for parts in parents.values()}):
                break
            depth += 1
        for index in indices:
            folders[index] = '/'.join(parents[index][-depth:])
    return folders

# vim: expandtab:sw=4:ts=4
