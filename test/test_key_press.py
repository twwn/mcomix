"""What a key press on the main window hands the keybinding manager.

The key controller is given a hardware keycode and the modifiers held,
and has to turn them into the accelerator a binding is written as:
lower case, with Shift only where it was not needed to type the key.
These go through the X server's own keymap, as a real key press does.
"""

import os
import unittest.mock

from gi.repository import Gdk

from . import MComixTest, pump

from mcomix import constants
from mcomix import icons
from mcomix import keybindings
from mcomix import main


class _Controller:

    """The one thing the handler asks of its key controller."""

    def get_group(self):
        return 0


class KeyPressTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()
        self.executed = []
        manager = keybindings.keybinding_manager(self.window)
        patcher = unittest.mock.patch.object(
            manager, 'execute', side_effect=self.executed.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _press(self, keyval, state=Gdk.ModifierType(0)):
        """Press the key that types <keyval> unshifted, with <state> held."""
        found, keys = self.window.get_display().map_keyval(keyval)
        self.assertTrue(found, 'the keymap has no key for %r' % keyval)
        key = min(keys, key=lambda key: (key.group, key.level))
        # The keyval GTK hands over is the one the modifiers make of it.
        _ok, typed, _group, _level, _consumed = \
            self.window.get_display().translate_key(key.keycode, state, 0)
        return self.window.event_handler.key_press_event(
            _Controller(), typed, key.keycode, state)

    def test_a_plain_letter(self):
        self._press(Gdk.KEY_n)
        self.assertEqual([(Gdk.KEY_n, 0)], self.executed)

    def test_shift_and_a_letter_is_the_lower_case_letter_with_shift(self):
        self._press(Gdk.KEY_n, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual([(Gdk.KEY_n, Gdk.ModifierType.SHIFT_MASK)],
                         self.executed)

    def test_shift_and_space_keeps_shift(self):
        self._press(Gdk.KEY_space, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual([(Gdk.KEY_space, Gdk.ModifierType.SHIFT_MASK)],
                         self.executed)

    def test_caps_lock_does_not_change_a_letters_binding(self):
        """Caps Lock types the letter in upper case, and a binding is
        written in lower case: with it on, no letter key reached its
        action."""
        self._press(Gdk.KEY_n, Gdk.ModifierType.LOCK_MASK)
        self.assertEqual([(Gdk.KEY_n, 0)], self.executed)

    def test_caps_lock_and_shift_is_still_shift(self):
        """Together they type the letter in lower case, which hid that
        Shift was held at all."""
        self._press(Gdk.KEY_n, Gdk.ModifierType.LOCK_MASK
                    | Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual([(Gdk.KEY_n, Gdk.ModifierType.SHIFT_MASK)],
                         self.executed)

    def test_a_modifier_no_accelerator_uses_is_left_out(self):
        self._press(Gdk.KEY_n, Gdk.ModifierType.SUPER_MASK)
        self.assertEqual([(Gdk.KEY_n, 0)], self.executed)

    def test_the_keys_that_move_the_thumbnail_selection_are_kept(self):
        """Up, Down, Space and Enter would otherwise also move the
        thumbnail bar's selection."""
        for keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_space,
                       Gdk.KEY_Return):
            with self.subTest(keyval=Gdk.keyval_name(keyval)):
                self.assertEqual(Gdk.EVENT_STOP, self._press(keyval))

    def test_other_keys_go_on_to_the_focused_widget(self):
        self.assertEqual(Gdk.EVENT_PROPAGATE, self._press(Gdk.KEY_n))
