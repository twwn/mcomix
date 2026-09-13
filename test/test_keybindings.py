"""Which action a key press reaches.

The manager holds one dictionary from accelerator to action.  These are
about what it does with a combination that is not in it, which is what
every key the reader presses over the page area goes through.
"""

import os

from . import MComixTest

from mcomix import constants
from mcomix import keybindings


class _StubUIManager:

    """Standing in for ui.MainUI, which is only told the shortcut to
    show beside an action in the menus."""

    def set_accelerator(self, name, accelerator):
        pass


class _StubWindow:

    def __init__(self):
        self.uimanager = _StubUIManager()


class KeybindingExecuteTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)
        self.manager = keybindings._KeybindingManager(_StubWindow())
        self.fired = []
        # The two MComix really binds to S, which differ by Shift alone.
        self.manager.register('slideshow', ['<Control>S'],
                              self.fired.append, args=['slideshow'])
        self.manager.register('extract_page', ['<Control><Shift>s'],
                              self.fired.append, args=['extract_page'])

    def _press(self, accelerator):
        self.manager.execute(keybindings.parse_accelerator(accelerator))

    def test_the_accelerator_pressed_is_the_action_that_runs(self):
        self._press('<Control>S')
        self._press('<Control><Shift>s')
        self.assertEqual(['slideshow', 'extract_page'], self.fired)

    def test_a_modifier_the_binding_does_not_ask_for_reaches_nothing(self):
        """Ctrl+Alt+S is bound to nothing, and is not Ctrl+S with an Alt
        that happens to be down: it must not start the slideshow."""
        self._press('<Control><Alt>S')
        self.assertEqual([], self.fired)

    def test_a_binding_is_not_reached_by_dropping_one_of_its_modifiers(self):
        """Ctrl+Shift+S extracts a page.  Shift+S is not that shortcut
        with the Control let go of; it is bound to nothing."""
        self._press('<Shift>S')
        self.assertEqual([], self.fired)

    def test_a_key_bound_to_nothing_is_a_no_op(self):
        self._press('<Control>y')
        self.assertEqual([], self.fired)

# vim: expandtab:sw=4:ts=4
