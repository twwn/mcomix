"""ui.py - UI definitions for main window.
"""

from gi.repository import Gio, GLib, Gtk

from typing import Any

from mcomix import bookmark_menu
from mcomix import openwith_menu
from mcomix import edit_dialog
from mcomix import enhance_dialog
from mcomix import preferences_dialog
from mcomix import recent
from mcomix import dialog_handler
from mcomix import constants
from mcomix import file_chooser_main_dialog
from mcomix.preferences import prefs
from mcomix.library import main_dialog as library_main_dialog
from mcomix.i18n import _

def _gio_name(name: str) -> str:
    """The name a Gio action can be registered under.

    Gio action names take alphanumerics, hyphens and dots, and MComix'
    names are full of underscores, so those become hyphens.  Nothing
    outside this module needs to know: actions are asked for by the names
    MComix has always used.
    """
    return name.replace('_', '-')


class _Action(object):

    """One of the window's actions, in the shape the rest of MComix asks
    for it.

    Gtk.Action offered activate(), set_active() and set_sensitive(), and
    those three are all that is used.  Gio spells them differently - a
    toggle is set by handing its action a GLib.Variant - so this keeps the
    callers reading as they did.
    """

    def __init__(self, action: Any, target: Any = None) -> None:
        self._action = action
        self._target = target

    def detailed(self, prefix: str) -> tuple:
        """How a menu item or tool button addresses this action."""
        return '%s.%s' % (prefix, self._action.get_name()), self._target

    def activate(self, *args: Any) -> None:
        self._action.activate(self._target)

    def set_active(self, active: Any) -> None:
        # Gtk.ToggleAction.set_active() was a no-op when the value did not
        # change; Gio.SimpleAction.change_state() always announces one, so
        # only change what has actually changed.
        if bool(active) != self.get_active():
            self._action.change_state(GLib.Variant('b', bool(active)))

    def get_active(self) -> bool:
        return bool(self._action.get_state().get_boolean())

    def get_current_value(self) -> int:
        """The value the radio group this belongs to currently holds."""
        return int(self._action.get_state().get_int32())

    def set_sensitive(self, sensitive: Any) -> None:
        self._action.set_enabled(bool(sensitive))

    def get_sensitive(self) -> bool:
        return bool(self._action.get_enabled())


class _Actions(object):

    """The window's actions, under the names the rest of MComix uses.

    The tables handed to add(), add_toggle() and add_radio() are the ones
    Gtk.ActionGroup took: (name, icon name, label, accelerator, tooltip,
    and a callback or, for a radio entry, its value).
    """

    #: The prefix menu items and tool buttons address these actions by.
    PREFIX = 'win'

    def __init__(self) -> None:
        self.group = Gio.SimpleActionGroup()
        self._by_name: dict = {}
        self._labels: dict = {}
        self._icons: dict = {}
        self._stateful: set = set()
        #: Tooltips, by label, for the status bar helper.
        self.tooltips: dict = {}

    def get_action(self, name: str) -> Any:
        return self._by_name[name]

    def detailed(self, name: str) -> tuple:
        return self._by_name[name].detailed(self.PREFIX)

    def label(self, name: str) -> str:
        return self._labels[name]

    def icon(self, name: str) -> Any:
        return self._icons[name]

    def is_stateful(self, name: str) -> bool:
        """Whether the action shows as pressed when it is on."""
        return name in self._stateful

    def _remember(self, name: str, entry: tuple, action: Any,
                  target: Any = None, stateful: bool = False) -> None:
        self._by_name[name] = _Action(action, target)
        label, tooltip = entry[2], (entry[4] if len(entry) > 4 else None)
        self._labels[name] = label
        self._icons[name] = entry[1]
        if stateful:
            self._stateful.add(name)
        if label and tooltip:
            self.tooltips[label] = tooltip

    def add(self, entries: Any, user_data: Any = None) -> None:
        """Add plain actions."""
        for entry in entries:
            action = Gio.SimpleAction.new(_gio_name(entry[0]), None)
            callback = entry[5] if len(entry) > 5 else None
            if callback is not None:
                action.connect('activate', self._activated, callback, user_data)
            self.group.add_action(action)
            self._remember(entry[0], entry, action)

    def add_toggle(self, entries: Any) -> None:
        """Add actions that are on or off."""
        for entry in entries:
            action = Gio.SimpleAction.new_stateful(
                _gio_name(entry[0]), None, GLib.Variant('b', False))
            callback = entry[5] if len(entry) > 5 else None
            action.connect('change-state', self._toggled, entry[0], callback)
            self.group.add_action(action)
            self._remember(entry[0], entry, action, stateful=True)

    def add_radio(self, name: str, entries: Any, value: int,
                  on_change: Any) -> None:
        """Add one group of mutually exclusive actions.

        Gtk.RadioAction gave every member its own action carrying a value;
        one stateful action holding that value says the same thing, with
        the members as targets on it.
        """
        action = Gio.SimpleAction.new_stateful(
            name, GLib.VariantType.new('i'), GLib.Variant('i', value))
        action.connect('change-state', self._radio_changed, name, on_change)
        self.group.add_action(action)
        for entry in entries:
            self._remember(entry[0], entry, action,
                           GLib.Variant('i', entry[5]), stateful=True)

    def _activated(self, action: Any, parameter: Any, callback: Any,
                   user_data: Any) -> None:
        if user_data is None:
            callback(action)
        else:
            callback(action, user_data)

    def _toggled(self, action: Any, value: Any, name: str,
                 callback: Any) -> None:
        action.set_state(value)
        if callback is not None:
            callback(self._by_name[name])

    def _radio_changed(self, action: Any, value: Any, name: str,
                       on_change: Any) -> None:
        action.set_state(value)
        if on_change is not None:
            on_change(_Action(action))



#: The menu bar, as the <menubar> element described it.  None is a
#: separator, and a pair is a submenu.
_MENUBAR = (
    ('menu_file', ('open', 'menu_recent', 'library', None,
                   'extract_page', 'refresh_archive', 'properties', None,
                   'menu_open_with', None,
                   'delete', None,
                   'minimize', 'close', 'save_and_quit', 'quit')),
    ('menu_edit', ('copy_page', None,
                   'edit_archive', 'comments', None,
                   'preferences')),
    ('menu_view', ('fullscreen', 'double_page', 'manga_mode', None,
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
    ('menu_help', ('about',)),
)

#: The right-click menu, as the <popup> element described it.
_POPUP = (
    ('menu_go_popup', ('next_page', 'previous_page', 'go_to',
                       'first_page', 'last_page', None,
                       'next_archive', 'previous_archive', None,
                       'next_directory', 'previous_directory')),
    ('menu_view_popup', ('fullscreen', 'double_page', 'manga_mode', None,
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
    'menu_bookmarks_popup',
    None,
    'open', 'menu_recent', 'library',
    None,
    'menu_open_with_popup',
    None,
    'preferences',
    None,
    'close', 'quit',
)

#: The tool bar, as the <toolbar> element described it.
_TOOLBAR = ('previous_archive', 'first_page', 'previous_page', 'go_to',
            'next_page', 'last_page', 'next_archive', None,
            'fullscreen', 'slideshow', 'expander',
            'best_fit_mode', 'fit_width_mode', 'fit_height_mode',
            'fit_size_mode', 'fit_manual_mode', None,
            'double_page', 'manga_mode', None,
            'lens')


class MainUI(object):

    def __init__(self, window):
        self._window = window
        self.actions = self._actions = _Actions()
        #: The accelerator each action currently answers to, by name.
        self._accelerators: dict = {}
        #: The idle that will build the menus again, if one is pending.
        self._rebuild_pending = None
        #: Accelerators that are not MComix' own keybindings hang here.
        #: Gtk.UIManager provided a Gtk.AccelGroup for this; GTK4 has
        #: shortcut controllers, which trigger the actions by name.
        self.shortcuts = Gtk.ShortcutController()
        self.shortcuts.set_scope(Gtk.ShortcutScope.GLOBAL)
        window.add_controller(self.shortcuts)

        def _action_lambda(fn, *args):
            return lambda *_: fn(*args)

        # ----------------------------------------------------------------
        # Create actions for the menus.
        # ----------------------------------------------------------------
        self._actions.add([
            ('copy_page', 'edit-copy', _('_Copy'),
                None, _('Copies the current page to clipboard.'),
                window.clipboard.copy_page),
            ('delete', 'edit-delete', _('_Delete'),
                None, _('Deletes the current file or archive from disk.'),
                window.delete),
            ('next_page', 'go-next', _('_Next page'),
             None, _('Next page'), _action_lambda(window.flip_page, +1)),
            ('previous_page', 'go-previous', _('_Previous page'),
             None, _('Previous page'), _action_lambda(window.flip_page, -1)),
            ('first_page', 'go-first', _('_First page'),
             None, _('First page'), _action_lambda(window.first_page)),
            ('last_page', 'go-last', _('_Last page'),
             None, _('Last page'), _action_lambda(window.last_page)),
            ('go_to', 'go-jump', _('_Go to page...'),
                None, _('Go to page...'), window.page_select),
            ('refresh_archive', 'view-refresh', _('Re_fresh'),
                None, _('Reloads the currently opened files or archive.'),
                window.filehandler.refresh_file),
            ('next_archive', 'media-skip-forward', _('Next _archive'),
                None, _('Next archive'), window.filehandler._open_next_archive),
            ('previous_archive', 'media-skip-backward', _('Previous a_rchive'),
                None, _('Previous archive'), window.filehandler._open_previous_archive),
            ('next_directory', 'edit-redo', _('Next directory'),
                None, _('Next directory'), window.filehandler.open_next_directory),
            ('previous_directory', 'edit-undo', _('Previous directory'),
                None, _('Previous directory'), window.filehandler.open_previous_directory),
            ('zoom_in', 'zoom-in', _('Zoom _In'),
                None, None, window.manual_zoom_in),
            ('zoom_out', 'zoom-out', _('Zoom _Out'),
                None, None, window.manual_zoom_out),
            ('zoom_original', 'zoom-original', _('_Normal Size'),
                None, None, window.manual_zoom_original),
            ('minimize', 'view-restore', _('Mi_nimize'),
                None, None, window.minimize),
            ('close', 'window-close', _('_Close'),
                None, _('Closes all opened files.'), _action_lambda(window.filehandler.close_file)),
            ('quit', 'application-exit', _('_Quit'),
                None, None, window.close_program),
            ('save_and_quit', 'application-exit', _('_Save and quit'),
                None, _('Quits and restores the currently opened file next time the program starts.'),
                window.save_and_terminate_program),
            ('rotate_90', 'mcomix-rotate-90', _('_Rotate 90 degrees CW'),
                None, None, window.rotate_90),
            ('rotate_180','mcomix-rotate-180', _('Rotate 180 de_grees'),
                None, None, window.rotate_180),
            ('rotate_270', 'mcomix-rotate-270', _('Rotat_e 90 degrees CCW'),
                None, None, window.rotate_270),
            ('flip_horiz', 'mcomix-flip-horizontal', _('Fli_p horizontally'),
                None, None, window.flip_horizontally),
            ('flip_vert', 'mcomix-flip-vertical', _('Flip _vertically'),
                None, None, window.flip_vertically),
            ('extract_page', 'document-save-as', _('Save _As'),
                None, None, window.extract_page),
            ('menu_zoom', 'mcomix-zoom', _('_Zoom')),
            ('menu_recent', 'text-x-generic', _('_Recent')),
            ('menu_bookmarks_popup', 'mcomix-add-bookmark', _('_Bookmarks')),
            ('menu_bookmarks', None, _('_Bookmarks')),
            ('menu_toolbars', None, _('T_oolbars')),
            ('menu_edit', None, _('_Edit')),
            ('menu_open_with', 'document-open', _('Open _with'), ''),
            ('menu_open_with_popup', 'document-open', _('Open _with'), ''),
            ('menu_file', None, _('_File')),
            ('menu_view', None, _('_View')),
            ('menu_view_popup', 'mcomix-image', _('_View')),
            ('menu_go', None, _('_Go')),
            ('menu_go_popup', 'go-next', _('_Go')),
            ('menu_tools', None, _('_Tools')),
            ('menu_help', None, _('_Help')),
            ('menu_transform', 'mcomix-transform', _('_Transform image')),
            ('menu_autorotate', None, _('_Auto-rotate image')),
            ('menu_autorotate_width', None, _('...when width exceeds height')),
            ('menu_autorotate_height', None, _('...when height exceeds width')),
            ('expander', None, None, None, None, None)])

        self._actions.add_toggle([
            ('fullscreen', 'view-fullscreen', _('_Fullscreen'),
                None, _('Fullscreen mode'), window.change_fullscreen),
            ('double_page', 'mcomix-double-page', _('_Double page mode'),
                None, _('Double page mode'), window.change_double_page),
            ('toolbar', None, _('_Toolbar'),
                None, None, window.change_toolbar_visibility),
            ('menubar', None, _('_Menubar'),
                None, None, window.change_menubar_visibility),
            ('statusbar', None, _('St_atusbar'),
                None, None, window.change_statusbar_visibility),
            ('scrollbar', None, _('S_crollbars'),
                None, None, window.change_scrollbar_visibility),
            ('thumbnails', None, _('Th_umbnails'),
                None, None, window.change_thumbnails_visibility),
            ('hide_all', None, _('H_ide all'),
                None, None, window.change_hide_all),
            ('manga_mode', 'mcomix-manga', _('_Manga mode'),
                None, _('Manga mode'), window.change_manga_mode),
            ('invert_scroll', 'edit-undo', _('Invert smart scroll'),
                None, _('Invert smart scrolling direction.'), window.change_invert_scroll),
            ('keep_transformation', None, _('_Keep transformation'),
                None, _('Keeps the currently selected transformation for the next pages.'),
                window.change_keep_transformation),
            ('slideshow', 'media-playback-start', _('Start _slideshow'),
                None, _('Start slideshow'), window.slideshow.toggle),
            ('lens', 'mcomix-lens', _('Magnifying _lens'),
                None, _('Magnifying lens'), window.lens.toggle),
            ('stretch', None, _('Stretch small images'),
                None, _('Stretch images to fit to the screen, depending on zoom mode.'),
                window.change_stretch),
            ('invert_color', None, _('_Invert image colors'),
                None, _('Invert image colors'), window.change_invert_color)])

        # Note: Don't change the default value for the radio buttons unless
        # also fixing the code for setting the correct one on start-up in main.py.
        self._actions.add_radio('zoom-mode', [
            ('best_fit_mode', 'mcomix-fitbest', _('_Best fit mode'),
                None, _('Best fit mode'), constants.ZoomMode.BEST),
            ('fit_width_mode', 'mcomix-fitwidth', _('Fit _width mode'),
                None, _('Fit width mode'), constants.ZoomMode.WIDTH),
            ('fit_height_mode', 'mcomix-fitheight', _('Fit _height mode'),
                None, _('Fit height mode'), constants.ZoomMode.HEIGHT),
            ('fit_size_mode', 'mcomix-fitsize', _('Fit _size mode'),
                None, _('Fit to size mode'), constants.ZoomMode.SIZE),
            ('fit_manual_mode', 'mcomix-fitmanual', _('M_anual zoom mode'),
                None, _('Manual zoom mode'), constants.ZoomMode.MANUAL)],
            3, window.change_zoom_mode)

        # Automatically rotate image if width>height or height>width
        self._actions.add_radio('autorotation', [
            ('no_autorotation', None, _('Never'),
             None, None, constants.AUTOROTATE_NEVER),
            ('rotate_90_width', 'mcomix-rotate-90', _('_Rotate 90 degrees CW'),
             None, None, constants.AUTOROTATE_WIDTH_90),
            ('rotate_270_width', 'mcomix-rotate-270', _('Rotat_e 90 degrees CCW'),
             None, None, constants.AUTOROTATE_WIDTH_270),
            ('rotate_90_height', 'mcomix-rotate-90', _('_Rotate 90 degrees CW'),
             None, None, constants.AUTOROTATE_HEIGHT_90),
            ('rotate_270_height', 'mcomix-rotate-270', _('Rotat_e 90 degrees CCW'),
             None, None, constants.AUTOROTATE_HEIGHT_270)],
            prefs['auto rotate depending on size'], window.change_autorotation)

        self._actions.add([
            ('about', 'help-about', _('_About'),
             None, None, dialog_handler.open_dialog)], (window, 'about-dialog'))

        self._actions.add([
            ('comments', 'mcomix-comments', _('Co_mments...'),
             None, None, dialog_handler.open_dialog)], (window, 'comments-dialog'))

        self._actions.add([
            ('properties', 'document-properties', _('Proper_ties'),
            None, None, dialog_handler.open_dialog)], (window,'properties-dialog'))

        self._actions.add([
            ('preferences', 'preferences-system', _('Pr_eferences'),
                None, None, preferences_dialog.open_dialog)], window)

        # Some actions added separately since they need extra arguments.
        self._actions.add([
            ('edit_archive', 'document-edit-symbolic', _('_Edit archive...'),
                None, _('Opens the archive editor.'),
                edit_dialog.open_dialog),
            ('open', 'document-open', _('_Open...'),
                None, None, file_chooser_main_dialog.open_main_filechooser_dialog),
            ('enhance_image', 'mcomix-enhance-image', _('En_hance image...'),
                None, None, enhance_dialog.open_dialog)], window)

        self._actions.add([
            ('library', 'mcomix-library', _('_Library...'),
                None, None, library_main_dialog.open_dialog)], window)

        self._window.insert_action_group(_Actions.PREFIX, self._actions.group)

        # The three menus whose contents change while the program runs
        # keep models of their own, spliced into the layouts below.
        self.bookmarks = bookmark_menu.BookmarksMenu(self, window)
        self.bookmarks_popup = self.bookmarks
        self.recent = recent.RecentFilesMenu(self, window)
        self.recentPopup = self.recent
        self._openwith = openwith_menu.OpenWithMenu(window)

        # Gtk.MenuBar is gone; a GTK4 menu bar is a row of popovers.
        self.menubar = Gtk.PopoverMenuBar.new_from_model(self._build(_MENUBAR))
        self.popup = Gtk.PopoverMenu.new_from_model(self._build(_POPUP))
        self.popup.set_parent(window)
        self.toolbar = self._build_toolbar()

        for menu in (self.menubar, self.popup):
            menu.set_visible(True)

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

    def _rebuild_menus(self) -> bool:
        self._rebuild_pending = None
        self.menubar.set_menu_model(self._build(_MENUBAR))
        self.popup.set_menu_model(self._build(_POPUP))
        return GLib.SOURCE_REMOVE

    def add_shortcut(self, accelerator, action):
        """Make <accelerator> trigger the named <action>."""
        self.shortcuts.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string(accelerator),
            Gtk.NamedAction.new(action)))

    def _dynamic(self, name):
        """The model of a submenu that is rebuilt as the program runs."""
        return {'menu_recent': self.recent.model,
                'menu_open_with': self._openwith.model,
                'menu_open_with_popup': self._openwith.model,
                'menu_bookmarks': self.bookmarks.model,
                'menu_bookmarks_popup': self.bookmarks.model}.get(name)

    def _build(self, layout):
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
            accelerator = self._accelerators.get(item)
            if accelerator:
                entry.set_attribute_value('accel',
                                          GLib.Variant('s', accelerator))
            section.append_item(entry)
        if section.get_n_items():
            model.append_section(None, section)
        return model

    def _build_toolbar(self):
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
