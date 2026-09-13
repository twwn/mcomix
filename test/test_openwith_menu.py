# -*- coding: utf-8 -*-

""" Tests for the "Open with" menu, which is a Gio.Menu model now. """

from gi.repository import GLib, Gtk

from . import MComixTest

from mcomix import callback
from mcomix import openwith_menu
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

    """A real window, so the menu's action group has somewhere to live."""

    def __init__(self):
        super(_StubWindow, self).__init__()
        self.filehandler = _StubFileHandler()


class OpenWithMenuTest(MComixTest):

    def setUp(self):
        super(OpenWithMenuTest, self).setUp()
        self.window = _StubWindow()
        self.executed = []
        self.real_execute = openwith_menu.openwith.OpenWithCommand.execute
        openwith_menu.openwith.OpenWithCommand.execute = \
            lambda command, window: self.executed.append(command.get_label())

    def tearDown(self):
        openwith_menu.openwith.OpenWithCommand.execute = self.real_execute
        super(OpenWithMenuTest, self).tearDown()

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

# vim: expandtab:sw=4:ts=4
