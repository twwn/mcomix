""" openwith.py - Logic and storage for Open with... commands. """
import operator
import sys
import os
import re
from gi.repository import Gtk

from mcomix.dialog import Dialog
from mcomix import column_list
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix import message_dialog
from mcomix import process
from mcomix import callback
from mcomix import i18n
from mcomix.i18n import _

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main
from mcomix.dialog import Response


NO_FILE_CONTEXT, IMAGE_FILE_CONTEXT, ARCHIVE_CONTEXT = 0, 1, 2


class OpenWithException(Exception):
    pass


class OpenWithManager:
    def __init__(self) -> None:
        """ Constructor. """
        pass

    @callback.Callback
    def set_commands(self, cmds: Sequence['OpenWithCommand']) -> None:
        prefs['openwith commands'] = [(cmd.get_label(), cmd.get_command(),
                                       cmd.get_cwd(), cmd.is_disabled_for_archives())
                                      for cmd in cmds]

    def get_commands(self) -> list['OpenWithCommand']:
        # Early versions stored a label and a command and nothing else,
        # so the two fields after them are read only if they are there.
        return [OpenWithCommand(str(stored[0]), str(stored[1]),
                                str(stored[2]) if len(stored) > 2 else '',
                                bool(stored[3]) if len(stored) > 3 else False)
                for stored in prefs['openwith commands']]


class OpenWithCommand:
    def __init__(self, label: str, command: str, cwd: str,
                 disabled_for_archives: bool) -> None:
        self.label = label
        self.command = command.strip()
        self.cwd = cwd.strip()

        self.disabled_for_archives = bool(disabled_for_archives)

    def get_label(self) -> str:
        return self.label

    def get_command(self) -> str:
        return self.command

    def get_cwd(self) -> str:
        return self.cwd

    def is_disabled_for_archives(self) -> bool:
        return self.disabled_for_archives

    def is_separator(self) -> bool:
        return bool(re.match(r'^-+$', self.get_label().strip()))

    def execute(self, window: 'main.MainWindow') -> None:
        """ Spawns a new process with the given executable
        and arguments. """
        if (self.is_disabled_for_archives() and
                window.filehandler.archive_type is not None):
            window.osd.show(_("'%s' is disabled for archives.") % self.get_label())
            return

        try:
            # The command's directory is the command's own: changing
            # MComix' working directory for it would change it for every
            # thread MComix runs as well.
            workdir = self.parse(window, text=self.get_cwd())[0] \
                if self.is_valid_workdir(window) else None

            # The command runs on its own from here; on Unix the SIGCHLD
            # handler installed in run.py collects it once it exits.
            args = self.parse(window)
            if sys.platform == 'win32':
                process.Win32Popen(args, workdir)
            else:
                process.popen(args, stdout=process.NULL, workdir=workdir)

        except Exception as e:
            text = _("Could not run command %(cmdlabel)s: %(exception)s") % \
                {'cmdlabel': self.get_label(), 'exception': str(e)}
            window.osd.show(text)

    def is_executable(self, window: 'main.MainWindow') -> bool:
        """ Check if a name is executable. This name can be either
        a relative path, when the executable is in PATH, or an
        absolute path. """
        args = self.parse(window)
        if not args:
            return False

        if self.is_valid_workdir(window):
            workdir = self.parse(window, text=self.get_cwd())[0]
        else:
            workdir = os.getcwd()

        exe = process.find_executable((args[0],), workdir=workdir)

        return exe is not None

    def is_valid_workdir(self, window: 'main.MainWindow',
                         allow_empty: bool = False) -> bool:
        """ Check if the working directory is valid. """
        cwd = self.get_cwd().strip()
        if not cwd:
            return allow_empty

        args = self.parse(window, text=cwd)
        if len(args) > 1:
            return False

        dir = args[0]
        if os.path.isdir(dir) and os.access(dir, os.X_OK):
            return True

        return False

    def parse(self, window: 'main.MainWindow', text: str = '') -> list[str]:
        """ Parses the command string and replaces special characters
        with their respective variable contents. Returns a list of
        arguments. """
        if not text:
            text = self.get_command()
        if not text.strip():
            raise OpenWithException(_('Command line is empty.'))

        return self._commandline_to_arguments(text, window,
                                              self._get_context_type(window))

    def _commandline_to_arguments(self, line: str, window: 'main.MainWindow',
                                  context_type: int) -> list[str]:
        """ Split <line> into the arguments to pass to Popen.

        Spaces separate arguments unless they stand inside a pair of
        quotes; "%" begins a variable, which _expand_variable() puts a
        file name in place of, and "%%" and \'%"\' are a per cent sign
        and a quotation mark of their own.

        The environment\'s own variables are expanded in what the reader
        typed, and only there: a file name that reads as one is a file
        name.  So the two are kept apart as the line is walked, <typed>
        holding the characters that came from the command line and <buf>
        what the argument has come to so far.

        The parser was contributed by Ark <aaku@users.sf.net>.
        """
        result = []
        typed = ""
        buf = ""
        quote = False
        escape = False
        inarg = False

        def expanded() -> str:
            """What has been typed since the last expansion, expanded."""
            nonlocal typed
            text = os.path.expandvars(typed)
            typed = ""
            return text

        for c in line:
            if escape:
                buf += expanded()
                if c == '%' or c == '"':
                    # Kept out of the expansion above: win32 writes the
                    # environment\'s variables between per cent signs, so
                    # a doubled one would be read as the start of a name.
                    buf += c
                else:
                    buf += self._expand_variable(c, window, context_type)
                escape = False
            elif c == ' ' or c == '\t':
                if quote:
                    typed += c
                elif inarg:
                    result.append(buf + expanded())
                    buf = ""
                    inarg = False
            else:
                if c == '"':
                    quote = not quote
                elif c == '%':
                    escape = True
                else:
                    typed += c
                inarg = True

        if escape:
            raise OpenWithException(
                _("Incomplete escape sequence. "
                  "For a literal '%', use '%%'."))
        if quote:
            raise OpenWithException(
                _("Incomplete quote sequence. "
                  "For a literal '\"', use '%\"'."))

        if inarg:
            result.append(buf + expanded())
        return result

    def _expand_variable(self, identifier: str, window: 'main.MainWindow',
                         context_type: int) -> str:
        """ Replaces variables with their respective file
        or archive path. """

        if not (context_type & IMAGE_FILE_CONTEXT) and identifier in ('f', 'd', 'b', 's', 'F', 'D', 'B', 'S'):
            raise OpenWithException(
                _("File-related variables can only be used for files."))

        if not (context_type & ARCHIVE_CONTEXT) and identifier in ('a', 'c', 'A', 'C'):
            raise OpenWithException(
                _("Archive-related variables can only be used for archives."))

        # Both of these answer None where there is nothing open, and
        # every variable below is built out of one of them, so None is
        # turned into the complaint this method raises for everything
        # else it cannot do before it can reach os.path.
        def base_path() -> str:
            answer = window.filehandler.get_path_to_base()
            if answer is None:
                raise OpenWithException(
                    _("File-related variables can only be used for files."))
            return answer

        def page_path() -> str:
            answer = window.imagehandler.get_path_to_page()
            if answer is None:
                raise OpenWithException(
                    _("File-related variables can only be used for files."))
            return answer

        if identifier == '/':
            return os.path.sep
        elif identifier == 'a':
            return window.filehandler.get_base_filename()
        elif identifier == 'd':
            return os.path.basename(os.path.dirname(page_path()))
        elif identifier == 'f':
            name = window.imagehandler.get_page_filename()
            if not isinstance(name, str):
                raise OpenWithException(
                    _("File-related variables can only be used for files."))
            return name
        elif identifier == 'c':
            return os.path.basename(os.path.dirname(base_path()))
        elif identifier == 'b':
            if (context_type & ARCHIVE_CONTEXT):
                return window.filehandler.get_base_filename()  # same as %a
            else:
                return os.path.basename(os.path.dirname(page_path()))  # same as %d
        elif identifier == 's':
            if (context_type & ARCHIVE_CONTEXT):
                return os.path.basename(os.path.dirname(base_path()))  # same as %c
            else:
                return os.path.basename(os.path.dirname(os.path.dirname(page_path())))
        elif identifier == 'A':
            return base_path()
        elif identifier == 'D':
            return os.path.normpath(os.path.dirname(page_path()))
        elif identifier == 'F':
            return os.path.normpath(page_path())
        elif identifier == 'C':
            return os.path.dirname(base_path())
        elif identifier == 'B':
            if (context_type & ARCHIVE_CONTEXT):
                return base_path()  # same as %A
            else:
                return os.path.normpath(os.path.dirname(page_path()))  # same as %D
        elif identifier == 'S':
            if (context_type & ARCHIVE_CONTEXT):
                return os.path.dirname(base_path())  # same as %C
            else:
                return os.path.dirname(os.path.dirname(page_path()))
        else:
            raise OpenWithException(
                _("Invalid escape sequence: %%%s") % identifier)

    def _get_context_type(self, window: 'main.MainWindow') -> int:
        context = 0
        if not window.filehandler.file_loaded:
            context = NO_FILE_CONTEXT  # no file loaded
        elif window.filehandler.archive_type is not None:
            context = IMAGE_FILE_CONTEXT | ARCHIVE_CONTEXT  # archive loaded
        else:
            context = IMAGE_FILE_CONTEXT  # image loaded (no archive)
        if not window.imagehandler.get_current_page():
            context &= ~IMAGE_FILE_CONTEXT  # empty archive
        return context


class OpenWithEditor(Dialog):
    """ The editor for changing and creating external commands. This window
    keeps its own internal model once initialized, and will overwrite
    the external model (i.e. preferences) only when properly closed. """

    def __init__(self, window: 'main.MainWindow',
                 openwithmanager: OpenWithManager) -> None:
        super().__init__(
            title=_('Edit external commands'), transient_for=window)
        self.set_destroy_with_parent(True)
        self._window = window
        self._openwith = openwithmanager
        self._changed = False

        self._command_list = column_list.ColumnListView()
        self.connect_while_open(self._command_list.selection,
                                'selection-changed', self._item_selected)
        self._add_button = Gtk.Button.new_with_mnemonic(_('_Add'))
        self._add_button.connect('clicked', self._add_command)
        self._add_sep_button = Gtk.Button.new_with_mnemonic(_('Add _separator'))
        self._add_sep_button.connect('clicked', self._add_sep_command)
        self._remove_button = Gtk.Button.new_with_mnemonic(_('_Remove'))
        self._remove_button.connect('clicked', self._remove_command)
        self._remove_button.set_sensitive(False)
        self._up_button = Gtk.Button.new_with_mnemonic(_('_Up'))
        self._up_button.connect('clicked', self._up_command)
        self._up_button.set_sensitive(False)
        self._down_button = Gtk.Button.new_with_mnemonic(_('_Down'))
        self._down_button.connect('clicked', self._down_command)
        self._down_button.set_sensitive(False)
        self._run_button = Gtk.Button.new_with_mnemonic(_('Run _command'))
        self._run_button.connect('clicked', self._run_command)
        self._run_button.set_sensitive(False)
        self._test_field = Gtk.Entry()
        self._test_field.set_property('editable', False)
        self._exec_label = Gtk.Label()
        self._exec_label.set_xalign(0)
        self._exec_label.set_yalign(0)
        self._set_exec_text('')
        self._save_button = self.add_button(_('_Save'), Response.ACCEPT)
        self.set_default_response(Response.ACCEPT)

        self._layout()
        self._setup_table()

        self.connect('response', self._response)
        # After the base class's own handler, which turns the close into
        # a response; this one only stops the window going with it.
        self.connect('close-request', self._refuse_to_close)
        self._window.page_changed += self.test_command
        self._window.filehandler.file_opened += self.test_command
        self._window.filehandler.file_closed += self.test_command
        # 'unrealize' rather than 'destroy', which GTK4 emits only when
        # the last reference to the window goes - whenever Python's
        # collector gets round to it, not when the window is closed.  Closing
        # the main window takes the editor with it without going
        # through close_editor(), and unrealizes it all the same.
        self.connect('unrealize', self._stop_following)

        self.set_default_size(600, 400)

    def _stop_following(self, *args: object) -> None:
        """Stop testing the selected command against the page shown.

        The callbacks hold the editor only weakly, but a destroyed
        editor is not collected, and one left listening would go on
        parsing its selected command for every page turned and every
        book opened, once for each time it had been opened.
        """
        self._window.page_changed -= self.test_command
        self._window.filehandler.file_opened -= self.test_command
        self._window.filehandler.file_closed -= self.test_command

    def save(self) -> None:
        """Hand the commands in the list back to the manager, which
        writes them out."""
        commands = self.get_commands()
        self._openwith.set_commands(commands)
        self._changed = False

    def get_commands(self) -> list[OpenWithCommand]:
        """ Retrieves a list of OpenWithCommand instances from
        the list model. """
        return [self._command_of(row)
                for row in self._command_list.each_row()]

    @staticmethod
    def _command_of(row: column_list.Row) -> OpenWithCommand:
        """ The command the fields of <row> describe. """
        return OpenWithCommand(row.label, row.command, row.cwd, row.disabled)

    def get_command(self) -> OpenWithCommand | None:
        """ Retrieves the selected command object. """
        row = self._command_list.get_selected_row()
        return self._command_of(row) if row is not None else None

    def test_command(self) -> None:
        """ Parses the currently selected command and displays the output in the
        text box next to the button. """
        command = self.get_command()
        self._run_button.set_sensitive(False)
        if not command:
            return

        # Test only if the selected field is a valid command
        if command.is_separator():
            self._test_field.set_text(_('This is a separator pseudo-command.'))
            self._set_exec_text('')
            return

        try:
            args = list(map(self._quote_if_necessary, command.parse(self._window)))
            self._test_field.set_text(" ".join(map(i18n.to_display_string, args)))
            self._run_button.set_sensitive(True)

            if not command.is_valid_workdir(self._window, allow_empty=True):
                self._set_exec_text(
                    _('"%s" does not have a valid working directory.') % command.get_label())
            elif not command.is_executable(self._window):
                self._set_exec_text(
                    _('"%s" does not appear to have a valid executable.') % command.get_label())
            else:
                self._set_exec_text('')
        except OpenWithException as e:
            self._test_field.set_text(str(e))
            self._set_exec_text('')

    def _add_command(self, button: Gtk.Button) -> None:
        """ Add a new empty label-command line to the list. """
        self._add_row(column_list.Row(label=_('Command label'), command='',
                                      cwd='', disabled=False, editable=True))

    def _add_sep_command(self, button: Gtk.Button) -> None:
        """ Adds a new separator line. """
        self._add_row(column_list.Row(label='-', command='', cwd='',
                                      disabled=False, editable=False))

    def _add_row(self, row: column_list.Row) -> None:
        """ Put <row> above the selected line, or at the end. """
        selected = self._command_list.get_selected_positions()
        if selected:
            self._command_list.insert_row(selected[0], row)
        else:
            self._command_list.append_row(row)
        self._changed = True

    def _remove_command(self, button: Gtk.Button) -> None:
        """ Removes the currently selected command from the list. """
        row = self._command_list.get_selected_row()
        if row is not None:
            self._command_list.remove_row(row)
            self._changed = True

    def _up_command(self, button: Gtk.Button) -> None:
        """ Moves the selected command up by one. """
        self._move_command(-1)

    def _down_command(self, button: Gtk.Button) -> None:
        """ Moves the selected command down by one. """
        self._move_command(1)

    def _move_command(self, offset: int) -> None:
        """ Moves the selected command <offset> lines along the list. """
        selected = self._command_list.get_selected_positions()
        if not selected:
            return
        position = selected[0]
        self._command_list.move_row(position, position + offset)
        # Following the line that moved, the way the selection did when
        # a Gtk.TreeView swapped two of its rows.
        self._command_list.select_only(
            max(0, min(position + offset,
                       self._command_list.store.get_n_items() - 1)))
        self._changed = True

    def _run_command(self, button: Gtk.Button) -> None:
        """ Executes the selected command in the current context. """
        command = self.get_command()
        if command and not command.is_separator():
            command.execute(self._window)

    def _item_selected(self, *args: object) -> None:
        """ Enable or disable buttons that depend on an item being selected. """
        selected = bool(self._command_list.get_selected_positions())
        for button in (self._remove_button, self._up_button,
                       self._down_button):
            button.set_sensitive(selected)

        if selected:
            self.test_command()
        else:
            self._test_field.set_text('')

    def _set_exec_text(self, text: str) -> None:
        self._exec_label.set_text(text)

    def _layout(self) -> None:
        """ Create and lay out UI components. """
        # All these boxes basically are just for adding a 4px border
        vbox = self.get_content_area()
        hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.pack(vbox, hbox, True, True, 4)
        content = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        content.set_spacing(6)
        widgets.pack(hbox, content, True, True, 4)

        scroll_window = Gtk.ScrolledWindow()
        scroll_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll_window.set_child(self._command_list)
        widgets.pack(content, scroll_window, True, True, 0)

        buttonbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.pack(buttonbox, self._add_button, False, False, 0)
        widgets.pack(buttonbox, self._add_sep_button, False, False, 0)
        widgets.pack(buttonbox, self._remove_button, False, False, 0)
        widgets.pack(buttonbox, self._up_button, False, False, 0)
        widgets.pack(buttonbox, self._down_button, False, False, 0)
        widgets.pack(content, buttonbox, False, False, 0)

        preview_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.pack(preview_box, Gtk.Label(label=_('Preview:')), False, False, 0)
        widgets.pack(preview_box, self._test_field, True, True, 4)
        widgets.pack(preview_box, self._run_button, False, False, 0)
        widgets.pack(content, preview_box, False, False, 0)

        widgets.pack(content, self._exec_label, False, False, 0)

        linklabel = Gtk.Label()
        linklabel.set_markup(_('Please refer to the <a href="%s">external command documentation</a> '
                               'for a list of usable variables and other hints.') %
                             'https://github.com/twwn/mcomix/blob/main/docs/external-commands.md')
        linklabel.set_xalign(0)
        linklabel.set_yalign(0)
        widgets.pack(content, linklabel, False, False, 4)

    def _setup_table(self) -> None:
        """ Initializes the list with settings and data. """
        # A separator has nothing to fill in, which is what a row's
        # 'editable' says: the three text cells and the checkbox all
        # read it.
        editable = operator.attrgetter('editable')
        for attr, label in (('label', _('Label')),
                            ('command', _('Command')),
                            ('cwd', _('Working directory'))):
            self._command_list.add_editable_column(
                label, attr, self._rewrote(attr), editable=editable,
                expand=attr == 'command')

        # The 'Disabled in archives' field is shown as toggle button
        self._command_list.add_toggle_column(
            _('Disabled in archives'), 'disabled', self._value_changed,
            activatable=editable)

        self._command_list.set_rows(
            column_list.Row(label=command.get_label(),
                            command=command.get_command(),
                            cwd=command.get_cwd(),
                            disabled=command.is_disabled_for_archives(),
                            editable=not command.is_separator())
            for command in self._openwith.get_commands())

        self._command_list.set_reorderable(True)

    def _rewrote(self, attr: str) -> "Callable[[column_list.Row, str], None]":
        """ Answer an edit of the <attr> field of a row. """
        def rewrote(row: column_list.Row, new_text: str) -> None:
            # Prevent changing command to separator, and completely
            # removing label
            if attr == 'label' and (not new_text.strip()
                                    or re.match(r'^-+$', new_text)):
                # Put back what the row still says, which is what the
                # cell was showing before the edit.
                row.changed()
                return

            if getattr(row, attr) != new_text:
                setattr(row, attr, new_text)
                self._changed = True
            self.test_command()
        return rewrote

    def _value_changed(self, row: column_list.Row, value: bool) -> None:
        """ Called when a toggle field is changed """
        row.disabled = value
        self._changed = True

    def _response(self, dialog: "OpenWithEditor", response: int) -> None:
        """Answer the editor: Save saves, anything else offers to.

        Every way out ends in close_editor(), and the editor stays on
        screen while the question about unsaved changes is asked, so
        that the prompt stands over the list it asks about.
        """
        if response == Response.ACCEPT:
            # The Save button is only enabled if all commands are valid
            self.save()
            self.close_editor()
        elif self._changed:
            confirm_diag = message_dialog.MessageDialog(
                self, modal=True, buttons=Gtk.ButtonsType.YES_NO)
            confirm_diag.set_text(_('Save changes to commands?'),
                                  _('You have made changes to the list of external commands that '
                                    'have not been saved yet. Press "Yes" to save all changes, '
                                    'or "No" to discard them.'))

            def confirmed(answer: int) -> None:
                if answer == Response.YES:
                    self.save()
                self.close_editor()

            confirm_diag.run_async(confirmed)
        else:
            self.close_editor()

    def close_editor(self) -> None:
        """Take the editor down, and say so.

        The editor closes itself rather than leaving that to whoever
        opened it, because only it knows when the question about unsaved
        changes has been answered.
        """
        self.destroy()
        self.editor_closed()

    @callback.Callback
    def editor_closed(self) -> None:
        """Announce that the editor has gone, once it has.

        Whoever opened it keeps the one instance there is meant to be,
        and needs to forget it when it goes.
        """
        pass

    def _refuse_to_close(self, *args: object) -> bool:
        """Never let the window manager take the editor down.

        The base class has already turned the close into a response by
        the time this runs, and _response() above closes the editor when
        it is ready to - which for an editor with unsaved changes is
        after the reader has answered, not before.
        """
        return True

    def _quote_if_necessary(self, arg: str) -> str:
        """ Quotes a command line argument if necessary. """
        if arg == "":
            return '""'
        if sys.platform == 'win32':
            # based on http://msdn.microsoft.com/en-us/library/17w5ykft%28v=vs.85%29.aspx
            backslash_counter = 0
            needs_quoting = False
            result = ""
            for c in arg:
                if c == '\\':
                    backslash_counter += 1
                else:
                    if c == '\"':
                        result += '\\' * (2 * backslash_counter + 1)
                    else:
                        result += '\\' * backslash_counter
                    backslash_counter = 0
                    result += c
                if c == ' ':
                    needs_quoting = True

            if needs_quoting:
                result += '\\' * (2 * backslash_counter)
                result = '"' + result + '"'
            else:
                result += '\\' * backslash_counter
            return result
        else:
            # simplified version of
            # http://www.gnu.org/software/bash/manual/bashref.html#Double-Quotes
            arg = arg.replace('\\', '\\\\')
            arg = arg.replace('"', '\\"')
            if " " in arg:
                return '"' + arg + '"'
            return arg


# vim: expandtab:sw=4:ts=4
