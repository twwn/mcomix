""" Dynamic hotkey management

This module handles the global hotkeys.  An action can answer to more than
one of them, which is why the bindings live here rather than on the menu
items: a menu model item carries a single accelerator, and this module
tells the menus which one to show.

Other modules register a callback under an action name, which has to be
one of the names in BINDING_INFO; anything else fails an assertion.  The
manager keeps three maps, because it has to get each of these three
things from the others: the callback and its arguments by action name,
the accelerators by action name, and the action name by accelerator.
The last is what a key press is looked up in.

The accelerators a reader has configured are read from the keybindings
file when the manager is built, before any action is registered, and the
defaults an action registers with are used only where that file held
nothing for it.
"""

import os
import shutil
from gi.repository import Gdk, Gtk
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TYPE_CHECKING

from mcomix import constants
from mcomix import log
from mcomix import tools
from mcomix.i18n import _

if TYPE_CHECKING:
    from mcomix import main

#: A parsed accelerator: the key, and the modifiers held with it.
Binding = tuple[int, Gdk.ModifierType]

#: Bindings defined in this dictionary will appear in the configuration
#: dialog: a title to show against the action, and the group the
#: shortcuts editor files it under.
BINDING_INFO: "dict[str, dict[str, str]]" = {
    # Navigation between pages, archives, directories
    'previous_page': {'title': _('Previous page'), 'group': _('Navigation')},
    'next_page': {'title': _('Next page'), 'group': _('Navigation')},
    'previous_page_ff': {'title': _('Back 10 pages'), 'group': _('Navigation')},
    'next_page_ff': {'title': _('Forward 10 pages'), 'group': _('Navigation')},
    'previous_page_dynamic': {'title': _('Page to the left'), 'group': _('Navigation')},
    'next_page_dynamic': {'title': _('Page to the right'), 'group': _('Navigation')},
    'previous_page_singlestep': {'title': _('Previous single page'), 'group': _('Navigation')},
    'next_page_singlestep': {'title': _('Next single page'), 'group': _('Navigation')},

    'first_page': {'title': _('First page'), 'group': _('Navigation')},
    'last_page': {'title': _('Last page'), 'group': _('Navigation')},
    'go_to': {'title': _('Go to page'), 'group': _('Navigation')},

    'next_archive': {'title': _('Next archive'), 'group': _('Navigation')},
    'previous_archive': {'title': _('Previous archive'), 'group': _('Navigation')},
    'next_directory': {'title': _('Next directory'), 'group': _('Navigation')},
    'previous_directory': {'title': _('Previous directory'), 'group': _('Navigation')},

    # Scrolling
    'scroll_left_bottom': {'title': _('Align bottom left'), 'group': _('Scroll')},
    'scroll_middle_bottom': {'title': _('Align bottom center'), 'group': _('Scroll')},
    'scroll_right_bottom': {'title': _('Align bottom right'), 'group': _('Scroll')},

    'scroll_left_middle': {'title': _('Align middle left'), 'group': _('Scroll')},
    'scroll_middle': {'title': _('Align center'), 'group': _('Scroll')},
    'scroll_right_middle': {'title': _('Align middle right'), 'group': _('Scroll')},

    'scroll_left_top': {'title': _('Align top left'), 'group': _('Scroll')},
    'scroll_middle_top': {'title': _('Align top center'), 'group': _('Scroll')},
    'scroll_right_top': {'title': _('Align top right'), 'group': _('Scroll')},

    'scroll_down': {'title': _('Scroll down'), 'group': _('Scroll')},
    'scroll_up': {'title': _('Scroll up'), 'group': _('Scroll')},
    'scroll_right': {'title': _('Scroll right'), 'group': _('Scroll')},
    'scroll_left': {'title': _('Scroll left'), 'group': _('Scroll')},

    'smart_scroll_up': {'title': _('Smart scroll up'), 'group': _('Scroll')},
    'smart_scroll_down': {'title': _('Smart scroll down'), 'group': _('Scroll')},

    # View
    'zoom_in': {'title': _('Zoom in'), 'group': _('Zoom')},
    'zoom_out': {'title': _('Zoom out'), 'group': _('Zoom')},
    'zoom_original': {'title': _('Normal size'), 'group': _('Zoom')},

    'keep_transformation': {'title': _('Keep transformation'), 'group': _('Transformation')},
    'rotate_90': {'title': _('Rotate 90° CW'), 'group': _('Transformation')},
    'rotate_180': {'title': _('Rotate 180°'), 'group': _('Transformation')},
    'rotate_270': {'title': _('Rotate 90° CCW'), 'group': _('Transformation')},
    'flip_horiz': {'title': _('Flip horizontally'), 'group': _('Transformation')},
    'flip_vert': {'title': _('Flip vertically'), 'group': _('Transformation')},
    'no_autorotation': {'title': _('Never autorotate'), 'group': _('Transformation')},

    'rotate_90_width': {'title': _('Rotate 90° CW'), 'group': _('Autorotate by width')},
    'rotate_270_width': {'title': _('Rotate 90° CCW'), 'group': _('Autorotate by width')},
    'rotate_90_height': {'title': _('Rotate 90° CW'), 'group': _('Autorotate by height')},
    'rotate_270_height': {'title': _('Rotate 90° CCW'), 'group': _('Autorotate by height')},

    'double_page': {'title': _('Double page mode'), 'group': _('View mode')},
    'manga_mode': {'title': _('Manga mode'), 'group': _('View mode')},
    'invert_scroll': {'title': _('Invert smart scroll'), 'group': _('View mode')},

    'lens': {'title': _('Magnifying lens'), 'group': _('View mode')},
    'stretch': {'title': _('Stretch small images'), 'group': _('View mode')},

    'best_fit_mode': {'title': _('Best fit mode'), 'group': _('View mode')},
    'fit_width_mode': {'title': _('Fit width mode'), 'group': _('View mode')},
    'fit_height_mode': {'title': _('Fit height mode'), 'group': _('View mode')},
    'fit_size_mode': {'title': _('Fit size mode'), 'group': _('View mode')},
    'fit_manual_mode': {'title': _('Manual zoom mode'), 'group': _('View mode')},

    # General UI
    'exit_fullscreen': {'title': _('Leave fullscreen'), 'group': _('User interface')},

    'osd_panel': {'title': _('OSD panel'), 'group': _('User interface')},
    'minimize': {'title': _('Minimize'), 'group': _('User interface')},
    'fullscreen': {'title': _('Fullscreen'), 'group': _('User interface')},
    'toolbar': {'title': _('Toolbar'), 'group': _('User interface')},
    'menubar': {'title': _('Menubar'), 'group': _('User interface')},
    'statusbar': {'title': _('Statusbar'), 'group': _('User interface')},
    'scrollbar': {'title': _('Scrollbars'), 'group': _('User interface')},
    'thumbnails': {'title': _('Thumbnails'), 'group': _('User interface')},
    'hide_all': {'title': _('Hide all'), 'group': _('User interface')},
    'slideshow': {'title': _('Start slideshow'), 'group': _('User interface')},

    # File operations
    'delete': {'title': _('Delete'), 'group': _('File')},
    'refresh_archive': {'title': _('Refresh'), 'group': _('File')},
    'close': {'title': _('Close'), 'group': _('File')},
    'quit': {'title': _('Quit'), 'group': _('File')},
    'save_and_quit': {'title': _('Save and quit'), 'group': _('File')},
    'extract_page': {'title': _('Save As'), 'group': _('File')},

    'comments': {'title': _('Archive comments'), 'group': _('File')},
    'properties': {'title': _('Properties'), 'group': _('File')},
    'preferences': {'title': _('Preferences'), 'group': _('File')},

    'edit_archive': {'title': _('Edit archive'), 'group': _('File')},
    'open': {'title': _('Open'), 'group': _('File')},
    'enhance_image': {'title': _('Enhance image'), 'group': _('File')},
    'library': {'title': _('Library'), 'group': _('File')},
    'invert_color': {'title': _('Invert image colors'), 'group': _('File')},
}

# Generate 9 entries for executing command 1 to 9
for i in range(1, 10):
    BINDING_INFO['execute_command_%d' % i] = {
            # The group says what kind of command it is, so the title
            # only has to tell one from another.
            'title': _('Command') + ' %d' % i,
            'group': _('External commands')
    }


def parse_accelerator(accelerator: str) -> Binding:
    """Return the (key, modifiers) <accelerator> stands for.

    Gtk.accelerator_parse() answers with a success flag in front of those
    two, and one that does not parse comes back as (0, 0).
    """
    ok, key, modifiers = Gtk.accelerator_parse(accelerator)
    if not ok and '<Mod1>' in accelerator:
        # GTK4 dropped <Mod1> for the Alt key it always stood for, and
        # will not parse it at all; keybindings.conf files written by
        # earlier versions are full of it.
        ok, key, modifiers = Gtk.accelerator_parse(
            accelerator.replace('<Mod1>', '<Alt>'))
    return (key, modifiers) if ok else (0, Gdk.ModifierType(0))


class _KeybindingManager:
    def __init__(self, window: 'main.MainWindow') -> None:
        #: Main window instance
        self._window = window

        #: action name => (func, args, kwargs)
        self._action_to_callback: dict[str, tuple[Callable[..., Any],  # type: ignore[explicit-any]  # an action takes what it was registered with
                                                  Sequence[Any],
                                                  Mapping[str, Any]]] = {}
        #: action name => the accelerators that reach it
        self._action_to_bindings: dict[str, list[Binding]] = defaultdict(list)
        #: accelerator => action name
        self._binding_to_action: dict[Binding, str] = {}

        self._migrate_from_old_bindings()
        self._initialize()

    def register(self, name: str, bindings: Sequence[str],  # type: ignore[explicit-any]  # an action takes what it was registered with
                 callback: Callable[..., Any],
                 args: Sequence[Any] | None = None,
                 kwargs: Mapping[str, Any] | None = None) -> None:
        """Have <callback> answer the action <name>, an entry of BINDING_INFO.

        <bindings> are the accelerators the action answers to by
        default, written the way Gtk.accelerator_parse() reads them, and
        they are used only where the reader's keybindings file held none
        for this action.  <args> and <kwargs> are passed to the callback
        whenever it runs; the key that was pressed is not, so an action
        bound to several keys cannot tell which of them reached it.

        An accelerator that already reaches another action is left where
        it is and only warned about, so of two actions asking for the
        same key the one registered first keeps it.
        """
        assert name in BINDING_INFO, "'%s' isn't a valid keyboard action." % name

        if args is None:
            args = []
        if kwargs is None:
            kwargs = {}

        # Load stored keybindings, or fall back to passed arguments
        keycodes = self._action_to_bindings[name]
        if keycodes == []:
            keycodes = [parse_accelerator(binding) for binding in bindings]

        for keycode in keycodes:
            if keycode in self._binding_to_action:
                if self._binding_to_action[keycode] != name:
                    log.warning(_('Keybinding for "%(action)s" overrides hotkey for another action.'),
                                {"action": name})
                    log.warning('Binding %s overrides %r', keycode, self._binding_to_action[keycode])
            else:
                self._binding_to_action[keycode] = name
                self._action_to_bindings[name].append(keycode)

        # Show the key against the action in the menus.
        if self._action_to_bindings[name]:
            key, mod = self._action_to_bindings[name][0]
            self.announce_accelerator(name, Gtk.accelerator_name(key, mod))

        self._action_to_callback[name] = (callback, args, kwargs)

    def announce_accelerator(self, name: str, accelerator: str) -> None:
        """Tell the menus which key <name> answers to.

        Gtk.AccelMap, which the menu labels used to read this from, is
        not in GTK4; a menu model item carries its accelerator itself.
        """
        uimanager = getattr(self._window, 'uimanager', None)
        if uimanager is not None:
            uimanager.set_accelerator(name, accelerator)

    def edit_accel(self, name: str, new_binding: str, old_binding: str) -> str | None:
        """Give the action <name> the accelerator <new_binding>.

        <old_binding> is the accelerator it replaces, and is empty where
        the action is being given a further key rather than having one
        changed.  A replacement keeps the place the old key held in the
        action's list, so that the key the menus show does not move
        about; a further key goes on the end.

        An accelerator reaches one action only, so <new_binding> is
        taken off whatever action held it before.  That action's name is
        the answer, and None where the key was free.  The bindings are
        written to disk before returning.
        """
        assert name in BINDING_INFO, "'%s' isn't a valid keyboard action." % name

        nb = parse_accelerator(new_binding)
        old_action_with_nb = self._binding_to_action.get(nb)
        if old_action_with_nb is not None:
            # An accelerator answers to one action, so wherever it was
            # bound before, it is not bound there any more.
            self._binding_to_action.pop(nb)
            self._action_to_bindings[old_action_with_nb].remove(nb)

        ob = parse_accelerator(old_binding) if old_binding else None
        self._binding_to_action[nb] = name
        # Whether this replaces a key turns on whether the key being
        # replaced is a different one, not on which action held the new
        # key: the action can hold both, and then the old key has to go
        # just the same.  Testing the action instead let a key the same
        # action held in another column arrive here, take the else
        # branch, and leave the key it was replacing bound - so the
        # editor showed it gone while it went on working, and came back
        # the next time the dialog was opened.
        if ob is not None and ob != nb \
                and ob in self._action_to_bindings[name]:
            self._binding_to_action.pop(ob, None)
            position = self._action_to_bindings[name].index(ob)
            self._action_to_bindings[name][position] = nb
        else:
            self._action_to_bindings[name].append(nb)

        self.save()
        return old_action_with_nb

    def clear_accel(self, name: str, binding: str) -> None:
        """ Remove binding for an action """
        assert name in BINDING_INFO, "'%s' isn't a valid keyboard action." % name

        ob = parse_accelerator(binding)
        self._action_to_bindings[name].remove(ob)
        self._binding_to_action.pop(ob)

        self.save()

    def clear_all(self) -> None:
        """ Removes all keybindings. The changes are only persisted if
        save() is called afterwards. """
        self._action_to_callback = {}
        self._action_to_bindings = defaultdict(list)
        self._binding_to_action = {}

    def execute(self, keybinding: Binding) -> None:
        """ Executes an action that has been registered for the
        passed keyboard event. If no action is bound to the passed key, this
        method is a no-op. """
        if keybinding in self._binding_to_action:
            action = self._binding_to_action[keybinding]
            func, args, kwargs = self._action_to_callback[action]
            # There is no key-press-event to stop in GTK4; the key
            # controller in event.py says so by what it answers.
            func(*args, **kwargs)
            return

        # Some keys enable additional modifiers (NumLock enables GDK_MOD2_MASK),
        # which prevent direct lookup simply by being pressed.
        # XXX: Looking up by key/modifier probably isn't the best implementation,
        # so limit possible states to begin with?
        for stored_binding, action in self._binding_to_action.items():
            stored_keycode, stored_flags = stored_binding
            if stored_keycode == keybinding[0] and stored_flags & keybinding[1]:
                func, args, kwargs = self._action_to_callback[action]
                func(*args, **kwargs)
                return

    def save(self) -> None:
        """ Stores the keybindings that have been set to disk. """
        # Collect keybindings for all registered actions
        action_to_keys = {
            action: [Gtk.accelerator_name(keyval, modifiers)
                     for keyval, modifiers in bindings]
            for action, bindings in self._action_to_bindings.items()
        }
        with tools.atomic_write(constants.KEYBINDINGS_CONF_PATH) as fp:
            json.dump(action_to_keys, fp, indent=2)

    def _initialize(self) -> None:
        """ Restore keybindings from disk. """
        try:
            with open(constants.KEYBINDINGS_CONF_PATH, "r") as fp:
                stored_action_bindings = json.load(fp)
        except Exception as e:
            log.error(_("Couldn't load keybindings: %s"), e)
            stored_action_bindings = {}

        for action in BINDING_INFO:
            if action in stored_action_bindings:
                bindings = [
                    parse_accelerator(keyname)
                    for keyname in stored_action_bindings[action]]
                self._action_to_bindings[action] = bindings
                for binding in bindings:
                    self._binding_to_action[binding] = action
            else:
                self._action_to_bindings[action] = []

    def get_bindings_for_action(self, name: str) -> list[Binding]:
        """ Returns the accelerators bound to the action <name>, as
        (key, modifiers) pairs. """
        return self._action_to_bindings[name]

    def _migrate_from_old_bindings(self) -> None:
        """ This method deals with upgrading from MComix 1.0 and older to
        MComix 1.01, which integrated all UI hotkeys into this class. Simply
        remove old files and start from default values. """
        gtkrc = os.path.join(constants.CONFIG_DIR, 'keybindings-Gtk.rc')
        if os.path.isfile(gtkrc):
            # In case the user has made modifications to his files,
            # keep the old ones around for reference.
            if not os.path.isfile(gtkrc + '.delete-me'):
                shutil.move(gtkrc, gtkrc + '.delete-me')

            if os.path.isfile(constants.KEYBINDINGS_CONF_PATH) and \
                    not os.path.isfile(constants.KEYBINDINGS_CONF_PATH + '.delete-me'):
                shutil.move(constants.KEYBINDINGS_CONF_PATH,
                            constants.KEYBINDINGS_CONF_PATH + '.delete-me')


_manager: _KeybindingManager | None = None


def keybinding_manager(window: 'main.MainWindow') -> _KeybindingManager:
    """ Returns a singleton instance of the keybinding manager. """
    global _manager
    if _manager:
        return _manager
    else:
        _manager = _KeybindingManager(window)
        return _manager

# vim: expandtab:sw=4:ts=4
