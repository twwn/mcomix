# -*- coding: utf-8 -*-

""" A window that actually starts, with its parts where they belong.

Most of the suite exercises pieces in isolation; nothing else builds the
real window, which is where a whole class of start-up regressions hides.
"""

import os
import warnings

from gi.repository import Gio, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.preferences import prefs


class MainWindowTest(MComixTest):

    def setUp(self):
        super(MainWindowTest, self).setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['show toolbar'] = True
        prefs['show menubar'] = True
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        self._pump()

    def tearDown(self):
        # Only terminate_program() stops the worker threads; without it the
        # interpreter will not exit.  It leaves the window itself behind,
        # and a GTK4 toplevel that is never destroyed goes on taking part
        # in the display's layout - the next test's window came out with
        # nothing allocated to it.
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        self._pump()
        super(MainWindowTest, self).tearDown()

    def _pump(self, rounds=2000):
        pump(rounds)

    @staticmethod
    def _children(widget):
        children = []
        child = widget.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def test_pitch_black_paints_the_page_area_black(self):
        # Whatever colour the preference holds, or the picture suggests.
        from mcomix import theme
        prefs['colour scheme'] = theme.BLACK
        self.window.set_bg_colour([0.5, 0.5, 0.5, 1.0])
        self.assertEqual(self.window.get_bg_colour(), [0.0, 0.0, 0.0, 1.0])

    def test_the_tool_bar_has_its_buttons(self):
        buttons = [item for item in self._children(self.window.toolbar)
                   if isinstance(item, Gtk.Button)]
        self.assertTrue(buttons, 'the tool bar is empty')
        self.assertTrue(all(button.get_visible() for button in buttons),
                        'a tool bar of hidden buttons collapses to nothing')

    def test_every_tool_bar_button_answers_to_an_action(self):
        for button in self._children(self.window.toolbar):
            if not isinstance(button, Gtk.Button):
                continue
            self.assertIsNotNone(button.get_action_name(),
                                 'a tool bar button does nothing')

    def test_the_tool_bar_takes_up_room(self):
        # It was packed, and its buttons were not shown, so it came out
        # seven pixels tall and looked like it had gone.
        self.window.toolbar.set_visible(True)
        wait_for(lambda: self.window.toolbar.get_height() > 20)
        self.assertGreater(self.window.toolbar.get_height(), 20)

    def test_the_menu_bar_has_its_menus(self):
        self.assertTrue(self._children(self.window.menubar),
                        'the menu bar is empty')

    def test_the_context_menu_is_not_open_to_begin_with(self):
        # A visible Gtk.PopoverMenu is an open one: it holds an input
        # grab, so keys and clicks go nowhere, and on Wayland it is an
        # xdg_popup that GTK asks the compositor for and then waits on -
        # which held up the window for tens of seconds.
        self.assertFalse(self.window.popup.get_visible(),
                         'the context menu is open before anyone asked')
        self.assertTrue(self.window.menubar.get_visible(),
                        'the menu bar should be shown')

    def test_a_window_border_goes_around_what_it_holds(self):
        # A margin on a toplevel falls outside the part of the surface
        # it paints, so it comes out as a transparent strip along the
        # edges rather than as a border.
        from gi.repository import Gtk
        from mcomix import widgets
        window = Gtk.Window()
        child = Gtk.Box()
        window.set_child(child)
        widgets.set_border(window, 6)
        self.assertEqual(window.get_margin_top(), 0)
        self.assertEqual(window.get_margin_end(), 0)
        self.assertEqual(child.get_margin_top(), 6)
        self.assertEqual(child.get_margin_end(), 6)
        window.destroy()

    def test_a_resized_canvas_says_so(self):
        # A window's default size is what it asked for rather than what
        # it was given, so watching that missed every resize the
        # compositor made and the pages kept their old scale.
        canvas = self.window._main_layout
        resized = []
        canvas.connect('resized', lambda *args: resized.append(1))
        canvas.allocate(max(1, canvas.get_width() - 120),
                        max(1, canvas.get_height() - 80), -1, None)
        wait_for(lambda: bool(resized), seconds=3)
        self.assertTrue(resized, 'a resized canvas said nothing')

    def test_being_told_of_a_resize_redraws_the_pages(self):
        drawn = []
        self.window.draw_image = lambda *a, **k: drawn.append(1)
        self.window._event_handler.resize_event(self.window._main_layout)
        self.assertTrue(drawn, 'a resize did not redraw the pages')

    def test_hiding_a_toggle_widget_goes_through_its_own_set_visible(self):
        """Gtk.Widget.show() and hide() reach the same C function that
        Gtk.Widget.set_visible() does, but without passing through a
        Python override of it. ThumbnailSidebar has such an override, and
        that is where the thumbnail thread is started and stopped, so a
        sidebar hidden with hide() went on updating."""
        sidebar = self.window.thumbnailsidebar
        # _should_toggle_be_visible() holds the sidebar back until the
        # archive has pages, and that happens on a worker thread. Without
        # waiting for it the sidebar never appears, and then hiding it is
        # not a change of visibility at all - which passes for the wrong
        # reason before the fix and fails for the wrong reason after it.
        self.assertTrue(
            wait_for(lambda: self.window.filehandler.file_loaded
                     and self.window.imagehandler.get_number_of_pages() > 0),
            'the test archive never finished loading')
        prefs['show thumbnails'] = True
        self.window._update_toggles_visibility()
        self._pump()
        self.assertTrue(sidebar.get_visible(), 'the sidebar never appeared')

        seen = []
        original = type(sidebar).set_visible
        type(sidebar).set_visible = lambda widget, visible: (
            seen.append(visible), original(widget, visible))[1]
        try:
            prefs['show thumbnails'] = False
            self.window._update_toggles_visibility()
            self._pump()
        finally:
            type(sidebar).set_visible = original
        self.assertEqual([False], seen,
                         'the sidebar was hidden behind its own back')
        self.assertFalse(sidebar.get_visible())

    def test_minimizing_the_window_does_not_raise(self):
        """The View menu and a keybinding both reach MainWindow.minimize().

        It called self.iconify(), which is what GTK3 named this; GTK4
        renamed it to minimize() and MainWindow.minimize() shadows that,
        so the working call was hidden behind a broken one.
        """
        self.assertFalse(hasattr(Gtk.Window, 'iconify'),
                         'GTK grew iconify() back; this test is stale')
        # A Gio action hands its callback the action and the parameter.
        self.window.minimize(None, None)
        self._pump()

    def test_quitting_keeps_the_hide_all_preference(self):
        """Nothing unsets 'hide all' on the way out.

        terminate_program() used to clear it when a hide_all_forced flag
        was set, which is how entering fullscreen once forced the
        preference on. Nothing forces it since the toggle rework, so the
        preference is the user's alone and has to survive a quit.
        """
        prefs['hide all'] = True
        self.window.terminate_program()
        self.assertTrue(prefs['hide all'],
                        "quitting turned the user's 'hide all' off")

    def test_the_window_does_not_shadow_the_widget_size_accessor(self):
        """get_size() on the window is Gtk.Widget's, not MComix' own.

        Gtk.Widget.get_size() takes an orientation and answers with the
        allocation along it. MComix' accessor takes nothing and answers
        with a pair, so while it was called get_size() as well the GTK
        one was unreachable on the window.
        """
        self.assertEqual(self.window.get_size(Gtk.Orientation.HORIZONTAL),
                         self.window.get_width())
        self.assertEqual(self.window.get_size(Gtk.Orientation.VERTICAL),
                         self.window.get_height())
        self.assertEqual(self.window.get_window_size(),
                         (self.window.get_width(), self.window.get_height()))

    def test_saving_a_page_opens_a_chooser(self):
        """extract_page() built its dialog the GTK3 way.

        Gtk.FileChooserDialog took a title, a parent and buttons as
        positional arguments; GTK4 takes properties, so the call raised
        a TypeError and "Save page as" opened nothing at all.  It is a
        Gtk.FileDialog now, which is not a widget at all - so what the
        chooser it puts up is asking for is where the name and the
        folder can be read back.

        What the user picks is left out: the answer comes back through
        a callback that only the real chooser can fire.
        """
        target_dir = os.path.join(constants.DATA_DIR, 'saved')
        os.makedirs(target_dir, exist_ok=True)
        prefs['path of last saved in filechooser'] = target_dir

        # There is nothing to save until the page has been extracted.
        handler = self.window.imagehandler
        self.assertTrue(
            wait_for(lambda: handler.get_path_to_page(
                handler.get_current_page()) is not None),
            'the first page never arrived')

        self.window.extract_page()
        self._pump()
        dialogs = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, Gtk.FileChooserDialog)]
        self.assertEqual(1, len(dialogs), 'no save dialog was opened')
        dialog = dialogs[0]
        try:
            with warnings.catch_warnings():
                # The chooser Gtk.FileDialog puts up is one GTK builds
                # for itself; reading it back is the deprecated call.
                warnings.simplefilter('ignore', DeprecationWarning)
                self.assertEqual(dialog.get_current_name(),
                                 '01-ZIP-Normal_01-JPG-Indexed.jpg')
                folder = dialog.get_current_folder()
            self.assertEqual(folder.get_path(), target_dir)
        finally:
            dialog.destroy()
            self._pump()

    def test_where_a_saved_page_went_is_remembered(self):
        """The folder for the next save is the one the page went into.

        It used to be read off the chooser widget, which a
        Gtk.FileDialog has none of, and which answered None whenever the
        pick was not a local folder - putting None in the preference.
        """
        target_dir = os.path.join(constants.DATA_DIR, 'saved')
        os.makedirs(target_dir, exist_ok=True)
        elsewhere = os.path.join(constants.DATA_DIR, 'saved-elsewhere')
        os.makedirs(elsewhere, exist_ok=True)
        prefs['path of last saved in filechooser'] = target_dir
        prefs['store last saved in directory'] = True

        handler = self.window.imagehandler
        self.assertTrue(
            wait_for(lambda: os.path.exists(
                handler.get_path_to_page(handler.get_current_page()) or '')),
            'the first page was never extracted')
        source = handler.get_path_to_page(handler.get_current_page())

        # What Gtk.FileDialog would have called back with, had the user
        # walked out of the folder it opened in and saved there.
        target = os.path.join(elsewhere, 'page.jpg')
        self.window._save_page_to(source, target)

        self.assertTrue(os.path.exists(target), 'the page was not written')
        self.assertEqual(prefs['path of last saved in filechooser'],
                         elsewhere)

    def test_the_right_click_menu_offers_to_save_a_page(self):
        """It offered every other thing the File menu does, but not the
        one that needs a page picked out - which is the one only it can
        do, since it is opened on the page it means."""
        self.assertIn('win.extract-page-popup',
                      self._menu_actions(self.window.uimanager.popup
                                         .get_menu_model()))

    def test_the_right_click_menu_saves_the_page_it_was_opened_over(self):
        """Save As on the menu bar offers both pages of a double page,
        one chooser after the other, because nothing says which of them
        is meant.  The right-click menu was opened on one of them."""
        target_dir = os.path.join(constants.DATA_DIR, 'saved')
        os.makedirs(target_dir, exist_ok=True)
        prefs['path of last saved in filechooser'] = target_dir

        handler = self.window.imagehandler
        self.assertTrue(
            wait_for(lambda: handler.get_path_to_page(2) is not None),
            'the second page never arrived')

        self.window.popup_page = 2
        self.window.extract_popup_page()
        self._pump()
        dialogs = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, Gtk.FileChooserDialog)]
        self.assertEqual(1, len(dialogs), 'no save dialog was opened')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                self.assertEqual(dialogs[0].get_current_name(),
                                 '01-ZIP-Normal_02-JPG-RGB.jpg')
        finally:
            dialogs[0].destroy()
            self._pump()

    def test_which_page_a_click_landed_on_is_answered_by_where_it_was(self):
        """Two pages stand side by side in double page mode, and only
        where the click was says which of them the menu is about."""
        prefs['default double page'] = True
        try:
            # The archive is listed on a worker thread, and set_page()
            # clamps to the pages counted so far.
            self.assertTrue(
                wait_for(lambda:
                         self.window.imagehandler.get_number_of_pages() > 1),
                'the archive was never listed')
            # The first page of an archive stands alone, as its cover.
            self.window.set_page(2)
            self.assertTrue(
                wait_for(lambda: len(self.window.layout.get_content_boxes())
                         == 2),
                'the second page was never laid out')
            boxes = self.window.layout.get_content_boxes()
            # The pages are placed on the layout as a whole; a click
            # gives its coordinates on the part of it that shows.
            scrolled_x = self.window._hadjust.get_value()
            scrolled_y = self.window._vadjust.get_value()
            for offset, content in enumerate(boxes):
                left, top = content.get_position()
                width, height = content.get_size()
                self.assertEqual(
                    self.window.page_at(left + width / 2 - scrolled_x,
                                        top + height / 2 - scrolled_y),
                    2 + offset)
            # The background around the pages is no page at all.
            widest = max(box.get_position()[0] + box.get_size()[0]
                         for box in boxes)
            self.assertIsNone(self.window.page_at(widest + 100 - scrolled_x,
                                                  -scrolled_y))
        finally:
            prefs['default double page'] = False

    @staticmethod
    def _menu_actions(model):
        """Every action the menu <model> and its submenus address."""
        actions = []
        for index in range(model.get_n_items()):
            action = model.get_item_attribute_value(
                index, Gio.MENU_ATTRIBUTE_ACTION, None)
            if action is not None:
                actions.append(action.get_string())
            for link in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
                child = model.get_item_link(index, link)
                if child is not None:
                    actions.extend(
                        MainWindowTest._menu_actions(child))
        return actions

    def test_the_popup_menu_opens_its_submenus_as_menus_of_their_own(self):
        """A sliding Gtk.PopoverMenu keeps every submenu page in one
        stack and is as wide as the widest item on any of them, so the
        eight short entries of the top level were laid out to fit
        "Previous archive" and its accelerator, three pages down: 292
        pixels where its own entries want 162.
        """
        self.assertEqual(self.window.uimanager.popup.props.flags,
                         Gtk.PopoverMenuFlags.NESTED)

    def test_the_window_holds_the_expected_parts(self):
        for part in (self.window.menubar, self.window.toolbar,
                     self.window.statusbar, self.window.thumbnailsidebar):
            self.assertIsNotNone(part.get_parent(),
                                 '%r was never packed' % part)

# vim: expandtab:sw=4:ts=4
