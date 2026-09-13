""" Tests for the "Open with" menu, which is a Gio.Menu model now. """

from gi.repository import GLib, Gtk

from . import MComixTest, pump

from mcomix import callback
from mcomix import openwith_menu
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


class _StubWindow(Gtk.Window):

    """A real window, so the menu's action group has somewhere to live."""

    def __init__(self):
        super().__init__()
        self.filehandler = _StubFileHandler()

    @callback.Callback
    def page_changed(self):
        """What the editor binds to, to re-test the selected command."""
        pass


class OpenWithMenuTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.window = _StubWindow()
        self.executed = []
        self.real_execute = openwith_menu.openwith.OpenWithCommand.execute
        openwith_menu.openwith.OpenWithCommand.execute = \
            lambda command, window: self.executed.append(command.get_label())

    def tearDown(self):
        editor = openwith_menu._openwith_edit_diag
        if editor is not None:
            editor.destroy()
            openwith_menu._openwith_edit_diag = None
        for window in Gtk.Window.list_toplevels():
            if window.get_visible() and window is not self.window:
                window.destroy()
        pump()
        openwith_menu.openwith.OpenWithCommand.execute = self.real_execute
        super().tearDown()

    def _menu(self, commands):
        prefs['openwith commands'] = commands
        return openwith_menu.OpenWithMenu(self.window)

    def _sections(self, menu):
        """The model's sections, each as a list of labels."""
        sections = []
        for index in range(menu.model.get_n_items()):
            link = menu.model.get_item_link(index, 'section')
            labels = []
            for inner in range(link.get_n_items()):
                labels.append(link.get_item_attribute_value(
                    inner, 'label').get_string())
            sections.append(labels)
        return sections

    def test_the_edit_entry_is_always_there(self):
        menu = self._menu([])
        self.assertEqual(self._sections(menu), [['_Edit commands']])

    def test_commands_are_listed_before_it(self):
        menu = self._menu([('One', 'true', '', False),
                           ('Two', 'true', '', False)])
        self.assertEqual(self._sections(menu),
                         [['One', 'Two'], ['_Edit commands']])

    def test_an_underscore_in_a_label_is_not_eaten(self):
        """A command's label is what the user typed, not a label MComix
        wrote, so it names no mnemonic - but GTK reads one out of it,
        because every item of a menu model is built with use-underline
        set.  Gtk.MenuItem, which the menu was made of before the port,
        showed the underscore."""
        menu = self._menu([('Edit_in_GIMP', 'true', '', False)])
        self.assertEqual(self._sections(menu),
                         [['Edit__in__GIMP'], ['_Edit commands']])

    def test_a_separator_starts_a_new_section(self):
        menu = self._menu([('One', 'true', '', False),
                           ('---', '', '', False),
                           ('Two', 'true', '', False)])
        self.assertEqual(self._sections(menu),
                         [['One'], ['Two'], ['_Edit commands']])

    def test_the_commands_follow_the_preference(self):
        menu = self._menu([('One', 'true', '', False)])
        openwith_menu._openwith_manager.set_commands(
            openwith_menu.openwith.OpenWithManager().get_commands())
        prefs['openwith commands'] = [('Other', 'true', '', False)]
        menu._construct_menu()
        self.assertEqual(self._sections(menu)[0], ['Other'])

    def test_running_an_entry_executes_that_command(self):
        menu = self._menu([('One', 'true', '', False),
                           ('Two', 'true', '', False)])
        # The commands are disabled until a file is open, and activating a
        # disabled action does nothing at all.
        self.window.filehandler.file_loaded = True
        self.window.filehandler.file_opened()
        menu._actions.lookup_action('run').activate(GLib.Variant('i', 1))
        self.assertEqual(self.executed, ['Two'])

    def test_the_commands_need_a_file_to_be_open(self):
        menu = self._menu([('One', 'true', '', False)])
        run = menu._actions.lookup_action('run')
        self.assertFalse(run.get_enabled())
        self.window.filehandler.file_loaded = True
        self.window.filehandler.file_opened()
        self.assertTrue(run.get_enabled())

    # -- The editor the menu opens ----------------------------------------

    def _editor(self, menu):
        menu._edit_commands()
        pump()
        return openwith_menu._openwith_edit_diag

    def _prompts(self, editor):
        return [window for window in Gtk.Window.list_toplevels()
                if window.get_visible() and window is not editor
                and window is not self.window]

    def test_editing_opens_one_editor_and_keeps_it(self):
        menu = self._menu([('One', 'true', '', False)])
        editor = self._editor(menu)
        self.assertIsNotNone(editor)
        self.assertIs(editor, self._editor(menu))

    def test_the_editor_is_forgotten_once_it_closes(self):
        menu = self._menu([('One', 'true', '', False)])
        editor = self._editor(menu)
        editor.response(Response.DELETE_EVENT)
        pump()
        self.assertIsNone(openwith_menu._openwith_edit_diag)
        self.assertIsNot(editor, self._editor(menu))

    def test_the_editor_outlives_the_question_it_asks(self):
        """The menu destroyed it on any response, so an editor with
        unsaved changes went the instant escape was pressed and the
        reader was left answering about a window that had gone."""
        menu = self._menu([('One', 'true', '', False)])
        editor = self._editor(menu)
        row = editor._command_list.get_row(0)
        editor._rewrote('command')(row, 'false')
        self.assertTrue(editor._changed)

        editor.response(Response.DELETE_EVENT)
        pump()
        prompts = self._prompts(editor)
        self.assertEqual(1, len(prompts))
        self.assertTrue(editor.get_visible(),
                        'the editor went before its question was answered')

        prompts[0].response(Response.YES)
        pump()
        self.assertFalse(editor.get_visible())
        self.assertIsNone(openwith_menu._openwith_edit_diag)
        self.assertEqual(prefs['openwith commands'],
                         [('One', 'false', '', False)])

# vim: expandtab:sw=4:ts=4
