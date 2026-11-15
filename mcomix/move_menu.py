"""move_menu.py - The "Move to" submenu of the right-click menus."""

import os

from gi.repository import Gio, GLib, Gtk

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from mcomix import bookmark_backend
from mcomix import constants
from mcomix import file_chooser_simple_dialog
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix import i18n
from mcomix.i18n import _

if TYPE_CHECKING:
    from mcomix import main
    from mcomix import recent as recent_module


class _MoveMenu:

    """A "Move to" submenu, listing the directories what is to be moved
    could be moved into.

    What it keeps is a Gio.Menu model, which the right-click menu takes.
    Moving goes through one action carrying the destination as its
    target, under a prefix of its own.

    Nothing knows where a reader wants their books to end up, so the
    menu offers the three sets of directories MComix does know about,
    each as a section of its own: the ones moved to before, the ones
    holding bookmarked books, and the ones holding recently opened
    files.  A destination that is in none of them is reached through the
    chooser at the foot, and by being chosen joins the first set.
    """

    #: Where this menu's actions live, as menu items address them.
    ACTION_PREFIX = 'moveto'

    #: How many directories each section offers at most.  A menu that
    #: has to be scrolled is no quicker than the chooser.
    SECTION_LIMIT = 5

    #: How many directories the "moved to before" list remembers.  It is
    #: longer than the section shows, so that a detour to one odd
    #: destination does not push the usual ones off the end.
    REMEMBERED = 10

    #: How wide a destination's label may be, in characters, before its
    #: middle is left out.
    _LABEL_WIDTH = 48

    def __init__(self, host: Gtk.Widget) -> None:
        """<host> is where the menu is shown, and its actions are
        found."""
        self.model = Gio.Menu()

        self._actions = Gio.SimpleActionGroup()
        # The directory as the bytes of its name, not as a string: a
        # GVariant string has to be UTF-8, and a directory name on disk
        # need not be.
        move = Gio.SimpleAction.new('move', GLib.VariantType.new('ay'))
        move.connect('activate', self._move_activated)
        self._actions.add_action(move)
        other = Gio.SimpleAction.new('other', None)
        other.connect('activate', self._other_activated)
        self._actions.add_action(other)
        host.insert_action_group(self.ACTION_PREFIX, self._actions)

    def _moving(self) -> list[str]:
        """The files a move would move."""
        raise NotImplementedError

    def _can_move(self) -> bool:
        """Whether there is anything to move."""
        raise NotImplementedError

    def _move(self, directory: str) -> None:
        """Move what is to be moved into <directory>."""
        raise NotImplementedError

    def _parent(self) -> Gtk.Window:
        """The window the chooser of another folder belongs to."""
        raise NotImplementedError

    def _recently_opened(self) -> list[str]:
        """The directories recently opened files came out of."""
        raise NotImplementedError

    def release(self) -> None:
        """Let go of the closed window: see MainUI.release()."""
        widgets.empty_action_group(self._actions)

    def remember(self, directory: str) -> None:
        """Put <directory> at the head of the destinations moved to."""
        remembered = [path for path in prefs['recent move destinations']
                      if path != directory]
        remembered.insert(0, directory)
        prefs['recent move destinations'] = remembered[:self.REMEMBERED]
        self._rebuild()

    def _rebuild(self, *args: object) -> None:
        """Build the menu entries from scratch."""
        self.model.remove_all()

        # A directory is offered once, in the first section it belongs
        # to, and the one the file is in already is offered nowhere:
        # moving a file to where it is would be refused as a name that
        # is taken, by itself.
        seen = {os.path.dirname(os.path.abspath(path))
                for path in self._moving()}

        sections = ((_('Moved to before'), prefs['recent move destinations']),
                    (_('From bookmarks'), self._bookmarked()),
                    (_('Opened before'), self._recently_opened()))
        for label, directories in sections:
            section = Gio.Menu()
            for directory in directories:
                directory = os.path.abspath(directory)
                if directory in seen or not self._is_destination(directory):
                    continue
                seen.add(directory)
                entry = Gio.MenuItem.new(self._label_for(directory), None)
                entry.set_action_and_target_value(
                    '%s.move' % self.ACTION_PREFIX,
                    GLib.Variant.new_bytestring(os.fsencode(directory)))
                section.append_item(entry)
                if section.get_n_items() >= self.SECTION_LIMIT:
                    break
            if section.get_n_items():
                self.model.append_section(label, section)

        chooser = Gio.Menu()
        chooser.append(_('Other folder...'), '%s.other' % self.ACTION_PREFIX)
        self.model.append_section(None, chooser)

        self._set_sensitivity()

    def update(self) -> None:
        """Offer what can be moved now, and where to."""
        self._rebuild()

    def _set_sensitivity(self, *args: object) -> None:
        can_move = self._can_move()
        for name in ('move', 'other'):
            widgets.simple_action(self._actions, name).set_enabled(can_move)

    @staticmethod
    def _is_destination(directory: str) -> bool:
        """Whether a file could be moved into <directory> at all.

        A bookmark or a recent file outlives the directory it named, and
        one that cannot be written to would only fail once it was
        picked, so neither is offered.
        """
        return os.path.isdir(directory) and os.access(directory, os.W_OK)

    @staticmethod
    def _bookmarked() -> list[str]:
        """The directories holding bookmarked books, newest first."""
        return [bookmark.get_directory() for bookmark
                in reversed(bookmark_backend.BookmarksStore.get_bookmarks())]

    @classmethod
    def _label_for(cls, directory: str) -> str:
        """How the menu names <directory>.

        The whole path, not the last component of it: a menu of three
        entries all reading "comics" says nothing about which is which.
        The home directory is written as the tilde a shell would use,
        and a path too long to show has its middle left out, keeping the
        end - which is the half that tells destinations apart.
        """
        home = constants.HOME_DIR
        if directory == home or directory.startswith(home + os.sep):
            directory = '~' + directory[len(home):]
        if len(directory) > cls._LABEL_WIDTH:
            head = (cls._LABEL_WIDTH - 3) // 3
            directory = '%s...%s' % (directory[:head],
                                     directory[head + 3 - cls._LABEL_WIDTH:])
        # A name that is not UTF-8 is shown with what cannot be read of
        # it replaced: a menu label has to be UTF-8.
        return widgets.menu_label(i18n.to_display_string(directory))

    def _move_activated(self, action: Gio.SimpleAction,
                        target: GLib.Variant) -> None:
        self._move(os.fsdecode(bytes(target.get_bytestring())))

    def _other_activated(self, *args: object) -> None:
        """Ask for a directory that is on none of the lists."""
        dialog = file_chooser_simple_dialog.SimpleFileChooserDialog(
            Gtk.FileChooserAction.SELECT_FOLDER, self._parent(),
            folder=prefs['path of last browsed in filechooser'])
        dialog.set_title(_('Move to folder'))

        def chosen(paths: list[str]) -> None:
            dialog.destroy()
            if paths:
                self._move(paths[0])

        dialog.run_async(chosen)


class MoveToMenu(_MoveMenu):

    """The main window's "Move to" submenu, for the file that is open -
    or the archive it is a page of."""

    def __init__(self, window: "main.MainWindow",
                 recent: "recent_module.RecentFilesMenu") -> None:
        super().__init__(window)
        self._window = window
        self._recent = recent
        self._rebuild()
        # What is on offer depends on the file that is open - the
        # directory it is in already is not a destination - so the menu
        # is built again whenever that changes.
        self._window.filehandler.file_opened += self._rebuild
        self._window.filehandler.file_closed += self._rebuild

    def _moving(self) -> list[str]:
        current = self._window.imagehandler.get_real_path()
        return [current] if current else []

    def _can_move(self) -> bool:
        # Not until a file is open.
        return self._window.filehandler.file_loaded

    def _move(self, directory: str) -> None:
        self._window.file_actions.move_current_file(directory)

    def _parent(self) -> Gtk.Window:
        return self._window

    def _recently_opened(self) -> list[str]:
        return [os.path.dirname(path) for path in self._recent.paths()]


class BooksMoveToMenu(_MoveMenu):

    """The same submenu over the library's covers, for the books
    selected there rather than the file that is open.  It is built
    each time the menu opens (update()), for the books selected then."""

    def __init__(self, host: Gtk.Widget,
                 selected: "Callable[[], Sequence[str]]",
                 move: "Callable[[str], None]",
                 recent: "Callable[[], Sequence[str]]") -> None:
        """<selected> gives the paths of the books selected, <move>
        moves them into the directory it is given, and <recent> gives
        the paths of the files recently opened."""
        super().__init__(host)
        self._host = host
        self._selected = selected
        self._move_books = move
        self._recent_paths = recent

    def _moving(self) -> list[str]:
        return list(self._selected())

    def _can_move(self) -> bool:
        return bool(self._selected())

    def _move(self, directory: str) -> None:
        self._move_books(directory)

    def _parent(self) -> Gtk.Window:
        root = self._host.get_root()
        assert isinstance(root, Gtk.Window), 'the covers are in no window'
        return root

    def _recently_opened(self) -> list[str]:
        return [os.path.dirname(path) for path in self._recent_paths()]

# vim: expandtab:sw=4:ts=4
