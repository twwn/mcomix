"""ui.py - UI definitions for main window.
"""

from gi.repository import Gio, GLib, Gtk

from collections.abc import Callable, Sequence
from typing import NamedTuple, Protocol, TYPE_CHECKING

from mcomix import bookmark_backend
from mcomix import bookmark_menu
from mcomix import move_menu
from mcomix import openwith_menu
from mcomix import edit_dialog
from mcomix import enhance_dialog
from mcomix import preferences_dialog
from mcomix import recent
from mcomix import dialog_handler
from mcomix import widgets
from mcomix import constants
from mcomix import file_chooser_main_dialog
from mcomix.preferences import prefs
from mcomix.library import main_dialog as library_main_dialog
from mcomix.i18n import _

if TYPE_CHECKING:
    from mcomix import main


def _gio_name(name: str) -> str:
    """The name a Gio action can be registered under.

    Gio action names take alphanumerics, hyphens and dots, and MComix'
    names are full of underscores, so those become hyphens.  Nothing
    outside this module needs to know: actions are asked for by the names
    MComix has always used.
    """
    return name.replace('_', '-')


# What a callback answers with is discarded - running a Gio action has
# no result to give back - so these say object rather than None: several
# of them are methods that report whether they did anything.

#: What a plain action's callback is handed: the action that ran.
type _PlainCallback = Callable[[Gio.SimpleAction], object]

#: What one added with user data is handed: the action and that data.
type _DataCallback[D] = Callable[[Gio.SimpleAction, D], object]

#: What a toggle's or a radio group's callback is handed: the action in
#: MComix' own shape, which is what get_active() is asked of.
type _ToggleCallback = Callable[["Action"], object]


class _Described(Protocol):

    """What every row of every action table says about its action.

    _remember() wants only these four, and the two kinds of row differ
    in what comes after them.
    """

    @property
    def name(self) -> str: ...
    @property
    def icon(self) -> "str | None": ...
    @property
    def label(self) -> "str | None": ...
    @property
    def tooltip(self) -> "str | None": ...


class _Entry[C](NamedTuple):

    """One row of an action table.

    The rows are three or five fields long, so the fields are named here
    rather than read out by index.  The tooltip and the callback are what
    the short rows leave off: a menu that only opens a submenu has
    nothing to explain and nothing to do.

    <C> is the shape of the callback, which is what tells the tables
    apart: a plain action's is handed the Gio action, a toggle's is
    handed MComix' own wrapper around it.
    """

    #: The name MComix knows the action by, which is also what the
    #: keybindings and the menu layouts refer to.
    name: str
    #: The icon a tool button draws, if this action has one.
    icon: str | None
    #: What a menu item is labelled.  Only the tool bar's expander, which
    #: is a spacer rather than anything to click, has none.
    label: str | None
    #: What the status bar says about it while the pointer is over it.
    tooltip: str | None = None
    #: What running it does.
    callback: "C | None" = None


class _Choice(NamedTuple):

    """One row of a radio table, which is an _Entry whose last field is
    the value that member stands for rather than a callback: the group
    has one callback of its own."""

    name: str
    icon: str | None
    label: str | None
    tooltip: str | None = None
    value: int = 0


class Action:

    """One of the window's actions, in the shape the rest of MComix asks
    for it.

    The callers activate an action, turn a toggle on or off, and make an
    action sensitive or not.  Gio spells those differently - a toggle is
    set by handing its action a GLib.Variant, and a member of a radio
    group is a target on the group's one action - so this keeps the
    spelling in one place.
    """

    def __init__(self, action: Gio.SimpleAction,
                 target: "GLib.Variant | None" = None) -> None:
        self._action = action
        self._target = target

    def detailed(self, prefix: str) -> "tuple[str, GLib.Variant | None]":
        """How a menu item or tool button addresses this action."""
        return '%s.%s' % (prefix, self._action.get_name()), self._target

    def activate(self, *args: object) -> None:
        self._action.activate(self._target)

    def set_active(self, active: bool) -> None:
        # Gio.SimpleAction.change_state() announces a change even to the
        # value the action already holds, and the callback runs for it,
        # so only a real change is asked for.
        if bool(active) != self.get_active():
            self._action.change_state(GLib.Variant('b', bool(active)))

    def show_active(self, active: bool) -> None:
        """Draw this toggle as on or off without running what it does.

        set_active() asks the action to change, which is how a menu item
        that has been clicked is answered.  This is for a state that is
        already true - the preference it stands for has been read
        somewhere else - where only the tick beside the item is out of
        step: Gio.SimpleAction.set_state() moves it without the
        change-state the callback hangs off.
        """
        self._action.set_state(GLib.Variant('b', bool(active)))

    def get_active(self) -> bool:
        state = self._action.get_state()
        # Only a toggle is asked whether it is on, and a toggle is
        # stateful; a plain action would answer with no state at all.
        assert state is not None
        return bool(state.get_boolean())

    def get_current_value(self) -> int:
        """The value the radio group this belongs to currently holds."""
        state = self._action.get_state()
        # As above: only a member of a radio group is asked this, and
        # the group's action holds the value as its state.
        assert state is not None
        return int(state.get_int32())

    def set_sensitive(self, sensitive: bool) -> None:
        self._action.set_enabled(bool(sensitive))

    def get_sensitive(self) -> bool:
        return bool(self._action.get_enabled())


class Actions:

    """The window's actions, under the names the rest of MComix uses.

    The tables handed to add(), add_toggle() and add_radio() are
    (name, icon name, label, tooltip, and a callback or, for a radio
    entry, its value); everything after the label may be left out.

    There is no accelerator among them: keybindings.py holds those, and
    the shortcuts editor edits them.
    """

    #: The prefix menu items and tool buttons address these actions by.
    PREFIX = 'win'

    def __init__(self) -> None:
        self.group = Gio.SimpleActionGroup()
        self._by_name: dict[str, Action] = {}
        self._labels: dict[str, str] = {}
        self._icons: dict[str, str | None] = {}
        self._stateful: set[str] = set()
        #: Tooltips, by label, for the status bar helper.
        self.tooltips: dict[str, str] = {}

    def get_action(self, name: str) -> Action:
        return self._by_name[name]

    def detailed(self, name: str) -> "tuple[str, GLib.Variant | None]":
        return self._by_name[name].detailed(self.PREFIX)

    def label(self, name: str) -> str:
        return self._labels[name]

    def icon(self, name: str) -> str | None:
        return self._icons[name]

    def is_stateful(self, name: str) -> bool:
        """Whether the action shows as pressed when it is on."""
        return name in self._stateful

    def _remember(self, entry: _Described, action: Gio.SimpleAction,
                  target: "GLib.Variant | None" = None,
                  stateful: bool = False) -> None:
        self._by_name[entry.name] = Action(action, target)
        # The tool bar's expander is the one entry with no label, being
        # a spacer rather than anything to click, and the tool bar skips
        # it before it asks for one.
        self._labels[entry.name] = entry.label or ''
        self._icons[entry.name] = entry.icon
        if stateful:
            self._stateful.add(entry.name)
        if entry.label and entry.tooltip:
            self.tooltips[entry.label] = entry.tooltip

    def add(self, entries: "Sequence[_Entry[_PlainCallback]]") -> None:
        """Add plain actions, each run with the action itself."""
        for entry in entries:
            action = Gio.SimpleAction.new(_gio_name(entry.name), None)
            if entry.callback is not None:
                action.connect('activate', self._activated, entry.callback)
            self.group.add_action(action)
            self._remember(entry, action)

    def add_with_data[D](self, entries: "Sequence[_Entry[_DataCallback[D]]]",
                         user_data: D) -> None:
        """Add plain actions, each run with the action and <user_data>.

        The dialogs are what needs this: one function opens any of them,
        and which one is what the data says.
        """
        for entry in entries:
            action = Gio.SimpleAction.new(_gio_name(entry.name), None)
            if entry.callback is not None:
                action.connect('activate', self._activated_with_data,
                               entry.callback, user_data)
            self.group.add_action(action)
            self._remember(entry, action)

    def add_toggle(self,
                   entries: "Sequence[_Entry[_ToggleCallback]]") -> None:
        """Add actions that are on or off."""
        for entry in entries:
            action = Gio.SimpleAction.new_stateful(
                _gio_name(entry.name), None, GLib.Variant('b', False))
            action.connect('change-state', self._toggled,
                           entry.name, entry.callback)
            self.group.add_action(action)
            self._remember(entry, action, stateful=True)

    def add_radio(self, name: str, entries: "Sequence[_Choice]",
                  value: int, on_change: _ToggleCallback) -> None:
        """Add one group of mutually exclusive actions.

        One stateful action holds the value the group is set to, and each
        member is a target on it: the value that member stands for.
        """
        action = Gio.SimpleAction.new_stateful(
            name, GLib.VariantType.new('i'), GLib.Variant('i', value))
        action.connect('change-state', self._radio_changed, name, on_change)
        self.group.add_action(action)
        for choice in entries:
            self._remember(choice, action,
                           GLib.Variant('i', choice.value), stateful=True)

    def _activated(self, action: Gio.SimpleAction,
                   parameter: "GLib.Variant | None",
                   callback: _PlainCallback) -> None:
        callback(action)

    def _activated_with_data[D](self, action: Gio.SimpleAction,
                                parameter: "GLib.Variant | None",
                                callback: "_DataCallback[D]",
                                user_data: D) -> None:
        callback(action, user_data)

    def _toggled(self, action: Gio.SimpleAction, value: GLib.Variant,
                 name: str,
                 callback: "_ToggleCallback | None") -> None:
        action.set_state(value)
        if callback is not None:
            callback(self._by_name[name])

    def _radio_changed(self, action: Gio.SimpleAction, value: GLib.Variant,
                       name: str,
                       on_change: "_ToggleCallback | None") -> None:
        action.set_state(value)
        if on_change is not None:
            on_change(Action(action))


#: A menu layout: the names of the actions its items run, None where a
#: separator goes, and a (name, sub-layout) pair for a submenu.
type _Layout = "Sequence[str | None | tuple[str, _Layout]]"


#: The menu bar.  None is a separator, and a pair is a submenu.
_MENUBAR = (
    ('menu_file', ('open', 'menu_recent', 'library', None,
                   'extract_page', 'refresh_archive', 'properties', None,
                   'menu_open_with', None,
                   'delete', None,
                   'about', None,
                   'minimize', 'close', 'save_and_quit', 'quit')),
    ('menu_edit', ('undo', 'redo', 'unpick_pages', None,
                   'copy_page', None,
                   'edit_archive', 'comments', None,
                   'preferences')),
    ('menu_view', ('fullscreen', 'double_page', 'title_page_alone', 'manga_mode', None,
                   'best_fit_mode', 'fit_width_mode', 'fit_height_mode',
                   'fit_size_mode', 'fit_manual_mode', None,
                   'slideshow', None,
                   'stretch', 'invert_scroll', 'lens',
                   ('menu_zoom', ('zoom_in', 'zoom_out', 'zoom_original')),
                   None,
                   ('menu_toolbars', ('menubar', 'toolbar', 'statusbar',
                                      'scrollbar', 'thumbnails', None,
                                      'hide_all')))),
    ('menu_go', ('next_page', 'previous_page', 'go_to',
                 'first_page', 'last_page', None,
                 'next_archive', 'previous_archive', None,
                 'next_directory', 'previous_directory')),
    'menu_bookmarks',
    ('menu_tools', ('enhance_image',
                    ('menu_transform', ('rotate_90', 'rotate_270',
                                        'rotate_180', None,
                                        ('menu_autorotate',
                                         ('no_autorotation', None,
                                          'menu_autorotate_height', None,
                                          'rotate_90_height',
                                          'rotate_270_height', None,
                                          'menu_autorotate_width', None,
                                          'rotate_90_width',
                                          'rotate_270_width')),
                                        None,
                                        'flip_horiz', 'flip_vert', None,
                                        'keep_transformation')))),
)

#: The actions whose menu items are left out while they are disabled
#: rather than greyed out.
_HIDDEN_WHEN_DISABLED = frozenset({'leave_fullscreen', 'remove_bookmark_popup'})

#: The right-click menu.
_POPUP = (
    # Shown only while the window fills the screen: the item under
    # View, two levels down, was the only way out with the mouse
    # (upstream feature requests 86 and 135).
    'leave_fullscreen',
    ('menu_go_popup', ('next_page', 'previous_page', 'go_to',
                       'first_page', 'last_page', None,
                       'next_archive', 'previous_archive', None,
                       'next_directory', 'previous_directory')),
    ('menu_view_popup', ('fullscreen', 'double_page', 'title_page_alone', 'manga_mode', None,
                         'best_fit_mode', 'fit_width_mode', 'fit_height_mode',
                         'fit_size_mode', 'fit_manual_mode', None,
                         'slideshow', None,
                         'enhance_image', None,
                         'stretch', 'invert_scroll', 'lens',
                         ('menu_zoom', ('zoom_in', 'zoom_out',
                                        'zoom_original')),
                         None,
                         ('menu_toolbars', ('menubar', 'toolbar', 'statusbar',
                                            'scrollbar', 'thumbnails', None,
                                            'hide_all')))),
    'menu_bookmarks_popup', 'remove_bookmark_popup',
    None,
    'open', 'menu_recent', 'library',
    None,
    'copy_page_popup', 'extract_page_popup',
    'rename_page_popup', 'delete_page_popup', 'unpick_pages',
    None,
    'menu_move_to_popup',
    None,
    'edit_archive',
    None,
    'menu_open_with_popup',
    None,
    'preferences',
    None,
    'close', 'quit',
)

#: The tool bar.
_TOOLBAR = ('previous_archive', 'first_page', 'previous_page', 'go_to',
            'next_page', 'last_page', 'next_archive', None,
            'fullscreen', 'slideshow', 'expander',
            'best_fit_mode', 'fit_width_mode', 'fit_height_mode',
            'fit_size_mode', 'fit_manual_mode', None,
            'double_page', 'manga_mode', None,
            'lens')


class MainUI:

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        self.actions = self._actions = Actions()
        #: The accelerator each action currently answers to, by name.
        self._accelerators: dict[str, str] = {}
        #: The idle that will build the menus again, if one is pending.
        self._rebuild_pending: int | None = None
        #: Accelerators that are not MComix' own keybindings hang here.
        #: A shortcut controller triggers the actions by name.
        self.shortcuts = Gtk.ShortcutController()
        self.shortcuts.set_scope(Gtk.ShortcutScope.GLOBAL)
        window.add_controller(self.shortcuts)

        def _action_lambda(fn: Callable[..., object],  # type: ignore[explicit-any]  # the function it wraps takes whatever it takes
                           *args: object) -> _PlainCallback:
            """A callback that runs <fn> with <args> and nothing else."""
            def run(_action: Gio.SimpleAction) -> None:
                fn(*args)
            return run

        # ----------------------------------------------------------------
        # Create actions for the menus.
        # ----------------------------------------------------------------
        self._actions.add([
            _Entry('copy_page', 'edit-copy', _('_Copy'), _('Copies the current page to clipboard.'),
                   window.clipboard.copy_page),
            _Entry('copy_page_popup', 'edit-copy', _('_Copy page'),
                   _('Copies the page the menu was opened over to the clipboard.'),
                   window.clipboard.copy_popup_page),
            _Entry('delete', 'edit-delete', _('_Delete'), _('Deletes the current file or archive from disk.'),
                   window.file_actions.delete),
            _Entry('rename_page_popup', 'document-edit', _('Re_name page...'),
                   _('Renames the page the menu was opened over.'),
                   window.file_actions.rename_popup_page),
            _Entry('delete_page_popup', 'edit-delete', _('_Delete page'),
                   _('Removes the page the menu was opened over from the book. The archive on disk is not changed until it is saved.'),
                   window.file_actions.delete_popup_page),
            _Entry('remove_bookmark_popup', 'edit-delete', _('_Remove bookmark'),
                   _('Removes the bookmark of the page the menu was opened over.'),
                   _action_lambda(self._remove_popup_bookmark)),
            _Entry('unpick_pages', 'edit-clear', _('Pu_t back pages picked out'),
                   _('Puts back every page picked out with CTRL and a click.'),
                   window.clear_selection),
            _Entry('undo', 'edit-undo', _('_Undo'),
                   _('Takes back the last page removed from the book.'),
                   window.file_actions.undo),
            _Entry('redo', 'edit-redo', _('_Redo'),
                   _('Removes again the page the last undo brought back.'),
                   window.file_actions.redo),
            _Entry('next_page', 'go-next-symbolic', _('_Next page'), _('Next page'), _action_lambda(window.flip_page, +1)),
            _Entry('previous_page', 'go-previous-symbolic', _('_Previous page'), _('Previous page'), _action_lambda(window.flip_page, -1)),
            _Entry('first_page', 'go-first-symbolic', _('_First page'), _('First page'), _action_lambda(window.first_page)),
            _Entry('last_page', 'go-last-symbolic', _('_Last page'), _('Last page'), _action_lambda(window.last_page)),
            _Entry('go_to', 'go-jump-symbolic', _('_Go to page...'), _('Go to page...'), window.page_select),
            _Entry('refresh_archive', 'view-refresh', _('Re_fresh'), _('Reloads the currently opened files or archive.'),
                   window.filehandler.refresh_file),
            _Entry('next_archive', 'media-skip-forward-symbolic', _('Next _archive'), _('Next archive'), window.filehandler.next_archive),
            _Entry('previous_archive', 'media-skip-backward-symbolic', _('Previous a_rchive'), _('Previous archive'), window.filehandler.previous_archive),
            _Entry('next_directory', 'edit-redo', _('Next directory'), _('Next directory'), window.filehandler.open_next_directory),
            _Entry('previous_directory', 'edit-undo', _('Previous directory'), _('Previous directory'), window.filehandler.open_previous_directory),
            _Entry('zoom_in', 'zoom-in', _('Zoom _In'), None, window.manual_zoom_in),
            _Entry('zoom_out', 'zoom-out', _('Zoom _Out'), None, window.manual_zoom_out),
            _Entry('zoom_original', 'zoom-original', _('_Normal Size'), None, window.manual_zoom_original),
            _Entry('minimize', 'view-restore', _('Mi_nimize'), None, window.minimize),
            _Entry('leave_fullscreen', 'view-restore-symbolic', _('Leave fullscreen'), None,
                   _action_lambda(self._leave_fullscreen)),
            _Entry('close', 'window-close', _('_Close'), _('Closes all opened files.'), _action_lambda(window.filehandler.close_file)),
            _Entry('quit', 'application-exit', _('_Quit'), None, window.close_program),
            _Entry('save_and_quit', 'application-exit', _('_Save and quit'), _('Quits and restores the currently opened file next time the program starts.'),
                   window.save_and_terminate_program),
            _Entry('rotate_90', 'mcomix-rotate-90', _('_Rotate 90° CW'), None, window.rotate_90),
            _Entry('rotate_180', 'mcomix-rotate-180', _('Rotate _180°'), None, window.rotate_180),
            _Entry('rotate_270', 'mcomix-rotate-270', _('Rotat_e 90° CCW'), None, window.rotate_270),
            _Entry('flip_horiz', 'mcomix-flip-horizontal', _('Fli_p horizontally'), None, window.flip_horizontally),
            _Entry('flip_vert', 'mcomix-flip-vertical', _('Flip _vertically'), None, window.flip_vertically),
            _Entry('extract_page', 'document-save-as', _('Save _As'), None, window.file_actions.extract_page),
            _Entry('extract_page_popup', 'document-save-as', _('Save _As'), _('Saves the page the menu was opened over.'),
                   window.file_actions.extract_popup_page),
            _Entry('menu_zoom', 'mcomix-zoom', _('_Zoom')),
            _Entry('menu_recent', 'text-x-generic', _('_Recent')),
            _Entry('menu_bookmarks_popup', 'mcomix-add-bookmark', _('_Bookmarks')),
            _Entry('menu_bookmarks', None, _('_Bookmarks')),
            _Entry('menu_toolbars', None, _('T_oolbars')),
            _Entry('menu_edit', None, _('_Edit')),
            _Entry('menu_open_with', 'document-open', _('Open _with')),
            _Entry('menu_open_with_popup', 'document-open', _('Open _with')),
            _Entry('menu_move_to_popup', 'folder-symbolic', _('_Move to'),
                   _('Moves the file, or the archive the page is in, to another folder.')),
            _Entry('menu_file', None, _('_File')),
            _Entry('menu_view', None, _('_View')),
            _Entry('menu_view_popup', 'mcomix-image', _('_View')),
            _Entry('menu_go', None, _('_Go')),
            _Entry('menu_go_popup', 'go-next', _('_Go')),
            _Entry('menu_tools', None, _('_Tools')),
            _Entry('menu_transform', 'mcomix-transform', _('_Transform image')),
            _Entry('menu_autorotate', None, _('_Auto-rotate image')),
            _Entry('menu_autorotate_width', None, _('...when width exceeds height')),
            _Entry('menu_autorotate_height', None, _('...when height exceeds width')),
            _Entry('expander', None, None, None, None)])

        self._actions.add_toggle([
            _Entry('fullscreen', 'view-fullscreen-symbolic', _('_Fullscreen'), _('Fullscreen mode'), window.change_fullscreen),
            _Entry('double_page', 'view-dual-symbolic', _('_Double page mode'), _('Double page mode'), window.change_double_page),
            _Entry('title_page_alone', None, _('_Title page alone'), None, window.change_title_page_alone),
            _Entry('toolbar', None, _('_Toolbar'), None, window.change_toolbar_visibility),
            _Entry('menubar', None, _('_Menubar'), None, window.change_menubar_visibility),
            _Entry('statusbar', None, _('St_atusbar'), None, window.change_statusbar_visibility),
            _Entry('scrollbar', None, _('S_crollbars'), None, window.change_scrollbar_visibility),
            _Entry('thumbnails', None, _('Th_umbnails'), None, window.change_thumbnails_visibility),
            _Entry('hide_all', None, _('H_ide all'), None, window.change_hide_all),
            _Entry('manga_mode', 'view-mirror-symbolic', _('_Manga mode'), _('Manga mode'), window.change_manga_mode),
            _Entry('invert_scroll', 'edit-undo', _('Invert smart scroll'), _('Invert smart scrolling direction.'), window.change_invert_scroll),
            _Entry('keep_transformation', None, _('_Keep transformation'), _('Keeps the currently selected transformation for the next pages.'),
                   window.change_keep_transformation),
            _Entry('slideshow', 'media-playback-start-symbolic', _('Start slid_eshow'), _('Start slideshow'), window.slideshow.toggle),
            _Entry('lens', 'edit-find-symbolic', _('Magnifying _lens'), _('Magnifying lens'), window.lens.toggle),
            _Entry('stretch', None, _('Stretch small images'), _('Stretch images to fit to the screen, depending on zoom mode.'),
                   window.change_stretch),
            _Entry('invert_color', None, _('_Invert image colors'), _('Invert image colors'), window.change_invert_color)])

        # Note: Don't change the default value for the radio buttons unless
        # also fixing the code for setting the correct one on start-up in main.py.
        self._actions.add_radio('zoom-mode', [
            _Choice('best_fit_mode', 'zoom-fit-best-symbolic', _('_Best fit mode'), _('Best fit mode'), constants.ZoomMode.BEST),
            _Choice('fit_width_mode', 'mcomix-fit-width-symbolic', _('Fit _width mode'), _('Fit width mode'), constants.ZoomMode.WIDTH),
            _Choice('fit_height_mode', 'mcomix-fit-height-symbolic', _('Fit _height mode'), _('Fit height mode'), constants.ZoomMode.HEIGHT),
            _Choice('fit_size_mode', 'mcomix-fit-size-symbolic', _('Fit _size mode'), _('Fit to size mode'), constants.ZoomMode.SIZE),
            _Choice('fit_manual_mode', 'mcomix-fit-manual-symbolic', _('M_anual zoom mode'), _('Manual zoom mode'), constants.ZoomMode.MANUAL)],
            3, window.change_zoom_mode)

        # Automatically rotate image if width>height or height>width
        self._actions.add_radio('autorotation', [
            _Choice('no_autorotation', None, _('Never'), None, constants.AUTOROTATE_NEVER),
            _Choice('rotate_90_width', 'mcomix-rotate-90', _('_Rotate 90° CW'), None, constants.AUTOROTATE_WIDTH_90),
            _Choice('rotate_270_width', 'mcomix-rotate-270', _('Rotat_e 90° CCW'), None, constants.AUTOROTATE_WIDTH_270),
            _Choice('rotate_90_height', 'mcomix-rotate-90', _('_Rotate 90° CW'), None, constants.AUTOROTATE_HEIGHT_90),
            _Choice('rotate_270_height', 'mcomix-rotate-270', _('Rotat_e 90° CCW'), None, constants.AUTOROTATE_HEIGHT_270)],
            prefs['auto rotate depending on size'], window.change_autorotation)

        self._actions.add_with_data([
            _Entry('about', 'help-about', _('A_bout'), None, dialog_handler.open_dialog)], (window, 'about-dialog'))

        self._actions.add_with_data([
            _Entry('comments', 'mcomix-comments', _('Co_mments...'), None, dialog_handler.open_dialog)], (window, 'comments-dialog'))

        self._actions.add_with_data([
            _Entry('properties', 'document-properties', _('Proper_ties'), None, dialog_handler.open_dialog)], (window, 'properties-dialog'))

        self._actions.add_with_data([
            _Entry('preferences', 'preferences-system', _('_Preferences'), None, preferences_dialog.open_dialog)], window)

        # Some actions added separately since they need extra arguments.
        self._actions.add_with_data([
            _Entry('edit_archive', 'document-edit-symbolic', _('_Edit archive...'), _('Opens the archive editor.'),
                   edit_dialog.open_dialog),
            _Entry('open', 'document-open', _('_Open...'), None, file_chooser_main_dialog.open_main_filechooser_dialog),
            _Entry('enhance_image', 'mcomix-enhance-image', _('Enha_nce image...'), None, enhance_dialog.open_dialog)], window)

        self._actions.add_with_data([
            _Entry('library', 'mcomix-library', _('_Library...'), None, library_main_dialog.open_dialog)], window)

        self._window.insert_action_group(Actions.PREFIX, self._actions.group)

        # The three menus whose contents change while the program runs
        # keep models of their own, spliced into the layouts below.
        self.bookmarks = bookmark_menu.BookmarksMenu(self, window)
        self.recent = recent.RecentFilesMenu(self, window)
        self._openwith = openwith_menu.OpenWithMenu(window)
        self.move_to = move_menu.MoveToMenu(window, self.recent)

        # A GTK4 menu bar is a row of popovers.
        self.menubar = Gtk.PopoverMenuBar.new_from_model(self._build(_MENUBAR))
        # NESTED: a submenu opens as a popover of its own.  A sliding
        # popover menu keeps every page in one stack and is as wide as
        # the widest item on any of them, so the eight short entries of
        # the top level would be laid out to fit "Previous archive" and its
        # accelerator, three pages down.
        self.popup = Gtk.PopoverMenu.new_from_model_full(
            self._build(_POPUP), Gtk.PopoverMenuFlags.NESTED)
        self.popup.set_parent(window)
        self.toolbar = self._build_toolbar()

        # A middle click on a recent file or a bookmark opens it in an
        # MComix of its own, and a menu model says nothing about which
        # button reached an item.
        widgets.watch_menu_clicks(self.menubar)
        widgets.watch_menu_clicks(self.popup)

        # Only the menu bar, which is a widget in the window like any
        # other.  The popup is a Gtk.PopoverMenu, and a popover that is
        # visible is *open*: it takes an input grab, and on Wayland it is
        # an xdg_popup the compositor has to be asked for, which GTK
        # waits on while the window maps.  It is shown by popup_at() when
        # there is a place to point it at.
        self.menubar.set_visible(True)

    def set_accelerator(self, name: str, accelerator: str) -> None:
        """Show <accelerator> against <name>'s items in the menus.

        Gtk.AccelMap is gone in GTK4, and with it the accelerator paths
        that kept a menu item's label in step with the keybinding.  A
        GTK4 menu takes the accelerator as an attribute of the model
        item, so the models are built again when one changes - once, from
        an idle, however many bindings are registered at a time.
        """
        if self._accelerators.get(name) == accelerator:
            return
        self._accelerators[name] = accelerator
        if self._rebuild_pending is None:
            self._rebuild_pending = GLib.idle_add(self._rebuild_menus)

    def accelerator(self, name: str) -> str | None:
        """The accelerator the menus show for the keybinding action
        <name>, if it has one."""
        return self._accelerators.get(name)

    def _rebuild_menus(self) -> bool:
        self._rebuild_pending = None
        self.menubar.set_menu_model(self._build(_MENUBAR))
        self.popup.set_menu_model(self._build(_POPUP))
        # The bookmarks menu builds its fixed entries itself.
        self.bookmarks.refresh()
        # A new model is a new set of popovers below the two roots.
        widgets.watch_menu_clicks(self.menubar)
        widgets.watch_menu_clicks(self.popup)
        return GLib.SOURCE_REMOVE

    def release(self) -> None:
        """Let go of the closed window.

        An action's handler is held with the action in C, out of sight
        of Python's collector, and most of them are the window's own
        methods or closures over it; while a group holds its actions,
        the window cannot be freed.  So every group the menus keep is
        emptied, this one's own included.
        """
        widgets.empty_action_group(self._actions.group)
        for menu in (self.bookmarks, self.recent, self._openwith,
                     self.move_to):
            menu.release()

    def _remove_popup_bookmark(self) -> None:
        page = self._window.popup_page
        if page is not None:
            bookmark_backend.BookmarksStore.remove_for_page(page)

    def _leave_fullscreen(self) -> None:
        """Turn the fullscreen toggle off, which leaves fullscreen."""
        self._actions.get_action('fullscreen').set_active(False)

    def add_shortcut(self, accelerator: str, action: str) -> None:
        """Make <accelerator> trigger the named <action>."""
        self.shortcuts.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string(accelerator),
            Gtk.NamedAction.new(action)))

    def _dynamic(self, name: str) -> "Gio.Menu | None":
        """The model of a submenu that is rebuilt as the program runs."""
        return {'menu_recent': self.recent.model,
                'menu_open_with': self._openwith.model,
                'menu_open_with_popup': self._openwith.model,
                'menu_bookmarks': self.bookmarks.model,
                'menu_bookmarks_popup': self.bookmarks.model,
                'menu_move_to_popup': self.move_to.model}.get(name)

    def _build(self, layout: _Layout) -> Gio.Menu:
        """Turn one of the layouts below into a Gio.Menu.

        A layout is a sequence of action names, with None where the XML
        this replaces had a separator - a menu model says that by starting
        a new section - and a (name, sub-layout) pair for a submenu.
        """
        model = Gio.Menu()
        section = Gio.Menu()
        for item in layout:
            if item is None:
                if section.get_n_items():
                    model.append_section(None, section)
                section = Gio.Menu()
                continue
            if isinstance(item, tuple):
                name, contents = item
                section.append_submenu(self._actions.label(name),
                                       self._build(contents))
                continue
            dynamic = self._dynamic(item)
            if dynamic is not None:
                # Built and rebuilt elsewhere.
                section.append_submenu(self._actions.label(item), dynamic)
                continue
            entry = Gio.MenuItem.new(self._actions.label(item), None)
            detailed, target = self._actions.detailed(item)
            entry.set_action_and_target_value(detailed, target)
            if item in _HIDDEN_WHEN_DISABLED:
                entry.set_attribute_value('hidden-when',
                                          GLib.Variant('s', 'action-disabled'))
            accelerator = self._accelerators.get(item)
            if accelerator:
                entry.set_attribute_value('accel',
                                          GLib.Variant('s', accelerator))
            section.append_item(entry)
        if section.get_n_items():
            model.append_section(None, section)
        return model

    def _build_toolbar(self) -> Gtk.Box:
        """Build the tool bar, which is a row of buttons on the actions.

        Gtk.Toolbar and every one of its items is gone in GTK4.  A tool
        bar there is a box of ordinary buttons carrying the 'toolbar'
        style class, which is what gives them the flat look.
        """
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar.add_css_class('toolbar')
        for name in _TOOLBAR:
            if name is None:
                toolbar.append(Gtk.Separator.new(Gtk.Orientation.VERTICAL))
                continue
            if name == 'expander':
                # Takes up the slack between the two groups of buttons.
                self.toolbar_expander = Gtk.Box()
                self.toolbar_expander.set_hexpand(True)
                toolbar.append(self.toolbar_expander)
                continue
            detailed, target = self._actions.detailed(name)
            stateful = self._actions.is_stateful(name)
            button = Gtk.ToggleButton() if stateful else Gtk.Button()
            icon = Gtk.Image.new_from_icon_name(self._actions.icon(name))
            # Gtk.IconSize.LARGE_TOOLBAR by another name.
            icon.set_icon_size(Gtk.IconSize.LARGE)
            button.set_child(icon)
            button.set_has_frame(False)
            # Keep the focus out of the tool bar, or space and the arrow
            # keys would work it instead of turning pages.
            button.set_can_focus(False)
            button.set_focus_on_click(False)
            tooltip = self._actions.tooltips.get(self._actions.label(name))
            if tooltip:
                button.set_tooltip_text(tooltip)
            if target is not None:
                button.set_action_target_value(target)
            button.set_action_name(detailed)
            toolbar.append(button)
            if name == 'slideshow':
                self.slideshow_button = button
        return toolbar

    def set_sensitivities(self) -> None:
        """Sets the main UI's widget's sensitivities appropriately."""
        general = ('properties',
                   'edit_archive',
                   'extract_page',
                   'extract_page_popup',
                   'delete_page_popup',
                   'unpick_pages',
                   'undo',
                   'redo',
                   'save_and_quit',
                   'close',
                   'delete',
                   'copy_page',
                   'slideshow',
                   'rotate_90',
                   'rotate_180',
                   'rotate_270',
                   'flip_horiz',
                   'flip_vert',
                   'next_page',
                   'previous_page',
                   'first_page',
                   'last_page',
                   'go_to',
                   'refresh_archive',
                   'next_archive',
                   'previous_archive',
                   'next_directory',
                   'previous_directory',
                   'keep_transformation',
                   'enhance_image')

        comment = ('comments',)

        general_sensitive = False
        comment_sensitive = False

        if self._window.filehandler.file_loaded:
            general_sensitive = True

            if self._window.filehandler.get_number_of_comments():
                comment_sensitive = True

        for name in general:
            self._actions.get_action(name).set_sensitive(general_sensitive)

        for name in comment:
            self._actions.get_action(name).set_sensitive(comment_sensitive)

        self.bookmarks.set_sensitive(general_sensitive)

# vim: expandtab:sw=4:ts=4
