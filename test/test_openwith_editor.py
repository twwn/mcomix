"""The editor for the "Open with" commands.

Three columns the user can type in, a checkbox, and a row that is a
separator and can be filled in nowhere. The other half of it is how the
editor closes: it owns that itself, because it is the only thing that
knows whether the question about unsaved changes has been answered.
"""

from unittest import mock

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import callback
from mcomix import openwith
from mcomix.dialog import Response
from mcomix.preferences import prefs


class _StubFileHandler:

    file_loaded = False

    @callback.Callback
    def file_opened(self):
        pass

    @callback.Callback
    def file_closed(self):
        pass


class _StubImageHandler:

    def get_current_page(self):
        return 0


class _StubWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.filehandler = _StubFileHandler()
        # Selecting a command tests it, which reads the page on screen.
        self.imagehandler = _StubImageHandler()

    @callback.Callback
    def page_changed(self):
        pass


class OpenWithEditorTest(MComixTest):

    COMMANDS = [
        ('Editor', 'gedit %F', '', False),
        ('-', '', '', False),
        ('Shell', 'sh -c ls', '/tmp', True),
    ]

    def setUp(self):
        super().setUp()
        prefs['openwith commands'] = list(self.COMMANDS)
        self.window = _StubWindow()
        self.manager = openwith.OpenWithManager()
        self.editor = openwith.OpenWithEditor(self.window, self.manager)
        # Shown, as the menu shows it: whether the editor is still on
        # screen is half of what the closing tests below look at.
        self.editor.set_visible(True)
        pump()

    def tearDown(self):
        # Before the editor, so that a prompt of the editor's that a
        # test left standing does not outlive this case and get
        # answered by the next test that goes looking for a dialog.
        for prompt in self._prompts():
            prompt.destroy()
        self.editor.destroy()
        self.window.destroy()
        pump()
        super().tearDown()

    def test_a_closed_editor_stops_testing_its_command(self):
        """A closed editor was destroyed but stayed listening, and parsed
        its selected command again for every page turned and every book
        opened for the rest of the session."""
        with mock.patch.object(openwith.OpenWithEditor, 'get_command',
                               return_value=None) as asked:
            self.window.page_changed()
            self.assertEqual(1, asked.call_count,
                             'an open editor did not test its command')
            asked.reset_mock()

            self.editor.close_editor()
            pump()
            self.window.page_changed()
            self.window.filehandler.file_opened()
            self.window.filehandler.file_closed()
        asked.assert_not_called()

    def _labels(self):
        return [row.label for row in self.editor._command_list.each_row()]

    # -- What it lists ----------------------------------------------------

    def test_the_commands_are_the_ones_in_the_preference(self):
        self.assertEqual(self._labels(), ['Editor', '-', 'Shell'])

    def test_a_row_carries_every_field_of_its_command(self):
        row = self.editor._command_list.get_row(2)
        self.assertEqual((row.label, row.command, row.cwd, row.disabled),
                         ('Shell', 'sh -c ls', '/tmp', True))

    def test_a_separator_is_the_one_row_that_cannot_be_filled_in(self):
        self.assertFalse(self.editor._command_list.get_row(1).editable)
        self.assertTrue(self.editor._command_list.get_row(0).editable)

    def test_the_commands_read_back_are_the_ones_that_went_in(self):
        self.assertEqual(
            [(command.get_label(), command.get_command(), command.get_cwd(),
              command.is_disabled_for_archives())
             for command in self.editor.get_commands()],
            self.COMMANDS)

    # -- Adding and removing ----------------------------------------------

    def test_a_new_command_goes_above_the_selected_one(self):
        self.editor._command_list.select_only(1)
        self.editor._add_command(None)
        self.assertEqual(self._labels(),
                         ['Editor', 'Command label', '-', 'Shell'])

    def test_a_new_command_goes_at_the_end_with_nothing_selected(self):
        self.editor._command_list.unselect_all()
        self.editor._add_command(None)
        self.assertEqual(self._labels()[-1], 'Command label')

    def test_a_new_separator_is_not_editable(self):
        self.editor._command_list.unselect_all()
        self.editor._add_sep_command(None)
        row = self.editor._command_list.get_row(len(self.COMMANDS))
        self.assertEqual(row.label, '-')
        self.assertFalse(row.editable)

    def test_removing_takes_the_selected_command_out(self):
        self.editor._command_list.select_only(0)
        self.editor._remove_command(None)
        self.assertEqual(self._labels(), ['-', 'Shell'])

    def test_removing_with_nothing_selected_removes_nothing(self):
        self.editor._command_list.unselect_all()
        self.editor._remove_command(None)
        self.assertEqual(self._labels(), ['Editor', '-', 'Shell'])

    # -- Reordering -------------------------------------------------------

    def test_a_command_can_be_moved_down_and_the_selection_follows(self):
        self.editor._command_list.select_only(0)
        self.editor._down_command(None)
        self.assertEqual(self._labels(), ['-', 'Editor', 'Shell'])
        self.assertEqual(self.editor._command_list.get_selected_positions(),
                         [1])

    def test_a_command_can_be_moved_up(self):
        self.editor._command_list.select_only(2)
        self.editor._up_command(None)
        self.assertEqual(self._labels(), ['Editor', 'Shell', '-'])

    def test_the_first_command_does_not_move_up(self):
        self.editor._command_list.select_only(0)
        self.editor._up_command(None)
        self.assertEqual(self._labels(), ['Editor', '-', 'Shell'])

    def test_the_last_command_does_not_move_down(self):
        self.editor._command_list.select_only(2)
        self.editor._down_command(None)
        self.assertEqual(self._labels(), ['Editor', '-', 'Shell'])

    # -- Trying a command out ---------------------------------------------

    def _tried(self, label, command, cwd):
        """Put one command in the list, select it, and answer with what
        the editor says of it: the command line, and the warning."""
        self.editor._command_list.unselect_all()
        self.editor._add_row(openwith.column_list.Row(
            label=label, command=command, cwd=cwd, disabled=False,
            editable=True))
        self.editor._command_list.select_only(len(self.COMMANDS))
        self.editor.test_command()
        return (self.editor._test_field.get_text(),
                self.editor._exec_label.get_text())

    def test_a_command_that_can_run_is_shown_as_it_would_run(self):
        self.assertEqual(('sh -c ls ""', ''),
                         self._tried('Listing', 'sh -c "ls" ""', self.tmp_dir))
        self.assertTrue(self.editor._run_button.get_sensitive())

    def test_a_working_directory_that_is_not_there_is_pointed_out(self):
        missing = self.tmp_dir + '/not-there'
        self.assertEqual(
            '"Listing" does not have a valid working directory.',
            self._tried('Listing', 'sh -c ls', missing)[1])

    def test_a_program_that_is_not_there_is_pointed_out(self):
        self.assertEqual(
            '"Missing" does not appear to have a valid executable.',
            self._tried('Missing', 'mcomix-no-such-program', '')[1])

    def test_nothing_selected_leaves_nothing_to_try(self):
        self._tried('Listing', 'sh -c ls', '')
        self.editor._command_list.unselect_all()
        pump()
        self.assertEqual('', self.editor._test_field.get_text())

    def test_the_run_button_runs_the_selected_command(self):
        self._tried('Listing', 'sh -c ls', '')
        with mock.patch.object(openwith.OpenWithCommand, 'execute') as run:
            self.editor._run_command(None)
        run.assert_called_once_with(self.window)

    # -- Editing ----------------------------------------------------------

    def test_typing_a_label_writes_it_to_the_row(self):
        row = self.editor._command_list.get_row(0)
        self.editor._rewrote('label')(row, 'Renamed')
        self.assertEqual(row.label, 'Renamed')
        self.assertTrue(self.editor._changed)

    def test_a_label_of_dashes_is_refused(self):
        """A line of dashes is what a separator is, and a command that
        turned into one could never be edited back."""
        row = self.editor._command_list.get_row(0)
        self.editor._rewrote('label')(row, '---')
        self.assertEqual(row.label, 'Editor')
        self.assertFalse(self.editor._changed)

    def test_an_empty_label_is_refused(self):
        row = self.editor._command_list.get_row(0)
        self.editor._rewrote('label')(row, '   ')
        self.assertEqual(row.label, 'Editor')

    def test_typing_the_same_text_again_is_not_a_change(self):
        row = self.editor._command_list.get_row(0)
        self.editor._rewrote('command')(row, 'gedit %F')
        self.assertFalse(self.editor._changed)

    def test_the_working_directory_can_be_typed_too(self):
        row = self.editor._command_list.get_row(0)
        self.editor._rewrote('cwd')(row, '/home')
        self.assertEqual(row.cwd, '/home')

    def test_the_archive_checkbox_writes_to_the_row(self):
        row = self.editor._command_list.get_row(0)
        self.editor._value_changed(row, True)
        self.assertTrue(row.disabled)
        self.assertTrue(self.editor._changed)

    # -- Saving -----------------------------------------------------------

    def test_saving_writes_the_list_to_the_preference(self):
        self.editor._command_list.select_only(0)
        self.editor._remove_command(None)
        self.editor.save()
        self.assertEqual(prefs['openwith commands'],
                         [('-', '', '', False), ('Shell', 'sh -c ls', '/tmp',
                                                 True)])
        self.assertFalse(self.editor._changed)

    # -- How it closes ----------------------------------------------------

    def _prompts(self):
        """Every window that is up besides the editor and its parent."""
        return [window for window in Gtk.Window.list_toplevels()
                if window.get_visible() and window is not self.editor
                and window is not self.window]

    def _change_a_command(self):
        row = self.editor._command_list.get_row(0)
        self.editor._rewrote('command')(row, 'kate %F')
        self.assertTrue(self.editor._changed)

    def test_the_save_button_saves_and_closes(self):
        self._change_a_command()
        self.editor.response(Response.ACCEPT)
        pump()
        self.assertEqual([], self._prompts())
        self.assertFalse(self.editor.get_visible())
        self.assertEqual(prefs['openwith commands'][0][1], 'kate %F')

    def test_closing_an_unchanged_editor_asks_nothing(self):
        self.editor.response(Response.DELETE_EVENT)
        pump()
        self.assertEqual([], self._prompts())
        self.assertFalse(self.editor.get_visible())

    def test_the_editor_stays_up_while_it_asks_about_changes(self):
        """It was destroyed the moment the response came, so the reader
        was asked whether to save a list that had already gone."""
        self._change_a_command()
        self.editor.response(Response.DELETE_EVENT)
        pump()
        prompts = self._prompts()
        self.assertEqual(1, len(prompts))
        self.assertTrue(self.editor.get_visible(),
                        'the editor went before the question was answered')
        # Answered, so that it is not left for the next test to find.
        prompts[0].response(Response.NO)
        pump()

    def test_answering_yes_saves_and_then_closes(self):
        self._change_a_command()
        self.editor.response(Response.DELETE_EVENT)
        pump()
        self._prompts()[0].response(Response.YES)
        pump()
        self.assertEqual(prefs['openwith commands'][0][1], 'kate %F')
        self.assertFalse(self.editor.get_visible())

    def test_answering_no_closes_without_saving(self):
        self._change_a_command()
        self.editor.response(Response.DELETE_EVENT)
        pump()
        self._prompts()[0].response(Response.NO)
        pump()
        self.assertEqual(prefs['openwith commands'][0][1], 'gedit %F')
        self.assertFalse(self.editor.get_visible())

    def test_the_window_manager_cannot_take_it_away_either(self):
        """close-request is turned into a response by the base class,
        and the editor answers that; the window itself must not go with
        it while there is still a question standing."""
        self._change_a_command()
        self.editor.emit('close-request')
        pump()
        self.assertEqual(1, len(self._prompts()))
        self.assertTrue(self.editor.get_visible())
        self._prompts()[0].response(Response.NO)
        pump()
        self.assertFalse(self.editor.get_visible())

    def test_it_announces_that_it_has_closed(self):
        """What the menu forgets its one instance on."""
        closed = []
        self.editor.editor_closed += lambda: closed.append(True)
        self.editor.response(Response.DELETE_EVENT)
        pump()
        self.assertEqual([True], closed)

# vim: expandtab:sw=4:ts=4
