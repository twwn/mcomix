"""bookmark_menu.py - Bookmarks menu."""

from gi.repository import Gio, GLib


from mcomix import bookmark_backend
from mcomix import bookmark_dialog
from mcomix import widgets
from mcomix.i18n import _

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import bookmark_menu_item
    from mcomix import main
    from mcomix import ui as ui_module


class BookmarksMenu(object):

    """The bookmarks menu: two fixed entries, and one per bookmark.

    What it keeps is a Gio.Menu model, which the menu bar takes.  Opening
    a bookmark goes through one action carrying its position as a target,
    under a prefix of its own.
    """

    #: Where this menu's actions live, as menu items address them.
    ACTION_PREFIX = 'bookmarks'

    #: The two permanent entries, and the keys that reach them.
    FIXED = (('add', _('Add _Bookmark'), '<Control>D'),
             ('edit', _('_Edit Bookmarks...'), '<Control>B'))

    def __init__(self, ui: "ui_module.MainUI",
                 window: "main.MainWindow") -> None:
        self._window = window
        self._bookmarks_store = bookmark_backend.BookmarksStore
        self._bookmarks_store.initialize(window)
        self._bookmarks: "list[bookmark_menu_item._Bookmark]" = []

        self.model = Gio.Menu()

        self._actions = Gio.SimpleActionGroup()
        for name, label, accelerator in self.FIXED:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', getattr(self, '_%s_activated' % name))
            self._actions.add_action(action)
        open_action = Gio.SimpleAction.new('open', GLib.VariantType.new('i'))
        open_action.connect('activate', self._open_activated)
        self._actions.add_action(open_action)
        window.insert_action_group(self.ACTION_PREFIX, self._actions)

        # The accelerators name the actions rather than hanging off the
        # menu items: the items are rebuilt whenever a bookmark is added
        # or removed, and an accelerator set on one would go with it.
        for name, label, accelerator in self.FIXED:
            ui.add_shortcut(accelerator, '%s.%s' % (self.ACTION_PREFIX, name))

        self._rebuild()
        self._bookmarks_store.add_bookmark += lambda bookmark: self._rebuild()
        self._bookmarks_store.remove_bookmark += lambda bookmark: self._rebuild()


    def _rebuild(self) -> None:
        """Put the fixed entries and the current bookmarks in the model."""
        self._bookmarks = self._bookmarks_store.get_bookmarks()
        self.model.remove_all()

        fixed = Gio.Menu()
        for name, label, accelerator in self.FIXED:
            entry = Gio.MenuItem.new(label, '%s.%s' % (self.ACTION_PREFIX, name))
            entry.set_attribute_value('accel', GLib.Variant('s', accelerator))
            fixed.append_item(entry)
        self.model.append_section(None, fixed)

        if self._bookmarks:
            listed = Gio.Menu()
            for position, bookmark in enumerate(self._bookmarks):
                entry = Gio.MenuItem.new(bookmark.get_label(), None)
                entry.set_action_and_target_value(
                    '%s.open' % self.ACTION_PREFIX, GLib.Variant('i', position))
                listed.append_item(entry)
            self.model.append_section(None, listed)

    def _open_activated(self, action: Gio.SimpleAction,
                        target: GLib.Variant) -> None:
        self._bookmarks[target.get_int32()].load()

    def _add_activated(self, *args: object) -> None:
        """Add the current page to the bookmarks list."""
        self._bookmarks_store.add_current_to_bookmarks()

    def _edit_activated(self, *args: object) -> None:
        """Open the bookmarks dialog."""
        bookmark_dialog._BookmarksDialog(self._window, self._bookmarks_store)

    def set_sensitive(self, loaded: bool) -> None:
        """Set the sensitivities of menu items as appropriate if <loaded>
        represents whether a file is currently loaded in the main program
        or not.
        """
        widgets.simple_action(self._actions, 'add').set_enabled(loaded)

# vim: expandtab:sw=4:ts=4
