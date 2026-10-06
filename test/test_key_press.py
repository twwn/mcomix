"""What a key press on the main window hands the keybinding manager.

The key controller is given a hardware keycode and the modifiers held,
and has to turn them into the accelerator a binding is written as:
lower case, with Shift only where it was not needed to type the key.
These go through the X server's own keymap, as a real key press does.
"""

import os
import unittest.mock

from gi.repository import Gdk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import keybindings
from mcomix import main
from mcomix.preferences import prefs


class _Controller:

    """The one thing the handler asks of its key controller."""

    def get_group(self):
        return 0


class _KeyPressWindowTest(MComixTest):

    """A main window, and a way to press a key in it."""

    #: Preferences set before the window is made.
    WINDOW_PREFS: dict = {}

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        prefs.update(self.WINDOW_PREFS)
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _press(self, keyval, state=Gdk.ModifierType(0)):
        """Press the key that types <keyval> unshifted, with <state> held."""
        found, keys = self.window.get_display().map_keyval(keyval)
        self.assertTrue(found, 'the keymap has no key for %r' % keyval)
        key = min(keys, key=lambda key: (key.group, key.level))
        # The keyval GTK hands over is the one the modifiers make of it.
        _ok, typed, _group, _level, _consumed = \
            self.window.get_display().translate_key(key.keycode, state, 0)
        return self.window.event_handler.key_press_event(
            _Controller(), typed, key.keycode, state)


class KeyPressTest(_KeyPressWindowTest):

    def setUp(self):
        super().setUp()
        self.executed = []
        manager = keybindings.keybinding_manager(self.window)
        patcher = unittest.mock.patch.object(
            manager, 'execute', side_effect=self.executed.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_plain_letter(self):
        self._press(Gdk.KEY_n)
        self.assertEqual([(Gdk.KEY_n, 0)], self.executed)

    def test_shift_and_a_letter_is_the_lower_case_letter_with_shift(self):
        self._press(Gdk.KEY_n, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual([(Gdk.KEY_n, Gdk.ModifierType.SHIFT_MASK)],
                         self.executed)

    def test_shift_and_space_keeps_shift(self):
        self._press(Gdk.KEY_space, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual([(Gdk.KEY_space, Gdk.ModifierType.SHIFT_MASK)],
                         self.executed)

    def test_caps_lock_does_not_change_a_letters_binding(self):
        """Caps Lock types the letter in upper case, and a binding is
        written in lower case: with it on, no letter key reached its
        action."""
        self._press(Gdk.KEY_n, Gdk.ModifierType.LOCK_MASK)
        self.assertEqual([(Gdk.KEY_n, 0)], self.executed)

    def test_caps_lock_and_shift_is_still_shift(self):
        """Together they type the letter in lower case, which hid that
        Shift was held at all."""
        self._press(Gdk.KEY_n, Gdk.ModifierType.LOCK_MASK
                    | Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual([(Gdk.KEY_n, Gdk.ModifierType.SHIFT_MASK)],
                         self.executed)

    def test_a_modifier_no_accelerator_uses_is_left_out(self):
        self._press(Gdk.KEY_n, Gdk.ModifierType.SUPER_MASK)
        self.assertEqual([(Gdk.KEY_n, 0)], self.executed)

    def test_the_keys_that_move_the_thumbnail_selection_are_kept(self):
        """Up, Down, Space and Enter would otherwise also move the
        thumbnail bar's selection."""
        for keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_space,
                       Gdk.KEY_Return):
            with self.subTest(keyval=Gdk.keyval_name(keyval)):
                self.assertEqual(Gdk.EVENT_STOP, self._press(keyval))

    def test_other_keys_go_on_to_the_focused_widget(self):
        self.assertEqual(Gdk.EVENT_PROPAGATE, self._press(Gdk.KEY_n))


class EscapeTest(_KeyPressWindowTest):

    """Escape puts the pages picked out back before it does what it is
    bound to; "Escape key closes program" made that true of quitting
    too, and now that quitting is a binding of Escape like any other,
    it is true whatever the key is bound to."""

    def setUp(self):
        super().setUp()
        self.executed = []
        manager = keybindings.keybinding_manager(self.window)
        patcher = unittest.mock.patch.object(
            manager, 'execute', side_effect=self.executed.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pages_picked_out_are_put_back_first(self):
        self.window.selected_pages = {1, 3}
        with unittest.mock.patch.object(self.window, 'clear_selection') \
                as cleared:
            self._press(Gdk.KEY_Escape)
        cleared.assert_called_once_with()
        self.assertEqual([], self.executed)

    def test_with_none_picked_out_escape_does_what_it_is_bound_to(self):
        self.window.selected_pages = set()
        self._press(Gdk.KEY_Escape)
        self.assertEqual([(Gdk.KEY_Escape, 0)], self.executed)


class _ScrollablePageTest(_KeyPressWindowTest):

    """A page far larger than the window, to scroll about in.

    A portrait page of 210 by 297 pixels, zoomed in eight steps, is 840
    by 1188 in a window that shows far less of it.
    """

    #: How many presses at the end of the page turn it.
    PRESSES = 3

    #: A window of a size the tests know.  Left to itself it opens at
    #: the size remembered, widened to what its menu bar and tool bar
    #: ask for and cut to the screen: 745 by 384 pixels of page under
    #: Arch's xvfb-run, whose screen is 640 by 480, and 745 by 504 on a
    #: 1280 by 1024 one - where six of these tests failed on the CI.
    #: Without the bars and the sidebar, and no larger than 640 by 480,
    #: it is the size asked for on either.
    WINDOW_PREFS = {'window width': 640, 'window height': 400,
                    'show menubar': False, 'show toolbar': False,
                    'show thumbnails': False}

    def setUp(self):
        super().setUp()
        prefs['flip with wheel'] = True
        prefs['number of key presses before page turn'] = self.PRESSES
        prefs['number of pixels to scroll per key event'] = 50
        prefs['zoom mode'] = constants.ZoomMode.MANUAL
        self.window.filehandler.open_file(
            get_testfile_path('images', 'portrait-no-exif.png'))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 1))
        self.window.change_zoom_mode()
        for _ in range(8):
            self.window.manual_zoom_in()
        # Until the scroll bars have been told the zoomed page's size,
        # a frame after it is laid out, _right() and _bottom() read the
        # size of the window instead: a test that took its expected end
        # from them there, under load, expected (14, 14).
        self._settle()
        self.assertTrue(self.window.is_scrollable())
        self.page = self.window.imagehandler.get_current_page()

    def _where(self):
        return (self.window.imagehandler.get_current_page(),
                self.window._vadjust.get_value())

    def _bottom(self):
        return (self.window._vadjust.get_upper()
                - self.window.get_visible_area_size()[1])

    def _right(self):
        return (self.window._hadjust.get_upper()
                - self.window.get_visible_area_size()[0])

    def _draw_without_a_frame(self):
        """Draw the page a key turned to, and stop short of the frame
        that tells the scroll bars its size - where a key pressed
        quickly after the one before lands."""
        self.assertTrue(self.window.imagehandler.page_is_available())
        # The redraw the page turn queued, run now rather than from the
        # main loop, which could let the frame clock tick first.
        self.window._draw_image()
        self.assertIsNotNone(self.window.page_area._wanted)

    def _settle(self):
        """Wait until the page shown is drawn and its size has reached
        the scroll bars, which is a frame after the page is laid out."""
        window = self.window

        def settled():
            # A key's page turn is drawn from the idle queue, and a page
            # still on its way is left hidden: until both are done, the
            # size the scroll bars hold is the page before's.
            if (window._waiting_for_redraw
                    or not window.imagehandler.page_is_available()
                    or not window.images[0].get_visible()):
                return False
            content = window.page_area.get_content_size()
            visible = window.get_visible_area_size()
            return ((window._hadjust.get_upper(), window._vadjust.get_upper())
                    == (max(content[0], visible[0]),
                        max(content[1], visible[1])))

        self.assertTrue(wait_for(settled))
        pump()


class ArrowKeysTest(_ScrollablePageTest):

    """The arrow keys scroll the page, and turn it at the end.

    Nothing ran MainWindow.scroll() or the four plain scroll bindings:
    the wheel's tests stop at which handler it calls.
    """

    def _down(self):
        self._press(Gdk.KEY_Down)
        self._settle()

    def test_down_scrolls_the_page_by_the_step_the_preferences_give(self):
        self._down()
        self.assertEqual((self.page, 50), self._where())
        self._press(Gdk.KEY_Up)
        pump()
        self.assertEqual((self.page, 0), self._where())

    def test_down_stops_at_the_bottom_of_the_page(self):
        while self._where()[1] < self._bottom():
            self._down()
        self.assertEqual((self.page, self._bottom()), self._where())

    def test_the_page_turns_only_after_the_presses_the_preference_asks(self):
        while self._where()[1] < self._bottom():
            self._down()
        for _ in range(self.PRESSES - 1):
            self._down()
            self.assertEqual(self.page, self._where()[0],
                             'the page turned before its presses were up')
        self._down()
        self.assertEqual((self.page + 1, 0), self._where())

    def test_up_at_the_top_goes_back_to_the_bottom_of_the_page_before(self):
        for _ in range(self.PRESSES):
            self._press(Gdk.KEY_Up)
            self._settle()
        self.assertEqual((self.page - 1, self._bottom()), self._where())

    def test_up_before_the_page_before_is_sized_scrolls_it(self):
        """An arrow key that comes in the frame between a page turn and
        the scroll bars learning the new page's size was read against
        the page turned from: the page before, opened at its end from
        a smaller one, did not move."""
        while self._where()[1] < self._bottom():
            self._down()
        for _ in range(self.PRESSES):
            self._down()
        self.assertEqual((self.page + 1, 0), self._where())
        for _ in range(self.PRESSES - 1):
            self._press(Gdk.KEY_Up)
            self._settle()
        self._press(Gdk.KEY_Up)
        self._draw_without_a_frame()
        self._press(Gdk.KEY_Up)
        self._settle()
        self.assertEqual((self.page, self._bottom() - 50), self._where())

    def test_with_flipping_off_the_keys_only_scroll(self):
        prefs['flip with wheel'] = False
        while self._where()[1] < self._bottom():
            self._down()
        for _ in range(self.PRESSES * 2):
            self._down()
        self.assertEqual((self.page, self._bottom()), self._where())

    def test_right_scrolls_across_before_it_turns(self):
        self._press(Gdk.KEY_Right)
        self._settle()
        self.assertEqual(self.page, self._where()[0])
        self.assertEqual(50, self.window._hadjust.get_value())


class SmartScrollKeysTest(_ScrollablePageTest):

    """Space reads the page the way a comic is read, and turns it.

    The walk itself is tested on the Scrolling class alone; nothing ran
    the handler the key reaches, which asks for the step, moves the view
    and turns the page where there is nothing left to read.
    """

    def _space(self, state=Gdk.ModifierType(0)):
        self._press(Gdk.KEY_space, state)
        self._settle()
        return (self.window.imagehandler.get_current_page(),
                self.window._hadjust.get_value(),
                self.window._vadjust.get_value())

    def test_each_row_is_read_across_before_going_down(self):
        self.assertEqual((self.page, self._right(), 0), self._space())
        page, x, y = self._space()
        self.assertEqual((self.page, 0), (page, x))
        self.assertGreater(y, 0)
        # No step is longer than the share of the view the preference
        # gives.
        self.assertLessEqual(
            y, prefs['smart scroll percentage']
            * self.window.get_visible_area_size()[1])

    def test_the_page_turns_as_soon_as_it_has_been_read(self):
        """A key press turns at once: the presses the wheel has to make
        at the end of a page are for the wheel alone."""
        where = None
        for _ in range(50):
            where = self._space()
            if where[0] != self.page:
                break
        self.assertEqual((self.page + 1, 0, 0), where)

    def test_shift_space_goes_back_to_the_end_of_the_page_before(self):
        """The end was set on the scroll bars before they had been told
        the page's size, which is a frame later; they cut it short to
        the size of the page being left, which fits the window, and the
        page came back a few pixels from its top left corner."""
        # Read now: the page after this one is not the same size.
        end = (self.page, self._right(), self._bottom())
        for _ in range(50):
            if self._space()[0] != self.page:
                break
        self.assertEqual(end, self._space(Gdk.ModifierType.SHIFT_MASK))

    def test_manga_reads_each_row_from_the_right(self):
        self.window.actiongroup.get_action('manga_mode').set_active(True)
        self.window.draw_image(scroll_to=constants.SCROLL_TO_START)
        self._settle()
        self.assertEqual(self._right(), self.window._hadjust.get_value())
        self.assertEqual((self.page, 0, 0), self._space())
        page, x, y = self._space()
        self.assertEqual((self.page, self._right()), (page, x))
        self.assertGreater(y, 0)

    def test_a_second_shift_space_before_the_page_is_sized_reads_on_back(self):
        """A key that comes in the frame between a page turn and the
        scroll bars learning the new page's size was read against the
        page turned from.  Shift+Space back from a page that fits the
        window found the layout at the top left of the page before
        rather than at its end, and turned back past it unseen."""
        for _ in range(50):
            if self._space()[0] != self.page:
                break
        self._space(Gdk.ModifierType.SHIFT_MASK)
        expected = self._space(Gdk.ModifierType.SHIFT_MASK)
        # Once more, with the second key before the frame.
        for _ in range(50):
            if self._space()[0] != self.page:
                break
        self._press(Gdk.KEY_space, Gdk.ModifierType.SHIFT_MASK)
        self._draw_without_a_frame()
        self.assertEqual(expected,
                         self._space(Gdk.ModifierType.SHIFT_MASK))


class _Scroll:

    """What a scroll controller tells the wheel handler: the modifiers
    and the time."""

    def get_current_event_state(self):
        return Gdk.ModifierType(0)

    def get_current_event_time(self):
        return 0


class SidewaysWheelTest(_ScrollablePageTest):

    """A sideways wheel - a tilt wheel, a touchpad - on a page wider
    than the window scrolls across it before it turns it, as the wheel
    turned down scrolls down it first."""

    def _tilt(self, delta_x):
        self.window.event_handler.scroll_wheel_event(_Scroll(), delta_x, 0)
        self._settle()

    def test_a_tilt_scrolls_across_the_page(self):
        """It turned the page, after three tilts, and the page was never
        scrolled across."""
        pixels = prefs['number of pixels to scroll per mouse wheel event']
        self._tilt(1)
        self.assertEqual(self.page, self._where()[0])
        self.assertEqual(pixels, self.window._hadjust.get_value())
        self._tilt(-1)
        self.assertEqual(0, self.window._hadjust.get_value())

    def test_a_tilt_at_the_side_turns_after_the_presses_asked(self):
        while self.window._hadjust.get_value() < self._right():
            self._tilt(1)
        for _ in range(self.PRESSES - 1):
            self._tilt(1)
            self.assertEqual(self.page, self._where()[0],
                             'the page turned before its tilts were up')
        self._tilt(1)
        self.assertEqual(self.page + 1, self._where()[0])
