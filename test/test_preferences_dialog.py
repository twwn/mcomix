"""The preferences dialog, and the state its controls come up in.

A pair of radio buttons stands for one either/or preference. Two of them
were given a preference each instead, and the one the first button was
given is not a preference at all: nothing reads it, and reading the
preferences file drops what it does not know, so whatever the button
said went out with the wash.
"""

import contextlib
import os
import shutil
import unittest.mock

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump

from mcomix import constants
from mcomix import i18n
from mcomix import icons
from mcomix import keybindings
from mcomix import main
from mcomix import message_dialog
from mcomix import preferences_dialog
from mcomix import theme
from mcomix import image_tools
from mcomix.dialog import Response
from mcomix.preferences import prefs


class PreferencesDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    dialog = None

    def _open(self):
        self.dialog = preferences_dialog._PreferencesDialog(self.window)
        pump()
        return self.dialog

    def test_the_gap_between_two_pages_goes_up_to_the_largest_gap(self):
        """The spinner stopped at 2 pixels, too narrow a gutter to see."""
        bounds = {}
        original = preferences_dialog._PreferencesDialog._create_pref_spinner

        def record(dialog, prefkey, scale, lower, upper, *rest):
            bounds[prefkey] = (lower, upper)
            return original(dialog, prefkey, scale, lower, upper, *rest)

        with unittest.mock.patch.object(
                preferences_dialog._PreferencesDialog,
                '_create_pref_spinner', record):
            self._open()
        self.assertEqual((0, preferences_dialog.LARGEST_PAGE_GAP),
                         bounds['space between two pages'])
        self.assertEqual(100, preferences_dialog.LARGEST_PAGE_GAP)

    def _background_buttons(self):
        """The two buttons of the Background section, in the order they
        are shown: the fixed colour, then the one off the page."""
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.CheckButton):
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(self.dialog.notebook.get_nth_page(0))
        fixed = [button for button in found
                 if button.get_label() == 'Use this colour as background:']
        dynamic = [button for button in found
                   if button.get_label() == 'Use dynamic background colour']
        self.assertTrue(fixed and dynamic, 'the pair was not built')
        return fixed[0], dynamic[0]

    # -- What the pair shows ----------------------------------------------

    def test_a_spinner_stores_its_value_in_the_unit_of_the_preference(self):
        """Three spinners show another unit than the preference is kept
        in: the slideshow delay in seconds for milliseconds, the smart
        scroll step in per cent for a fraction, and the lens
        magnification with a decimal place.  Everything else is a whole
        number of pixels or pages."""
        dialog = self._open()
        for preference, shown, stored in (
                ('slideshow delay', 2.5, 2500),
                ('smart scroll percentage', 40, 0.4),
                ('lens magnification', 2.5, 2.5),
                ('thumbnail size', 120, 120),
                ('max pages to cache', -1, -1)):
            spinner = Gtk.SpinButton.new(
                Gtk.Adjustment.new(0, -10, 10000, 1, 10, 0), 0.0, 2)
            spinner.set_value(shown)
            dialog._spinner_cb(spinner, preference)
            self.assertEqual(prefs[preference], stored, preference)
            self.assertIs(type(prefs[preference]), type(stored), preference)

    def test_turning_pages_by_their_metadata_turns_the_thumbnails_too(self):
        """The sidebar's thumbnails are turned as the pages are, so
        changing the preference has to make them again, not only
        redraw the page."""
        dialog = self._open()
        button = Gtk.CheckButton(active=not prefs['auto rotate from exif'])
        with unittest.mock.patch.object(self.window.thumbnailsidebar,
                                        'resize') as remade:
            dialog._check_button_cb(button, 'auto rotate from exif')
        remade.assert_called_once_with()
        self.assertEqual(prefs['auto rotate from exif'], button.get_active())

    def test_reading_folders_with_the_ones_in_them_reopens_the_book(self):
        """The folder that is open gains or loses the pictures of the
        folders in it at once, not when it is next opened."""
        dialog = self._open()
        button = Gtk.CheckButton(active=True)
        with unittest.mock.patch.object(self.window.filehandler,
                                        'refresh_file') as reopened:
            dialog._check_button_cb(button, 'open folder tree as one book')
        reopened.assert_called_once_with()
        self.assertTrue(prefs['open folder tree as one book'])

    def test_turning_pages_by_their_metadata_forgets_the_drawn_covers(self):
        """The library's covers are kept as they were drawn, turned or
        not; with the library closed, the next one opened would have
        drawn them the old way from what was kept."""
        from mcomix.library import pixbuf_cache
        dialog = self._open()
        cache = pixbuf_cache.get_pixbuf_cache()
        cache.add('/books/kept.cbz', image_tools.missing_page())
        button = Gtk.CheckButton(active=not prefs['auto rotate from exif'])
        dialog._check_button_cb(button, 'auto rotate from exif')
        self.assertIsNone(cache.get('/books/kept.cbz'))

    def test_the_pair_shows_the_colour_the_preference_names(self):
        prefs['smart bg'] = False
        self._open()
        fixed, dynamic = self._background_buttons()
        self.assertTrue(fixed.get_active(),
                        'the dialog came up showing neither of the two')
        self.assertFalse(dynamic.get_active())

    def test_the_pair_shows_the_colour_off_the_page(self):
        prefs['smart bg'] = True
        self._open()
        fixed, dynamic = self._background_buttons()
        self.assertTrue(dynamic.get_active())
        self.assertFalse(fixed.get_active())

    # -- What picking one writes ------------------------------------------

    def test_picking_the_colour_off_the_page_is_remembered(self):
        prefs['smart bg'] = False
        self._open()
        _fixed, dynamic = self._background_buttons()
        dynamic.set_active(True)
        self.assertTrue(prefs['smart bg'])

    def test_picking_a_fixed_colour_is_remembered(self):
        prefs['smart bg'] = True
        self._open()
        fixed, _dynamic = self._background_buttons()
        fixed.set_active(True)
        self.assertFalse(prefs['smart bg'])

    def test_the_pair_writes_no_key_that_is_not_a_preference(self):
        """The first button had a key of its own, which is not a
        preference at all: nothing reads it, and reading the preferences
        file back drops every key it does not know."""
        known = set(prefs)
        self._open()
        fixed, dynamic = self._background_buttons()
        for button in (fixed, dynamic, fixed):
            button.set_active(True)
        self.assertEqual(set(prefs) - known, set())

    # -- The colour the fixed button stands beside -------------------------

    def _colour_buttons(self):
        """The colour buttons of the Background section, in the order
        they are shown: the page background, then the thumbnails'."""
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.ColorDialogButton):
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(self.dialog.notebook.get_nth_page(0))
        self.assertTrue(found, 'no colour button was built')
        return found

    def test_picking_a_background_colour_is_remembered(self):
        """Gtk.ColorButton said 'color-set' once a colour had been
        picked.  What replaced it says nothing of the kind: the colour
        arrives as a change to the rgba property, and a button left
        listening for the old signal would hear nothing at all."""
        prefs['bg colour'] = [0.0, 0.0, 0.0, 1.0]
        self._open()
        self._colour_buttons()[0].set_rgba(image_tools.rgba(0.25, 0.5, 0.75, 1.0))
        self.assertEqual([round(value, 2) for value in prefs['bg colour']],
                         [0.25, 0.5, 0.75, 1.0])

    def test_a_colour_button_comes_up_showing_the_colour_it_stands_for(self):
        prefs['thumb bg colour'] = [1.0, 0.0, 0.5, 1.0]
        self._open()
        rgba = self._colour_buttons()[1].get_rgba()
        self.assertEqual([round(value, 2) for value in
                          (rgba.red, rgba.green, rgba.blue, rgba.alpha)],
                         [1.0, 0.0, 0.5, 1.0])

    def test_the_thumbnail_pair_is_the_same_arrangement(self):
        prefs['smart thumb bg'] = False
        self._open()
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.CheckButton):
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(self.dialog.notebook.get_nth_page(0))
        fixed = [button for button in found
                 if button.get_label()
                 == 'Use this colour as the thumbnail background:']
        self.assertTrue(fixed and fixed[0].get_active())

    # -- Taking back a "Do not ask again" ----------------------------------

    _DELETE = message_dialog.RememberedDialog.DELETE_OPENED_FILE
    _REMOVE = message_dialog.RememberedDialog.LIBRARY_REMOVE_BOOK_FROM_DISK
    _RESUME = message_dialog.RememberedDialog.RESUME_FROM_LAST_READ_PAGE

    def _choosers(self):
        """What each prompt is answered with, by the prompt.

        The Behaviour tab builds one chooser per entry of
        message_dialog.REMEMBERED_DIALOGS, in that order.
        """
        return dict(zip(message_dialog.REMEMBERED_DIALOGS,
                        self._open()._remembered_answers))

    def test_every_prompt_that_can_be_answered_for_good_is_listed(self):
        """A prompt with nowhere to take its answer back can only be
        cleared along with every other one."""
        choosers = self._choosers()
        self.assertEqual(list(message_dialog.REMEMBERED_DIALOGS),
                         list(choosers))
        for prompt, chooser in choosers.items():
            self.assertIsNotNone(chooser.get_parent(),
                                 '%s is on no page' % prompt)

    def test_a_prompt_that_was_never_answered_asks_every_time(self):
        for prompt, chooser in self._choosers().items():
            self.assertIsNone(chooser.get_value(), prompt)

    def test_it_shows_the_answer_that_is_stored(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        self.assertEqual(int(Response.OK),
                         self._choosers()[self._DELETE].get_value())

    def test_one_answer_can_be_taken_back_on_its_own(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        prefs['stored dialog choices'][self._REMOVE] = int(Response.YES)
        self._choosers()[self._DELETE].set_value(None)
        pump()
        self.assertEqual({self._REMOVE: int(Response.YES)},
                         prefs['stored dialog choices'])

    def test_an_answer_can_be_given_here_rather_than_at_the_prompt(self):
        """Picking one is the "Do not ask again" tick, without waiting
        for the prompt to come up."""
        self._choosers()[self._RESUME].set_value(int(Response.NO))
        pump()
        self.assertEqual({self._RESUME: int(Response.NO)},
                         prefs['stored dialog choices'])
        self.assertTrue(self.dialog.reset_button.get_sensitive())

    def test_clearing_them_all_puts_every_chooser_back_to_asking(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        choosers = self._choosers()
        self.dialog.response(constants.RESPONSE_REVERT_TO_DEFAULT)
        pump()
        self.assertIsNone(choosers[self._DELETE].get_value())

    def test_the_reset_button_offers_to_clear_the_dialog_choices(self):
        """It is the only way back from a "Do not ask again" tick, and
        the button it lives on says something else on the Shortcuts
        tab."""
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        self._open()
        self.assertEqual('Clear _dialog choices',
                         self.dialog.reset_button.get_label())
        self.assertTrue(self.dialog.reset_button.get_sensitive())

    def test_with_nothing_remembered_there_is_nothing_to_clear(self):
        self._open()
        self.assertFalse(self.dialog.reset_button.get_sensitive())

    def test_pressing_it_forgets_the_answers_and_says_so(self):
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        prefs['stored dialog choices'][self._REMOVE] = int(Response.YES)
        self._open()
        self.dialog.response(constants.RESPONSE_REVERT_TO_DEFAULT)
        pump()
        self.assertEqual({}, prefs['stored dialog choices'])
        self.assertFalse(self.dialog.reset_button.get_sensitive())

    # -- Changing the interface language -----------------------------------

    def _prompts(self):
        """The prompts the dialog has put on screen."""
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_visible()]

    def _pick_language(self, language):
        """Pick <language> in the dialog's language chooser."""
        self._open()
        self.dialog._language_chooser.set_value(language)
        pump()
        return self._prompts()

    def test_picking_another_language_offers_a_restart(self):
        """Most of the interface is translated before any window exists,
        so the language picked here cannot reach the one on screen."""
        prompts = self._pick_language('de')
        self.assertEqual(1, len(prompts))
        self.assertEqual('de', prefs['language'])
        prompts[0].destroy()

    def test_picking_the_language_in_use_offers_nothing(self):
        """A reader who picks another language and then picks the one
        they started in is back where they were."""
        self._open()
        self.dialog._language_chooser.set_value('de')
        pump()
        for prompt in self._prompts():
            prompt.destroy()
        pump()
        self.dialog._language_chooser.set_value('auto')
        pump()
        self.assertEqual([], self._prompts())
        self.assertEqual('auto', prefs['language'])

    def test_every_translation_can_be_picked(self):
        """Lithuanian was translated in 2017 and never offered: the list
        of languages is written out by hand, and nothing held it to the
        catalogues that ship."""
        messages = os.path.join(
            os.path.dirname(preferences_dialog.__file__), 'messages')
        shipped = {name for name in os.listdir(messages)
                   if os.path.isfile(os.path.join(
                       messages, name, 'LC_MESSAGES', 'mcomix.mo'))}
        self.assertGreater(len(shipped), 20)
        self._open()
        offered = set(self.dialog._language_chooser._values)
        self.assertEqual(set(), shipped - offered)
        self.assertEqual(set(), offered - shipped - {'auto', 'en'})

    def test_the_offer_follows_the_interface_not_the_stored_choice(self):
        """A reader who picks a language and declines the restart leaves
        the preference ahead of the interface, and this dialog is built
        afresh every time it is opened.  A second opening compared the
        next choice against the preference, so picking the language
        actually on screen offered a restart that would change nothing.
        """
        with unittest.mock.patch.object(i18n, '_language_preference',
                                        'auto'):
            # What the earlier, declined choice left behind.
            prefs['language'] = 'de'
            self._open()
            self.dialog._language_chooser.set_value('auto')
            pump()
            self.assertEqual([], self._prompts())
            self.assertEqual('auto', prefs['language'])

    def test_answering_yes_starts_mcomix_again(self):
        restarted = []
        self.window.restart_program = lambda: restarted.append(True)
        prompts = self._pick_language('de')
        prompts[0].response(Response.YES)
        pump()
        self.assertEqual([True], restarted)

    def test_answering_no_leaves_the_program_where_it_is(self):
        """The preference is kept even so: it is what the next start
        reads."""
        restarted = []
        self.window.restart_program = lambda: restarted.append(True)
        prompts = self._pick_language('de')
        prompts[0].response(Response.NO)
        pump()
        self.assertEqual([], restarted)
        self.assertEqual('de', prefs['language'])

    def test_the_shortcuts_tab_offers_the_keys_instead(self):
        """The same button resets the keyboard shortcuts there, so a
        test of one has to know which tab it is on."""
        prefs['stored dialog choices'][self._DELETE] = int(Response.OK)
        self._open()
        shortcuts = self.dialog.notebook.page_num(self.dialog.shortcuts)
        self.dialog.notebook.set_current_page(shortcuts)
        pump()
        self.assertEqual('_Reset keys', self.dialog.reset_button.get_label())
        self.assertEqual({self._DELETE: int(Response.OK)},
                         prefs['stored dialog choices'])

    def test_reset_keys_puts_the_defaults_back_and_they_still_work(self):
        """Reset keys empties the key manager - callbacks and all - and
        has the window register its keys again, so a key has to reach
        its action afterwards as well as be listed."""
        km = keybindings.keybinding_manager(self.window)
        default = list(km.get_bindings_for_action('next_page'))
        km.edit_accel('next_page', '<Control>F9', '')
        self.assertIn(keybindings.parse_accelerator('<Control>F9'),
                      km.get_bindings_for_action('next_page'))
        self._open()
        shortcuts = self.dialog.notebook.page_num(self.dialog.shortcuts)
        self.dialog.notebook.set_current_page(shortcuts)
        pump()
        self.dialog.response(constants.RESPONSE_REVERT_TO_DEFAULT)
        self.assertEqual(default, km.get_bindings_for_action('next_page'))
        reached = []
        with unittest.mock.patch.object(
                self.window, 'flip_page',
                side_effect=lambda *args, **kwargs: reached.append(args)):
            km.execute(default[0])
        self.assertTrue(reached, 'the default key reaches nothing')
        with open(constants.KEYBINDINGS_CONF_PATH) as stored:
            self.assertTrue('<Control>F9' not in stored.read(),
                            'the key given by hand was saved after the reset')

    def _never_store_recent(self, recent_count):
        """Answer "Never" to "Store recently opened files", over a
        recent list of <recent_count> and one book's page remembered.
        Returns the stood-in recent list and the questions asked."""
        prefs['store recent file info'] = True
        last_read = self.window.filehandler.last_read_page
        last_read.set_enabled(True)
        book = os.path.join(self.tmp_dir, 'book.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), book)
        last_read.set_page(book, 3)
        recent = unittest.mock.Mock()
        recent.count.return_value = recent_count
        self.window.uimanager.recent = recent
        self._open()
        chooser = unittest.mock.Mock()
        chooser.get_value.return_value = False
        self.dialog._store_recent_changed_cb(chooser)
        pump()
        return recent, [window for window in Gtk.Window.list_toplevels()
                        if isinstance(window, message_dialog.MessageDialog)
                        and window.get_visible()]

    def test_never_storing_recent_files_asks_to_forget_them(self):
        recent, questions = self._never_store_recent(2)
        self.assertEqual(1, len(questions))
        questions[0].response(Response.YES)
        pump()
        recent.remove_all.assert_called_once_with()
        self.assertEqual(0, self.window.filehandler.last_read_page.count())
        self.assertFalse(prefs['store recent file info'])

    def test_keeping_them_forgets_nothing(self):
        recent, questions = self._never_store_recent(2)
        questions[0].response(Response.NO)
        pump()
        recent.remove_all.assert_not_called()


class PreferenceCallbacksTest(MComixTest):

    """What each control of the dialog stores, and what it has the
    window do beside storing it."""

    #: What the callbacks may call on the window, by name.
    TARGETS = ('draw_image', 'set_bg_colour', 'change_zoom_mode',
               'update_space', 'slideshow.update_delay',
               'thumbnailsidebar.resize',
               'thumbnailsidebar.toggle_page_numbers_visible',
               'imagehandler.do_cacheing',
               'event_handler.reset_extra_scroll_events',
               'filehandler.update_comment_extensions',
               'filehandler.refresh_file',
               'thumbnailsidebar.change_thumbnail_background_color')

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()
        self.dialog = preferences_dialog._PreferencesDialog(self.window)
        pump()

    def tearDown(self):
        self.dialog.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _called(self, callback):
        """Run <callback> with the window's methods stood in for, and
        return the names of those it called."""
        mocks = {}
        with contextlib.ExitStack() as stack:
            for name in self.TARGETS:
                owner = self.window
                *path, attribute = name.split('.')
                for step in path:
                    owner = getattr(owner, step)
                mocks[name] = stack.enter_context(
                    unittest.mock.patch.object(owner, attribute))
            callback()
        return {name for name, mock in mocks.items() if mock.called}

    def _spin(self, preference, value):
        spinner = unittest.mock.Mock()
        spinner.get_value.return_value = value
        return self._called(
            lambda: self.dialog._spinner_cb(spinner, preference))

    def _check(self, preference, active):
        button = unittest.mock.Mock()
        button.get_active.return_value = active
        return self._called(
            lambda: self.dialog._check_button_cb(button, preference))

    def test_each_spinner_stores_its_value_and_has_the_window_follow(self):
        for preference, value, stored, called in (
                ('slideshow delay', 2.5, 2500, {'slideshow.update_delay'}),
                ('smart scroll percentage', 40, 0.4, set()),
                ('lens magnification', 2.5, 2.5, set()),
                ('thumbnail size', 90, 90,
                 {'thumbnailsidebar.resize', 'draw_image'}),
                ('max pages to cache', 5, 5, {'imagehandler.do_cacheing'}),
                ('number of key presses before page turn', 2, 2,
                 {'event_handler.reset_extra_scroll_events'}),
                ('fit to size width wide', 500, 500, {'change_zoom_mode'}),
                ('space between two pages', 4, 4, {'update_space'})):
            with self.subTest(preference=preference):
                self.assertEqual(called, self._spin(preference, value))
                self.assertEqual(stored, prefs[preference])

    def test_each_check_button_has_the_window_follow(self):
        for preference, active, called in (
                ('smart bg', True, {'draw_image'}),
                ('smart bg', False, {'set_bg_colour'}),
                ('checkered bg for transparent images', True, {'draw_image'}),
                ('show page numbers on thumbnails', True,
                 {'thumbnailsidebar.toggle_page_numbers_visible'}),
                ('smart thumb bg', True, {'draw_image'}),
                ('smart thumb bg', False,
                 {'thumbnailsidebar.change_thumbnail_background_color'})):
            with self.subTest(preference=preference, active=active):
                self.assertEqual(called, self._check(preference, active))
                self.assertEqual(active, prefs[preference])

    def test_hiding_everything_in_fullscreen_redraws_only_in_fullscreen(self):
        for fullscreen, called in ((False, set()), (True, {'draw_image'})):
            with self.subTest(fullscreen=fullscreen), \
                    unittest.mock.patch.object(self.window, 'is_fullscreen',
                                               return_value=fullscreen):
                self.assertEqual(called,
                                 self._check('hide all in fullscreen', True))

    def test_a_thumbnail_background_colour_is_stored_and_shown(self):
        """Shown at once where the thumbnails do not take their colour
        off the page; where they do, the next page drawn shows it."""
        button = unittest.mock.Mock()
        # Built by image_tools.rgba(): PyGObject 3.46, the floor, hands
        # the arguments of Gdk.RGBA(red=...) to nothing.
        button.get_rgba.return_value = image_tools.rgba(1.0, 0.5, 0.25, 1.0)
        for smart, called in (
                (False,
                 {'thumbnailsidebar.change_thumbnail_background_color'}),
                (True, set())):
            with self.subTest(smart=smart):
                prefs['smart thumb bg'] = smart
                prefs['thumb bg colour'] = [0.0, 0.0, 0.0, 1.0]
                with unittest.mock.patch.object(
                        self.window.filehandler, 'file_loaded', True):
                    self.assertEqual(called, self._called(
                        lambda: self.dialog._color_button_cb(
                            button, None, 'thumb bg colour')))
                self.assertEqual([1.0, 0.5, 0.25, 1.0],
                                 prefs['thumb bg colour'])

    def test_the_double_page_choice_is_stored_and_redrawn(self):
        chooser = unittest.mock.Mock()
        chooser.get_value.return_value = constants.SHOW_DOUBLE_AS_ONE_WIDE
        self.assertEqual({'draw_image'}, self._called(
            lambda: self.dialog._double_page_changed_cb(chooser)))
        self.assertEqual(constants.SHOW_DOUBLE_AS_ONE_WIDE,
                         prefs['virtual double page for fitting images'])

    def _choose(self, callback, value):
        chooser = unittest.mock.Mock()
        chooser.get_value.return_value = value
        return self._called(lambda: getattr(self.dialog, callback)(chooser))

    def test_each_chooser_stores_its_value_and_has_the_window_follow(self):
        """A choice that changes the order of the pages opens the book
        again, one that changes how they are drawn draws them again, and
        a choice that is the one already made does neither."""
        refresh, draw = {'filehandler.refresh_file'}, {'draw_image'}
        prefs['scaling quality'] = 2
        prefs['animation mode'] = constants.ANIMATION_NORMAL
        for callback, preference, value, called in (
                ('_double_page_autoresize_changed_cb',
                 'double page autoresize',
                 constants.DOUBLE_PAGE_AUTORESIZE_FIT_SIZE, draw),
                ('_sort_by_changed_cb', 'sort by', constants.SORT_SIZE,
                 refresh),
                ('_sort_order_changed_cb', 'sort order',
                 constants.SORT_DESCENDING, refresh),
                ('_sort_archive_by_changed_cb', 'sort archive by',
                 constants.SORT_NAME_LITERAL, refresh),
                ('_sort_archive_order_changed_cb', 'sort archive order',
                 constants.SORT_DESCENDING, refresh),
                ('_scaling_quality_changed_cb', 'scaling quality', 3, draw),
                ('_scaling_quality_changed_cb', 'scaling quality', 3, set()),
                ('_animation_mode_changed_cb', 'animation mode',
                 constants.ANIMATION_DISABLED, refresh),
                ('_animation_mode_changed_cb', 'animation mode',
                 constants.ANIMATION_DISABLED, set())):
            with self.subTest(callback=callback, value=value, called=called):
                self.assertEqual(called, self._choose(callback, value))
                self.assertEqual(value, prefs[preference])

    def test_the_page_number_choice_is_stored_and_shown_again(self):
        prefs['page counter'] = 0
        box = self.dialog._create_page_counter_combobox()
        with unittest.mock.patch.object(
                self.window.page_counter, 'update') as update:
            box.set_selected(2)
            box.set_selected(2)
        self.assertEqual(2, prefs['page counter'])
        update.assert_called_once_with(again=True)

    def test_a_screen_profile_typed_in_is_stored_and_redraws_once(self):
        entry = self.dialog._create_screen_profile_entry()
        with unittest.mock.patch.object(
                self.window.enhancer, 'signal_update') as update:
            entry.set_text(' /a/screen.icc ')
            entry.emit('activate')
            entry.emit('activate')
        self.assertEqual('/a/screen.icc', prefs['screen profile'])
        update.assert_called_once_with()

    def test_the_rendering_intent_redraws_only_where_a_profile_is_set(self):
        prefs['rendering intent'] = 0
        box = self.dialog._create_rendering_intent_combobox()
        for profile, intent, calls in (('', 1, 0), ('/a/screen.icc', 3, 1)):
            prefs['screen profile'] = profile
            with self.subTest(profile=profile), unittest.mock.patch.object(
                    self.window.enhancer, 'signal_update') as update:
                box.set_selected(intent)
                self.assertEqual(intent, prefs['rendering intent'])
                self.assertEqual(calls, update.call_count)

    def test_a_colour_scheme_repaints_the_page_and_the_thumbnails(self):
        """They are painted from a colour, not from the style sheet the
        scheme changes."""
        with unittest.mock.patch.object(theme, 'apply_colour_scheme') as \
                applied:
            called = self._choose('_colour_scheme_changed_cb', theme.DARK)
        applied.assert_called_once_with()
        self.assertEqual(theme.DARK, prefs['colour scheme'])
        self.assertEqual({'set_bg_colour',
                          'thumbnailsidebar.change_thumbnail_background_color'},
                         called)

    def test_the_comment_extensions_are_read_out_of_their_entry(self):
        entry = unittest.mock.Mock()
        entry.get_text.return_value = 'txt, nfo ,, xml'
        self.assertEqual({'filehandler.update_comment_extensions'},
                         self._called(lambda: self.dialog._entry_cb(entry)))
        self.assertEqual(['txt', 'nfo', 'xml'], prefs['comment extensions'])

# vim: expandtab:sw=4:ts=4
