# -*- coding: utf-8 -*-

"""The keyboard shortcut editor in the preferences dialog.

It was a Gtk.TreeStore of groups and the actions under them, drawn by a
Gtk.TreeView whose shortcut columns were Gtk.CellRendererAccels. What
the renderers did - taking the next combination pressed, clearing on
backspace, and taking a shortcut away from wherever it was bound before
- is what these are about.
"""

import os

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import constants
from mcomix import keybindings
from mcomix import keybindings_editor
from mcomix import preferences_dialog


class _StubUIManager(object):

    def __init__(self):
        self.announced = []

    def set_accelerator(self, name, accelerator):
        self.announced.append((name, accelerator))


class _StubWindow(object):

    def __init__(self):
        self.uimanager = _StubUIManager()


class KeybindingEditorTest(MComixTest):

    ACTION = 'next_page'
    OTHER = 'previous_page'

    def setUp(self):
        super(KeybindingEditorTest, self).setUp()
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)
        self.window = _StubWindow()
        self.manager = keybindings._KeybindingManager(self.window)
        self.manager.register(self.ACTION, ['<Control>n'], lambda *a: None)
        self.manager.register(self.OTHER, ['<Control>p'], lambda *a: None)
        self.editor = keybindings_editor.KeybindingEditorWindow(self.manager)
        pump()
        # register() announces what it bound; the tests are about what
        # the editor announces afterwards.
        self.window.uimanager.announced = []

    def _row(self, action):
        return self.editor.action_rows[action]

    def _shown(self):
        return [row.title for row in self.editor._list.each_row()]

    # -- How wide it comes out --------------------------------------------

    def test_the_list_fits_the_width_the_preferences_dialog_opens_at(self):
        """The Shortcuts tab is the widest thing in the dialog - a name
        and four shortcuts beside it - so it is what the dialog's width
        is chosen for.  Where it does not fit, the columns are squeezed
        down to their minimum and the names are ellipsized away to
        nothing before the list will scroll sideways.
        """
        wanted = self.editor._list.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        room = (preferences_dialog._PreferencesDialog._DEFAULT_WIDTH
                - self._DIALOG_CHROME)
        self.assertLessEqual(wanted, room)

    #: What the dialog's own borders and the notebook's take out of the
    #: width the dialog is given, measured on GTK 4.22.
    _DIALOG_CHROME = 32

    # -- What it lists ----------------------------------------------------

    def test_only_the_groups_are_shown_until_one_is_opened(self):
        """A Gtk.TreeView showed a tree collapsed, and this one is a
        list of eleven groups rather than of two hundred actions."""
        groups = sorted(set(info['group']
                            for info in keybindings.BINDING_INFO.values()))
        self.assertEqual(self._shown(), groups)

    def test_the_actions_of_a_group_are_under_it(self):
        group = keybindings.BINDING_INFO[self.ACTION]['group']
        self.editor._list.expand_to(self._row(self.ACTION))
        shown = self._shown()
        title = keybindings.BINDING_INFO[self.ACTION]['title']
        self.assertIn(title, shown)
        self.assertLess(shown.index(group), shown.index(title))

    def test_a_group_heading_stands_for_no_action(self):
        heading = self.editor._list.get_row(0)
        self.assertIsNone(heading.action)

    def test_an_action_shows_the_shortcut_it_is_bound_to(self):
        self.assertEqual(self._row(self.ACTION).key0, '<Control>n')

    def test_an_action_with_one_shortcut_shows_nothing_in_the_others(self):
        self.assertEqual(self._row(self.ACTION).key1, '')

    # -- Rebinding --------------------------------------------------------

    def test_pressing_a_combination_binds_it(self):
        rebound = self.editor._rebound(1)
        rebound(self._row(self.ACTION), '<Control>j')
        self.assertEqual(self._row(self.ACTION).key1, '<Control>j')
        self.assertIn(
            Gtk.accelerator_parse('<Control>j')[1:],
            self.manager.get_bindings_for_action(self.ACTION))

    def test_a_shortcut_is_taken_off_the_action_that_had_it(self):
        """A combination answers to one action, so binding it somewhere
        else has to clear it where it was."""
        self.editor._rebound(1)(self._row(self.ACTION), '<Control>p')
        self.assertEqual(self._row(self.ACTION).key1, '<Control>p')
        self.assertEqual(self._row(self.OTHER).key0, '')

    def test_binding_a_shortcut_the_action_already_has_elsewhere_moves_it(self):
        self.editor._rebound(1)(self._row(self.ACTION), '<Control>n')
        self.assertEqual(self._row(self.ACTION).key1, '<Control>n')
        self.assertEqual(self._row(self.ACTION).key0, '')

    def test_the_menus_are_told_about_the_first_shortcut(self):
        self.editor._rebound(0)(self._row(self.ACTION), '<Control>k')
        self.assertIn((self.ACTION, '<Control>k'),
                      self.window.uimanager.announced)

    # -- Clearing ---------------------------------------------------------

    def test_clearing_unbinds_the_shortcut(self):
        self.editor._rebound(0)(self._row(self.ACTION), None)
        self.assertEqual(self._row(self.ACTION).key0, '')
        self.assertEqual(self.manager.get_bindings_for_action(self.ACTION), [])
        self.assertIn((self.ACTION, ''), self.window.uimanager.announced)

    def test_clearing_a_shortcut_that_was_not_there_changes_nothing(self):
        self.editor._rebound(2)(self._row(self.ACTION), None)
        self.assertEqual(self._row(self.ACTION).key0, '<Control>n')
        self.assertEqual(self.window.uimanager.announced, [])

    def test_a_group_heading_has_no_shortcut_to_rebind(self):
        heading = self.editor._list.get_row(0)
        self.editor._rebound(0)(heading, '<Control>q')
        self.assertEqual(self.window.uimanager.announced, [])

# vim: expandtab:sw=4:ts=4
