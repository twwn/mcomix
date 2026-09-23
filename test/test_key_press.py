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


class _ScrollablePageTest(_KeyPressWindowTest):

    """A page far larger than the window, to scroll about in.

    A portrait page of 210 by 297 pixels, zoomed in eight steps, is 840
    by 1188 in a window that shows far less of it.
    """

    #: How many presses at the end of the page turn it.
    PRESSES = 3

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
        pump()
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
