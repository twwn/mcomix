"""Which action a key press reaches.

The manager holds one dictionary from accelerator to action.  These are
about what it does with a combination that is not in it, which is what
every key the reader presses over the page area goes through.
"""

import ast
import json
import os
import re

from . import MComixTest

from mcomix import constants
from mcomix import keybindings
import mcomix.event


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


class StoredKeybindingsTest(MComixTest):

    """What the manager makes of the accelerators in keybindings.conf.

    That file is written by MComix but is plain JSON a reader can edit,
    and one written by an earlier version can spell an accelerator in a
    way this GTK no longer reads.  Nothing in it may leave an action
    with a key that cannot be pressed.
    """

    def setUp(self):
        super().setUp()
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)

    def _manager(self, stored):
        """Return a manager over a keybindings.conf holding <stored>,
        with the four actions the tests use registered on it."""
        with open(constants.KEYBINDINGS_CONF_PATH, 'w') as fp:
            json.dump(stored, fp)
        manager = keybindings._KeybindingManager(_StubWindow())
        self.fired = []
        for action, default in (('slideshow', '<Control>S'),
                                ('extract_page', '<Control><Shift>s'),
                                ('close', '<Control>W'),
                                ('quit', '<Control>Q')):
            manager.register(action, [default],
                             self.fired.append, args=[action])
        return manager

    def _press(self, manager, accelerator):
        manager.execute(keybindings.parse_accelerator(accelerator))

    def test_a_shortcut_this_gtk_cannot_read_falls_back_to_the_default(self):
        """A stored accelerator that does not parse used to be kept as
        the (0, 0) parse_accelerator() answers with.  That is a binding
        no key press can produce, and it filled the action's list, so
        the default was never applied: one bad line left the action with
        no shortcut at all."""
        manager = self._manager({'slideshow': ['no-such-key']})
        self.assertEqual([keybindings.parse_accelerator('<Control>S')],
                         manager.get_bindings_for_action('slideshow'))
        self._press(manager, '<Control>S')
        self.assertEqual(['slideshow'], self.fired)

    def test_two_shortcuts_this_gtk_cannot_read_are_not_the_same_shortcut(self):
        """Every accelerator that fails to parse comes back as the same
        (0, 0), so two of them in one file read as two actions asking
        for one key.  They are two unrelated bad lines."""
        manager = self._manager({'slideshow': ['no-such-key'],
                                 'extract_page': ['also-bad']})
        self._press(manager, '<Control>S')
        self._press(manager, '<Control><Shift>s')
        self.assertEqual(['slideshow', 'extract_page'], self.fired)

    def test_an_unreadable_shortcut_is_not_written_back_over_the_stored_one(self):
        """Gtk.accelerator_name(0, 0) is the empty string, so saving a
        kept (0, 0) replaced the accelerator the reader had written with
        nothing, and the typo could not be corrected by hand afterwards
        because the original spelling was gone."""
        manager = self._manager({'slideshow': ['no-such-key']})
        manager.save()
        with open(constants.KEYBINDINGS_CONF_PATH) as fp:
            self.assertEqual(['<Control>s'], json.load(fp)['slideshow'])

    def test_one_shortcut_stored_for_two_actions_reaches_only_one(self):
        """<Mod1>x and <Alt>x are the same accelerator - the first is
        how MComix wrote the Alt key before GTK4 - so a file can hold
        one binding under two actions.  Only one action can answer a key
        press, and the other must not go on showing the key in its menu
        label and its editor row."""
        manager = self._manager({'close': ['<Mod1>x'], 'quit': ['<Alt>x']})
        alt_x = keybindings.parse_accelerator('<Alt>x')
        holders = [action for action in ('close', 'quit')
                   if alt_x in manager.get_bindings_for_action(action)]
        self.assertEqual(['close'], holders)
        self._press(manager, '<Alt>x')
        self.assertEqual(['close'], self.fired)
        # quit stored nothing that survived, so it keeps its default.
        self._press(manager, '<Control>Q')
        self.assertEqual(['close', 'quit'], self.fired)


class DefaultKeybindingsTest(MComixTest):

    """The accelerators the actions in event.py register with.

    A default that Gtk.accelerator_parse() will not read is the one case
    _initialize()'s guard cannot catch, because it never goes near the
    keybindings file: register() would claim
    keybindings.UNREADABLE for it, and the action would end up with no
    key that can be pressed.  Nothing would say so - the shortcuts
    editor would show the action with an empty accelerator, as it does
    for one that is genuinely unbound.  So the defaults are read out of
    the source rather than from a running window, which needs neither a
    MainWindow nor the manager singleton.
    """

    #: Actions whose names are built at import time rather than written
    #: out, so that ast cannot read them as constants.
    GENERATED = 'execute_command_'

    def _registered(self):
        """Return {action name: [accelerator, ...]} for every
        manager.register() call in event.py whose arguments are literal.

        The name and the accelerators of a call that builds either of
        them come back as None, so that a call this cannot read shows up
        rather than being silently left out.
        """
        source = os.path.join(os.path.dirname(mcomix.event.__file__),
                              'event.py')
        with open(source) as fp:
            tree = ast.parse(fp.read())

        def literal(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.List) and all(
                    isinstance(e, ast.Constant) for e in node.elts):
                return [e.value for e in node.elts]
            return None

        return [(literal(call.args[0]), literal(call.args[1]))
                for call in ast.walk(tree)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == 'register'
                and len(call.args) >= 2]

    def test_every_default_accelerator_can_be_parsed(self):
        unreadable = [(action, accelerator)
                      for action, accelerators in self._registered()
                      if accelerators is not None
                      for accelerator in accelerators
                      if keybindings.parse_accelerator(accelerator)
                      == keybindings.UNREADABLE]
        self.assertEqual([], unreadable)

    def test_every_action_the_editor_offers_is_registered(self):
        """BINDING_INFO is what the shortcuts editor lists, so an action
        in it that nothing registers is a row the reader can give a key
        to that then runs nothing."""
        registered = {action for action, _accelerators in self._registered()
                      if action is not None}
        self.assertEqual(
            [], [action for action in keybindings.BINDING_INFO
                 if action not in registered
                 and not action.startswith(self.GENERATED)])

    def test_the_generated_command_actions_are_registered(self):
        """The nine external command actions are registered in a loop, so
        their names are not literals and the check above cannot see
        them.  What can be read is that the loop is there."""
        self.assertTrue(
            any(action is None for action, _accelerators
                in self._registered()))
        self.assertEqual(
            9, len([action for action in keybindings.BINDING_INFO
                    if action.startswith(self.GENERATED)]))


class DocumentedMouseBindingsTest(MComixTest):

    """What wiki/content/Keybindings.md promises the mouse can do.

    The page documented "Mouse4" for the OSD panel, and event.py had a
    branch for button 4 to match - but GDK turns X11 buttons 4 and 5 into
    scroll events and never hands them to a click gesture, so the branch
    could not run and the documented binding did nothing.  Nothing noticed
    because the code and the page agreed with each other while both were
    wrong about GTK.
    """

    #: The page's name for each button the handlers act on.
    SPELLINGS = {1: 'LeftMouse', 2: 'MiddleMouse', 3: 'RightMouse'}

    def _documented_buttons(self):
        """Every Mouse<number> the keybindings page names."""
        page = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(mcomix.event.__file__))),
            'wiki', 'content', 'Keybindings.md')
        with open(page, encoding='utf-8') as fp:
            return {int(number) for number in
                    re.findall(r'\bMouse(\d+)\b', fp.read())}

    def _handled_buttons(self):
        """Every button the click handlers in event.py branch on."""
        source = os.path.join(os.path.dirname(mcomix.event.__file__),
                              'event.py')
        with open(source) as fp:
            tree = ast.parse(fp.read())
        handled = set()
        for function in ast.walk(tree):
            if not (isinstance(function, ast.FunctionDef)
                    and function.name in ('mouse_press_event',
                                          'mouse_release_event')):
                continue
            for node in ast.walk(function):
                if (isinstance(node, ast.Compare)
                        and isinstance(node.left, ast.Name)
                        and node.left.id == 'button'
                        and len(node.comparators) == 1
                        and isinstance(node.comparators[0], ast.Constant)):
                    handled.add(node.comparators[0].value)
        return handled

    def test_the_page_names_no_button_the_handlers_do_not_act_on(self):
        self.assertEqual(set(), self._documented_buttons()
                         - self._handled_buttons())

    def test_the_handlers_act_on_no_button_gdk_reports_as_a_scroll(self):
        """Buttons 4 and 5 are the wheel on X11 and arrive as scroll
        events: a branch on either of them in a click handler is dead."""
        self.assertEqual(set(), self._handled_buttons() & {4, 5})

    def test_the_buttons_the_handlers_do_act_on_are_the_expected_ones(self):
        """So that a branch added or lost shows up here rather than only
        in whichever of the two assertions above happens to cover it."""
        self.assertEqual({1, 2, 3}, self._handled_buttons())

# vim: expandtab:sw=4:ts=4
