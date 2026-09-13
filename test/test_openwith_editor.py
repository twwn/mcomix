# -*- coding: utf-8 -*-

"""The editor for the "Open with" commands.

It was a Gtk.TreeView over a five-column Gtk.ListStore: three
Gtk.CellRendererTexts the user could type in, a Gtk.CellRendererToggle,
and a fifth column saying whether the line was a separator, which the
other four read to decide whether they could be edited at all.
"""

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import callback
from mcomix import openwith
from mcomix.preferences import prefs


class _StubFileHandler(object):

    file_loaded = False

    @callback.Callback
    def file_opened(self):
        pass

    @callback.Callback
    def file_closed(self):
        pass


class _StubWindow(Gtk.Window):

    def __init__(self):
        super(_StubWindow, self).__init__()
        self.filehandler = _StubFileHandler()

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
        super(OpenWithEditorTest, self).setUp()
        prefs['openwith commands'] = list(self.COMMANDS)
        self.window = _StubWindow()
        self.manager = openwith.OpenWithManager()
        self.editor = openwith.OpenWithEditor(self.window, self.manager)
        pump()

    def tearDown(self):
        self.editor.destroy()
        self.window.destroy()
        pump()
        super(OpenWithEditorTest, self).tearDown()

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

# vim: expandtab:sw=4:ts=4
