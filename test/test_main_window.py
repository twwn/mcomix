""" A window that actually starts, with its parts where they belong.

Most of the suite exercises pieces in isolation; nothing else builds the
real window, which is where a whole class of start-up regressions hides.
"""

import os
import shutil
import threading
import time
import warnings

from gi.repository import Gdk, Gio, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import dialog as dialog_module
from mcomix import file_chooser_simple_dialog as simple_chooser
from mcomix import icons
from mcomix import image_tools
from mcomix import main
from mcomix import message_dialog
from mcomix.preferences import prefs


class MainWindowTest(MComixTest):

    def setUp(self):
        super().setUp()
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

        self.window.extract_page()
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
        self.window.delete()
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

    def test_the_menu_item_says_what_the_colours_do(self):
        """The enhance dialog sets the enhancer directly, so the item
        and the enhancer can fall out of step; using the item then has
        to bring them together rather than invert whatever the enhancer
        happened to hold."""
        action = self.window.actiongroup.get_action('invert_color')
        self.assertFalse(action.get_active())
        # What ticking "Invert colours" in the enhance dialog does.
        self.window.enhancer.invert_color = True
        action.set_active(True)
        self._pump()
        self.assertTrue(self.window.enhancer.invert_color,
                        'the menu says inverted and the pages are not')
        self.assertTrue(prefs['invert color'])
        action.set_active(False)
        self._pump()
        self.assertFalse(self.window.enhancer.invert_color)
        self.assertFalse(prefs['invert color'])

    def test_showing_a_toggle_as_on_does_not_run_it(self):
        """What the start-up sync needs: the tick moves, the colours
        are left alone because they are already what it says."""
        action = self.window.actiongroup.get_action('invert_color')
        action.show_active(True)
        self._pump()
        self.assertTrue(action.get_active())
        self.assertFalse(self.window.enhancer.invert_color,
                         'showing the tick inverted the pages as well')

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
        self.window.extract_popup_page()
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
        self.assertIs(cursor, self.window._main_layout.get_cursor())
        self.window.set_layout_cursor(None)
        self.assertIsNone(self.window._main_layout.get_cursor())

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


class InvertedColoursAtStartUpTest(MComixTest):

    """The menu item for inverted colours, on a window that starts with
    the preference already set.

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

    def test_the_menu_item_says_the_colours_are_inverted(self):
        """The enhancer reads the preference, so a window whose item
        started unticked inverted the pages and said it did not."""
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

# vim: expandtab:sw=4:ts=4
