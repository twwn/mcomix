"""What the menu bar and the right-click menu hold, and the Help menu's
entries.

The menus are tuples in ui.py, so where an item stands is read from
them; what an item does is read from the window it was built for.
"""

import unittest.mock

from gi.repository import GLib, Gtk

from . import (MComixTest, MainWindowLaterTest, MainWindowOpenTest, hold_open,
               pump, wait_for)

from mcomix import constants
from mcomix import keybindings
from mcomix import preferences_dialog
from mcomix import ui


def _submenu(layout, name):
    """The items of the submenu <name> in <layout>, at its top level."""
    return dict(item for item in layout if isinstance(item, tuple))[name]


def _names(layout):
    """Every action name in <layout> and its submenus."""
    for item in layout:
        if isinstance(item, tuple):
            yield item[0]
            yield from _names(item[1])
        elif item is not None:
            yield item


class LayoutTest(MComixTest):

    def test_the_menu_bar_ends_with_help(self):
        tops = [item[0] if isinstance(item, tuple) else item
                for item in ui._MENUBAR]
        self.assertEqual(['menu_file', 'menu_edit', 'menu_view', 'menu_go',
                          'menu_bookmarks', 'menu_image', 'menu_help'], tops)
        self.assertIn('about', _submenu(ui._MENUBAR, 'menu_help'))
        self.assertNotIn('about', _submenu(ui._MENUBAR, 'menu_file'))

    def test_the_right_click_menu_turns_the_page_too(self):
        """With the menu bar hidden it is the only menu there is, and it
        had no way to rotate or flip a page."""
        image = _submenu(ui._POPUP, 'menu_image_popup')
        self.assertEqual(_submenu(ui._MENUBAR, 'menu_image'), image)
        for name in ('rotate_90', 'rotate_270', 'flip_horiz',
                     'invert_color', 'enhance_image'):
            self.assertIn(name, set(_names(image)))

    def test_the_submenus_the_two_menus_share_are_the_same(self):
        for bar, popup in (('menu_view', 'menu_view_popup'),
                           ('menu_go', 'menu_go_popup')):
            self.assertEqual(_submenu(ui._MENUBAR, bar),
                             _submenu(ui._POPUP, popup))

    def test_the_shortcuts_tab_files_the_image_menu_s_keys_together(self):
        """Enhance and invert colours were filed under File, and the
        rotations under a group of their own."""
        top = [name for name in _submenu(ui._MENUBAR, 'menu_image')
               if isinstance(name, str)]
        groups = {keybindings.BINDING_INFO[name]['group'] for name in top
                  if name in keybindings.BINDING_INFO}
        self.assertEqual({'Image'}, groups)
        for name in ('preferences', 'edit_archive', 'undo'):
            self.assertEqual('Edit', keybindings.BINDING_INFO[name]['group'])

    def test_no_item_is_in_two_places_of_the_menu_bar(self):
        names = [name for name in _names(ui._MENUBAR)
                 if not name.startswith('menu_')]
        self.assertEqual(sorted(set(names)), sorted(names))


def _accelerators(model):
    """Every accelerator the items of <model> and its submenus show."""
    for index in range(model.get_n_items()):
        accel = model.get_item_attribute_value(index, 'accel', None)
        if accel is not None:
            yield accel.get_string()
        links = model.iterate_item_links(index)
        while links.next():
            yield from _accelerators(links.get_value())


class MenusBuiltOnceTest(MainWindowLaterTest):

    """A new window built both menus, then built them again from an
    idle once it had registered its keybindings, each of which changes
    the key an item shows: 18 ms of the 65 a window with a book took to
    build and draw first.  The right-click menu, which many readers
    never open, is built when it is first opened."""

    def setUp(self):
        super().setUp()
        self.built = []
        build = ui.MainUI._build

        def counted(uimanager, layout, hide_disabled=False):
            if layout is ui._MENUBAR:
                self.built.append('menu bar')
            elif layout is ui._POPUP:
                self.built.append('right-click menu')
            return build(uimanager, layout, hide_disabled)
        patcher = unittest.mock.patch.object(ui.MainUI, '_build', counted)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.open_main_window()
        pump()

    def _keys(self, menu):
        return set(_accelerators(menu.get_menu_model()))

    def _open_the_right_click_menu(self):
        hold_open(self.window.popup)
        self.window.show_page_menu(self.window.page_area, 1, 1, None)
        self.assertTrue(wait_for(self.window.popup.get_visible))
        self.window.popup.popdown()
        pump()

    def test_a_new_window_builds_its_menu_bar_once_with_its_keys(self):
        self.assertEqual(['menu bar'], self.built)
        self.assertIn('<Control>o', self._keys(self.window.menubar))

    def test_the_right_click_menu_is_built_once_when_first_opened(self):
        self._open_the_right_click_menu()
        self._open_the_right_click_menu()
        self.assertEqual(['menu bar', 'right-click menu'], self.built)
        self.assertIn('<Control>o', self._keys(self.window.popup))

    def test_a_key_changed_shows_in_both_menus(self):
        self._open_the_right_click_menu()
        self.window.uimanager.set_accelerator('open', '<Control>F12')
        pump()
        self.assertIn('<Control>F12', self._keys(self.window.menubar))
        self._open_the_right_click_menu()
        self.assertIn('<Control>F12', self._keys(self.window.popup))
        self.assertEqual(['menu bar', 'right-click menu', 'menu bar',
                          'right-click menu'], self.built)


class RightClickMenuHeightTest(MComixTest):

    """The right-click menu on a page is as tall as its items, wherever
    on the page it opens, while the screen has room for all of it."""

    def setUp(self):
        super().setUp()
        self.open_main_window_on_a_book()
        self.popup = self.window.popup
        hold_open(self.popup)

    def _heights_opened_at(self, y):
        """The menu's height and the height its items want, opened on
        the first page <y> pixels down the page area."""
        self.window.show_page_menu(self.window.page_area, 20, y, 1)
        self.assertTrue(wait_for(lambda: self.popup.get_mapped()
                                 and self.popup.get_height() > 0))
        pump()
        natural = self.popup.measure(Gtk.Orientation.VERTICAL, -1)[1]
        screen = self.window.get_display().get_monitor_at_surface(
            self.window.get_surface()).get_geometry()
        if screen.height < natural + 100:
            self.skipTest('a screen %d pixels high has no room for a menu '
                          'of %d' % (screen.height, natural))
        return self.popup.get_height(), natural

    def test_the_first_opening_is_not_cut_short(self):
        """The menu is built when it first opens, and GTK adds the lines
        between its sections from an idle: opened in the same turn, it
        was measured without them, 618 pixels for 709, and scrolled."""
        height, natural = self._heights_opened_at(5)
        self.assertEqual(natural, height)

    def test_opened_low_on_the_page_it_moves_up_rather_than_scrolling(self):
        """Below the point, GTK flips a popover above it where it fits
        there, and otherwise cuts it to the room below: with the pointer
        low in a window 600 pixels high the menu came out 579 pixels for
        709, on a screen of 1024."""
        height, natural = self._heights_opened_at(
            self.window.page_area.get_height() - 5)
        self.assertEqual(natural, height)


class HelpMenuTest(MainWindowOpenTest):

    def tearDown(self):
        preferences_dialog._close_dialog()
        super().tearDown()

    def test_the_manual_is_handed_to_the_desktop_s_browser(self):
        with unittest.mock.patch.object(ui.Gtk, 'UriLauncher') as launcher:
            self.window.actiongroup.get_action('manual').activate()
        launcher.new.assert_called_once_with(constants.MANUAL_URL)
        launch = launcher.new.return_value.launch
        self.assertEqual(1, launch.call_count)
        self.assertIs(self.window, launch.call_args.args[0])

    def test_a_manual_that_cannot_be_opened_says_why(self):
        launcher = unittest.mock.Mock()
        launcher.launch_finish.side_effect = GLib.Error('no browser')
        with unittest.mock.patch.object(self.window.osd, 'show') as show:
            self.window.uimanager._manual_shown(launcher, None)
        show.assert_called_once_with(
            'Could not open the manual: no browser')

    def test_a_manual_the_reader_dismissed_says_nothing(self):
        """Where a portal asks which program to use, turning the question
        down is an answer, not a failure."""
        launcher = unittest.mock.Mock()
        launcher.launch_finish.side_effect = GLib.Error.new_literal(
            Gtk.dialog_error_quark(), 'dismissed',
            int(Gtk.DialogError.DISMISSED))
        with unittest.mock.patch.object(self.window.osd, 'show') as show:
            self.window.uimanager._manual_shown(launcher, None)
        show.assert_not_called()

    def test_keyboard_shortcuts_opens_the_preferences_on_their_tab(self):
        self.window.actiongroup.get_action('shortcuts').activate()
        pump()
        dialog = preferences_dialog._dialog
        self.assertIsNotNone(dialog)
        self.assertIs(dialog.shortcuts, dialog.notebook.get_nth_page(
            dialog.notebook.get_current_page()))

    def test_it_turns_an_open_dialog_to_that_tab_as_well(self):
        self.window.actiongroup.get_action('preferences').activate()
        pump()
        dialog = preferences_dialog._dialog
        dialog.notebook.set_current_page(0)
        self.window.actiongroup.get_action('shortcuts').activate()
        pump()
        self.assertIs(dialog, preferences_dialog._dialog)
        self.assertIs(dialog.shortcuts, dialog.notebook.get_nth_page(
            dialog.notebook.get_current_page()))


# vim: expandtab:sw=4:ts=4
