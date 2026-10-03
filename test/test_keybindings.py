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

    def test_a_first_start_without_the_file_logs_no_error(self):
        """A new profile has no keybindings.conf, and every first start
        logged "Couldn't load keybindings: [Errno 2] No such file or
        directory" as an error, about a file nothing had been asked to
        write yet."""
        self.assertFalse(os.path.exists(constants.KEYBINDINGS_CONF_PATH))
        with self.assertNoLogs('mcomix', level='ERROR'):
            manager = keybindings._KeybindingManager(_StubWindow())
        manager.register('slideshow', ['<Control>S'], lambda: None)
        self.assertEqual([keybindings.parse_accelerator('<Control>S')],
                         manager.get_bindings_for_action('slideshow'))

    def test_a_file_of_the_wrong_shape_leaves_the_defaults(self):
        """Any JSON that was not an object of lists of names stopped
        MComix before it had a window, and a name where a list belongs
        bound every letter of it."""
        default = [keybindings.parse_accelerator('<Control>S')]
        for stored in ([], 'x', {'slideshow': None},
                       {'slideshow': '<Control>S'}, {'slideshow': [1]}):
            with self.subTest(stored=stored):
                manager = self._manager(stored)
                self.assertEqual(default,
                                 manager.get_bindings_for_action('slideshow'))

    def test_a_file_that_is_not_json_leaves_the_defaults(self):
        with open(constants.KEYBINDINGS_CONF_PATH, 'w') as fp:
            fp.write('not json')
        with self.assertLogs('mcomix', level='ERROR'):
            manager = keybindings._KeybindingManager(_StubWindow())
        manager.register('slideshow', ['<Control>S'], lambda: None)
        self.assertEqual([keybindings.parse_accelerator('<Control>S')],
                         manager.get_bindings_for_action('slideshow'))

    def test_a_file_it_cannot_read_is_kept_rather_than_written_over(self):
        """The defaults it falls back to were saved on quitting, over
        the reader's hand-edited file with its one stray comma (upstream
        bug 155).  The file is kept beside, as preferences.conf is."""
        for content in ('{"slideshow": ["<Control>S"],}', '[]'):
            with self.subTest(content=content):
                with open(constants.KEYBINDINGS_CONF_PATH, 'w') as fp:
                    fp.write(content)
                with self.assertLogs('mcomix', level='ERROR'):
                    manager = keybindings._KeybindingManager(_StubWindow())
                manager.register('slideshow', ['<Control>S'], lambda: None)
                manager.save()
                with open(constants.KEYBINDINGS_CONF_PATH + '.broken') as fp:
                    self.assertEqual(content, fp.read())

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
        with open(source, encoding='utf-8') as fp:
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

    """What docs/shortcuts.md promises the mouse can do.

    The page documented "Mouse4" for the OSD panel, and event.py had a
    branch for button 4 to match - but GDK turns X11 buttons 4 and 5 into
    scroll events and never hands them to a click gesture, so the branch
    could not run and the documented binding did nothing.  Nothing noticed
    because the code and the page agreed with each other while both were
    wrong about GTK.
    """

    #: The page's name for each button the handlers act on.  The thumb
    #: buttons are named for what a mouse prints on them, which is how a
    #: reader knows them; nothing prints a number on a mouse button.
    SPELLINGS = {1: 'LeftMouse', 2: 'MiddleMouse', 3: 'RightMouse',
                 8: 'BackMouse', 9: 'ForwardMouse'}

    #: Any word with Mouse in it, which is how the page names both the
    #: buttons and the wheel.
    MOUSE_WORD = re.compile(r'\b\w*Mouse\w*\b')

    #: The wheel among those: GDK reports it as a scroll rather than as
    #: a button, so it is no business of the click handlers.
    WHEEL_WORD = re.compile(r'\bMouseWheel\w*\b')

    def _named_on_the_page(self):
        """Every button name docs/shortcuts.md uses."""
        page = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(mcomix.event.__file__))),
            'docs', 'shortcuts.md')
        with open(page, encoding='utf-8') as fp:
            return set(self.MOUSE_WORD.findall(
                self.WHEEL_WORD.sub('', fp.read())))

    def _documented_buttons(self):
        """Every button the keybindings page names, by number."""
        by_name = {name: button for button, name in self.SPELLINGS.items()}
        return {by_name[name] for name in self._named_on_the_page()
                if name in by_name}

    def _handled_buttons(self):
        """Every button the click handlers in event.py branch on."""
        source = os.path.join(os.path.dirname(mcomix.event.__file__),
                              'event.py')
        with open(source, encoding='utf-8') as fp:
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

    def test_the_page_names_every_button_under_a_name_spellings_knows(self):
        """A button documented under a name nothing here recognises is a
        binding the comparison above quietly skips, which is how "Mouse4"
        stayed on the page while it could not fire."""
        self.assertEqual(set(), self._named_on_the_page()
                         - set(self.SPELLINGS.values()))

    def test_the_handlers_act_on_no_button_gdk_reports_as_a_scroll(self):
        """Buttons 4 and 5 are the wheel on X11 and arrive as scroll
        events: a branch on either of them in a click handler is dead."""
        self.assertEqual(set(), self._handled_buttons() & {4, 5})

    def test_the_buttons_the_handlers_do_act_on_are_the_expected_ones(self):
        """So that a branch added or lost shows up here rather than only
        in whichever of the two assertions above happens to cover it."""
        self.assertEqual({1, 2, 3, 8, 9}, self._handled_buttons())


class DocumentedKeyBindingsTest(MComixTest):

    """Whether docs/shortcuts.md names the keys MComix binds.

    The page is the only list of the bindings a reader ever sees, and
    nothing checked it: it said the first page was on "Pos1", which is the
    German name for Home, it put the single-step page turns on CTRL+SHIFT
    when they are on CTRL, and it left out the keypad key of every pair
    that has one.  Compared by parsing both sides into (keyval, modifiers)
    rather than by spelling, so the page can go on writing KeyPadHome for
    what Gtk calls KP_Home.
    """

    #: Each row of the page whose keys can be compared one for one with
    #: an action in BINDING_INFO.  A mouse binding inside a row is
    #: skipped - DocumentedMouseBindingsTest covers those - and a row
    #: standing for several actions is left out of the table entirely,
    #: which is why "Scroll to left, right, bottom, top" and the two
    #: rows naming a whole-page turn beside a ten-page one are absent.
    ROWS = {
        'Open file': 'open',
        'Open library': 'library',
        'Close file': 'close',
        'Previous page': 'previous_page',
        'Page to the right': 'next_page_dynamic',
        'Page to the left': 'previous_page_dynamic',
        'Back ten pages': 'previous_page_ff',
        'Forward only one page (in double page mode)': 'next_page_singlestep',
        'One page to the right (in double page mode)':
            'next_page_singlestep_dynamic',
        'One page to the left (in double page mode)':
            'previous_page_singlestep_dynamic',
        'Go back only one page (in double page mode)':
            'previous_page_singlestep',
        'First page': 'first_page',
        'Last page': 'last_page',
        'Go to page': 'go_to',
        'Next archive': 'next_archive',
        'Previous archive': 'previous_archive',
        'Next directory': 'next_directory',
        'Previous directory': 'previous_directory',
        'Scroll down': 'scroll_down',
        'Scroll up': 'scroll_up',
        'Scroll left': 'scroll_left',
        'Scroll right': 'scroll_right',
        'Inverse direction of smart scrolling': 'invert_scroll',
        'Show OSD panel': 'osd_panel',
        'Toggle fullscreen mode': 'fullscreen',
        'Leave fullscreen mode': 'exit_fullscreen',
        'Toggle double page mode': 'double_page',
        'Toggle manga mode': 'manga_mode',
        'Toggle slideshow mode': 'slideshow',
        'Best fit mode': 'best_fit_mode',
        'Fit to width mode': 'fit_width_mode',
        'Fit to height mode': 'fit_height_mode',
        'Fixed size mode': 'fit_size_mode',
        'Manual zoom mode': 'fit_manual_mode',
        'Stretch small images': 'stretch',
        'Zoom in': 'zoom_in',
        'Zoom out': 'zoom_out',
        'Reset zoom': 'zoom_original',
        'Rotate 90 degrees clockwise': 'rotate_90',
        'Rotate 90 degrees anticlockwise': 'rotate_270',
        'Keep transformation between pages': 'keep_transformation',
        'Invert image colours': 'invert_color',
        'Show/hide menubar': 'menubar',
        'Show/hide thumbnails': 'thumbnails',
        'Hide/show all UI elements': 'hide_all',
        'Preferences': 'preferences',
        'Archive comments': 'comments',
        'Properties': 'properties',
        'Enhance image': 'enhance_image',
        'Save currently opened image': 'extract_page',
        'Reload currently opened directory or archive': 'refresh_archive',
        'Delete the page or the file': 'delete',
        'Undo': 'undo',
        'Redo': 'redo',
        'Add bookmark': 'add_bookmark',
        'Edit bookmarks': 'edit_bookmarks',
        'Minimize window': 'minimize',
        'Quit program': 'quit',
        'Save and quit': 'save_and_quit',
    }

    #: How the page writes each modifier.
    MODIFIERS = {'CTRL+': '<Control>', 'SHIFT+': '<Shift>', 'ALT+': '<Alt>'}

    #: How the page spells a key Gtk calls something else.  Gtk's names
    #: for the printable keys are lower case and, unlike a letter, do not
    #: parse in any other case.  Looked up as a whole name rather than
    #: replaced as a substring, because Space is inside BackSpace.
    KEY_NAMES = {
        'PageDown': 'Page_Down',
        'PageUp': 'Page_Up',
        'Backspace': 'BackSpace',
        'TAB': 'Tab',
        'Plus': 'plus',
        'Minus': 'minus',
        'Equal': 'equal',
        'Space': 'space',
    }

    #: What the page puts in front of a keypad key's name.
    KEYPAD = 'KeyPad'

    def _page(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(mcomix.event.__file__))),
            'docs', 'shortcuts.md')
        with open(path, encoding='utf-8') as fp:
            return fp.read()

    def _documented(self):
        """Return {row label: {binding, ...}} for the rows in ROWS."""
        documented = {}
        for line in self._page().splitlines():
            label, _, bindings = line.partition(' | ')
            if label not in self.ROWS:
                continue
            documented[label] = {
                keybindings.parse_accelerator(self._translate(key))
                for key in map(str.strip, bindings.split(','))
                if 'Mouse' not in key}
        return documented

    def _translate(self, key):
        """Turn the page's spelling of <key> into Gtk's."""
        for theirs, ours in self.MODIFIERS.items():
            key = key.replace(theirs, ours)
        # Whatever follows the last modifier is the key's own name.
        modifiers, bracket, name = key.rpartition('>')
        keypad = name.startswith(self.KEYPAD)
        if keypad:
            name = name[len(self.KEYPAD):]
        name = self.KEY_NAMES.get(name, name)
        return modifiers + bracket + ('KP_' + name if keypad else name)

    def _registered(self):
        """Return {action: {binding, ...}} from event.py's defaults."""
        source = os.path.join(os.path.dirname(mcomix.event.__file__),
                              'event.py')
        with open(source, encoding='utf-8') as fp:
            tree = ast.parse(fp.read())
        return {
            call.args[0].value: {keybindings.parse_accelerator(element.value)
                                 for element in call.args[1].elts}
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == 'register' and len(call.args) >= 2
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[1], ast.List)
            and all(isinstance(element, ast.Constant)
                    for element in call.args[1].elts)}

    def test_every_row_this_test_names_is_on_the_page(self):
        """So that renaming a row silently drops it out of the comparison
        rather than being checked against nothing."""
        self.assertEqual(set(self.ROWS), set(self._documented()))

    def test_no_documented_key_is_one_gtk_cannot_read(self):
        """A spelling neither the page nor SPELLINGS accounts for parses
        as UNREADABLE, which would otherwise quietly compare equal to
        another unreadable one."""
        unreadable = {label for label, bindings in self._documented().items()
                      if keybindings.UNREADABLE in bindings}
        self.assertEqual(set(), unreadable)

    def test_the_page_names_the_keys_the_actions_are_bound_to(self):
        registered = self._registered()
        documented = self._documented()
        wrong = {label: (documented[label], registered[action])
                 for label, action in self.ROWS.items()
                 if documented[label] != registered[action]}
        self.assertEqual({}, wrong)

# vim: expandtab:sw=4:ts=4
