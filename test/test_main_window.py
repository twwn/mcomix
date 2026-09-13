""" A window that actually starts, with its parts where they belong.

Most of the suite exercises pieces in isolation; nothing else builds the
real window, which is where a whole class of start-up regressions hides.
"""

import contextlib
import os
import shutil
import threading
import zipfile
import time
import unittest.mock
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
from mcomix.dialog import Response
from mcomix.library import backend
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

    def test_asking_for_fullscreen_leaves_the_menu_item_usable(self):
        """change_fullscreen() used to make the item insensitive and rely
        on notify::fullscreened to put it back.  Nothing else re-enables
        it - 'fullscreen' is not one of the toggle actions
        _update_toggles_sensitivity() walks - so wherever the request is
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

    # -- Picking a page out, and deleting it ------------------------------

    def _pages(self):
        return list(self.window.imagehandler._image_files or [])

    def _quietly(self):
        """Delete a page without the prompt that offers to save."""
        return unittest.mock.patch.object(self.window, 'offer_to_save')

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
        handler = self.window._event_handler
        handler.mouse_press_event(self._Click(1), 1, x, y)
        handler.mouse_release_event(self._Click(1, state), 1, x, y)
        self._pump()

    def _wheel(self, delta_x, delta_y, state=0):
        self.window._event_handler.scroll_wheel_event(
            self._Scroll(state), delta_x, delta_y)
        self._pump()

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
    _WHEEL_TARGETS = ('_scroll_with_flipping', '_smart_scroll_up',
                      '_smart_scroll_down', '_next_page_with_protection',
                      '_previous_page_with_protection')

    def _wheel_dispatch(self, delta_x, delta_y, state=0):
        """Return what one wheel turn reached, as (name, args) pairs."""
        handler = self.window._event_handler
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
        self.assertEqual([('_scroll_with_flipping', (0, pixels))],
                         self._wheel_dispatch(0, 1))
        self.assertEqual([('_scroll_with_flipping', (0, -pixels))],
                         self._wheel_dispatch(0, -1))

    def test_the_wheel_scrolls_smartly_when_the_preference_says_so(self):
        prefs['smart scroll'] = True
        pixels = prefs['number of pixels to scroll per mouse wheel event']
        self.assertEqual([('_smart_scroll_down', (pixels,))],
                         self._wheel_dispatch(0, 1))
        self.assertEqual([('_smart_scroll_up', (pixels,))],
                         self._wheel_dispatch(0, -1))

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
        handler = self.window._event_handler
        turned = []
        with unittest.mock.patch.object(
                handler, '_flip_page',
                side_effect=lambda pages, **kwargs: turned.append(pages)):
            for manga in (False, True):
                self.window.is_manga_mode = manga
                handler._left_right_page_progress(1)
        self.assertEqual([1, -1], turned)

    def test_a_sideways_turn_is_a_page_either_way(self):
        """Nothing scrolls horizontally past the end of a page, so
        sideways never scrolls; which way round it reads depends on the
        book."""
        for manga, rightwards in ((False, '_next_page_with_protection'),
                                  (True, '_previous_page_with_protection')):
            self.window.is_manga_mode = manga
            self.assertEqual([(rightwards, ())], self._wheel_dispatch(1, 0))

    def test_a_diagonal_turn_is_read_as_a_vertical_one(self):
        """A wheel reporting both axes at once is the vertical one:
        sideways turns a page outright, so reading a diagonal nudge that
        way would jump the book about."""
        prefs['smart scroll'] = False
        pixels = prefs['number of pixels to scroll per mouse wheel event']
        self.assertEqual([('_scroll_with_flipping', (0, pixels))],
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

    def test_a_plain_click_turns_the_page_as_it_always_did(self):
        self._ready()
        self._click()
        self.assertEqual(self.window.imagehandler.get_current_page(), 2)
        self.assertEqual(self.window.selected_pages, set())

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
            self.assertTrue(self.window.delete_page())
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
            self.assertTrue(self.window.delete_page())
        self._pump()
        self.assertEqual(self._pages(), [before[1]] + before[3:])

    def test_the_pages_still_picked_out_move_up_with_the_book(self):
        """Removing a page moves every page after it up, and a number
        remembered against the old listing would name another page."""
        before = self._ready()
        self.window.select_page(1)
        self.window.select_page(3)
        with self._quietly():
            self.window.delete_page(2)
        self._pump()
        self.assertEqual(self._pages(), before[:1] + before[2:])
        self.assertEqual(self.window.selected_pages, {1, 2})
        self.assertEqual(self.window.selected_page_paths(),
                         [before[0], before[2]])

    def test_deleting_a_page_can_be_taken_back(self):
        before = self._ready()
        self.window.select_page(2)
        with self._quietly():
            self.window.delete_page()
        self._pump()
        self.assertTrue(self.window.undo())
        self._pump()
        self.assertEqual(self._pages(), before)
        self.assertTrue(self.window.redo())
        self._pump()
        self.assertEqual(self._pages(), before[:1] + before[2:])

    def test_there_is_nothing_to_take_back_before_a_page_goes(self):
        self.assertFalse(self.window.can_undo())
        self.assertFalse(self.window.can_redo())
        self.assertFalse(self.window.undo())
        self.assertFalse(self.window.redo())

    def test_a_deletion_after_an_undo_leaves_nothing_to_redo(self):
        self._ready()
        with self._quietly():
            self.window.select_page(1)
            self.window.delete_page()
            self._pump()
            self.window.undo()
            self._pump()
            self.window.select_page(2)
            self.window.delete_page()
        self._pump()
        self.assertFalse(self.window.can_redo())

    def test_the_last_page_of_a_book_is_not_deleted(self):
        """A book with no pages in it is not a book, and the editor
        leaves one standing too."""
        handler = self.window.imagehandler
        self.window.pages_replaced(self._ready()[:1])
        self._pump()
        self.assertEqual(handler.get_number_of_pages(), 1)
        self.window.select_page(1)
        with self._quietly():
            self.assertFalse(self.window.delete_page())
        self.assertEqual(handler.get_number_of_pages(), 1)

    def test_delete_removes_the_picked_out_page_rather_than_the_file(self):
        """Delete acts on a selection wherever there is one; with
        nothing picked out it still asks to remove the file."""
        before = self._ready()
        self.window.select_page(1)
        with self._quietly():
            self.window.delete()
        self._pump()
        self.assertEqual(self._pages(), before[1:])
        self.assertEqual(self._delete_dialogs(), [],
                         'it asked about the file as well')

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
        self.window.delete_page()
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
        self.window.delete_page()
        self._pump()
        try:
            prompt = self._save_prompts()[0]
            self.assertIs(prompt.get_default_widget(),
                          prompt.get_widget_for_response(Response.NO))
        finally:
            for dialog in self._save_prompts():
                dialog.destroy()
            self._pump()

    def test_a_book_in_a_format_that_cannot_be_written_is_not_offered(self):
        """Writing in place keeps the name the file has, so it has to
        keep the format that name says."""
        self._ready()
        with unittest.mock.patch.object(self.window.filehandler,
                                        'archive_type', constants.LHA):
            self.assertIsNone(self.window.writeable_archive_type())
            self.assertFalse(self.window.save_archive())
            self.window.select_page(2)
            self.window.delete_page()
            self._pump()
        self.assertEqual(self._save_prompts(), [],
                         'it offered to write a format it cannot write')

    def test_a_format_other_than_zip_needs_the_preference(self):
        """A save that kept the name and changed the format would put a
        ZIP inside a file still called .cbt."""
        self._ready()
        with unittest.mock.patch.object(self.window.filehandler,
                                        'archive_type', constants.TAR):
            prefs['keep archive format when saving'] = False
            self.assertIsNone(self.window.writeable_archive_type())
            prefs['keep archive format when saving'] = True
            self.assertEqual(self.window.writeable_archive_type(),
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
            self.window.delete_page()
        self._pump()
        print('DEBUG archive_type=%r base=%r can_write=%r pref=%r' % (
            self.window.filehandler.archive_type,
            self.window.filehandler.get_path_to_base(),
            self.window.writeable_archive_type(),
            prefs['keep archive format when saving']))
        self.assertTrue(self.window.save_archive(), 'the save failed')

        with zipfile.ZipFile(source) as written:
            pages = [name for name in written.namelist()
                     if not name.endswith('.txt')]
        self.assertEqual(len(pages), before - 1,
                         'the archive on disk still holds the page')
        self.assertEqual(os.stat(source).st_mode, mode,
                         'the archive came back with different permissions')

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
                unittest.mock.patch.object(main.archive_packer,
                                           'write_archive'):
            self.assertTrue(self.window.save_archive())

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

        self.assertTrue(self.window.save_archive(), 'the save failed')

        with zipfile.ZipFile(source) as written:
            self.assertEqual(
                [info.filename for info in written.infolist()
                 if info.is_dir()], [])

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
                     if not name.endswith('.txt')]
        self.assertEqual(len(pages), before - 2,
                         'the archive on disk still holds the pages')
        self.assertEqual(opened, [True], 'it did not go on to the next book')

    def test_the_right_click_menu_offers_to_delete_a_page(self):
        self.assertIn('win.delete-page-popup',
                      self._menu_actions(self.window.uimanager.popup
                                         .get_menu_model()))

    def test_the_right_click_menu_deletes_the_page_it_was_opened_over(self):
        before = self._ready()
        self.window.popup_page = 2
        with self._quietly():
            self.window.delete_popup_page()
        self._pump()
        self.assertEqual(self._pages(), before[:1] + before[2:])

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

        self.window.move_current_file(destination)
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

    def test_a_destination_moved_to_is_offered_next_time(self):
        self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)

        self.window.move_current_file(destination)
        self._pump()

        self.assertEqual(prefs['recent move destinations'], [destination])

    def test_the_library_follows_a_book_that_is_moved(self):
        source = self._movable_book()
        destination = os.path.join(self.tmp_dir, 'destination')
        os.makedirs(destination)
        library = backend.LibraryBackend()
        self.assertTrue(library.add_book(source))

        self.window.move_current_file(destination)
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

        self.window.move_current_file(destination)
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
