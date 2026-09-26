""" A window that actually starts, with its parts where they belong.

Most of the suite exercises pieces in isolation; nothing else builds the
real window, which is where a whole class of start-up regressions hides.
"""

import contextlib
import datetime
import errno
import os
import pickle
import shutil
import threading
import zipfile
import time
import unittest.mock
import warnings

from gi.repository import Gdk, Gio, Gtk

from . import MComixTest, get_testfile_path, hold_open, pump, wait_for

from mcomix import archive_packer
from mcomix import bookmark_backend
from mcomix import constants
from mcomix import dialog as dialog_module
from mcomix import edit_dialog
from mcomix import file_chooser_simple_dialog as simple_chooser
from mcomix import icons
from mcomix import image_tools
from mcomix import keybindings
from mcomix import file_actions
from mcomix import file_mover
from mcomix import main
from mcomix import message_dialog
from mcomix import rename_dialog
from mcomix import tools
from mcomix.dialog import Response
from mcomix.library import backend
from mcomix.preferences import prefs


def _descriptors_on(path):
    """The descriptors this process holds open on the file at <path>.

    Windows moves and replaces no file that is open; Linux does both,
    so this is how a test here sees what would fail there.
    """
    wanted = os.stat(path)
    held = []
    for fd in os.listdir('/proc/self/fd'):
        try:
            found = os.stat(os.path.join('/proc/self/fd', fd))
        except OSError:
            continue
        if (found.st_dev, found.st_ino) == (wanted.st_dev, wanted.st_ino):
            held.append(fd)
    return held


class MainWindowTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['show toolbar'] = True
        prefs['show menubar'] = True
        icons.load_icons()
        # The keybinding manager is one for the process and tells the
        # menus of the window it was built with; without this, that is
        # the window of whichever test built one first on this worker.
        keybindings._manager = None
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
        super().tearDown()

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

    def test_the_bookmark_key_is_the_keybinding_managers(self):
        """CTRL+D was a Gtk.Shortcut of the bookmarks menu's own, which the
        Shortcuts tab did not list and could not change.  It is now an
        action of the keybinding manager, and the menu shows its key."""
        wait_for(lambda: self.window.filehandler.file_loaded, seconds=10)
        # The store is one for the process and keeps the first window it
        # was given, which on a shared worker is another test's.
        store = bookmark_backend.BookmarksStore
        store._initialized = False
        store._bookmarks = []
        store.initialize(self.window)
        manager = keybindings.keybinding_manager(self.window)
        manager.execute(keybindings.parse_accelerator('<Control>d'))
        self.assertEqual(1, len(store.get_bookmarks()))
        self._pump()
        fixed = self.window.uimanager.bookmarks.model.get_item_link(
            0, 'section')
        accelerator = fixed.get_item_attribute_value(0, 'accel')
        self.assertIsNotNone(accelerator, 'the menu shows no key')
        self.assertEqual(keybindings.parse_accelerator('<Control>d'),
                         keybindings.parse_accelerator(
                             accelerator.get_string()))

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

    def test_the_slideshow_button_keeps_its_icon_while_it_changes_it(self):
        """Starting and stopping a slideshow put an icon of the default
        size, full colour rather than symbolic, in place of the tool
        bar's own: Gtk.Button.set_icon_name() replaces the button's child
        with an image of its own."""
        button = self.window.uimanager.slideshow_button
        icon = button.get_child()
        action = self.window.actiongroup.get_action('slideshow')
        for running, name in ((True, 'media-playback-stop-symbolic'),
                              (False, 'media-playback-start-symbolic')):
            action.set_active(running)
            self.assertIs(button.get_child(), icon)
            self.assertEqual(icon.get_icon_name(), name)
            self.assertEqual(icon.get_icon_size(), Gtk.IconSize.LARGE)

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
        canvas = self.window.page_area
        resized = []
        canvas.connect('resized', lambda *args: resized.append(1))
        canvas.allocate(max(1, canvas.get_width() - 120),
                        max(1, canvas.get_height() - 80), -1, None)
        wait_for(lambda: bool(resized), seconds=3)
        self.assertTrue(resized, 'a resized canvas said nothing')

    def test_being_told_of_a_resize_redraws_the_pages(self):
        drawn = []
        self.window.draw_image = lambda *a, **k: drawn.append(1)
        self.window.event_handler.resize_event(self.window.page_area)
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
        """It is MComix' own chooser, so it follows MComix' theme.

        A Gtk.FileDialog asks the desktop for a chooser, which is drawn
        by the file chooser portal where one is installed - another
        program, which nothing MComix states about its colours reaches.

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

        self.window.file_actions.extract_page()
        self._pump()
        dialogs = self._save_dialogs()
        self.assertEqual(1, len(dialogs), 'no save dialog was opened')
        dialog = dialogs[0]
        try:
            self.assertIsInstance(dialog, dialog_module.Dialog,
                                  'the chooser is not one MComix paints')
            with warnings.catch_warnings():
                # Gtk.FileChooserWidget is what MComix' own chooser is
                # built around, and reading it back is deprecated with
                # the rest of the interface.
                warnings.simplefilter('ignore', DeprecationWarning)
                self.assertEqual(dialog.filechooser.get_current_name(),
                                 '01-ZIP-Normal_01-JPG-Indexed.jpg')
                folder = dialog.filechooser.get_current_folder()
            self.assertEqual(folder.get_path(), target_dir)
        finally:
            dialog.destroy()
            self._pump()

    def _message_dialogs(self):
        """Every message dialog this window has standing open."""
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_transient_for() is self.window]

    def test_deleting_a_file_asks_before_it_does_and_defaults_to_cancel(self):
        """The dialog deletes a file from the disk, so Enter must answer
        it with the button that does nothing."""
        copied = os.path.join(self.tmp_dir, 'delete-me.zip')
        shutil.copyfile(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                        copied)
        self.window.filehandler.open_file(copied)
        self._pump()
        self.window.file_actions.delete()
        self._pump()
        dialogs = self._message_dialogs()
        self.assertEqual(1, len(dialogs), 'nothing asked before deleting')
        dialog = dialogs[0]
        try:
            cancel = dialog.get_widget_for_response(dialog_module.Response.CANCEL)
            deletes = dialog.get_widget_for_response(dialog_module.Response.OK)
            self.assertIsNotNone(cancel, 'the dialog offers no way out')
            self.assertIs(dialog.get_default_widget(), cancel,
                          'Enter would delete the file')
            self.assertTrue(deletes.has_css_class('destructive-action'),
                            'the deleting button is drawn as an ordinary one')
        finally:
            # Never answered: answering it would delete the copy, and a
            # dialog left standing is answered by the next test that
            # goes looking for one.
            dialog.destroy()
            self._pump()
        self.assertTrue(os.path.isfile(copied), 'the file was deleted anyway')

    def test_the_action_says_what_the_colours_do(self):
        """The enhance dialog sets the enhancer directly, so the action
        and the enhancer can fall out of step; changing the action then
        has to bring them together rather than invert whatever the
        enhancer happened to hold."""
        action = self.window.actiongroup.get_action('invert_color')
        self.assertFalse(action.get_active())
        # What ticking "Invert colours" in the enhance dialog does.
        self.window.enhancer.invert_color = True
        action.set_active(True)
        self._pump()
        self.assertTrue(self.window.enhancer.invert_color,
                        'the action says inverted and the pages are not')
        self.assertTrue(prefs['invert color'])
        action.set_active(False)
        self._pump()
        self.assertFalse(self.window.enhancer.invert_color)
        self.assertFalse(prefs['invert color'])

    def test_asking_for_fullscreen_leaves_the_menu_item_usable(self):
        """change_fullscreen() used to make the item insensitive and rely
        on notify::fullscreened to put it back.  Nothing else re-enables
        it - 'fullscreen' is not one of the toggle actions
        update_toggles_sensitivity() walks - so wherever the request is
        not granted, the item stayed greyed out for the rest of the
        session.  Under a bare X server with no window manager, which is
        what this suite runs on, the property never changes and the
        notification never arrives at all."""
        action = self.window.actiongroup.get_action('fullscreen')
        self.assertTrue(action.get_sensitive(),
                        'the item was not usable to begin with')

        action.set_active(True)
        self._pump()

        self.assertTrue(action.get_sensitive(),
                        'asking for fullscreen greyed the item out for good')

    def test_the_size_to_go_back_to_is_never_a_fullscreen_one(self):
        """The saved size is what the window is given at the next start
        and what leaving fullscreen restores, so recording the screen it
        was filling would make fullscreen permanent.  close_program()
        knew that and asked; save_window_geometry() now knows it itself,
        for every caller."""
        # A size no window can really be, so that the assertion cannot
        # pass by happening to match the window this test was given.
        prefs['window width'] = -1
        prefs['window height'] = -1
        with unittest.mock.patch.object(type(self.window), 'is_fullscreen',
                                        return_value=True):
            self.window.save_window_geometry()

        self.assertEqual((-1, -1),
                         (prefs['window width'], prefs['window height']))

    def test_the_size_is_saved_when_the_window_is_not_fullscreen(self):
        prefs['window width'] = -1
        prefs['window height'] = -1
        self.window.save_window_geometry()

        self.assertEqual(self.window.get_window_size(),
                         (prefs['window width'], prefs['window height']))

    # -- Filling the screen and hiding everything --------------------------

    _TOGGLES = ('menubar', 'scrollbar', 'statusbar', 'thumbnails', 'toolbar')

    def _toggles_usable(self):
        return {name: self.window.actiongroup.get_action(name).get_sensitive()
                for name in self._TOGGLES}

    def _state_changes_to(self, fullscreen):
        """Tell the window it has filled the screen, or stopped, as the
        notification from the window manager does; the bare X server
        the suite runs on has none to grant the request."""
        with unittest.mock.patch.object(type(self.window), 'is_fullscreen',
                                        return_value=fullscreen):
            self.window.event_handler.window_state_event(self.window, None)

    def test_hide_all_leaves_the_bars_it_hides_unusable(self):
        """Hidden by "hide all", a bar's own item could not show it, so
        each is greyed out until "hide all" is turned off again."""
        hide_all = self.window.actiongroup.get_action('hide_all')
        hide_all.set_active(True)
        self._pump()
        self.assertEqual({name: False for name in self._TOGGLES},
                         self._toggles_usable())
        hide_all.set_active(False)
        self._pump()
        self.assertEqual({name: True for name in self._TOGGLES},
                         self._toggles_usable())

    def test_filling_the_screen_hides_all_where_that_is_asked_for(self):
        prefs['hide all in fullscreen'] = True
        with unittest.mock.patch.object(self.window, 'draw_image') as drawn:
            self._state_changes_to(True)
        self.assertTrue(self.window.was_fullscreen)
        self.assertEqual({name: False for name in self._TOGGLES},
                         self._toggles_usable())
        drawn.assert_called_once_with()
        with unittest.mock.patch.object(
                self.window, 'restore_window_geometry',
                return_value=False), \
                unittest.mock.patch.object(self.window,
                                           'draw_image') as drawn:
            self._state_changes_to(False)
        self.assertFalse(self.window.was_fullscreen)
        self.assertEqual({name: True for name in self._TOGGLES},
                         self._toggles_usable())
        # The size it went back to is the size it had, so there is no
        # resize to redraw it.
        drawn.assert_called_once_with()

    def _bars_shown(self, fullscreen):
        """Which of the menu bar, the status bar and the tool bar the
        window shows, in fullscreen or out of it."""
        with unittest.mock.patch.object(type(self.window), 'is_fullscreen',
                                        return_value=fullscreen):
            self.window._update_toggles_visibility()
        return {'menubar': self.window.menubar.get_visible(),
                'statusbar': self.window.statusbar.get_visible(),
                'toolbar': self.window.toolbar.get_visible()}

    def test_in_fullscreen_the_bars_follow_hide_all_in_fullscreen(self):
        """"Hide all" is the answer outside fullscreen only; inside
        it, "hide all in fullscreen" is."""
        for preference in ('show menubar', 'show statusbar', 'show toolbar'):
            prefs[preference] = True
        shown = {'menubar': True, 'statusbar': True, 'toolbar': True}
        hidden = {'menubar': False, 'statusbar': False, 'toolbar': False}
        prefs['hide all'] = True
        prefs['hide all in fullscreen'] = False
        self.assertEqual(hidden, self._bars_shown(False))
        self.assertEqual(shown, self._bars_shown(True))
        prefs['hide all'] = False
        prefs['hide all in fullscreen'] = True
        self.assertEqual(shown, self._bars_shown(False))
        self.assertEqual(hidden, self._bars_shown(True))

    def test_going_back_to_a_new_size_leaves_the_redraw_to_the_resize(self):
        self._state_changes_to(True)
        with unittest.mock.patch.object(
                self.window, 'restore_window_geometry',
                return_value=True), \
                unittest.mock.patch.object(self.window,
                                           'draw_image') as drawn:
            self._state_changes_to(False)
        drawn.assert_not_called()

    def test_a_notification_that_changes_nothing_is_let_pass(self):
        """Both notify::fullscreened and notify::maximized arrive, and
        the second finds the change already dealt with."""
        self._state_changes_to(True)
        with unittest.mock.patch.object(self.window, 'draw_image') as drawn:
            self._state_changes_to(True)
        drawn.assert_not_called()
        self._state_changes_to(False)

    def test_save_and_quit_keeps_the_window_size(self):
        """It is the entry that promises to put the reader back where
        they were, and it went straight to terminate_program(), which
        writes the configuration files without asking the window how
        large it is.  Plain Quit and the window's own close button both
        go through close_program(), which does ask."""
        prefs['window width'] = -1
        prefs['window height'] = -1
        with unittest.mock.patch.object(type(self.window),
                                        'terminate_program'):
            self.window.save_and_terminate_program()

        self.assertEqual(self.window.get_window_size(),
                         (prefs['window width'], prefs['window height']))
        self.assertTrue(prefs['previous quit was quit and save'],
                        'the preference the next start reads was not set')

    def test_showing_a_toggle_as_on_does_not_run_it(self):
        """What the start-up sync needs: the state moves, the colours
        are left alone because they are already what it says."""
        action = self.window.actiongroup.get_action('invert_color')
        action.show_active(True)
        self._pump()
        self.assertTrue(action.get_active())
        self.assertFalse(self.window.enhancer.invert_color,
                         'showing the state inverted the pages as well')

    def _save_dialogs(self):
        """Every save chooser this window has standing open.

        Whose it is matters: the suite is sharded, and a chooser
        another test left on screen is a toplevel like any other.
        """
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, simple_chooser.SimpleFileChooserDialog)
                and window.get_transient_for() is self.window]

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
        self.window.file_actions._save_page_to(source, target)

        self.assertTrue(os.path.exists(target), 'the page was not written')
        self.assertEqual(prefs['path of last saved in filechooser'],
                         elsewhere)

    def _save_first_page(self, target_dir):
        """Ask to save the first page into <target_dir>, and answer with
        the one chooser that opened."""
        prefs['path of last saved in filechooser'] = target_dir
        handler = self.window.imagehandler
        self.assertTrue(
            wait_for(lambda: os.path.exists(
                handler.get_path_to_page(1) or '')),
            'the first page was never extracted')
        self.window.file_actions.extract_page()
        self._pump()
        dialogs = self._save_dialogs()
        self.assertEqual(1, len(dialogs), 'no save dialog was opened')
        self.addCleanup(dialogs[0].destroy)
        return dialogs[0]

    def test_a_name_taken_in_the_folder_is_offered_with_a_number(self):
        target_dir = os.path.join(constants.DATA_DIR, 'saved')
        os.makedirs(target_dir, exist_ok=True)
        for name in ('01-ZIP-Normal_01-JPG-Indexed.jpg',
                     '01-ZIP-Normal_01-JPG-Indexed (1).jpg'):
            with open(os.path.join(target_dir, name), 'wb'):
                pass
        dialog = self._save_first_page(target_dir)
        self.assertEqual('01-ZIP-Normal_01-JPG-Indexed (2).jpg',
                         dialog.save_name)

    def test_the_page_is_written_where_the_chooser_answers(self):
        target_dir = os.path.join(constants.DATA_DIR, 'saved')
        os.makedirs(target_dir, exist_ok=True)
        dialog = self._save_first_page(target_dir)
        target = os.path.join(target_dir, 'kept.jpg')
        dialog.files_chosen([target])
        self._pump()
        self.assertEqual(
            os.path.getsize(self.window.imagehandler.get_path_to_page(1)),
            os.path.getsize(target))
        self.assertEqual([], self._save_dialogs(),
                         'the chooser was left standing')

    def test_a_save_that_was_cancelled_writes_nothing(self):
        target_dir = os.path.join(constants.DATA_DIR, 'saved')
        os.makedirs(target_dir, exist_ok=True)
        dialog = self._save_first_page(target_dir)
        with unittest.mock.patch.object(
                self.window.file_actions, '_save_page_to') as saved:
            dialog.files_chosen([])
        self._pump()
        saved.assert_not_called()
        self.assertEqual([], os.listdir(target_dir))
        self.assertEqual([], self._save_dialogs(),
                         'the chooser was left standing')

    def test_the_right_click_menu_offers_to_save_a_page(self):
        """It offered every other thing the File menu does, but not the
        one that needs a page picked out - which is the one only it can
        do, since it is opened on the page it means."""
        self.assertIn('win.extract-page-popup',
                      self._menu_actions(self.window.uimanager.popup
                                         .get_menu_model()))

    # -- Picking a page out, and deleting it ------------------------------

    def _pages(self):
        return list(self.window.imagehandler._image_files or [])

    def _quietly(self):
        """Delete a page without the prompt that offers to save."""
        return unittest.mock.patch.object(self.window.file_actions,
                                          'offer_to_save')

    def _ready(self):
        """Wait until the book has been listed, and say what it holds."""
        self.assertTrue(
            wait_for(lambda: self.window.imagehandler
                     .get_number_of_pages() > 2, seconds=20),
            'the fixture archive never listed its pages')
        return self._pages()

    def _selected_images(self):
        """The page widgets drawn with the picked-out outline."""
        return [index for index, image in enumerate(self.window.images)
                if image.has_css_class(self.window._SELECTED_CLASS)]

    def test_no_page_is_picked_out_to_begin_with(self):
        self.assertEqual(self.window.selected_pages, set())
        self.assertEqual(self._selected_images(), [])

    def test_picking_a_page_out_outlines_the_widget_showing_it(self):
        self._ready()
        self.window.select_page(1)
        self.assertEqual(self.window.selected_pages, {1})
        self.assertEqual(self._selected_images(), [0])

    def test_picking_out_the_page_already_picked_out_puts_it_back(self):
        """The way out of a selection made by mistake."""
        self._ready()
        self.window.select_page(1)
        self.window.select_page(1)
        self.assertEqual(self.window.selected_pages, set())
        self.assertEqual(self._selected_images(), [])

    def test_a_page_that_is_not_there_is_not_picked_out(self):
        self.window.select_page(999)
        self.assertEqual(self.window.selected_pages, set())

    def test_more_than_one_page_can_be_picked_out(self):
        """The point of picking pages out while reading is to gather
        them up and deal with them together at the end."""
        self._ready()
        self.window.select_page(1)
        self.window.select_page(3)
        self.assertEqual(self.window.selected_pages, {1, 3})

    def test_the_menu_puts_back_every_page_picked_out(self):
        """Only a second CTRL and click on each page put it back, one
        page at a time."""
        self._ready()
        self.window.select_page(1)
        self.window.select_page(3)
        action = self.window.actiongroup.get_action('unpick_pages')
        self.assertTrue(action.get_sensitive())
        action.activate()
        self.assertEqual(self.window.selected_pages, set())
        self.assertEqual(self._selected_images(), [])

    def test_escape_puts_back_the_pages_picked_out_first(self):
        """Escape lets go of a selection before it leaves fullscreen,
        or quits where the preferences say so."""
        self._ready()
        self.window.select_page(1)
        with unittest.mock.patch.dict(prefs, {'escape quits': True}), \
                unittest.mock.patch.object(self.window,
                                           'close_program') as closed:
            self.window.event_handler.escape_event()
            self.assertEqual(self.window.selected_pages, set())
            closed.assert_not_called()
            self.window.event_handler.escape_event()
            closed.assert_called_once_with()

    def test_otherwise_escape_leaves_fullscreen(self):
        fullscreen = self.window.actiongroup.get_action('fullscreen')
        with unittest.mock.patch.dict(prefs, {'escape quits': False}), \
                unittest.mock.patch.object(fullscreen,
                                           'set_active') as set_active:
            self.window.event_handler.escape_event()
        set_active.assert_called_once_with(False)

    def test_a_number_key_runs_that_command_of_open_with(self):
        """Counted over the commands alone: a separator is no command a
        key could run."""
        from mcomix import openwith
        prefs['openwith commands'] = [
            ('First', 'first', '', False), ('-', '', '', False),
            ('Second', 'second', '', False)]
        with unittest.mock.patch.object(openwith.OpenWithCommand,
                                        'execute', autospec=True) as run:
            self.window.event_handler._execute_command(1)
            self.assertEqual(['Second'],
                             [call.args[0].get_label()
                              for call in run.call_args_list])
            self.window.event_handler._execute_command(2)
            self.assertEqual(1, run.call_count)

    def test_the_scroll_left_key_scrolls_left_by_the_key_step(self):
        prefs['number of pixels to scroll per key event'] = 17
        with unittest.mock.patch.object(self.window.event_handler,
                                        'scroll_with_flipping') as scrolled:
            self.window.event_handler._scroll_left()
        scrolled.assert_called_once_with(-17, 0)

    def test_turning_the_page_keeps_the_pages_picked_out(self):
        """Pages are picked out as they go by and dealt with at the end
        of the book, so a page turn cannot be what forgets them."""
        self._ready()
        self.window.select_page(1)
        self.window.set_page(2)
        self._pump()
        self.assertEqual(self.window.selected_pages, {1})
        self.assertEqual(self._selected_images(), [],
                         'a page not on screen was outlined')
        self.window.set_page(1)
        self._pump()
        self.assertEqual(self._selected_images(), [0],
                         'the page came back without its outline')

    def test_closing_the_book_puts_every_picked_out_page_back(self):
        self._ready()
        self.window.select_page(1)
        self.window.filehandler.close_file()
        self._pump()
        self.assertEqual(self.window.selected_pages, set())

    class _Click:

        """What a Gtk.GestureClick tells a handler about a click.

        The two handlers ask a gesture for the button and the modifiers
        and nothing else, and a Gdk.Event cannot be built from Python to
        give a real one.
        """

        def __init__(self, button, state=0):
            self._button = button
            self._state = state

        def get_current_button(self):
            return self._button

        def get_current_event_state(self):
            return self._state

        def get_widget(self):
            return None

    class _Scroll:

        """What a Gtk.EventControllerScroll tells a handler about a scroll.

        The handler asks the controller for the modifiers and nothing
        else; the deltas arrive as arguments.
        """

        def __init__(self, state=0):
            self._state = state

        def get_current_event_state(self):
            return self._state

    #: A motion controller tells a handler the same as a scroll one.
    _Motion = _Scroll

    def _click(self, state=0):
        """Click the middle of the first page, and say where that was."""
        boxes = self.window.layout.get_content_boxes()
        self.assertTrue(boxes, 'no page was laid out to click on')
        (left, top), (wide, high) = boxes[0].get_position(), boxes[0].get_size()
        x, y = left + wide / 2, top + high / 2
        # A click into a window that had lost the focus raises it rather
        # than reaching the page, and every test window shares one
        # display: whichever of them the display last gave the focus to,
        # this one is being clicked on purpose.
        self.window.was_out_of_focus = False
        handler = self.window.event_handler
        handler.mouse_press_event(self._Click(1), 1, x, y)
        handler.mouse_release_event(self._Click(1, state), 1, x, y)
        self._pump()
        return x, y

    def _refocus(self):
        """Take the focus from the window and give it back, as a click
        into it from another window does before the click itself."""
        self.window.lost_focus()
        self.window.gained_focus()

    def _wheel(self, delta_x, delta_y, state=0):
        self.window.event_handler.scroll_wheel_event(
            self._Scroll(state), delta_x, delta_y)
        self._pump()

    def _press(self, button):
        """Press <button> over the top left corner of the page area."""
        self.window.was_out_of_focus = False
        self.window.event_handler.mouse_press_event(
            self._Click(button), 1, 0, 0)

    def test_the_back_thumb_button_turns_back_a_page(self):
        """Button 8 is the one a mouse marks "back", and the page before
        this one is the only back a book has."""
        self._ready()
        self.window.set_page(3)
        self._pump()
        self._press(8)
        self._pump()
        self.assertEqual(2, self.window.imagehandler.get_current_page())

    def test_the_forward_thumb_button_shows_the_osd_panel(self):
        """Button 9 carries what the keybindings page documented on
        button 4 for years, which GDK never reported as a press."""
        self._ready()
        self.window.osd.clear()
        self._press(9)
        self.assertIsNotNone(self.window.osd._last_osd_rect,
                             'the OSD panel was not put on the page')
        self.window.osd.clear()

    def test_a_sideways_wheel_turn_obeys_the_flip_with_wheel_preference(self):
        """Every other wheel direction stops turning pages when the
        preference is off, and sideways has to as well."""
        self._ready()
        prefs['flip with wheel'] = False
        self._wheel(1, 0)
        self.assertEqual(self.window.imagehandler.get_current_page(), 1)
        self._wheel(-1, 0)
        self.assertEqual(self.window.imagehandler.get_current_page(), 1)

    #: What scroll_wheel_event() can dispatch to, and so what the tests
    #: below watch for.  Asserted by name rather than by what the page
    #: does, because whether a page can be scrolled at all depends on the
    #: room the window was allocated, which varies between runs.
    _WHEEL_TARGETS = ('scroll_with_flipping', '_smart_scroll_up',
                      '_smart_scroll_down', '_next_page_with_protection',
                      '_previous_page_with_protection')

    def _wheel_dispatch(self, delta_x, delta_y, state=0):
        """Return what one wheel turn reached, as (name, args) pairs."""
        handler = self.window.event_handler
        reached = []
        with contextlib.ExitStack() as patches:
            for name in self._WHEEL_TARGETS:
                patches.enter_context(unittest.mock.patch.object(
                    handler, name,
                    side_effect=lambda *args, _name=name: reached.append(
                        (_name, args)) or False))
            for name in ('manual_zoom_in', 'manual_zoom_out'):
                patches.enter_context(unittest.mock.patch.object(
                    self.window, name,
                    side_effect=lambda _name=name: reached.append((_name, ()))))
            handler.scroll_wheel_event(self._Scroll(state), delta_x, delta_y)
        return reached

    def test_the_wheel_scrolls_the_page_and_turns_it_at_the_end(self):
        prefs['smart scroll'] = False
        pixels = prefs['number of pixels to scroll per mouse wheel event']
        self.assertEqual([('scroll_with_flipping', (0, pixels))],
                         self._wheel_dispatch(0, 1))
        self.assertEqual([('scroll_with_flipping', (0, -pixels))],
                         self._wheel_dispatch(0, -1))

    def test_the_wheel_scrolls_smartly_when_the_preference_says_so(self):
        prefs['smart scroll'] = True
        pixels = prefs['number of pixels to scroll per mouse wheel event']
        self.assertEqual([('_smart_scroll_down', (pixels,))],
                         self._wheel_dispatch(0, 1))
        self.assertEqual([('_smart_scroll_up', (pixels,))],
                         self._wheel_dispatch(0, -1))

    def test_a_smart_scroll_step_is_capped_by_the_wheel_or_the_percentage(self):
        """The wheel gives its pixels as the cap; the space bar gives
        none, and "smart scroll percentage" of the visible area caps it."""
        self._ready()
        handler = self.window.event_handler
        prefs['smart scroll percentage'] = 0.5
        width, height = self.window.get_visible_area_size()
        for small_step, cap in ((7, [7, 7]), (None, [0.5 * width, 0.5 * height])):
            with self.subTest(small_step=small_step), \
                    unittest.mock.patch.object(
                        self.window.layout, 'scroll_smartly',
                        return_value=0) as scrolled:
                handler._smart_scrolling(small_step, False)
            self.assertEqual(cap, scrolled.call_args.args[0])

    def test_control_and_the_wheel_zooms_rather_than_scrolling(self):
        for smart in (False, True):
            prefs['smart scroll'] = smart
            self.assertEqual(
                [('manual_zoom_out', ())],
                self._wheel_dispatch(0, 1, Gdk.ModifierType.CONTROL_MASK))
            self.assertEqual(
                [('manual_zoom_in', ())],
                self._wheel_dispatch(0, -1, Gdk.ModifierType.CONTROL_MASK))

    def test_a_turn_towards_the_right_follows_how_the_book_reads(self):
        """_left_right_page_progress() is what the ALT and arrow bindings
        reach, and its docstring used to say the opposite of what it does:
        a positive count goes forward in a book read left to right, and
        back in manga mode, because the reader is asking for the page in a
        direction on screen."""
        handler = self.window.event_handler
        turned = []
        with unittest.mock.patch.object(
                handler, '_flip_page',
                side_effect=lambda pages, **kwargs: turned.append(pages)):
            for manga in (False, True):
                self.window.is_manga_mode = manga
                handler._left_right_page_progress(1)
        self.assertEqual([1, -1], turned)

    def test_a_sideways_turn_scrolls_across_either_way(self):
        """Sideways scrolls across, and turns the page at the side;
        which way the turn goes depends on the book, which
        scroll_with_flipping() works out."""
        pixels = prefs['number of pixels to scroll per mouse wheel event']
        for manga in (False, True):
            self.window.is_manga_mode = manga
            self.assertEqual([('scroll_with_flipping', (pixels, 0))],
                             self._wheel_dispatch(1, 0))
            self.assertEqual([('scroll_with_flipping', (-pixels, 0))],
                             self._wheel_dispatch(-1, 0))

    def test_a_diagonal_turn_is_read_as_a_vertical_one(self):
        """A wheel reporting both axes at once is the vertical one:
        read sideways, a diagonal nudge on a page that fits the window
        would turn it and jump the book about."""
        prefs['smart scroll'] = False
        pixels = prefs['number of pixels to scroll per mouse wheel event']
        self.assertEqual([('scroll_with_flipping', (0, pixels))],
                         self._wheel_dispatch(1, 1))

    def test_a_wheel_event_that_reports_no_movement_does_nothing(self):
        self.assertEqual([], self._wheel_dispatch(0, 0))

    def test_the_wheel_is_left_alone_while_the_lens_is_held(self):
        """The middle button shows the magnifying lens, and the wheel
        belongs to whatever is under it then."""
        self.assertEqual(
            [], self._wheel_dispatch(0, 1, Gdk.ModifierType.BUTTON2_MASK))

    def test_a_sideways_wheel_turn_reads_the_other_way_in_manga_mode(self):
        self._ready()
        prefs['flip with wheel'] = True
        self.window.is_manga_mode = True
        self._wheel(-1, 0)
        self.assertEqual(self.window.imagehandler.get_current_page(), 2)

    def test_resorting_an_archive_keeps_the_page_that_was_shown(self):
        """Changing how an archive's files are sorted reopens it, and it
        came back at the same page number - which, sorted the other way,
        is another picture.  A directory's files are sorted the same
        way and came back at the picture that was shown."""
        self._ready()
        handler = self.window.imagehandler
        self.window.set_page(2)
        self._pump()
        shown = os.path.basename(handler.get_path_to_page(2))
        prefs['sort archive order'] = constants.SORT_DESCENDING
        self.window.filehandler.refresh_file()
        self.assertTrue(wait_for(
            lambda: not self.window.filehandler.file_loading
            and handler.get_number_of_pages() > 2
            and handler.page_is_available(), seconds=20))
        page = handler.get_current_page()
        self.assertEqual(shown,
                         os.path.basename(handler.get_path_to_page(page)))
        self.assertNotEqual(2, page)

    def test_the_page_a_book_was_left_on_follows_its_picture(self):
        """Where a book was left is kept by page number, and sorting the
        archive the other way made that number name another picture."""
        self._ready()
        handler = self.window.imagehandler
        filehandler = self.window.filehandler
        filehandler.last_read_page.set_enabled(True)
        path = filehandler.get_path_to_base()
        self.window.set_page(2)
        self._pump()
        shown = os.path.basename(handler.get_path_to_page(2))
        filehandler.close_file()
        self._pump()
        prefs['sort archive order'] = constants.SORT_DESCENDING
        prefs['stored dialog choices'][
            message_dialog.RememberedDialog.RESUME_FROM_LAST_READ_PAGE] = \
            Response.YES
        filehandler.open_file(path)
        self.assertTrue(wait_for(
            lambda: not filehandler.file_loading
            and handler.get_number_of_pages() > 2
            and handler.page_is_available(), seconds=20))
        page = handler.get_current_page()
        self.assertEqual(shown,
                         os.path.basename(handler.get_path_to_page(page)))

    def test_the_last_file_is_kept_with_the_file_of_its_page(self):
        """"Automatically open the last viewed file" reopened it at the
        page number, which names another picture once the archive is
        sorted the other way."""
        self._ready()
        prefs['auto load last file'] = True
        self.window.set_page(2)
        self._pump()
        self.window.terminate_program()
        self.assertEqual(2, prefs['page of last file'])
        self.assertEqual('images/02-JPG-RGB.jpg',
                         prefs['member of last file'])

    def test_quit_and_save_keeps_the_file_of_the_page(self):
        """What an older MComix reads of it - the file and the index of
        the page - comes first and is unchanged."""
        self._ready()
        self.window.set_page(2)
        self._pump()
        self.window.filehandler.write_fileinfo_file()
        with open(constants.FILEINFO_PICKLE_PATH, 'rb') as stored:
            pair = pickle.load(stored)
            member = pickle.load(stored)
        self.assertEqual([self.window.imagehandler.get_real_path(), 1], pair)
        self.assertEqual('images/02-JPG-RGB.jpg', member)

    def test_a_plain_click_turns_the_page_as_it_always_did(self):
        self._ready()
        self._click()
        self.assertEqual(self.window.imagehandler.get_current_page(), 2)
        self.assertEqual(self.window.selected_pages, set())

    def test_a_click_that_raises_the_window_does_not_turn_the_page(self):
        """The focus comes back before the click that brought it, and
        the release was told apart from a page turn by where the press
        before it had been, which the press into an unfocused window
        does not record: a click at the spot the last one was made,
        which is where a reader keeps clicking, turned the page."""
        self._ready()
        x, y = self._click()
        self.assertEqual(self.window.imagehandler.get_current_page(), 2)
        self._refocus()
        handler = self.window.event_handler
        handler.mouse_press_event(self._Click(1), 1, x, y)
        self._pump()
        handler.mouse_release_event(self._Click(1), 1, x, y)
        self._pump()
        self.assertEqual(self.window.imagehandler.get_current_page(), 2)

    def test_a_drag_that_raises_the_window_moves_the_view_from_its_start(self):
        """The press into an unfocused window did not record where it
        was, so the first move of the drag was measured from the click
        before it and threw the view across the page."""
        self._ready()
        x, y = self._click()
        self._refocus()
        handler = self.window.event_handler
        handler.mouse_press_event(self._Click(1), 1, x + 30, y + 20)
        self._pump()
        scrolled = []
        with unittest.mock.patch.object(
                self.window, 'scroll',
                side_effect=lambda dx, dy: scrolled.append((dx, dy))):
            handler.mouse_move_event(
                self._Motion(Gdk.ModifierType.BUTTON1_MASK), x + 40, y + 20)
        self.assertEqual(scrolled, [(-10, 0)])

    def test_control_and_a_click_picks_the_page_out_instead(self):
        """A plain click is how a book is read, so it cannot be the
        gesture that stops on a page as well."""
        self._ready()
        self._click(Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(self.window.selected_pages, {1})
        self.assertEqual(self.window.imagehandler.get_current_page(), 1,
                         'the page was turned as well as picked out')
        self.assertEqual(self._selected_images(), [0])

    def test_control_and_a_click_on_the_page_again_puts_it_back(self):
        self._ready()
        self._click(Gdk.ModifierType.CONTROL_MASK)
        self._click(Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(self.window.selected_pages, set())

    def test_deleting_a_page_takes_it_out_of_the_book(self):
        before = self._ready()
        self.window.select_page(2)
        with self._quietly():
            self.assertTrue(self.window.file_actions.delete_page())
        self._pump()
        self.assertEqual(self._pages(), before[:1] + before[2:])
        self.assertEqual(self.window.selected_pages, set(),
                         'the page that is gone was left picked out')

    def test_deleting_takes_out_every_page_that_is_picked_out(self):
        before = self._ready()
        self.assertGreater(len(before), 3, 'the fixture has too few pages')
        self.window.select_page(1)
        self.window.select_page(3)
        with self._quietly():
            self.assertTrue(self.window.file_actions.delete_page())
        self._pump()
        self.assertEqual(self._pages(), [before[1]] + before[3:])

    def test_the_pages_still_picked_out_move_up_with_the_book(self):
        """Removing a page moves every page after it up, and a number
        remembered against the old listing would name another page."""
        before = self._ready()
        self.window.select_page(1)
        self.window.select_page(3)
        with self._quietly():
            self.window.file_actions.delete_page(2)
        self._pump()
        self.assertEqual(self._pages(), before[:1] + before[2:])
        self.assertEqual(self.window.selected_pages, {1, 2})
        self.assertEqual(self.window.selected_page_paths(),
                         [before[0], before[2]])

    def test_deleting_a_page_can_be_taken_back(self):
        before = self._ready()
        self.window.select_page(2)
        with self._quietly():
            self.window.file_actions.delete_page()
        self._pump()
        self.assertTrue(self.window.file_actions.undo())
        self._pump()
        self.assertEqual(self._pages(), before)
        self.assertTrue(self.window.file_actions.redo())
        self._pump()
        self.assertEqual(self._pages(), before[:1] + before[2:])

    def test_there_is_nothing_to_take_back_before_a_page_goes(self):
        self.assertFalse(self.window.file_actions.can_undo())
        self.assertFalse(self.window.file_actions.can_redo())
        self.assertFalse(self.window.file_actions.undo())
        self.assertFalse(self.window.file_actions.redo())

    def test_a_deletion_after_an_undo_leaves_nothing_to_redo(self):
        self._ready()
        with self._quietly():
            self.window.select_page(1)
            self.window.file_actions.delete_page()
            self._pump()
            self.window.file_actions.undo()
            self._pump()
            self.window.select_page(2)
            self.window.file_actions.delete_page()
        self._pump()
        self.assertFalse(self.window.file_actions.can_redo())

    def test_the_last_page_of_a_book_is_not_deleted(self):
        """A book with no pages in it is not a book, and the editor
        leaves one standing too."""
        handler = self.window.imagehandler
        self.window.pages_replaced(self._ready()[:1])
        self._pump()
        self.assertEqual(handler.get_number_of_pages(), 1)
        self.window.select_page(1)
        with self._quietly():
            self.assertFalse(self.window.file_actions.delete_page())
        self.assertEqual(handler.get_number_of_pages(), 1)

    def test_delete_removes_the_picked_out_page_rather_than_the_file(self):
        """Delete acts on a selection wherever there is one; with
        nothing picked out it still asks to remove the file."""
        before = self._ready()
        self.window.select_page(1)
        with self._quietly():
            self.window.file_actions.delete()
        self._pump()
        self.assertEqual(self._pages(), before[1:])
        self.assertEqual(self._delete_dialogs(), [],
                         'it asked about the file as well')

    def _bookmark_store(self):
        """The process-wide store, emptied for this test."""
        store = bookmark_backend.BookmarksStore
        store._initialized = False
        store._bookmarks = []
        store.initialize(self.window)
        self.addCleanup(setattr, store, '_bookmarks', [])
        return store

    def test_deleting_a_bookmarked_file_asks_about_its_bookmarks(self):
        """A bookmark is a page the reader marked, not a record of a
        file, so it is the one thing a delete does not take unasked."""
        source = self._movable_book()
        store = self._bookmark_store()
        store.add_bookmark_by_values('Movable', source, 2, 4, None,
                                     datetime.datetime(2026, 1, 1))

        self.window.file_actions._delete_answered(Response.OK, source)
        self._pump()

        dialogs = self._delete_dialogs()
        self.assertEqual(len(dialogs), 1, 'nothing asked about the bookmark')
        self.assertEqual(len(store.get_bookmarks()), 1,
                         'the bookmark went without being asked about')
        dialogs[0].emit('response', Response.YES)
        self._pump()
        self.assertEqual(store.get_bookmarks(), [])

    def test_keeping_the_bookmarks_of_a_deleted_file_keeps_them(self):
        source = self._movable_book()
        store = self._bookmark_store()
        store.add_bookmark_by_values('Movable', source, 2, 4, None,
                                     datetime.datetime(2026, 1, 1))

        self.window.file_actions._delete_answered(Response.OK, source)
        self._pump()

        dialogs = self._delete_dialogs()
        self.assertEqual(len(dialogs), 1)
        dialogs[0].emit('response', Response.NO)
        self._pump()
        self.assertEqual(len(store.get_bookmarks()), 1)

    def test_deleting_a_file_nobody_bookmarked_asks_nothing(self):
        source = self._movable_book()
        self._bookmark_store()

        self.window.file_actions._delete_answered(Response.OK, source)
        self._pump()

        self.assertEqual(self._delete_dialogs(), [])

    def test_the_library_lets_go_of_a_book_that_was_deleted(self):
        """The library holds a record of a file; deleting the file left
        it offering a book that is not there, to be cleaned up by hand."""
        source = self._movable_book()
        library = backend.LibraryBackend()
        self.assertTrue(library.add_book(source))
        self.assertIsNotNone(library.get_book_by_path(source))

        self.window.file_actions._delete_answered(Response.OK, source)
        self._pump()

        self.assertFalse(os.path.exists(source), 'the file is still there')
        self.assertIsNone(library.get_book_by_path(source))

    def test_the_recent_list_lets_go_of_a_file_that_was_deleted(self):
        """A deleted file can never be opened again, and the entry for
        it went on standing in the recent files."""
        source = self._movable_book()
        recent_menu = self.window.uimanager.recent

        with unittest.mock.patch.object(recent_menu,
                                        'remove_path') as forgotten:
            self.window.file_actions._delete_answered(Response.OK, source)
            self._pump()

        self.assertFalse(os.path.exists(source), 'the file is still there')
        forgotten.assert_called_once_with(source)

    def _folder_book(self, count):
        """A folder of <count> pictures, opened; their paths in order."""
        folder = os.path.join(self.tmp_dir, 'folder')
        os.makedirs(folder)
        paths = []
        for number in range(1, count + 1):
            path = os.path.join(folder, '%02d.png' % number)
            shutil.copy(get_testfile_path('images', 'blue.png'), path)
            paths.append(path)
        self.window.filehandler.open_file(paths[0])
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == count,
            seconds=20))
        self._pump()
        return paths

    def _shown(self):
        return self.window.imagehandler.get_path_to_page()

    def test_deleting_a_picture_of_a_folder_goes_on_to_the_next(self):
        paths = self._folder_book(4)
        self.window.set_page(2)
        self._pump()
        self.window.file_actions._delete_answered(Response.OK, paths[1])
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 3,
            seconds=20))
        self._pump()
        self.assertFalse(os.path.exists(paths[1]))
        self.assertEqual(paths[2], self._shown())

    def test_deleting_the_last_picture_of_a_folder_goes_back_one(self):
        paths = self._folder_book(3)
        self.window.set_page(3)
        self._pump()
        self.window.file_actions._delete_answered(Response.OK, paths[2])
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 2,
            seconds=20))
        self._pump()
        self.assertFalse(os.path.exists(paths[2]))
        self.assertEqual(paths[1], self._shown())

    def test_deleting_the_only_picture_of_a_folder_closes_it(self):
        paths = self._folder_book(1)
        self.window.file_actions._delete_answered(Response.OK, paths[0])
        self._pump()
        self.assertFalse(os.path.exists(paths[0]))
        self.assertFalse(self.window.filehandler.file_loaded)

    def _delete_dialogs(self):
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_transient_for() is self.window]

    # -- Writing the book back over its archive ---------------------------

    def _save_prompts(self):
        return [window for window in self._delete_dialogs()
                if window.dialog_id == message_dialog.RememberedDialog
                .SAVE_EDITED_ARCHIVE]

    def test_removing_a_page_asks_whether_to_write_the_archive_again(self):
        self._ready()
        self.window.select_page(2)
        self.window.file_actions.delete_page()
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'nothing offered to save the archive')
        finally:
            for dialog in self._save_prompts():
                dialog.destroy()
            self._pump()

    def test_the_prompt_defaults_to_leaving_the_archive_alone(self):
        """Enter must not overwrite an archive."""
        self._ready()
        self.window.select_page(2)
        self.window.file_actions.delete_page()
        self._pump()
        try:
            prompt = self._save_prompts()[0]
            self.assertIs(prompt.get_default_widget(),
                          prompt.get_widget_for_response(Response.NO))
        finally:
            for dialog in self._save_prompts():
                dialog.destroy()
            self._pump()

    def _answer_save_prompt(self, response):
        """Remove a page, answer the prompt with <response>, and say
        whether the archive would have been written.  The book is the
        fixture itself, so the writing is not let through."""
        self._ready()
        self.window.select_page(2)
        self.window.file_actions.delete_page()
        self._pump()
        prompts = self._save_prompts()
        self.assertEqual(1, len(prompts), 'nothing offered to save')
        with unittest.mock.patch.object(self.window.file_actions,
                                        'save_archive') as saved:
            prompts[0].response(response)
            self._pump()
        self.assertEqual([], self._save_prompts(), 'the prompt stayed up')
        return saved.called

    def test_save_in_the_prompt_writes_the_archive(self):
        self.assertTrue(self._answer_save_prompt(Response.YES))

    def test_not_now_in_the_prompt_leaves_it_alone(self):
        self.assertFalse(self._answer_save_prompt(Response.NO))

    def test_a_book_in_a_format_that_cannot_be_written_is_not_offered(self):
        """Writing in place keeps the name the file has, so it has to
        keep the format that name says."""
        self._ready()
        with unittest.mock.patch.object(self.window.filehandler,
                                        'archive_type', constants.LHA):
            self.assertIsNone(self.window.file_actions.writeable_archive_type())
            self.assertFalse(self.window.file_actions.save_archive())
            self.window.select_page(2)
            self.window.file_actions.delete_page()
            self._pump()
        self.assertEqual(self._save_prompts(), [],
                         'it offered to write a format it cannot write')

    def _page_area_cursor(self):
        """The name of the cursor drawn over the page area, or None.

        Read off the widget rather than off the cursor handler, because
        the point of the fix is that the two used to disagree: a cursor
        set with set_layout_cursor() never reached _current_cursor.
        """
        cursor = self.window.page_area.get_cursor()
        return None if cursor is None else cursor.get_name()

    def test_a_failed_save_does_not_leave_a_wait_cursor_behind(self):
        """save_archive() answers OSError and nothing else, so anything
        else that gets out of the write used to leave the whole program
        pointing at a wait cursor with no way back."""
        self._ready()
        self.assertIsNone(self._page_area_cursor(),
                          'the page area started out with a cursor set')
        with unittest.mock.patch.object(
                archive_packer, 'write_archive',
                side_effect=RuntimeError('not an OSError')):
            with self.assertRaises(RuntimeError):
                self.window.file_actions.save_archive()

        self.assertIsNone(self._page_area_cursor(),
                          'the wait cursor outlived the save')

    def test_a_save_that_fails_says_so_and_leaves_the_book(self):
        """The one failure save_archive() answers: the reader is told,
        in a dialog of its own, that the original is still there."""
        self._ready()
        path = self.window.filehandler.get_path_to_base()
        with open(path, 'rb') as book:
            before = book.read()
        with unittest.mock.patch.object(
                archive_packer, 'write_archive',
                side_effect=OSError(28, 'No space left on device')):
            self.assertFalse(self.window.file_actions.save_archive())
        self._pump()
        notices = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, message_dialog.MessageDialog)
                   and window.get_visible()]
        try:
            self.assertEqual(1, len(notices))
            self.assertEqual('The new archive could not be saved!',
                             notices[0]._primary.get_text())
        finally:
            for notice in notices:
                notice.destroy()
            self._pump()
        with open(path, 'rb') as book:
            self.assertEqual(before, book.read())
        self.assertIsNone(self._page_area_cursor())

    def test_a_save_shows_the_wait_cursor_while_it_runs(self):
        """And through the cursor handler, so that the pointer does not
        hide itself part way through - see HandSetCursorTest."""
        self._ready()
        handler = self.window.cursor_handler
        busy = []

        def watch(*args, **kwargs):
            busy.append(handler._current_cursor)

        with unittest.mock.patch.object(archive_packer, 'write_archive',
                                        side_effect=watch):
            self.assertTrue(self.window.file_actions.save_archive())

        self.assertEqual([constants.WAIT_CURSOR], busy,
                         'the save ran without saying it was working')
        self.assertIsNone(self._page_area_cursor(),
                          'the wait cursor outlived the save')

    def test_nothing_outside_the_cursor_handler_sets_the_cursor(self):
        """set_layout_cursor() asks callers to go through the handler, and
        the reason is HandSetCursorTest: a cursor set behind its back is
        replaced by the hidden one when the hide timer runs out.  Four call
        sites in edit_dialog.py and three in main.py did it anyway."""
        direct = []
        for module in (main, edit_dialog):
            with open(module.__file__, encoding='utf-8') as fp:
                for number, line in enumerate(fp, 1):
                    if ('set_layout_cursor(' in line
                            and 'def set_layout_cursor' not in line
                            and not line.lstrip().startswith('#')):
                        direct.append('%s:%d' % (
                            os.path.basename(module.__file__), number))
        self.assertEqual([], direct)

    def test_a_format_other_than_zip_needs_the_preference(self):
        """A save that kept the name and changed the format would put a
        ZIP inside a file still called .cbt."""
        self._ready()
        with unittest.mock.patch.object(self.window.filehandler,
                                        'archive_type', constants.TAR):
            prefs['keep archive format when saving'] = False
            self.assertIsNone(self.window.file_actions.writeable_archive_type())
            prefs['keep archive format when saving'] = True
            self.assertEqual(self.window.file_actions.writeable_archive_type(),
                             constants.TAR)

    def test_saving_writes_the_book_over_the_archive_it_came_from(self):
        source = os.path.join(self.tmp_dir, 'Book.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), source)
        self.window.filehandler.open_file(source)
        self.assertTrue(
            wait_for(lambda: self.window.imagehandler
                     .get_number_of_pages() > 2, seconds=20),
            'the copied archive never listed its pages')
        before = self.window.imagehandler.get_number_of_pages()
        mode = os.stat(source).st_mode

        self.window.select_page(1)
        with self._quietly():
            self.window.file_actions.delete_page()
        self._pump()
        self.assertTrue(self.window.file_actions.save_archive(), 'the save failed')

        with zipfile.ZipFile(source) as written:
            pages = [name for name in written.namelist()
                     if image_tools.is_image_file(name)]
        self.assertEqual(len(pages), before - 1,
                         'the archive on disk still holds the page')
        with zipfile.ZipFile(source) as written:
            self.assertIn('ComicInfo.xml', written.namelist(),
                          'the book was saved as a plain ZIP of pictures')
        self.assertEqual(os.stat(source).st_mode, mode,
                         'the archive came back with different permissions')

    @unittest.skipUnless(os.path.isdir('/proc/self/fd'),
                         'the open descriptors are read from /proc')
    def test_nothing_holds_the_archive_open_when_it_is_written_over(self):
        """Windows replaces no file that is open, and the extractor kept
        the archive open for as long as the book was: saving there failed
        with "Access is denied"."""
        source = os.path.join(self.tmp_dir, 'Book.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), source)
        self.window.filehandler.open_file(source)
        self.assertTrue(
            wait_for(lambda: self.window.imagehandler
                     .get_number_of_pages() > 2, seconds=20),
            'the copied archive never listed its pages')
        self.window.select_page(1)
        with self._quietly():
            self.window.file_actions.delete_page()
        self._pump()
        replace = os.replace
        held = []

        def replacing(tmp_path, archive_path):
            held.extend(_descriptors_on(archive_path))
            replace(tmp_path, archive_path)

        with unittest.mock.patch.object(archive_packer.os, 'replace',
                                        replacing):
            self.assertTrue(self.window.file_actions.save_archive(),
                            'the save failed')
        self.assertEqual([], held)

    def test_saving_waits_for_the_comments_as_well_as_the_pages(self):
        """A comment is extracted like anything else in the archive.

        The packer reads every file's size before it writes it, so a
        save that waited only for the pages raised FileNotFoundError on
        a comment that was not out yet and refused the save - which
        happened whenever the reader saved soon after opening the book.
        """
        self._ready()
        asked = []
        # The packer is stubbed out: the book open here is the committed
        # fixture itself, and a save writes over the archive it came
        # from.  What the test is about is the waiting, not the writing.
        with unittest.mock.patch.object(
                self.window.filehandler, 'wait_for_files',
                side_effect=lambda paths: asked.extend(paths)), \
                unittest.mock.patch.object(file_actions.archive_packer,
                                           'write_archive'):
            self.assertTrue(self.window.file_actions.save_archive())

        comments = [self.window.filehandler.get_comment_name(number)
                    for number in range(
                        1, self.window.filehandler
                        .get_number_of_comments() + 1)]
        self.assertTrue(comments, 'the fixture holds no comment')
        for comment in comments:
            self.assertIn(comment, asked)

    def test_saving_does_not_write_the_directory_its_pages_were_in(self):
        """The fixture was packed from a folder, so it holds an entry for
        that folder.  Nothing can extract one - opening it for writing
        raises - and nothing should write one either: the packer renames
        every page into the archive root, so there is no folder left for
        the entry to stand for."""
        source = os.path.join(self.tmp_dir, 'Book.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), source)
        with zipfile.ZipFile(source) as original:
            self.assertTrue(
                [info.filename for info in original.infolist()
                 if info.is_dir()],
                'the fixture holds no directory entry, so this proves nothing')
        self.window.filehandler.open_file(source)
        # The book opened in setUp also has more than two pages, so the
        # page count alone is true before this one has opened at all.
        self.assertTrue(
            wait_for(lambda: self.window.filehandler.get_path_to_base()
                     == source and self.window.imagehandler
                     .get_number_of_pages() > 2, seconds=20),
            'the copied archive never opened')

        self.assertTrue(self.window.file_actions.save_archive(), 'the save failed')

        with zipfile.ZipFile(source) as written:
            self.assertEqual(
                [info.filename for info in written.infolist()
                 if info.is_dir()], [])

    def test_the_rename_key_names_the_page_being_read(self):
        """A key press carries no pointer position, so the page a menu
        was opened over earlier must not be the one it renames."""
        self._ready()
        self.window.popup_page = 3
        with unittest.mock.patch.object(self.window.file_actions,
                                        'rename_page_dialog') as asked:
            self.window.file_actions.rename_page_being_read()
        asked.assert_called_once_with(
            self.window.imagehandler.get_current_page())

    def test_the_menu_opened_beside_the_pages_renames_the_page_being_read(self):
        self._ready()
        self.window.popup_page = None
        with unittest.mock.patch.object(self.window.file_actions,
                                        'rename_page_dialog') as asked:
            self.window.file_actions.rename_popup_page()
        asked.assert_called_once_with(
            self.window.imagehandler.get_current_page())

    def test_the_rename_key_does_nothing_without_a_book(self):
        with unittest.mock.patch.object(self.window.file_actions,
                                        'rename_page_dialog') as asked, \
                unittest.mock.patch.object(
                    self.window.imagehandler, 'get_current_page',
                    return_value=0):
            self.window.file_actions.rename_page_being_read()
        asked.assert_not_called()

    # -- Closing a book whose changes have not been written ---------------

    def _forget_stored_answer(self):
        """Take back the remembered answer a test stored, which is
        written into the preferences the whole process shares."""
        prefs['stored dialog choices'].pop(
            message_dialog.RememberedDialog.SAVE_EDITED_ARCHIVE, None)

    def _remember_answer(self, response):
        prefs['stored dialog choices'][
            message_dialog.RememberedDialog.SAVE_EDITED_ARCHIVE] = \
            int(response)
        self.addCleanup(self._forget_stored_answer)

    def test_a_change_that_has_not_been_written_is_one_to_save(self):
        self._ready()
        self.assertFalse(self.window.file_actions.has_unsaved_changes())
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self.assertTrue(self.window.file_actions.has_unsaved_changes())

    def test_a_change_taken_back_is_nothing_to_save(self):
        """The first listing the undo stack kept is the book as it was
        opened, and an undo that empties the stack is back at it."""
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self.assertTrue(self.window.file_actions.undo())
        self.assertFalse(self.window.file_actions.has_unsaved_changes())

    def test_a_page_named_what_it_is_called_already_is_nothing_to_save(self):
        """Renaming a page back to the name of its own file leaves the
        packer nothing to do differently."""
        pages = self._ready()
        own_name = os.path.basename(pages[0])
        with self._quietly():
            self.assertEqual(self.window.file_actions.rename_page(
                1, 'Cover.png'), 'Cover.png')
            self.assertEqual(self.window.file_actions.rename_page(
                1, own_name), own_name)
        self.assertEqual(self.window.file_actions.page_names(), {})
        self.assertFalse(self.window.file_actions.has_unsaved_changes())

    def test_closing_the_book_offers_to_write_the_changes_first(self):
        """The offer made at the change itself is not the last word:
        closing is what throws the change away."""
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self.window.filehandler.close_file()
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'the change was thrown away without a word')
            self.assertTrue(self.window.filehandler.file_loaded,
                            'the book closed before the question was answered')
        finally:
            self._close_prompts()

    def test_saying_yes_on_the_way_out_writes_the_archive(self):
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self._remember_answer(Response.YES)
        with unittest.mock.patch.object(self.window.file_actions,
                                        'save_archive') as written:
            self.window.filehandler.close_file()
            self._pump()
        written.assert_called_once_with()
        self.assertFalse(self.window.filehandler.file_loaded,
                         'the book stayed open after the archive was written')

    def test_saying_no_on_the_way_out_closes_the_book_as_it_is(self):
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self._remember_answer(Response.NO)
        with unittest.mock.patch.object(self.window.file_actions,
                                        'save_archive') as written:
            self.window.filehandler.close_file()
            self._pump()
        written.assert_not_called()
        self.assertFalse(self.window.filehandler.file_loaded,
                         'the book was left open')

    def test_opening_another_book_over_it_offers_to_write_it_first(self):
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self.window.filehandler.open_file(
            get_testfile_path('archives', 'double-pages-test.cbz'))
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'the book was replaced without a word')
        finally:
            self._close_prompts()

    def test_turning_past_the_end_offers_to_write_the_changes_first(self):
        """Turning past the last page opens the next archive in the
        folder, which closed the book before the question about its
        changes was asked - and closed, it had no changes to ask about,
        so they were thrown away without a word."""
        self._ready()
        prefs['auto open next archive'] = True
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        opened = self.window.filehandler.get_path_to_base()
        self.window.next_book()
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'the next book was opened without a word')
            self.assertEqual(self.window.filehandler.get_path_to_base(),
                             opened, 'the book went before the answer')
            self._save_prompts()[0].emit('response', Response.NO)
            self._pump()
            self.assertTrue(wait_for(
                lambda: self.window.filehandler.get_path_to_base()
                not in (None, opened), seconds=10),
                'the next book was not opened after the answer')
        finally:
            self._close_prompts()

    def test_turning_back_past_the_start_offers_to_write_the_changes_first(self):
        self._ready()
        prefs['auto open next archive'] = True
        self.window.filehandler.open_file(
            get_testfile_path('archives', 'double-pages-test.cbz'))
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self.window.previous_book()
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'the previous book was opened without a word')
        finally:
            self._close_prompts()

    def test_which_book_or_folder_comes_next_follows_the_two_preferences(self):
        """Past either end of a book: the next archive in the folder if
        "auto open next archive" is set, and failing that the next
        folder if "auto open next directory" is - but from an archive
        only when both are set, so that archives alone do not lead out
        of their folder."""
        for (archive_open, next_archive, next_folder, found_archive,
             archive_tried, folder_tried) in (
                (True, True, True, True, True, False),
                (True, True, True, False, True, True),
                (True, False, True, False, False, False),
                (False, False, True, False, False, True),
                (False, True, False, False, True, False)):
            prefs['auto open next archive'] = next_archive
            prefs['auto open next directory'] = next_folder
            for method, archive_step, folder_step in (
                    ('_open_next_book', 'open_next_archive',
                     'open_next_directory'),
                    ('_open_previous_book', 'open_previous_archive',
                     'open_previous_directory')):
                with self.subTest(archive_open=archive_open,
                                  next_archive=next_archive,
                                  next_folder=next_folder,
                                  found_archive=found_archive,
                                  method=method), \
                        unittest.mock.patch.object(
                            self.window.filehandler, 'archive_type',
                            'zip' if archive_open else None), \
                        unittest.mock.patch.object(
                            self.window.filehandler, archive_step,
                            return_value=found_archive) as archive, \
                        unittest.mock.patch.object(
                            self.window.filehandler, folder_step) as folder:
                    getattr(self.window, method)()
                    self.assertEqual(archive_tried, archive.called)
                    self.assertEqual(folder_tried, folder.called)

    def test_turning_past_the_end_into_a_folder_offers_to_write_first(self):
        """With no archive after it, turning past the end walks on to
        the next folder - which moved the walk before anything asked
        about the book, and then threw its changes away."""
        first = os.path.join(self.tmp_dir, 'a')
        second = os.path.join(self.tmp_dir, 'b')
        os.mkdir(first)
        os.mkdir(second)
        book = os.path.join(first, 'book.zip')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), book)
        shutil.copy(get_testfile_path('images', 'blue.png'), second)
        prefs['auto open next archive'] = True
        prefs['auto open next directory'] = True
        self.window.filehandler.open_file(book)
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self.window.next_book()
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'the next folder was opened without a word')
            self.assertEqual(self.window.filehandler.get_path_to_base(), book,
                             'the book went before the answer')
            self._save_prompts()[0].emit('response', Response.NO)
            self._pump()
            self.assertTrue(wait_for(
                lambda: self.window.filehandler.get_path_to_base() == second,
                seconds=10), 'the next folder was not opened after the answer')
        finally:
            self._close_prompts()

    def test_quitting_offers_to_write_the_changes_first(self):
        """And the window stays until the question has been answered:
        it is the window the question stands against."""
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        with unittest.mock.patch.object(self.window,
                                        'terminate_program') as quit_now:
            self.assertTrue(self.window.close_program(),
                            'the window went with the question still on it')
            self._pump()
            try:
                prompts = self._save_prompts()
                self.assertEqual(len(prompts), 1, 'MComix quit without a word')
                quit_now.assert_not_called()
                prompts[0].emit('response', Response.NO)
                self._pump()
            finally:
                self._close_prompts()
            quit_now.assert_called_once_with()

    def test_the_offer_is_made_once_for_the_close_that_follows_it(self):
        """A close reaches it more than once - quitting asks, and the
        file handler it closes asks again - and one answer stands for
        the whole of it."""
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        closed = []
        self.window.file_actions.before_closing(lambda: closed.append('first'))
        self.window.file_actions.before_closing(lambda: closed.append('second'))
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'the same close was asked about twice')
            self.assertEqual(closed, ['second'],
                             'the second close waited for an answer of its own')
        finally:
            self._close_prompts()

    def test_a_change_made_afterwards_is_asked_about_again(self):
        self._ready()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(1, 2))
        self._remember_answer(Response.NO)
        self.window.file_actions.before_closing(lambda: None)
        self._pump()
        with self._quietly():
            self.assertTrue(self.window.file_actions.swap_pages(2, 3))
        self._forget_stored_answer()
        self.window.file_actions.before_closing(lambda: None)
        self._pump()
        try:
            self.assertEqual(len(self._save_prompts()), 1,
                             'the new change was let go without a word')
        finally:
            self._close_prompts()

    # -- Leaving a book with pages still picked out -----------------------

    def _leaving_prompts(self):
        return [window for window in self._delete_dialogs()
                if window.dialog_id == message_dialog.RememberedDialog
                .REMOVE_PICKED_OUT_PAGES]

    def _close_prompts(self):
        for dialog in self._delete_prompts_open():
            dialog.destroy()
        self._pump()

    def _delete_prompts_open(self):
        return self._leaving_prompts() + self._save_prompts()

    def test_leaving_a_book_offers_to_remove_the_pages_picked_out(self):
        """Pages are picked out as a book goes by so that they can be
        dealt with together, and the end of the book is where that is."""
        self._ready()
        self.window.select_page(1)
        opened = []
        self.window._leaving_book(lambda: opened.append(True))
        self._pump()
        try:
            self.assertEqual(len(self._leaving_prompts()), 1,
                             'nothing offered to remove the pages')
            self.assertEqual(opened, [],
                             'it went on to the next book before answering')
        finally:
            self._close_prompts()

    def test_leaving_with_nothing_picked_out_asks_nothing(self):
        self._ready()
        opened = []
        self.window._leaving_book(lambda: opened.append(True))
        self._pump()
        self.assertEqual(self._leaving_prompts(), [])
        self.assertEqual(opened, [True], 'it did not go on to the next book')

    def test_leaving_a_book_that_cannot_be_written_asks_nothing(self):
        """An offer to remove pages that could then not be saved would
        take the book apart for nothing."""
        self._ready()
        self.window.select_page(1)
        opened = []
        with unittest.mock.patch.object(self.window.filehandler,
                                        'archive_type', constants.LHA):
            self.window._leaving_book(lambda: opened.append(True))
            self._pump()
        self.assertEqual(self._leaving_prompts(), [])
        self.assertEqual(opened, [True])

    def test_the_leaving_prompt_defaults_to_keeping_the_pages(self):
        """Enter must not take pages out of an archive."""
        self._ready()
        self.window.select_page(1)
        self.window._leaving_book(lambda: None)
        self._pump()
        try:
            prompt = self._leaving_prompts()[0]
            self.assertIs(prompt.get_default_widget(),
                          prompt.get_widget_for_response(Response.NO))
        finally:
            self._close_prompts()

    def test_keeping_them_leaves_the_book_as_it_was(self):
        before = self._ready()
        self.window.select_page(1)
        opened = []
        self.window._leaving_answered(Response.NO, lambda: opened.append(True))
        self._pump()
        self.assertEqual(self._pages(), before)
        self.assertEqual(opened, [True])

    def test_removing_them_takes_them_out_and_writes_the_archive(self):
        source = os.path.join(self.tmp_dir, 'Book.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), source)
        self.window.filehandler.open_file(source)
        self.assertTrue(
            wait_for(lambda: self.window.imagehandler
                     .get_number_of_pages() > 2, seconds=20),
            'the copied archive never listed its pages')
        before = self.window.imagehandler.get_number_of_pages()

        self.window.select_page(1)
        self.window.select_page(2)
        opened = []
        self.window._leaving_answered(Response.YES,
                                      lambda: opened.append(True))
        self._pump()

        self.assertEqual(self.window.imagehandler.get_number_of_pages(),
                         before - 2)
        with zipfile.ZipFile(source) as written:
            pages = [name for name in written.namelist()
                     if image_tools.is_image_file(name)]
        self.assertEqual(len(pages), before - 2,
                         'the archive on disk still holds the pages')
        self.assertEqual(opened, [True], 'it did not go on to the next book')

    # -- The other buttons ------------------------------------------------

    def _button(self, button, state=0):
        """Press and release <button> over the middle of the first page."""
        (left, top), (wide, high) = (
            self.window.layout.get_content_boxes()[0].get_position(),
            self.window.layout.get_content_boxes()[0].get_size())
        x, y = left + wide / 2, top + high / 2
        self.window.was_out_of_focus = False
        handler = self.window.event_handler
        handler.mouse_press_event(self._Click(button), 1, x, y)
        handler.mouse_release_event(self._Click(button, state), 1, x, y)
        self._pump()

    def _page(self):
        return self.window.imagehandler.get_current_page()

    def test_the_first_and_last_page_actions_go_there(self):
        pages = len(self._ready())
        self.window.set_page(2)
        self._pump()
        self.window.actiongroup.get_action('last_page').activate()
        self._pump()
        self.assertEqual(pages, self._page())
        self.window.actiongroup.get_action('first_page').activate()
        self._pump()
        self.assertEqual(1, self._page())

    def test_turning_back_from_the_first_page_goes_to_the_book_before(self):
        self._ready()
        self.window.set_page(1)
        self._pump()
        with unittest.mock.patch.object(self.window, 'previous_book') as back:
            self.window.flip_page(-1)
        back.assert_called_once_with()
        self.assertEqual(1, self._page())

    def test_leaving_fullscreen_asks_the_window_to_leave_it(self):
        action = self.window.actiongroup.get_action('fullscreen')
        with unittest.mock.patch.object(self.window, 'fullscreen') as into, \
                unittest.mock.patch.object(self.window,
                                           'unfullscreen') as out:
            action.set_active(True)
            self._pump()
            action.set_active(False)
            self._pump()
        into.assert_called_once_with()
        out.assert_called_once_with()

    def _info_panel(self):
        with unittest.mock.patch.object(self.window.osd, 'show') as shown:
            self.window.show_info_panel()
        return [call.args[0] for call in shown.call_args_list]

    def test_the_info_panel_names_the_file_its_place_and_the_page(self):
        self._ready()
        self.window.set_page(2)
        self._pump()
        number, count = self.window.filehandler.get_file_number()
        self.assertGreater(count, 1, 'the archive stands alone')
        self.assertEqual(['01-ZIP-Normal.zip\n(%d / %d)\nPage 2 / 4'
                          % (number, count)], self._info_panel())

    def test_for_loose_images_it_leaves_out_the_place_of_the_file(self):
        self._folder_book(3)
        self.assertEqual(['folder/01.png\n\nPage 1 / 3'], self._info_panel())

    def test_with_no_book_open_it_shows_nothing(self):
        self.window.filehandler.close_file()
        self._pump()
        self.assertEqual([], self._info_panel())

    def test_the_window_goes_back_to_being_maximised(self):
        prefs['window maximized'] = True
        with unittest.mock.patch.object(self.window, 'maximize') as maximize, \
                unittest.mock.patch.object(type(self.window), 'is_maximized',
                                           return_value=False):
            self.assertTrue(self.window.restore_window_geometry())
        maximize.assert_called_once_with()

    def test_a_window_that_has_its_size_already_is_left_alone(self):
        prefs['window width'], prefs['window height'] = \
            self.window.get_window_size()
        prefs['window maximized'] = self.window.is_maximized()
        with unittest.mock.patch.object(self.window,
                                        'set_default_size') as sized:
            self.assertFalse(self.window.restore_window_geometry())
        sized.assert_not_called()

    def test_the_gap_between_two_pages_is_taken_and_drawn(self):
        prefs['space between two pages'] = 7
        with unittest.mock.patch.object(self.window, 'draw_image') as drawn:
            self.window.update_space()
        self.assertEqual(7, self.window._spacing)
        drawn.assert_called_once_with()

    def test_shift_and_a_click_turns_ten_pages_or_to_the_last(self):
        pages = len(self._ready())
        self._button(1, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(min(11, pages), self._page())

    def test_shift_and_a_right_click_turns_back_ten_or_to_the_first(self):
        pages = len(self._ready())
        self.window.set_page(pages)
        self._pump()
        self._button(3, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(max(1, pages - 10), self._page())

    def test_alt_and_a_right_click_turns_back_a_page(self):
        self._ready()
        self.window.set_page(3)
        self._pump()
        self._button(3, Gdk.ModifierType.ALT_MASK)
        self.assertEqual(2, self._page())

    def test_the_middle_button_holds_the_lens_while_it_is_down(self):
        self._ready()
        lens = self.window.actiongroup.get_action('lens')
        self.assertFalse(lens.get_active())
        self._press(2)
        self.assertTrue(lens.get_active())
        self.window.event_handler.mouse_release_event(self._Click(2), 1, 0, 0)
        self.assertFalse(lens.get_active())

    def test_a_right_click_opens_the_menu_over_the_page_under_it(self):
        self._ready()
        hold_open(self.window.popup)
        self.window.popup_page = None
        self._button(3)
        try:
            self.assertTrue(self.window.popup.get_visible(),
                            'the menu did not open')
            self.assertEqual(1, self.window.popup_page)
            self.assertEqual(1, self._page(), 'the page was turned as well')
        finally:
            self.window.popup.popdown()
            self._pump()

    def test_the_right_click_menu_offers_to_delete_a_page(self):
        self.assertIn('win.delete-page-popup',
                      self._menu_actions(self.window.uimanager.popup
                                         .get_menu_model()))

    def test_the_right_click_menu_deletes_the_page_it_was_opened_over(self):
        before = self._ready()
        self.window.popup_page = 2
        with self._quietly():
            self.window.file_actions.delete_popup_page()
        self._pump()
        self.assertEqual(self._pages(), before[:1] + before[2:])

    def test_the_right_click_menu_offers_to_copy_the_page(self):
        self.assertIn('win.copy-page-popup',
                      self._menu_actions(self.window.uimanager.popup
                                         .get_menu_model()))

    def test_the_right_click_menu_copies_the_page_it_was_opened_over(self):
        """The menu bar's Copy takes the view; the popup stands on one
        page, and takes that one, as its Save As and Delete page do."""
        self._ready()
        prefs['default double page'] = False
        self.window.set_page(2)
        self._pump()
        self.window.popup_page = 2
        copied = []
        with unittest.mock.patch.object(
                self.window.clipboard, 'copy',
                side_effect=lambda text, pixbuf: copied.append((text, pixbuf))):
            self.window.clipboard.copy_popup_page()

        self.assertEqual(len(copied), 1)
        text, pixbuf = copied[0]
        self.assertEqual(text,
                         self.window.imagehandler.get_path_to_page(2))
        self.assertIsNotNone(pixbuf)

    def test_copying_from_the_background_takes_the_whole_view(self):
        """Opened on the background around the pages, the menu stands on
        no page at all, and the view is what there is to copy."""
        self._ready()
        self.window.popup_page = None
        copied = []
        with unittest.mock.patch.object(
                self.window.clipboard, 'copy',
                side_effect=lambda text, pixbuf: copied.append((text, pixbuf))):
            self.window.clipboard.copy_popup_page()

        self.assertEqual(len(copied), 1)
        self.assertEqual(copied[0][0],
                         self.window.imagehandler.get_path_to_page())

    def test_the_right_click_menu_offers_to_move_the_file(self):
        self.assertIn('moveto.other',
                      self._menu_actions(self.window.uimanager.popup
                                         .get_menu_model()))

    # -- Moving the file, or the archive it is a page of ------------------

    def _movable_book(self):
        """A copy of the fixture archive that a test may move about."""
        source = os.path.join(self.tmp_dir, 'Movable.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), source)
        self.window.filehandler.open_file(source)
        self._ready()
        return source

    def test_moving_the_archive_goes_on_reading_it_where_it_landed(self):
        """The page being read comes back, which is what makes this
        different from moving the file and opening it again by hand."""
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        self.window.set_page(3)
        self._pump()

        self.window.file_actions.move_current_file(destination)
        self._pump()

        moved = os.path.join(destination, 'Movable.cbz')
        self.assertTrue(os.path.isfile(moved))
        self.assertFalse(os.path.exists(source))
        # get_path_to_base() is set as the book opens, before its pages
        # have been listed, so the page is what there is to wait for.
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_current_page() == 3,
            seconds=20), 'the book did not come back to the page being read')
        self.assertEqual(self.window.filehandler.get_path_to_base(), moved)

    @unittest.skipUnless(os.path.isdir('/proc/self/fd'),
                         'the open descriptors are read from /proc')
    def test_nothing_holds_the_archive_open_when_it_is_moved(self):
        """Windows moves no file that is open, and the extractor kept the
        archive open for as long as the book was: moving it failed there
        with "being used by another process"."""
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        move = shutil.move
        held = []

        def moving(path, target):
            held.extend(_descriptors_on(path))
            return move(path, target)

        with unittest.mock.patch.object(file_mover.shutil, 'move', moving):
            self.window.file_actions.move_current_file(destination)
        self._pump()
        self.assertTrue(os.path.isfile(os.path.join(destination,
                                                    'Movable.cbz')))
        self.assertFalse(os.path.exists(source))
        self.assertEqual([], held)

    def _move_refused(self, destination):
        """Move the book into <destination>, which will not take it, and
        answer with what the message that says so gives as the reason."""
        source = self.window.filehandler.get_path_to_base()
        self.window.file_actions.move_current_file(destination)
        self._pump()
        messages = self._message_dialogs()
        self.assertEqual(1, len(messages), 'nothing said it did not move')
        self.addCleanup(messages[0].destroy)
        self.assertTrue(os.path.isfile(source), 'the book moved all the same')
        self.assertEqual([], prefs['recent move destinations'])
        return messages[0]._secondary.get_text()

    def test_a_name_taken_in_the_destination_is_said_to_be(self):
        self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        with open(os.path.join(destination, 'Movable.cbz'), 'wb'):
            pass
        self.assertEqual('A file of that name is there already.',
                         self._move_refused(destination))

    def test_a_destination_without_room_says_how_large_the_file_is(self):
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        full = OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        with unittest.mock.patch.object(file_mover, 'move_file',
                                        side_effect=full):
            reason = self._move_refused(destination)
        self.assertEqual('There is not enough room there: the file is %s.'
                         % tools.format_byte_size(os.path.getsize(source)),
                         reason)

    def test_any_other_refusal_gives_the_system_s_own_reason(self):
        self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        denied = OSError(errno.EACCES, os.strerror(errno.EACCES))
        with unittest.mock.patch.object(file_mover, 'move_file',
                                        side_effect=denied):
            self.assertEqual(str(denied), self._move_refused(destination))

    def test_a_destination_moved_to_is_offered_next_time(self):
        self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)

        self.window.file_actions.move_current_file(destination)
        self._pump()

        self.assertEqual(prefs['recent move destinations'], [destination])

    def test_a_bookmark_follows_a_book_that_is_moved(self):
        """A bookmark holds the path of the file it marks, and the book
        moved out from under it: opening the bookmark afterwards said
        the file was not there."""
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        # The store is one for the process and keeps whatever another
        # test left in it.
        store = bookmark_backend.BookmarksStore
        store._initialized = False
        store._bookmarks = []
        store.initialize(self.window)
        self.addCleanup(setattr, store, '_bookmarks', [])
        store.add_bookmark_by_values('Movable', source, 2, 4, None,
                                     datetime.datetime(2026, 1, 1))

        self.window.file_actions.move_current_file(destination)
        self._pump()

        moved = os.path.join(destination, 'Movable.cbz')
        self.assertEqual([bookmark._path
                          for bookmark in store.get_bookmarks()], [moved])

    def test_the_recent_list_lets_go_of_the_path_a_book_has_left(self):
        """The book is opened again where it landed, which records that.
        The entry for where it was would open nothing."""
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        recent_menu = self.window.uimanager.recent

        with unittest.mock.patch.object(recent_menu,
                                        'remove_path') as forgotten:
            self.window.file_actions.move_current_file(destination)
            self._pump()

        forgotten.assert_called_once_with(source)

    def test_the_library_follows_a_book_that_is_moved(self):
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        library = backend.LibraryBackend()
        self.assertTrue(library.add_book(source))

        self.window.file_actions.move_current_file(destination)
        self._pump()

        self.assertIsNone(library.get_book_by_path(source))
        self.assertIsNotNone(library.get_book_by_path(
            os.path.join(destination, 'Movable.cbz')))

    def test_a_name_that_is_taken_stops_the_move_and_says_so(self):
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        with open(os.path.join(destination, 'Movable.cbz'), 'wb') as handle:
            handle.write(b'not the book')

        self.window.file_actions.move_current_file(destination)
        self._pump()

        self.assertTrue(os.path.isfile(source), 'the book moved anyway')
        self.assertEqual(len(self._delete_dialogs()), 1,
                         'nothing said why the move did not happen')
        self.assertEqual(prefs['recent move destinations'], [])
        # Left standing it would be answered by the next test that goes
        # looking for a dialog.
        for dialog in self._delete_dialogs():
            dialog.destroy()
        self._pump()

    def _drag(self, start, end, state):
        """Press at <start>, move, and release at <end>, holding <state>."""
        handler = self.window.event_handler
        self.window.was_out_of_focus = False
        handler.mouse_press_event(self._Click(1), 1, *start)
        handler.mouse_release_event(self._Click(1, state), 1, *end)
        self._pump()

    def _spread_points(self):
        """The middle of each of the two pages on screen."""
        boxes = self.window.layout.get_content_boxes()
        self.assertEqual(len(boxes), 2, 'two pages are not on screen')
        scrolled_x, scrolled_y = self.window.scroll_offset()
        points = []
        for content in boxes:
            left, top = content.get_position()
            width, height = content.get_size()
            points.append((left + width / 2 - scrolled_x,
                           top + height / 2 - scrolled_y))
        return points

    def test_dragging_a_page_onto_the_other_swaps_the_two(self):
        """A spread whose halves arrived the wrong way round is put
        right by dragging one onto the other."""
        prefs['default double page'] = True
        try:
            before = self._ready()
            self.window.set_page(2)
            self.assertTrue(wait_for(
                lambda: len(self.window.layout.get_content_boxes()) == 2))
            first, second = self._spread_points()

            with self._quietly():
                self._drag(first, second, Gdk.ModifierType.CONTROL_MASK
                           | Gdk.ModifierType.SHIFT_MASK)

            self.assertEqual(self._pages(),
                             [before[0], before[2], before[1]] + before[3:])
        finally:
            prefs['default double page'] = False

    def test_a_drag_that_ends_where_it_started_swaps_nothing(self):
        prefs['default double page'] = True
        try:
            before = self._ready()
            self.window.set_page(2)
            self.assertTrue(wait_for(
                lambda: len(self.window.layout.get_content_boxes()) == 2))
            first, _second = self._spread_points()

            self._drag(first, (first[0] + 20, first[1] + 20),
                       Gdk.ModifierType.CONTROL_MASK
                       | Gdk.ModifierType.SHIFT_MASK)

            self.assertEqual(self._pages(), before)
        finally:
            prefs['default double page'] = False

    def test_a_plain_drag_still_moves_the_view(self):
        """Panning is what a drag without the modifiers does, and the
        swap must not have taken it."""
        self._ready()
        self._pump()
        scrolled = []
        with unittest.mock.patch.object(
                self.window, 'scroll',
                side_effect=lambda dx, dy: scrolled.append((dx, dy))):
            self.window.event_handler.mouse_move_event(
                self._Motion(Gdk.ModifierType.BUTTON1_MASK), 10, 10)
        self.assertTrue(scrolled, 'the view did not move')

    def test_a_drag_that_swaps_does_not_move_the_view(self):
        self._ready()
        self._pump()
        scrolled = []
        with unittest.mock.patch.object(
                self.window, 'scroll',
                side_effect=lambda dx, dy: scrolled.append((dx, dy))):
            self.window.event_handler.mouse_move_event(
                self._Motion(Gdk.ModifierType.BUTTON1_MASK
                             | Gdk.ModifierType.CONTROL_MASK
                             | Gdk.ModifierType.SHIFT_MASK), 10, 10)
        self.assertEqual(scrolled, [], 'the pages moved under the drag')

    # -- Renaming a page --------------------------------------------------

    def test_renaming_a_page_gives_it_the_name_that_was_typed(self):
        self._ready()
        with self._quietly():
            self.assertEqual(
                self.window.file_actions.rename_page(1, 'Cover.png'),
                'Cover.png')
        self.assertEqual(self.window.file_actions.page_name(1), 'Cover.png')

    def test_a_name_with_no_extension_keeps_the_old_one(self):
        """What MComix and every other reader take for a page is
        decided by the extension, so a name without one keeps it."""
        self._ready()
        old = self.window.file_actions.page_name(1)
        with self._quietly():
            self.window.file_actions.rename_page(1, 'Cover')
        self.assertEqual(self.window.file_actions.page_name(1),
                         'Cover' + os.path.splitext(old)[1])

    def test_a_name_with_a_folder_in_front_of_it_is_read_as_a_name(self):
        self._ready()
        with self._quietly():
            self.window.file_actions.rename_page(1, '/books/Cover.png')
        self.assertEqual(self.window.file_actions.page_name(1), 'Cover.png')

    def test_a_name_that_says_nothing_renames_nothing(self):
        self._ready()
        before = self.window.file_actions.page_name(1)
        self.assertIsNone(self.window.file_actions.rename_page(1, '   '))
        self.assertIsNone(self.window.file_actions.rename_page(1, before))
        self.assertEqual(self.window.file_actions.page_name(1), before)

    def test_the_archive_is_written_with_the_name_that_was_given(self):
        source = self._movable_book()
        self._ready()
        with self._quietly():
            self.window.file_actions.rename_page(1, 'Cover.jpg')
        self.assertTrue(self.window.file_actions.save_archive())
        self._pump()

        with zipfile.ZipFile(source) as written:
            names = written.namelist()
        self.assertIn('Cover.jpg', names)
        self.assertEqual(len([name for name in names
                              if image_tools.is_image_file(name)]),
                         len(self._pages()))

    def test_closing_the_book_forgets_the_names(self):
        self._ready()
        with self._quietly():
            self.window.file_actions.rename_page(1, 'Cover.png')
        # A name that has not been written is offered to be written
        # before the book closes; this is the book closing all the same.
        self._remember_answer(Response.NO)
        self.window.filehandler.close_file()
        self._pump()
        self.assertEqual(self.window.file_actions.page_names(), {})

    def test_the_menu_offers_to_rename_the_page(self):
        self.assertIn('win.rename-page-popup',
                      self._menu_actions(self.window.uimanager.popup
                                         .get_menu_model()))

    def test_the_rename_dialog_offers_the_name_with_the_stem_picked_out(self):
        """A file manager leaves the extension out of what it selects,
        so that typing replaces the name and keeps the kind."""
        self._ready()
        self.window.popup_page = 1
        name = self.window.file_actions.page_name(1)

        self.window.file_actions.rename_popup_page()
        self._pump()

        dialogs = self._delete_dialogs()
        self.assertEqual(len(dialogs), 1, 'nothing asked for a name')
        entries = [child
                   for child in self._children(dialogs[0].get_content_area())
                   if isinstance(child, Gtk.Entry)]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].get_text(), name)
        self.assertEqual(entries[0].get_selection_bounds(),
                         (0, len(os.path.splitext(name)[0])),
                         'the extension is selected as well')
        for dialog in dialogs:
            dialog.destroy()
        self._pump()

    def test_renaming_a_loose_image_renames_the_file_on_disk(self):
        """A book read as a folder of images has no archive to write,
        so the rename happens at once."""
        directory = os.path.join(self.tmp_dir, 'loose')
        os.makedirs(directory)
        for number in range(3):
            shutil.copy(get_testfile_path('images', 'blue.png'),
                        os.path.join(directory, '%d.png' % number))
        self.window.filehandler.open_file(
            os.path.join(directory, '0.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 3,
            seconds=20))

        self.assertEqual(self.window.file_actions.rename_page(1, 'Cover.png'),
                         'Cover.png')
        self._pump()

        self.assertTrue(os.path.isfile(os.path.join(directory, 'Cover.png')))
        self.assertFalse(os.path.exists(os.path.join(directory, '0.png')))
        self.assertEqual(self.window.file_actions.page_name(1), 'Cover.png')

    def test_a_loose_image_is_not_renamed_over_another_file(self):
        directory = os.path.join(self.tmp_dir, 'loose2')
        os.makedirs(directory)
        for number in range(3):
            shutil.copy(get_testfile_path('images', 'blue.png'),
                        os.path.join(directory, '%d.png' % number))
        self.window.filehandler.open_file(
            os.path.join(directory, '0.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 3,
            seconds=20))

        self.assertIsNone(self.window.file_actions.rename_page(1, '1.png'))
        self._pump()

        self.assertTrue(os.path.isfile(os.path.join(directory, '0.png')))
        self.assertEqual(len(self._delete_dialogs()), 1,
                         'nothing said why the page was not renamed')
        for dialog in self._delete_dialogs():
            dialog.destroy()
        self._pump()

    def test_a_loose_image_is_renamed_to_its_own_name_in_other_case(self):
        """On a file system that ignores case - Windows', and macOS' by
        default - the new name of a page renamed to 0.PNG from 0.png is
        there already: it is the file itself.  The rename was refused
        with "A file of that name is there already"."""
        directory = self._loose_book('case')

        def folded(path):
            """The entry that <path> names where case is ignored."""
            wanted = os.path.basename(path).casefold()
            parent = os.path.dirname(path)
            if not os.path.isdir(parent):
                return None
            for entry in os.listdir(parent):
                if entry.casefold() == wanted:
                    return os.path.join(parent, entry)
            return None

        with unittest.mock.patch(
                'os.path.lexists',
                side_effect=lambda path: folded(path) is not None), \
                unittest.mock.patch(
                    'os.path.samefile',
                    side_effect=lambda one, two: folded(one) == folded(two)):
            renamed = self.window.file_actions.rename_page(1, '0.PNG')
        self._pump()

        self.assertEqual(renamed, '0.PNG')
        self.assertEqual(sorted(os.listdir(directory)),
                         ['0.PNG', '1.png', '2.png'])
        self.assertEqual(self._delete_dialogs(), [])

    # -- Renaming to a name another page holds ----------------------------

    def _loose_book(self, name, pages=3):
        """Open a directory of <pages> images, and answer with its path."""
        directory = os.path.join(self.tmp_dir, name)
        os.makedirs(directory)
        for number in range(pages):
            shutil.copy(get_testfile_path('images', 'blue.png'),
                        os.path.join(directory, '%d.png' % number))
        self.window.filehandler.open_file(os.path.join(directory, '0.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == pages,
            seconds=20), 'the folder of images never opened')
        return directory

    def test_a_page_that_will_not_load_is_drawn_as_large_as_a_page(self):
        """The picture for a page that would not load was drawn at 24
        pixels and shown at that size, or scaled up from it into a
        blur where small pages are enlarged; the library and the
        thumbnails drew it at the size they show it at."""
        directory = self._loose_book('broken-page', pages=2)
        with open(os.path.join(directory, '0.png'), 'wb') as damaged:
            damaged.write(b'not an image')
        prefs['stretch'] = False
        with unittest.mock.patch.object(
                image_tools, 'missing_image_icon',
                wraps=image_tools.missing_image_icon) as drawn:
            self.window.filehandler.refresh_file()
            self._pump()
            self.window.set_page(1)
            self.window.draw_image()
            self._pump()
        shown = self.window.images[0].get_paintable()
        height = shown.get_intrinsic_height()
        self.assertGreater(height, 200,
                           'the picture was shown at the size of an icon')
        self.assertIn(height, [call.args[1] for call in drawn.call_args_list
                               if len(call.args) == 2],
                      'the picture was scaled rather than drawn at its size')

    def _rename_dialog(self, page=1):
        """Open the rename dialog on <page> and answer with it."""
        self.window.popup_page = page
        self.window.file_actions.rename_popup_page()
        self._pump()
        dialogs = self._delete_dialogs()
        self.assertEqual(len(dialogs), 1, 'nothing asked for a name')
        return dialogs[0]

    def _typed_in(self, dialog, name):
        """Type <name> into the dialog's entry."""
        entries = [child
                   for child in self._children(dialog.get_content_area())
                   if isinstance(child, Gtk.Entry)]
        self.assertEqual(len(entries), 1)
        entries[0].set_text(name)

    @staticmethod
    def _warning_line(dialog):
        """The line the dialog warns on, whether or not it is shown."""
        return [child for child in dialog.get_content_area()
                if child.has_css_class('warning')]

    def test_a_name_another_page_holds_is_warned_about(self):
        """It was taken without a word, and the packer put an
        underscore in front of it when the book was written."""
        self._ready()
        held = self.window.file_actions.page_name(2)
        dialog = self._rename_dialog()
        try:
            warnings = self._warning_line(dialog)
            self.assertEqual(len(warnings), 1, 'the dialog has no warning line')
            self.assertFalse(warnings[0].get_visible(),
                             'it warned about the name the page has')
            self._typed_in(dialog, held)
            self.assertTrue(warnings[0].get_visible(),
                            'the name was taken without a word')
            told = [child for child in warnings[0]
                    if isinstance(child, Gtk.Label)]
            self.assertEqual(len(told), 1)
            self.assertIn(held, told[0].get_text())
        finally:
            dialog.destroy()
            self._pump()

    def test_a_name_another_page_holds_offers_a_swap_and_a_replace(self):
        self._ready()
        held = self.window.file_actions.page_name(2)
        dialog = self._rename_dialog()
        try:
            renames = dialog.get_widget_for_response(Response.OK)
            swaps = dialog.get_widget_for_response(
                rename_dialog.SWAP)
            replaces = dialog.get_widget_for_response(
                rename_dialog.REPLACE)
            self.assertTrue(renames.get_visible())
            self.assertFalse(swaps.get_visible())
            self.assertFalse(replaces.get_visible())

            self._typed_in(dialog, held)
            self.assertFalse(renames.get_visible(),
                             'it still offered to take a name twice over')
            self.assertTrue(swaps.get_visible())
            self.assertTrue(replaces.get_visible())
            self.assertIs(dialog.get_default_widget(),
                          dialog.get_widget_for_response(Response.CANCEL),
                          'Enter would have written a page over')

            self._typed_in(dialog, 'Cover.png')
            self.assertTrue(renames.get_visible(),
                            'the warning outlived the name that earned it')
            self.assertFalse(swaps.get_visible())
            self.assertFalse(self._warning_line(dialog)[0].get_visible())
        finally:
            dialog.destroy()
            self._pump()

    def test_swapping_the_names_gives_each_page_the_others(self):
        self._ready()
        names = self.window.file_actions
        first, second = names.page_name(1), names.page_name(2)
        with self._quietly():
            self.assertTrue(names.swap_page_names(1, second))
        self.assertEqual(names.page_name(1), second)
        self.assertEqual(names.page_name(2), first)

    def test_replacing_takes_the_page_that_held_the_name_out(self):
        """Two pages cannot both be called one name, so the page
        written over leaves the book, as an overwritten file does."""
        before = self._ready()
        names = self.window.file_actions
        held = names.page_name(2)
        with self._quietly():
            self.assertTrue(names.replace_page_named(1, held))
        self._pump()
        self.assertEqual(self._pages(), [before[0]] + before[2:])
        self.assertEqual(names.page_name(1), held)
        self.assertTrue(names.can_undo(), 'the page cannot be brought back')

    def test_a_name_no_page_holds_is_neither_swapped_nor_replaced(self):
        self._ready()
        names = self.window.file_actions
        self.assertFalse(names.swap_page_names(1, 'Nobody.png'))
        self.assertFalse(names.replace_page_named(1, 'Nobody.png'))
        self.assertEqual(names.page_names(), {})

    def test_the_dialog_answers_reach_the_swap_and_the_replace(self):
        self._ready()
        names = self.window.file_actions
        with unittest.mock.patch.object(names, 'swap_page_names') as swapped:
            names._rename_answered(rename_dialog.SWAP,
                                   1, 'Held.png')
        swapped.assert_called_once_with(1, 'Held.png')
        with unittest.mock.patch.object(names,
                                        'replace_page_named') as replaced:
            names._rename_answered(rename_dialog.REPLACE,
                                   1, 'Held.png')
        replaced.assert_called_once_with(1, 'Held.png')

    def test_swapping_the_names_of_a_loose_book_renames_both_files(self):
        """A book read as a folder of images has no archive to write,
        so both files change their names at once - through a third
        name, neither file being written over."""
        directory = self._loose_book('swap-names')
        names = self.window.file_actions
        self.assertTrue(names.swap_page_names(1, '1.png'))
        self._pump()
        self.assertEqual(self._pages()[:2],
                         [os.path.join(directory, '1.png'),
                          os.path.join(directory, '0.png')])
        for name in ('0.png', '1.png', '2.png'):
            self.assertTrue(os.path.isfile(os.path.join(directory, name)),
                            '%s is gone' % name)
        self.assertEqual(
            [name for name in os.listdir(directory)
             if not name.endswith('.png')], [],
            'the name a file was put aside under was left behind')

    def _swap_failing_at(self, directory, failing):
        """Swap the names of the first two pages while the first rename
        for which <failing> says True raises, and return what is left."""
        rename = os.rename
        failed = []

        def _rename(source, target):
            if not failed and failing(source, target):
                failed.append(source)
                raise PermissionError(13, 'Permission denied', source)
            rename(source, target)

        with self._quietly(), \
                unittest.mock.patch('os.rename', _rename):
            self.assertFalse(
                self.window.file_actions.swap_page_names(1, '1.png'))
        return sorted(os.listdir(directory))

    def test_a_swap_whose_last_rename_fails_puts_both_files_back(self):
        """The file put aside went back only when its own name was free,
        and the page's file was only moved off that name afterwards, so
        it stayed under the name it was put aside under."""
        directory = self._loose_book('swap-fails-last')
        before = sorted(os.listdir(directory))
        left = self._swap_failing_at(
            directory,
            lambda source, target: source.endswith('.mcomix-swap'))
        self.assertEqual(before, left)

    def test_a_swap_whose_second_rename_fails_puts_both_files_back(self):
        directory = self._loose_book('swap-fails-second')
        before = sorted(os.listdir(directory))
        left = self._swap_failing_at(
            directory,
            lambda source, target: source.endswith('0.png'))
        self.assertEqual(before, left)

    def test_a_swap_whose_first_rename_fails_leaves_both_files_alone(self):
        directory = self._loose_book('swap-fails-first')
        before = sorted(os.listdir(directory))
        pages = self._pages()
        left = self._swap_failing_at(
            directory,
            lambda source, target: target.endswith('.mcomix-swap'))
        self.assertEqual(before, left)
        self.assertEqual(pages, self._pages())

    def test_a_replace_that_fails_puts_the_page_it_took_out_back(self):
        """The page that held the name is taken out to make room; a
        rename the file system refuses leaves the name where it was,
        so the page comes back."""
        directory = self._loose_book('replace-fails')
        before = sorted(os.listdir(directory))
        pages = self._pages()
        refused = PermissionError(13, 'Permission denied')
        with self._quietly(), \
                unittest.mock.patch('os.replace', side_effect=refused):
            self.assertFalse(
                self.window.file_actions.replace_page_named(1, '1.png'))
        self._pump()
        self.assertEqual(before, sorted(os.listdir(directory)))
        self.assertEqual(pages, self._pages())

    def test_a_rename_the_file_system_refuses_renames_nothing(self):
        directory = self._loose_book('rename-fails')
        before = sorted(os.listdir(directory))
        refused = PermissionError(13, 'Permission denied')
        with unittest.mock.patch('os.rename', side_effect=refused):
            self.assertIsNone(
                self.window.file_actions.rename_page(1, 'Cover.png'))
        self._pump()
        self.assertEqual(before, sorted(os.listdir(directory)))
        self.assertEqual('0.png', self.window.file_actions.page_name(1))

    def test_replacing_a_page_of_a_loose_book_writes_over_the_file(self):
        directory = self._loose_book('replace-names')
        names = self.window.file_actions
        self.assertTrue(names.replace_page_named(1, '1.png'))
        self._pump()
        self.assertFalse(os.path.exists(os.path.join(directory, '0.png')),
                         'the page kept its own file as well')
        self.assertEqual(sorted(os.listdir(directory)), ['1.png', '2.png'])
        self.assertEqual(self._pages(),
                         [os.path.join(directory, '1.png'),
                          os.path.join(directory, '2.png')])

    # -- Swapping two pages -----------------------------------------------

    def test_marking_a_page_and_another_swaps_the_two(self):
        """Two pages change places in the book being read; the archive
        on disk is not touched until it is saved."""
        before = self._ready()
        with self._quietly():
            self.window.mark_for_swap(1)
            self.assertEqual(self.window.swap_page, 1)
            self.window.mark_for_swap(3)
        self._pump()

        self.assertIsNone(self.window.swap_page, 'the mark stayed behind')
        self.assertEqual(self._pages(),
                         [before[2], before[1], before[0]] + before[3:])

    def test_marking_the_marked_page_again_takes_the_mark_off(self):
        before = self._ready()
        self.window.mark_for_swap(2)
        self.window.mark_for_swap(2)
        self._pump()

        self.assertIsNone(self.window.swap_page)
        self.assertEqual(self._pages(), before, 'the book changed anyway')

    def test_a_swap_can_be_undone(self):
        before = self._ready()
        with self._quietly():
            self.window.mark_for_swap(1)
            self.window.mark_for_swap(2)
        self._pump()
        self.assertNotEqual(self._pages(), before)

        self.window.file_actions.undo()
        self._pump()
        self.assertEqual(self._pages(), before)

    def test_a_page_picked_out_goes_with_it_when_it_is_swapped(self):
        """A page is picked out for its file, not for its number."""
        before = self._ready()
        self.window.select_page(1)
        with self._quietly():
            self.window.file_actions.swap_pages(1, 3)
        self._pump()

        self.assertEqual(self.window.selected_pages, {3})
        self.assertEqual(self.window.selected_page_paths(), [before[0]])

    def test_a_swap_with_a_page_that_is_not_there_changes_nothing(self):
        before = self._ready()
        self.assertFalse(self.window.file_actions.swap_pages(1, 99))
        self.assertFalse(self.window.file_actions.swap_pages(2, 2))
        self._pump()
        self.assertEqual(self._pages(), before)

    def test_the_mark_is_drawn_on_the_page_it_stands_on(self):
        self._ready()
        self.window.set_page(1)
        self._pump()
        self.window.mark_for_swap(1)
        self._pump()

        self.assertTrue(self.window.images[0].has_css_class(
            main.MainWindow._MARKED_CLASS), 'the mark is not drawn')
        self.window.mark_for_swap(1)
        self._pump()
        self.assertFalse(self.window.images[0].has_css_class(
            main.MainWindow._MARKED_CLASS), 'the mark is still drawn')

    def test_closing_the_book_forgets_the_mark(self):
        self._ready()
        self.window.mark_for_swap(2)
        self.window.filehandler.close_file()
        self._pump()
        self.assertIsNone(self.window.swap_page)

    def test_control_and_shift_and_a_click_mark_the_page_under_it(self):
        """Ctrl and a click picks a page out; Ctrl, Shift and a click
        marks it to be swapped. The point of the test is that the one
        gesture is not read as the other."""
        self._ready()

        self._click(Gdk.ModifierType.CONTROL_MASK
                    | Gdk.ModifierType.SHIFT_MASK)

        self.assertEqual(self.window.swap_page, 1)
        self.assertEqual(self.window.selected_pages, set(),
                         'it picked the page out as well')
        self.assertEqual(self.window.imagehandler.get_current_page(), 1,
                         'the page was turned as well as marked')

    # -- The right-click menu from the keyboard ---------------------------

    def test_the_context_menu_action_opens_the_menu_over_the_page(self):
        """With the menu bar hidden the popup is the only menu there is,
        and it opened for a right click and nothing else.  A key press
        carries no position, so the page it acts on is the one on
        screen."""
        self._ready()
        self.window.set_page(2)
        self._pump()
        self.assertFalse(self.window.popup.get_visible())
        hold_open(self.window.popup)

        self.window.event_handler._open_popup_menu()
        self._pump()

        self.assertTrue(self.window.popup.get_visible(),
                        'the menu did not open')
        self.assertEqual(self.window.popup_page,
                         self.window.imagehandler.get_current_page())
        self.window.popup.popdown()
        self._pump()

    def test_the_context_menu_is_bound_to_the_keys_that_ask_for_one(self):
        manager = keybindings.keybinding_manager(self.window)
        self.assertEqual(
            [Gtk.accelerator_name(*binding)
             for binding in manager.get_bindings_for_action('popup_menu')],
            ['Menu', '<Shift>F10'])

    # -- Saving a page out of the book ------------------------------------

    def test_a_page_that_could_not_be_saved_says_so(self):
        """A copy that failed was logged and nothing more, so the reader
        was left with a dialog that had closed and no page where they
        had asked for one."""
        self._ready()
        page = self.window.imagehandler.get_path_to_page(1)
        self.assertIsNotNone(page)
        # Whether the page is out of the archive does not matter here:
        # the folder it would be copied into is not there either way.
        before = prefs['path of last saved in filechooser']
        # A folder that is not there: the copy raises, as it would on a
        # folder that cannot be written to or has no room left.
        target = os.path.join(self.tmp_dir, 'nowhere', 'page.png')

        self.window.file_actions._save_page_to(page, target)
        self._pump()

        self.assertEqual(len(self._delete_dialogs()), 1,
                         'nothing said why the page was not saved')
        self.assertEqual(prefs['path of last saved in filechooser'], before,
                         'a save that failed moved where the next starts')
        for dialog in self._delete_dialogs():
            dialog.destroy()
        self._pump()

    def test_a_page_saved_where_there_is_no_room_says_how_large_it_is(self):
        self._ready()
        self.assertTrue(
            wait_for(lambda: self.window.imagehandler.page_is_available(1),
                     seconds=20),
            'page 1 never came out of the archive')
        page = self.window.imagehandler.get_path_to_page(1)
        full = OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        with unittest.mock.patch.object(file_actions.shutil, 'copy2',
                                        side_effect=full):
            self.window.file_actions._save_page_to(
                page, os.path.join(self.tmp_dir, 'saved.png'))
        self._pump()
        dialogs = self._delete_dialogs()
        self.assertEqual(1, len(dialogs),
                         'nothing said why the page was not saved')
        self.addCleanup(dialogs[0].destroy)
        self.assertEqual('There is not enough room there: the file is %s.'
                         % tools.format_byte_size(os.path.getsize(page)),
                         dialogs[0]._secondary.get_text())

    def test_a_page_that_was_saved_says_nothing(self):
        self._ready()
        # The listing says the page is there; the extractor says the
        # file is. Without the wait this test saved a page that was not
        # out of the archive yet, and failed about one run in eight.
        self.assertTrue(
            wait_for(lambda: self.window.imagehandler.page_is_available(1),
                     seconds=20),
            'page 1 never came out of the archive')
        page = self.window.imagehandler.get_path_to_page(1)
        target = os.path.join(self.tmp_dir, 'saved.png')

        self.window.file_actions._save_page_to(page, target)
        self._pump()

        self.assertTrue(os.path.isfile(target))
        self.assertEqual(self._delete_dialogs(), [])

    def test_the_right_click_menu_offers_the_archive_editor(self):
        """The editor was on the Edit menu and nowhere else, so a reader
        with the menu bar hidden - which the right-click menu is there
        for - had no way to reach it at all."""
        self.assertIn('win.edit-archive',
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
        self.window.file_actions.extract_popup_page()
        self._pump()
        dialogs = self._save_dialogs()
        self.assertEqual(1, len(dialogs), 'no save dialog was opened')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                self.assertEqual(dialogs[0].filechooser.get_current_name(),
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
            scrolled_x, scrolled_y = self.window.scroll_offset()
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

    def test_the_page_count_on_screen_is_how_many_pages_are_shown(self):
        """displayed_page_count() sizes every caller that asks for what
        is on screen - the pixbufs to draw, the page numbers in the
        title, the colour read off the pages - so it has to agree with
        the page widgets that are really visible."""
        self.assertTrue(
            wait_for(lambda:
                     self.window.imagehandler.get_number_of_pages() > 1),
            'the archive was never listed')

        def shown():
            return sum(image.get_visible() for image in self.window.images)

        # The first page of an archive stands alone, as its cover.
        self.assertFalse(self.window.displayed_double())
        self.assertEqual(1, self.window.displayed_page_count())
        self.assertTrue(wait_for(lambda: shown() == 1),
                        'the cover was never the only page on screen')

        prefs['default double page'] = True
        try:
            self.window.set_page(2)
            self.assertTrue(self.window.displayed_double())
            self.assertEqual(2, self.window.displayed_page_count())
            self.assertTrue(wait_for(lambda: shown() == 2),
                            'the second page was never shown beside the first')
        finally:
            prefs['default double page'] = False

        self.window.draw_image()
        self.assertEqual(1, self.window.displayed_page_count())
        self.assertTrue(wait_for(lambda: shown() == 1),
                        'the second page was never taken off screen')

    def test_manga_mode_numbers_a_double_page_in_reading_order(self):
        """The status bar lists the file names, the sizes and the
        resolutions of a double page right to left in manga mode.  The
        page numbers in the same bar, and in the window title, are the
        same two pages and are listed the same way round."""
        self.assertTrue(
            wait_for(lambda:
                     self.window.imagehandler.get_number_of_pages() > 2),
            'the archive was never listed')
        prefs['default double page'] = True
        try:
            self.window.set_page(2)
            self.assertTrue(
                wait_for(lambda: self.window.imagehandler.
                         get_path_to_page(3) is not None),
                'the second page never arrived')

            self.window.is_manga_mode = False
            self.window._update_page_information()
            self.assertEqual('2,3 / 4', self.window.statusbar.get_page_number())
            self.assertIn('[2,3 / 4]', self.window.get_title())

            self.window.is_manga_mode = True
            self.window._update_page_information()
            self.assertEqual('3,2 / 4', self.window.statusbar.get_page_number())
            self.assertIn('[3,2 / 4]', self.window.get_title())
            self.assertEqual(
                ', '.join(reversed(
                    [os.path.basename(self.window.imagehandler
                                      .get_path_to_page(page))
                     for page in (2, 3)])),
                self.window.statusbar._filename,
                'the file names and the page numbers disagree on the order')
        finally:
            self.window.is_manga_mode = False
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

    def test_quitting_does_not_wait_for_the_page_that_is_animating(self):
        """An animated page is decoded by a daemon thread which runs
        until the page it draws is replaced or cleared.  Quitting waited
        for every live thread, and it clears no page, so an MComix
        showing an animation never got as far as leaving.
        """
        pixbuf = image_tools.load_pixbuf(
            get_testfile_path('images', 'animated.gif'))
        image = self.window.images[0]
        image.show_pixbuf(pixbuf)
        self.assertIsNotNone(image._worker, 'nothing is decoding the page')
        # Stop the decoder anyway if quitting does wait for it, so that a
        # regression fails this test rather than hanging the whole suite.
        # Setting the event is what asks the thread to go, and it is the
        # one part of the widget another thread may touch.
        watchdog = threading.Timer(10.0, image._stopping.set)
        # And nothing waits for the watchdog itself, which is a thread
        # like any other and would be the next thing quitting waits for.
        watchdog.daemon = True
        watchdog.start()
        started = time.monotonic()
        try:
            self.window.terminate_program()
        finally:
            watchdog.cancel()
        waited = time.monotonic() - started
        # Leave nothing decoding behind: a thread that outlives its test
        # goes on drawing frames for the rest of the run, and is joined
        # by whatever quits next.
        image.clear()
        self.assertLess(waited, 5.0,
                        'quitting waited for the animation to end')

    def test_the_window_holds_the_expected_parts(self):
        for part in (self.window.menubar, self.window.toolbar,
                     self.window.statusbar, self.window.thumbnailsidebar):
            self.assertIsNotNone(part.get_parent(),
                                 '%r was never packed' % part)

    def test_the_window_answers_gtks_own_question_about_fullscreen(self):
        # A property of the same name shadowed Gtk.Window.is_fullscreen(),
        # so calling the method GTK4 provides raised TypeError: the
        # property had already answered with a bool.
        self.assertIs(False, self.window.is_fullscreen())

    def test_the_cursor_of_the_page_area_is_set_through_its_own_method(self):
        # set_cursor() is Gtk.Widget's in GTK4 and puts the cursor on the
        # widget it is called on; MComix wants it on the page area, which
        # is what set_layout_cursor() says.
        cursor = Gdk.Cursor.new_from_name('wait', None)
        self.window.set_layout_cursor(cursor)
        self.assertIs(cursor, self.window.page_area.get_cursor())
        self.window.set_layout_cursor(None)
        self.assertIsNone(self.window.page_area.get_cursor())

    # -- What a pending redraw does with a later scroll --------------------
    #
    # draw_image() coalesces redraws onto one idle callback.  It used to
    # drop the whole call, scroll destination and all, so a page turn
    # landing on the redraw some toggled widget had scheduled opened
    # wherever the page before it had been left.

    def _watch_scrolls(self):
        """Collect what _draw_image() asks the layout to scroll to."""
        wait_for(lambda: self.window.imagehandler.page_is_available(),
                 seconds=20)
        scrolls = []
        self.window.scroll_to_predefined = (
            lambda destination, index=None:
            scrolls.append((tuple(destination), index)))
        return scrolls

    def test_a_pending_redraw_does_not_swallow_a_scroll_destination(self):
        scrolls = self._watch_scrolls()
        self.window.draw_image()
        self.window.draw_image(scroll_to=constants.SCROLL_TO_END)
        self._pump()
        self.assertEqual([((constants.SCROLL_TO_END,) * 2,
                           constants.LAST_INDEX)], scrolls)

    def test_the_last_scroll_destination_asked_for_is_the_one_used(self):
        scrolls = self._watch_scrolls()
        self.window.draw_image(scroll_to=constants.SCROLL_TO_END)
        self.window.draw_image(scroll_to=constants.SCROLL_TO_START)
        self._pump()
        self.assertEqual([((constants.SCROLL_TO_START,) * 2,
                           constants.FIRST_INDEX)], scrolls)

    def test_a_scroll_destination_is_not_used_again_by_the_next_redraw(self):
        scrolls = self._watch_scrolls()
        self.window.draw_image(scroll_to=constants.SCROLL_TO_END)
        self._pump()
        self.window.draw_image()
        self._pump()
        self.assertEqual(1, len(scrolls))

    def test_a_redraw_while_a_page_is_coming_keeps_where_it_opens(self):
        """The destination waited with the page, and any redraw in the
        meantime - a resize, a toggled statusbar - replaced it with
        none, so the page opened where the one before had been left."""
        wait_for(self.window.imagehandler.page_is_available, seconds=10)
        self._pump()
        with unittest.mock.patch.object(
                self.window.imagehandler, 'page_is_available',
                return_value=False):
            self.window.draw_image(scroll_to=constants.SCROLL_TO_END)
            self._pump()
            self.window.draw_image()
            self._pump()
        with unittest.mock.patch.object(
                self.window, 'scroll_to_predefined') as scrolled:
            self.window._page_available(
                self.window.imagehandler.get_current_page())
            self._pump()
        self.assertTrue(scrolled.called, 'the arriving page was not scrolled')
        self.assertEqual((constants.SCROLL_TO_END,) * 2,
                         tuple(scrolled.call_args[0][0]))


class RestartTest(MComixTest):

    """Starting MComix again, which is how a new language is shown."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        # What restart_program() has to get right is the order: the path
        # and the page are read while the file is still open, because
        # terminate_program() closes the file handler. These answer as a
        # closed handler would once the program has been closed.
        self.closed = []
        self.window.imagehandler.get_real_path = (
            lambda: None if self.closed else '/books/one.cbz')
        self.window.imagehandler.get_current_page = (
            lambda: 0 if self.closed else 7)
        self.window.close_program = lambda: self.closed.append('closed')
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def test_it_carries_the_book_and_its_page_over(self):
        with unittest.mock.patch.object(main.process,
                                        'launch_mcomix') as launch:
            self.window.restart_program()
        self.assertEqual(['closed'], self.closed)
        launch.assert_called_once_with('/books/one.cbz', 7)

    def test_the_program_is_closed_before_the_new_one_starts(self):
        """Two MComix writing the configuration files at once is a race
        of its own; closing first keeps them apart, and is also what
        writes the geometry the new window comes up with."""
        order = []
        self.window.close_program = lambda: order.append('closed')
        with unittest.mock.patch.object(
                main.process, 'launch_mcomix',
                side_effect=lambda *args: order.append('launched')):
            self.window.restart_program()
        self.assertEqual(['closed', 'launched'], order)


class ResumeAfterSaveAndQuitTest(MComixTest):

    """The next start after "Save and quit" opens the book at its page.

    The quit's half was tested - it sets the preference and keeps the
    window size - but nothing started a window afterwards to see what
    it made of the file the quit had written.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()

    def _window(self, path=None):
        window = main.MainWindow(open_path=path)
        main.set_main_window(window)
        self.addCleanup(self._close, window)
        return window

    @staticmethod
    def _close(window):
        window.terminate_program()
        window.destroy()
        main.set_main_window(None)
        pump()

    @staticmethod
    def _where(window):
        page = window.imagehandler.get_current_page()
        return page, window.imagehandler.get_page_filename(page)

    def _quit_and_start_again(self, path, page):
        """Open <path> at <page>, quit as "Save and quit" leaves things,
        and start a window with no file named; what that one shows."""
        window = self._window(path)
        self.assertTrue(wait_for(
            lambda: window.imagehandler.get_number_of_pages() >= page))
        window.set_page(page)
        pump()
        left = self._where(window)
        # What save_and_terminate_program() leaves, less the quit.
        prefs['previous quit was quit and save'] = True
        window.write_config_files()
        self._close(window)

        again = self._window()
        self.assertTrue(wait_for(
            lambda: again.imagehandler.get_number_of_pages() > 0))
        pump()
        self.assertFalse(prefs['previous quit was quit and save'])
        return left, self._where(again)

    def test_an_archive_opens_at_the_page_it_was_left_on(self):
        left, again = self._quit_and_start_again(
            get_testfile_path('archives', '01-ZIP-Normal.zip'), 3)
        self.assertEqual((3, '03-PNG-RGB.png'), left)
        self.assertEqual(left, again)

    def test_a_directory_opens_at_the_image_it_was_left_on(self):
        left, again = self._quit_and_start_again(
            get_testfile_path('images', 'portrait-no-exif.png'), 5)
        self.assertEqual(left, again)

    def test_a_plain_quit_before_it_opens_nothing(self):
        window = self._window(
            get_testfile_path('archives', '01-ZIP-Normal.zip'))
        self.assertTrue(wait_for(
            lambda: window.imagehandler.get_number_of_pages() > 0))
        window.write_config_files()
        self._close(window)
        again = self._window()
        pump()
        self.assertFalse(again.filehandler.file_loaded)


class InvertedColoursAtStartUpTest(MComixTest):

    """The action Ctrl+I inverts the colours with, on a window that
    starts with the preference already set.

    One main window at a time: building a second inside a live one hangs
    on the worker threads, so this starts its own rather than reusing
    MainWindowTest's.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        prefs['invert color'] = True
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def test_the_action_starts_as_inverted_as_the_pages(self):
        """The enhancer reads the preference, so an action that started
        off would make the first Ctrl+I set the colours to what they
        already were."""
        self.assertTrue(self.window.enhancer.invert_color)
        self.assertTrue(self.window.actiongroup.get_action(
            'invert_color').get_active())


class ZoomModeAtStartUpTest(MComixTest):

    """Which zoom modes a window passes through as it starts.

    Gtk.RadioAction only announced a change that changed something, so
    starting in manual mode - the value the radio group was built with -
    needed another mode activated first to make the callback run. The
    modes are one Gio.SimpleAction now, and activating it emits
    change-state whatever its current value is, so the detour is not
    needed; it ran change_zoom_mode() for a mode the reader had not
    asked for, wrote that mode into the preference and redrew.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        prefs['zoom mode'] = constants.ZoomMode.MANUAL
        self.seen = []
        original = main.MainWindow.change_zoom_mode

        def change_zoom_mode(window, radioaction=None, *args):
            original(window, radioaction, *args)
            self.seen.append(prefs['zoom mode'])

        main.MainWindow.change_zoom_mode = change_zoom_mode
        self.addCleanup(setattr, main.MainWindow, 'change_zoom_mode',
                        original)
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def test_manual_mode_is_reached_without_passing_through_another(self):
        self.assertEqual([constants.ZoomMode.MANUAL], self.seen,
                         'starting in manual mode changed the zoom mode '
                         'more than once')

    def test_the_preference_is_the_mode_it_started_in(self):
        self.assertEqual(constants.ZoomMode.MANUAL, prefs['zoom mode'])



class StartUpOptionsTest(MComixTest):

    """What the command line and the preferences ask of a window as it
    starts: each is an action activated once, so the menus show what
    is in effect."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        keybindings._manager = None

    def _start(self, **options):
        self.window = main.MainWindow(**options)
        main.set_main_window(self.window)
        self.addCleanup(self._close)
        pump()
        return self.window

    def _close(self):
        from mcomix.library import main_dialog
        main_dialog._close_dialog()
        if self.window.slideshow.is_running():
            self.window.actiongroup.get_action('slideshow').activate()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()

    def _active(self, name):
        return self.window.actiongroup.get_action(name).get_active()

    def test_the_command_line_options_are_in_effect(self):
        self._start(fullscreen=True, manga_mode=True, double_page=True,
                    zoom_mode=constants.ZoomMode.WIDTH)
        for name in ('fullscreen', 'manga_mode', 'double_page'):
            with self.subTest(action=name):
                self.assertTrue(self._active(name))
        self.assertEqual(constants.ZoomMode.WIDTH, prefs['zoom mode'])

    def test_a_slideshow_asked_for_starts_once_the_book_is_open(self):
        """"mcomix --slideshow book.cbz" started no slideshow: the action
        was activated as the window was built, while the book was still
        being read, and an action is not usable without a book open."""
        self._start(open_path=get_testfile_path('archives',
                                                '01-ZIP-Normal.zip'),
                    is_slideshow=True)
        self.assertTrue(wait_for(lambda: self.window.filehandler.file_loaded))
        pump()
        self.assertTrue(self.window.slideshow.is_running())
        self.assertTrue(self._active('slideshow'))
        # Once: the next book opened does not start it again.
        self.window.actiongroup.get_action('slideshow').activate()
        self.window.filehandler.open_file(
            get_testfile_path('images', 'blue.png'))
        self.assertTrue(wait_for(lambda: self.window.filehandler.file_loaded))
        pump()
        self.assertFalse(self.window.slideshow.is_running())

    def test_the_library_can_be_asked_for_at_start(self):
        from mcomix.library import main_dialog
        self._start(show_library=True)
        self.assertIsNotNone(main_dialog.get_dialog())

    def test_the_preferences_that_are_toggles_are_shown_on(self):
        for preference in ('stretch', 'invert smart scroll',
                           'keep transformation'):
            prefs[preference] = True
        prefs['rotation'] = 90
        self._start()
        for name in ('stretch', 'invert_scroll', 'keep_transformation'):
            with self.subTest(action=name):
                self.assertTrue(self._active(name))
        self.assertEqual(90, prefs['rotation'])

    def test_a_turn_is_forgotten_unless_it_is_to_be_kept(self):
        prefs['keep transformation'] = False
        prefs['rotation'] = 90
        prefs['horizontal flip'] = prefs['vertical flip'] = True
        self._start()
        self.assertEqual((0, False, False),
                         (prefs['rotation'], prefs['horizontal flip'],
                          prefs['vertical flip']))


class ResumeAtTheFileOfThePageTest(MComixTest):

    """A "quit and save" is resumed at the file of its page, where it
    was kept, rather than at the page number."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.terminate_program()
            self.window.destroy()
            main.set_main_window(None)
        pump()
        super().tearDown()

    def test_the_file_of_the_page_decides_over_its_number(self):
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        with open(constants.FILEINFO_PICKLE_PATH, 'wb') as stored:
            pickle.dump([path, 1], stored)
            pickle.dump('images/03-PNG-RGB.png', stored)
        prefs['previous quit was quit and save'] = True
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.assertTrue(wait_for(
            lambda: not self.window.filehandler.file_loading
            and self.window.imagehandler.page_is_available(), seconds=20))
        self.assertEqual(3, self.window.imagehandler.get_current_page())

# vim: expandtab:sw=4:ts=4
