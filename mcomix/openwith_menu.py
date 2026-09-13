""" openwith_menu.py - Menu shell for the Open with... menu. """

from gi.repository import Gio, GLib

from typing import TYPE_CHECKING

from mcomix import openwith
from mcomix import widgets
from mcomix.i18n import _

if TYPE_CHECKING:
    from mcomix import main

# Reference to the OpenWith command manager
_openwith_manager = openwith.OpenWithManager()
# Reference to the edit dialog (to keep only one instance)
_openwith_edit_diag = None

class OpenWithMenu:

    """The "Open with" submenu, listing the commands the user has set up.

    What it keeps is a Gio.Menu model, which the menu bar takes.  Running
    a command goes through one action carrying the command's position as
    its target, under a prefix of its own.
    """

    #: Where this menu's actions live, as menu items address them.
    ACTION_PREFIX = 'openwith'

    def __init__(self, window: "main.MainWindow") -> None:
        """ Constructor. """
        self._window = window
        self._openwith_manager = _openwith_manager
        self._commands: "list[openwith.OpenWithCommand]" = []

        self.model = Gio.Menu()

        self._actions = Gio.SimpleActionGroup()
        run = Gio.SimpleAction.new('run', GLib.VariantType.new('i'))
        run.connect('activate', self._run_command)
        self._actions.add_action(run)
        edit = Gio.SimpleAction.new('edit', None)
        edit.connect('activate', self._edit_commands)
        self._actions.add_action(edit)
        window.insert_action_group(self.ACTION_PREFIX, self._actions)

        self._construct_menu()

        self._window.filehandler.file_opened += self._set_sensitivity
        self._window.filehandler.file_closed += self._set_sensitivity
        self._openwith_manager.set_commands += self._construct_menu


    def _construct_menu(self, *args: object) -> None:
        """ Build the menu entries from scratch. """
        self._commands = self._openwith_manager.get_commands()
        self.model.remove_all()

        # A separator in the command list starts a new section, which is
        # how a menu model spells the same thing.
        section = Gio.Menu()
        for position, command in enumerate(self._commands):
            if command.is_separator():
                if section.get_n_items():
                    self.model.append_section(None, section)
                section = Gio.Menu()
                continue
            entry = Gio.MenuItem.new(command.get_label(), None)
            entry.set_action_and_target_value('%s.run' % self.ACTION_PREFIX,
                                              GLib.Variant('i', position))
            section.append_item(entry)
        if section.get_n_items():
            self.model.append_section(None, section)

        editing = Gio.Menu()
        editing.append(_('_Edit commands'), '%s.edit' % self.ACTION_PREFIX)
        self.model.append_section(None, editing)

        self._set_sensitivity()

    def _set_sensitivity(self, *args: object) -> None:
        """ Enables or disables the commands depending on files being loaded. """
        widgets.simple_action(self._actions, 'run').set_enabled(
            self._window.filehandler.file_loaded)

    def _run_command(self, action: Gio.SimpleAction,
                     target: GLib.Variant) -> None:
        """ Execute the command the activated entry stands for. """
        command = self._commands[target.get_int32()]
        openwith.OpenWithCommand(command.get_label(), command.get_command(),
                                 command.get_cwd(),
                                 command.is_disabled_for_archives()
                                 ).execute(self._window)

    def _edit_commands(self, *args: object) -> None:
        """ When clicked, opens the command editor to set up the menu. Make
        sure the dialog isn't opened more than once. """
        global _openwith_edit_diag
        if not _openwith_edit_diag:
            _openwith_edit_diag = openwith.OpenWithEditor(self._window,
                    self._openwith_manager)
            _openwith_edit_diag.connect_after('response', self._dialog_closed)

        _openwith_edit_diag.set_visible(True)
        _openwith_edit_diag.present()

    def _dialog_closed(self, *args: object) -> None:
        """ Watch for the dialog getting closed and unset the local instance. """
        global _openwith_edit_diag
        if _openwith_edit_diag is not None:
            _openwith_edit_diag.destroy()
        _openwith_edit_diag = None

# vim: expandtab:sw=4:ts=4
