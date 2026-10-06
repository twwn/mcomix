"""event.py - Event handling (keyboard, mouse, etc.) for the main window.
"""

from gi.repository import Gdk, Gtk

from mcomix.preferences import prefs
from mcomix import constants
from mcomix import widgets
from mcomix import keybindings
from mcomix import openwith

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # main imports this module, so the window it hands over can only be
    # named while the checker is reading and not while Python is.
    from mcomix import main


class EventHandler:

    def __init__(self, window: 'main.MainWindow') -> None:
        self._window = window

        # Where the pointer was, in the fractional coordinates the
        # controllers below report.
        self._last_pointer_pos_x = 0.0
        self._last_pointer_pos_y = 0.0
        self._pressed_pointer_pos_x = 0.0
        self._pressed_pointer_pos_y = 0.0
        #: Set by a press that brought the window back into focus, which
        #: its release must not answer.
        self._raising_click = False

        #: For scrolling "off the page".
        self._extra_scroll_events = 0
        #: If True, increment _extra_scroll_events before switching pages
        self._scroll_protection = False

    def register_controllers(self, window: 'main.MainWindow',
                             page_area: Gtk.Widget) -> None:
        """Add the controllers input arrives through in GTK4.

        A widget gets what the controllers added to it deliver.  The
        keys are taken in the capture phase, ahead of the thumbnail list,
        which would otherwise make its own use of Up and Space.
        """
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.key_press_event)
        window.add_controller(keys)

        clicks = Gtk.GestureClick()
        # Every button, as the button masks asked for.
        clicks.set_button(0)
        clicks.connect('pressed', self.mouse_press_event)
        clicks.connect('released', self.mouse_release_event)
        clicks.connect('cancel', self.mouse_cancel_event)
        page_area.add_controller(clicks)

        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self.mouse_move_event)
        page_area.add_controller(motion)

        scroll = Gtk.EventControllerScroll()
        scroll.set_flags(Gtk.EventControllerScrollFlags.BOTH_AXES |
                         Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect('scroll', self.scroll_wheel_event)
        page_area.add_controller(scroll)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect('drop', self.drag_n_drop_event)
        page_area.add_controller(drop)

    def focus_changed(self, window: 'main.MainWindow',
                      _parameter: object) -> None:
        """Handle the main window gaining or losing the focus.

        One handler serves both: the window reports it as the one
        is-active property rather than a signal per direction.
        """
        if window.get_property('is-active'):
            self._window.gained_focus()
        else:
            self._window.lost_focus()

    def resize_event(self, *args: object) -> None:
        """Handle the room the pages are drawn in changing size.

        The canvas says so only when it really has changed, so there is
        nothing left to compare against here.
        """
        self._window.previous_size = self._window.get_window_size()
        self._window.draw_image()

    def window_state_event(self, window: 'main.MainWindow',
                           _parameter: object) -> None:
        """Handle the window having filled the screen, or stopped.

        Both notify::fullscreened and notify::maximized arrive here, and
        whichever of the two the compositor sends first does the work:
        everything below turns on the fullscreen state, which the other
        notification then finds already dealt with.  A maximize on its own
        reaches this and does nothing, since the size change is the
        canvas' to report through resize_event().

        Which toggle widgets are usable depends on the fullscreen state,
        through the "hide all in fullscreen" preference, so they are asked
        again here.  Going back to a window redraws only where the size it
        is given is the size it already had, because otherwise the resize
        that follows does it.
        """
        is_fullscreen = self._window.is_fullscreen()
        if self._window.was_fullscreen != is_fullscreen:
            self._window.was_fullscreen = is_fullscreen
            if is_fullscreen:
                redraw = True
            else:
                redraw = not self._window.restore_window_geometry()
            self._window.update_toggles_sensitivity()
            # The right-click menu offers the way out only while there
            # is one to take.
            self._window.actiongroup.get_action('leave_fullscreen') \
                .set_sensitive(is_fullscreen)
            if redraw:
                self._window.previous_size = self._window.get_window_size()
                self._window.draw_image()

    def register_key_events(self) -> None:
        """ Registers keyboard events and their default binings, and hooks
        them up with their respective callback functions. """

        manager = keybindings.keybinding_manager(self._window)

        # Navigation keys
        manager.register('previous_page',
                         ['Page_Up', 'KP_Page_Up', 'BackSpace'],
                         self._flip_page, kwargs={'number_of_pages': -1})
        manager.register('next_page',
                         ['Page_Down', 'KP_Page_Down'],
                         self._flip_page, kwargs={'number_of_pages': 1})
        manager.register('previous_page_singlestep',
                         ['<Ctrl>Page_Up', '<Ctrl>KP_Page_Up', '<Ctrl>BackSpace'],
                         self._flip_page, kwargs={'number_of_pages': -1, 'single_step': True})
        manager.register('next_page_singlestep',
                         ['<Ctrl>Page_Down', '<Ctrl>KP_Page_Down'],
                         self._flip_page, kwargs={'number_of_pages': 1, 'single_step': True})
        manager.register('previous_page_dynamic',
                         ['<Alt>Left'],
                         self._left_right_page_progress, kwargs={'number_of_pages': -1})
        manager.register('next_page_dynamic',
                         ['<Alt>Right'],
                         self._left_right_page_progress, kwargs={'number_of_pages': 1})

        # One page in the direction on screen, as ALT and the arrows turn
        # two in double page mode (upstream feature request 134).
        manager.register('previous_page_singlestep_dynamic',
                         ['<Ctrl>Left', '<Ctrl>KP_Left'],
                         self._left_right_page_progress,
                         kwargs={'number_of_pages': -1, 'single_step': True})
        manager.register('next_page_singlestep_dynamic',
                         ['<Ctrl>Right', '<Ctrl>KP_Right'],
                         self._left_right_page_progress,
                         kwargs={'number_of_pages': 1, 'single_step': True})

        manager.register('previous_page_ff',
                         ['<Shift>Page_Up', '<Shift>KP_Page_Up', '<Shift>BackSpace'],
                         self._flip_page, kwargs={'number_of_pages': -10})
        manager.register('next_page_ff',
                         ['<Shift>Page_Down', '<Shift>KP_Page_Down'],
                         self._flip_page, kwargs={'number_of_pages': 10})
        # Ten pages in the direction on screen, as ALT and the arrows
        # turn one (upstream bug 57).
        manager.register('previous_page_ff_dynamic',
                         ['<Shift><Alt>Left'],
                         self._left_right_page_progress,
                         kwargs={'number_of_pages': -10})
        manager.register('next_page_ff_dynamic',
                         ['<Shift><Alt>Right'],
                         self._left_right_page_progress,
                         kwargs={'number_of_pages': 10})

        manager.register('first_page',
                         ['Home', 'KP_Home'],
                         self._window.first_page)
        manager.register('last_page',
                         ['End', 'KP_End'],
                         self._window.last_page)
        manager.register('go_to',
                         ['G'],
                         self._window.page_select)

        # Numpad (without numlock) aligns the image depending on the key.
        manager.register('scroll_left_bottom',
                         ['KP_1'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (-1, 1), 'index': constants.UNION_INDEX})
        manager.register('scroll_middle_bottom',
                         ['KP_2'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (constants.SCROLL_TO_CENTER, 1),
                                 'index': constants.UNION_INDEX})
        manager.register('scroll_right_bottom',
                         ['KP_3'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (1, 1), 'index': constants.UNION_INDEX})

        manager.register('scroll_left_middle',
                         ['KP_4'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (-1, constants.SCROLL_TO_CENTER),
                                 'index': constants.UNION_INDEX})
        manager.register('scroll_middle',
                         ['KP_5'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (constants.SCROLL_TO_CENTER,
                                                 constants.SCROLL_TO_CENTER), 'index': constants.UNION_INDEX})
        manager.register('scroll_right_middle',
                         ['KP_6'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (1, constants.SCROLL_TO_CENTER),
                                 'index': constants.UNION_INDEX})

        manager.register('scroll_left_top',
                         ['KP_7'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (-1, -1), 'index': constants.UNION_INDEX})
        manager.register('scroll_middle_top',
                         ['KP_8'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (constants.SCROLL_TO_CENTER, -1),
                                 'index': constants.UNION_INDEX})
        manager.register('scroll_right_top',
                         ['KP_9'],
                         self._window.scroll_to_predefined,
                         kwargs={'destination': (1, -1), 'index': constants.UNION_INDEX})

        # Enter/exit fullscreen.  Escape puts picked-out pages back
        # first, whatever it is bound to: key_press_event() sees to it.
        manager.register('exit_fullscreen',
                         ['Escape'],
                         self._window.actiongroup.get_action('fullscreen')
                         .set_active, args=[False])

        # View modes
        manager.register('double_page',
                         ['d'],
                         self._window.actiongroup.get_action('double_page').activate)

        manager.register('title_page_alone',
                         [],
                         self._window.actiongroup.get_action('title_page_alone').activate)

        manager.register('best_fit_mode',
                         ['b'],
                         self._window.actiongroup.get_action('best_fit_mode').activate)

        manager.register('fit_width_mode',
                         ['w'],
                         self._window.actiongroup.get_action('fit_width_mode').activate)

        manager.register('fit_height_mode',
                         ['h'],
                         self._window.actiongroup.get_action('fit_height_mode').activate)

        manager.register('fit_size_mode',
                         ['s'],
                         self._window.actiongroup.get_action('fit_size_mode').activate)

        manager.register('fit_manual_mode',
                         ['a'],
                         self._window.actiongroup.get_action('fit_manual_mode').activate)

        manager.register('manga_mode',
                         ['m'],
                         self._window.actiongroup.get_action('manga_mode').activate)

        manager.register('invert_scroll',
                         ['x'],
                         self._window.actiongroup.get_action('invert_scroll').activate)

        manager.register('keep_transformation',
                         ['k'],
                         self._window.actiongroup.get_action('keep_transformation').activate)

        manager.register('lens',
                         ['l'],
                         self._window.actiongroup.get_action('lens').activate)

        manager.register('stretch',
                         ['y'],
                         self._window.actiongroup.get_action('stretch').activate)

        # Zooming commands for manual zoom mode
        manager.register('zoom_in',
                         ['plus', 'KP_Add', 'equal'],
                         self._window.actiongroup.get_action('zoom_in').activate)
        manager.register('zoom_out',
                         ['minus', 'KP_Subtract'],
                         self._window.actiongroup.get_action('zoom_out').activate)
        manager.register('zoom_original',
                         ['<Control>0', 'KP_0'],
                         self._window.actiongroup.get_action('zoom_original').activate)

        manager.register('rotate_90',
                         ['r'],
                         self._window.rotate_90)

        manager.register('rotate_270',
                         ['<Shift>r'],
                         self._window.rotate_270)

        manager.register('rotate_180',
                         [],
                         self._window.rotate_180)

        manager.register('flip_horiz',
                         [],
                         self._window.flip_horizontally)

        manager.register('flip_vert',
                         [],
                         self._window.flip_vertically)

        manager.register('no_autorotation',
                         [],
                         self._window.actiongroup.get_action('no_autorotation').activate)

        manager.register('rotate_90_width',
                         [],
                         self._window.actiongroup.get_action('rotate_90_width').activate)
        manager.register('rotate_270_width',
                         [],
                         self._window.actiongroup.get_action('rotate_270_width').activate)

        manager.register('rotate_90_height',
                         [],
                         self._window.actiongroup.get_action('rotate_90_height').activate)

        manager.register('rotate_270_height',
                         [],
                         self._window.actiongroup.get_action('rotate_270_height').activate)

        # Arrow keys scroll the image
        manager.register('scroll_down',
                         ['Down', 'KP_Down'],
                         self._scroll_down)
        manager.register('scroll_up',
                         ['Up', 'KP_Up'],
                         self._scroll_up)
        manager.register('scroll_right',
                         ['Right', 'KP_Right'],
                         self._scroll_right)
        manager.register('scroll_left',
                         ['Left', 'KP_Left'],
                         self._scroll_left)

        # File operations
        manager.register('close',
                         ['<Control>W'],
                         self._window.filehandler.close_file)

        manager.register('quit',
                         ['<Control>Q'],
                         self._window.close_program)

        manager.register('save_and_quit',
                         ['<Control><shift>q'],
                         self._window.save_and_terminate_program)

        manager.register('delete',
                         ['Delete'],
                         self._window.file_actions.delete)

        manager.register('delete_permanently',
                         ['<Shift>Delete'],
                         self._window.file_actions.delete_permanently)

        manager.register('rename_page',
                         ['F2'],
                         self._window.file_actions.rename_page_being_read)

        manager.register('undo',
                         ['<Control>z'],
                         self._window.file_actions.undo)

        manager.register('redo',
                         ['<Control>y', '<Control><Shift>z'],
                         self._window.file_actions.redo)

        manager.register('extract_page',
                         ['<Control><Shift>s'],
                         self._window.file_actions.extract_page)

        manager.register('refresh_archive',
                         ['<control><shift>R'],
                         self._window.filehandler.refresh_file)

        manager.register('next_archive',
                         ['<control><shift>N'],
                         self._window.filehandler.next_archive)

        manager.register('previous_archive',
                         ['<control><shift>P'],
                         self._window.filehandler.previous_archive)

        manager.register('next_directory',
                         ['<control>N'],
                         self._window.filehandler.open_next_directory)

        manager.register('previous_directory',
                         ['<control>P'],
                         self._window.filehandler.open_previous_directory)

        manager.register('comments',
                         ['c'],
                         self._window.actiongroup.get_action('comments').activate)

        manager.register('properties',
                         ['<Alt>Return'],
                         self._window.actiongroup.get_action('properties').activate)

        manager.register('preferences',
                         ['F12'],
                         self._window.actiongroup.get_action('preferences').activate)

        manager.register('edit_archive',
                         [],
                         self._window.actiongroup.get_action('edit_archive').activate)

        manager.register('open',
                         ['<Control>O'],
                         self._window.actiongroup.get_action('open').activate)

        manager.register('enhance_image',
                         ['e'],
                         self._window.actiongroup.get_action('enhance_image').activate)

        manager.register('library',
                         ['<Control>L'],
                         self._window.actiongroup.get_action('library').activate)

        # The bookmarks menu keeps actions of its own rather than in
        # actiongroup, since its items are rebuilt with every bookmark.
        manager.register('add_bookmark',
                         ['<Control>D'],
                         self._window.uimanager.bookmarks.activate, args=['add'])
        manager.register('edit_bookmarks',
                         ['<Control>B'],
                         self._window.uimanager.bookmarks.activate, args=['edit'])

        manager.register('invert_color',
                         ['<Control>I'],
                         self._window.actiongroup.get_action('invert_color').activate)

        # Space key scrolls down a percentage of the window height or the
        # image height at a time. When at the bottom it flips to the next
        # page.
        #
        # It also has a "smart scrolling mode" in which we try to follow
        # the flow of the comic.
        #
        # If Shift is pressed we should backtrack instead.
        manager.register('smart_scroll_down',
                         ['space'],
                         self._smart_scroll_down)
        manager.register('smart_scroll_up',
                         ['<Shift>space'],
                         self._smart_scroll_up)

        # User interface
        manager.register('osd_panel',
                         ['Tab'],
                         self._window.show_info_panel)

        manager.register('minimize',
                         ['n'],
                         self._window.minimize)

        manager.register('fullscreen',
                         ['f', 'F11'],
                         self._window.actiongroup.get_action('fullscreen').activate)

        manager.register('toolbar',
                         [],
                         self._window.actiongroup.get_action('toolbar').activate)

        manager.register('menubar',
                         ['<Control>M'],
                         self._window.actiongroup.get_action('menubar').activate)

        # The menu key and Shift+F10 are what a GTK3 widget was told to
        # show a context menu by; a GTK4 widget hears them itself, and
        # here they are an action of their own so that a reader can
        # rebind them like any other.
        manager.register('popup_menu',
                         ['Menu', '<Shift>F10'],
                         self._open_popup_menu)

        manager.register('statusbar',
                         [],
                         self._window.actiongroup.get_action('statusbar').activate)

        manager.register('scrollbar',
                         [],
                         self._window.actiongroup.get_action('scrollbar').activate)

        manager.register('thumbnails',
                         ['F9'],
                         self._window.actiongroup.get_action('thumbnails').activate)

        manager.register('hide_all',
                         ['i'],
                         self._window.actiongroup.get_action('hide_all').activate)

        manager.register('slideshow',
                         ['<Control>S'],
                         self._window.actiongroup.get_action('slideshow').activate)

        # Execute external command. Bind keys from 1 to 9 to commands 1 to 9.
        for i in range(1, 10):
            manager.register('execute_command_%d' % i, ['%d' % i],
                             self._execute_command, args=[i - 1])

        # What the preferences used to say about a key, now that every
        # action has its own.
        manager.take_over_moved_keys()

    def key_press_event(self, controller: Gtk.EventControllerKey,
                        keyval: int, keycode: int,
                        state: Gdk.ModifierType) -> bool:
        """Handle key press events on the main window."""

        # This is set on demand by callback functions
        self._scroll_protection = False

        # Dispatch keyboard input handling
        manager = keybindings.keybinding_manager(self._window)
        # Some keys can only be pressed with certain modifiers that
        # are irrelevant to the actual hotkey. Find out and ignore them.
        ALL_ACCELS_MASK = (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK |
                           Gdk.ModifierType.ALT_MASK)

        # The display translates a key, and the controller knows which
        # layout it was typed in.  'consumed' is the modifiers that were
        # needed to type the key, which are not part of the accelerator
        # it stands for: on a German layout an underscore is typed with
        # Shift, so Shift+minus is not Shift+underscore.  The group and
        # level the translation landed in are of no interest here.
        translated, accel_keyval, _group, _level, consumed = \
            self._window.get_display().translate_key(
                keycode, state, controller.get_group())

        if translated:
            if Gdk.keyval_to_upper(accel_keyval) != Gdk.keyval_to_lower(accel_keyval):
                # A letter is bound in lower case, with <Shift> if Shift
                # was held - whichever case it came out in.  Shift alone
                # types it in upper case, Caps Lock does too, and the two
                # together type it in lower case, each time with Shift
                # among the consumed modifiers.
                accel_keyval = Gdk.keyval_to_lower(accel_keyval)
                consumed &= ~Gdk.ModifierType.SHIFT_MASK
            elif state & Gdk.ModifierType.SHIFT_MASK:
                # A key with no case, such as Space, keeps the Shift held
                # with it as well.
                consumed &= ~Gdk.ModifierType.SHIFT_MASK

            modifiers = state & ~consumed & ALL_ACCELS_MASK
            if (accel_keyval == Gdk.KEY_Escape and not modifiers
                    and self._window.selected_pages):
                # Escape lets go of what is picked out before it does
                # what it is bound to, as it lets go of a selection
                # anywhere else: leaving fullscreen, or quitting.
                self._window.clear_selection()
            else:
                manager.execute((accel_keyval, modifiers))

        # ----------------------------------------------------------------
        # We kill the signals here for the Up, Down, Space and Enter keys,
        # or they will start fiddling with the thumbnail selector (bad).
        # ----------------------------------------------------------------
        if (keyval in (Gdk.KEY_Up, Gdk.KEY_Down,
                       Gdk.KEY_space, Gdk.KEY_KP_Enter, Gdk.KEY_KP_Up,
                       Gdk.KEY_KP_Down, Gdk.KEY_KP_Home, Gdk.KEY_KP_End,
                       Gdk.KEY_KP_Page_Up, Gdk.KEY_KP_Page_Down) or
            (keyval == Gdk.KEY_Return and
           not state & Gdk.ModifierType.ALT_MASK)):

            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def _open_popup_menu(self) -> None:
        """Open the right-click menu over the page being read.

        With the menu bar hidden it is the only menu there is, and it
        opened for a right click and nothing else.  A key press carries
        no position, so it stands in the middle of the page area, and
        the page it acts on is the one on screen rather than the one
        under the pointer.
        """
        self._window.popup_page = \
            self._window.imagehandler.get_current_page()
        area = self._window.page_area
        widgets.popup_at(self._window.popup, area,
                         area.get_width() / 2, area.get_height() / 2)

    def scroll_wheel_event(self, controller: Gtk.EventControllerScroll,
                           delta_x: float, delta_y: float) -> bool:
        """Handle a turn of the scroll wheel over the page area.

        A scroll controller says how far and along which axis, not which
        way: there is no Gdk.ScrollDirection to ask it for, and the sign
        of the delta is what carries the direction.  Down the page and
        across it - a tilt wheel, a touchpad - both scroll, and turn the
        page where there is nothing left to scroll that way, across
        reading the way the book does.  A wheel that reports both axes at
        once is taken as the vertical one, because reading a diagonal
        nudge as a page turn would jump the book about.

        The middle button is the magnifying lens, and the wheel belongs to
        whatever is under it while the lens is up.
        """
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.BUTTON2_MASK:
            return Gdk.EVENT_PROPAGATE

        self._scroll_protection = True
        pixels = prefs['number of pixels to scroll per mouse wheel event']

        if delta_y:
            down = delta_y > 0
            if state & Gdk.ModifierType.CONTROL_MASK:
                if down:
                    self._window.manual_zoom_out()
                else:
                    self._window.manual_zoom_in()
            elif prefs['smart scroll']:
                if down:
                    self._smart_scroll_down(pixels)
                else:
                    self._smart_scroll_up(pixels)
            else:
                self.scroll_with_flipping(0, pixels if down else -pixels)

        elif delta_x:
            # Which way a turn at the side goes depends on the book, and
            # is scroll_with_flipping()'s to work out.
            self.scroll_with_flipping(pixels if delta_x > 0 else -pixels, 0)

        return Gdk.EVENT_STOP

    def mouse_press_event(self, gesture: Gtk.GestureClick, n_press: int,
                          x: float, y: float) -> None:
        """Handle a mouse button going down over the page area.

        Only the buttons a click gesture can be handed reach this: GDK
        turns X11 buttons 4 and 5 into scroll events and never reports
        them as presses, so scroll_wheel_event() is where the wheel is
        answered.  The thumb buttons a mouse marks "back" and "forward"
        arrive here as 8 and 9.
        """

        # The coordinates are the page area's own, since there is no
        # root window to give them in.  Both the press and the release are
        # measured against it, and the page area does not move under the
        # pointer while it scrolls, so the comparisons still hold.
        button = gesture.get_current_button()
        state = gesture.get_current_event_state()

        if button == 1:
            # Even for a click that only raises the window: a drag it
            # starts pans from here, not from wherever the click before
            # it was.
            self._pressed_pointer_pos_x = x
            self._pressed_pointer_pos_y = y
            self._last_pointer_pos_x = x
            self._last_pointer_pos_y = y

        if self._window.was_out_of_focus:
            # This click raised the window.  gained_focus() clears the
            # flag from the idle queue, which runs before the release
            # arrives, so the release is told here instead.
            self._raising_click = True
            return

        if button == 2:
            self._window.actiongroup.get_action('lens').set_active(True)

        elif (button == 3 and
              not state & Gdk.ModifierType.ALT_MASK and
              not state & Gdk.ModifierType.SHIFT_MASK):
            self._window.cursor_handler.set_cursor_type(constants.NORMAL_CURSOR)
            # Which page the menu stands on is worth knowing by the time
            # it is answered: two of them are on screen in double page
            # mode, and the pointer has moved to the menu by then.
            self._window.popup_page = self._window.page_at(x, y)
            # A gesture that fires is on a widget; the window is where
            # the popup is parented anyway.
            over = gesture.get_widget() or self._window
            widgets.popup_at(self._window.popup, over, x, y)

        elif button == 8:
            # The thumb button marked "back".  A book has no history to
            # go back through, so the page before this one is what going
            # back means in one.
            self._flip_page(-1)

        elif button == 9:
            self._window.show_info_panel()

    def mouse_cancel_event(self, gesture: Gtk.GestureClick,
                           sequence: "Gdk.EventSequence | None") -> None:
        """Put away the lens a press of another button cut short.

        A second button pressed while the middle one holds the lens up
        is not reported as a press: GTK cancels the middle button's
        click instead, and both releases come unpaired.  The release
        that would have put the lens away never arrived, and the lens
        stayed up after both buttons were let go (upstream bug 70).
        """
        if gesture.get_current_button() == 2:
            self._window.actiongroup.get_action('lens').set_active(False)

    def mouse_release_event(self, gesture: Gtk.GestureClick, n_press: int,
                            x: float, y: float) -> None:
        """Handle mouse button release events on the main layout area."""

        button = gesture.get_current_button()
        state = gesture.get_current_event_state()

        self._window.cursor_handler.set_cursor_type(constants.NORMAL_CURSOR)

        raising, self._raising_click = self._raising_click, False
        if raising:
            return

        if (button == 1):

            if x == self._pressed_pointer_pos_x and \
                    y == self._pressed_pointer_pos_y and \
                    not self._window.was_out_of_focus:

                if self._is_swap_gesture(state):
                    # Marking a page to swap with another, which is the
                    # picking-out gesture with something added: the two
                    # are the two ways of naming a page with the mouse.
                    self._window.mark_for_swap(self._window.page_at(x, y))
                elif state & Gdk.ModifierType.CONTROL_MASK:
                    # Picking a page out rather than turning it: a plain
                    # click is how a book is read, and it cannot be the
                    # gesture that stops on a page as well.
                    self._window.select_page(self._window.page_at(x, y))
                elif state & Gdk.ModifierType.SHIFT_MASK:
                    self._flip_page(10)
                else:
                    self._flip_page(1)

            elif self._is_swap_gesture(state) \
                    and not self._window.was_out_of_focus:
                # The same two pages, named by dragging one onto the
                # other rather than by clicking each in turn, which is
                # what a spread the wrong way round asks for.
                self._swap_dragged(x, y)
            else:
                self._window.was_out_of_focus = False

        elif button == 2:
            self._window.actiongroup.get_action('lens').set_active(False)

        elif button == 3:
            if state & Gdk.ModifierType.ALT_MASK:
                self._flip_page(-1)
            elif state & Gdk.ModifierType.SHIFT_MASK:
                self._flip_page(-10)

    @staticmethod
    def _is_swap_gesture(state: Gdk.ModifierType) -> bool:
        """Whether <state> is the modifiers a swap is asked for with."""
        return bool(state & Gdk.ModifierType.CONTROL_MASK
                    and state & Gdk.ModifierType.SHIFT_MASK)

    def _swap_dragged(self, x: float, y: float) -> None:
        """Swap the page the drag started on with the one it ended on.

        Nothing happens where either end is not on a page, or where
        both are on the same one: a drag that begins and ends on one
        page is the reader changing their mind.
        """
        first = self._window.page_at(self._pressed_pointer_pos_x,
                                     self._pressed_pointer_pos_y)
        second = self._window.page_at(x, y)
        if first is None or second is None or first == second:
            return
        self._window.file_actions.swap_pages(first, second)

    def mouse_move_event(self, controller: Gtk.EventControllerMotion,
                         x: float, y: float) -> None:
        """Handle mouse pointer movement events."""

        # Only the page area brings the cursor back, so it stays hidden
        # while a modal dialog is up.  There is no hook on the whole
        # event stream to do better with.
        self._window.cursor_handler.refresh()

        state = controller.get_current_event_state()
        if not state & Gdk.ModifierType.BUTTON1_MASK:
            return
        if self._is_swap_gesture(state):
            # A page being dragged onto another is not the view being
            # dragged about: the pages have to stay where they are for
            # the drag to end on the one it was aimed at.
            return
        self._window.cursor_handler.set_cursor_type(constants.GRAB_CURSOR)
        self._window.scroll(self._last_pointer_pos_x - x,
                            self._last_pointer_pos_y - y)
        self._last_pointer_pos_x = x
        self._last_pointer_pos_y = y

    def drag_n_drop_event(self, target: Gtk.DropTarget,
                          value: Gdk.FileList, x: float,
                          y: float) -> bool:
        """Handle a drop of files on the main layout area."""
        # The drag source is inside MComix itself, so we ignore.
        drop = target.get_current_drop()
        if drop is not None and drop.get_drag() is not None:
            return False

        # A Gdk.FileList carries the files themselves, so there are no
        # URIs left to unquote and turn back into paths by hand.
        paths = [path for path in
                 (dropped.get_path() for dropped in value.get_files())
                 if path is not None]

        if not paths:
            return False

        if len(paths) > 1:
            self._window.filehandler.open_file(paths)
        else:
            self._window.filehandler.open_file(paths[0])

        return True

    def scroll_with_flipping(self, x: float, y: float) -> bool:
        """Handle scrolling with the scroll wheel or the arrow keys, for which
        the pages might be flipped depending on the preferences.  Returns True
        if able to scroll without flipping and False if a new page was flipped
        to.
        """

        self._scroll_protection = True

        if self._window.scroll(x, y):
            self._extra_scroll_events = 0
            return True

        if y > 0 or (self._window.is_manga_mode and x < 0) or (
          not self._window.is_manga_mode and x > 0):
            page_flipped = self._next_page_with_protection()
        else:
            page_flipped = self._previous_page_with_protection()

        return not page_flipped

    def _scroll_down(self) -> None:
        """ Scrolls down. """
        self.scroll_with_flipping(0, prefs['number of pixels to scroll per key event'])

    def _scroll_up(self) -> None:
        """ Scrolls up. """
        self.scroll_with_flipping(0, -prefs['number of pixels to scroll per key event'])

    def _scroll_right(self) -> None:
        """ Scrolls right. """
        self.scroll_with_flipping(prefs['number of pixels to scroll per key event'], 0)

    def _scroll_left(self) -> None:
        """ Scrolls left. """
        self.scroll_with_flipping(-prefs['number of pixels to scroll per key event'], 0)

    def _smart_scroll_down(self, small_step: int | None = None) -> None:
        """Take one smart scrolling step along the reading order.

        <small_step> is how far to move in pixels, which the wheel gives;
        the keyboard gives none and gets a fraction of the page instead.
        """
        self._smart_scrolling(small_step, False)

    def _smart_scroll_up(self, small_step: int | None = None) -> None:
        """Take one smart scrolling step back against the reading order."""
        self._smart_scrolling(small_step, True)

    def _smart_scrolling(self, small_step: int | None,
                         backwards: bool) -> None:
        """Move one step through the page the way a comic is read.

        Sideways until the page runs out that way, then down and back to
        the near edge, rather than straight down - so that a page too wide
        for the window is read a column at a time.

        <small_step> caps the step in pixels and is what the wheel asks
        for; without one the cap is a fraction of the visible area, which
        is what "smart scroll percentage" holds - a fraction rather than
        the percentage its name says, since the preferences dialog shows
        percent and divides by a hundred on the way in.  The cap is given
        per axis, so there is one for each of the two the layout has.

        Which axis is stepped along first is what "invert smart scroll"
        turns round: sideways-then-down against down-then-sideways.

        scroll_smartly() answers with the page the viewport ended up on,
        or with an index outside the layout where there was nothing left
        to scroll to - and then the page is turned rather than redrawn,
        through the protection so that reaching the bottom does not run
        straight on into the next page.
        """
        viewport_size = self._window.get_visible_area_size()
        if small_step is None:
            fraction = prefs['smart scroll percentage']
            max_scroll = [fraction * viewport_size[0],
                          fraction * viewport_size[1]]
        else:
            max_scroll = [small_step] * len(viewport_size)
        axis_map = constants.SWAPPED_AXES if prefs['invert smart scroll'] \
            else constants.NORMAL_AXES
        self._window.update_layout_position()

        new_index = self._window.layout.scroll_smartly(
            max_scroll, backwards, axis_map)

        if new_index == -1:
            self._previous_page_with_protection()
        elif new_index == self._window.displayed_page_count():
            self._next_page_with_protection()
        else:
            self._window.update_viewport_position()

    def _next_page_with_protection(self) -> bool:
        """Advance a page, unless the reader should scroll on first.

        Returns True when the page was turned.

        Nothing happens at all while the "flip with wheel" preference is
        off, since scrolling past the end of a page is the only thing
        that arrives here.  When it is on and the scroll protection is
        armed, the end of the page has to be hit as many times as
        "number of key presses before page turn" says before the page
        turns, so that scrolling down to the bottom does not run
        straight on into the next page.  A page that does not scroll at
        all has no end to overshoot and turns on the first attempt.

        What arms the protection is a wheel event, or one of the plain
        scroll bindings.  A key press clears it before anything is
        dispatched, so smart scrolling from the keyboard turns the page
        as soon as the page runs out.

        The count of attempts is signed - forwards counts up and
        backwards counts down - and changing direction restarts it
        rather than working off what was counted the other way.
        """

        if not prefs['flip with wheel']:
            self._extra_scroll_events = 0
            return False

        if (not self._scroll_protection
                or self._extra_scroll_events >= prefs['number of key presses before page turn'] - 1
                or not self._window.is_scrollable()):

            self._flip_page(1)
            return True

        # The protection is armed - the branch above is taken when it is
        # not - so this is an overshoot to be counted rather than turned
        # on.
        self._extra_scroll_events = max(1, self._extra_scroll_events + 1)
        return False

    def _previous_page_with_protection(self) -> bool:
        """Go back a page, unless the reader should scroll on first.

        The mirror image of _next_page_with_protection(), which explains
        the protection.  The count of attempts runs negative in this
        direction.  Returns True when the page was turned.
        """

        if not prefs['flip with wheel']:
            self._extra_scroll_events = 0
            return False

        if (not self._scroll_protection
                or self._extra_scroll_events <= -prefs['number of key presses before page turn'] + 1
                or not self._window.is_scrollable()):

            self._flip_page(-1)
            return True

        self._extra_scroll_events = min(-1, self._extra_scroll_events - 1)
        return False

    def reset_extra_scroll_events(self) -> None:
        """Forget the scrolls past the edge of the page counted so far.

        They turn the page once there are as many as the preference
        'number of key presses before page turn' asks for, so a change
        to that number starts the count again.
        """
        self._extra_scroll_events = 0

    def _flip_page(self, number_of_pages: int,
                   single_step: bool = False) -> None:
        """Turn <number_of_pages> pages, forwards or backwards.

        In double page mode a turn of one page moves two, unless
        <single_step> asks for the single page.  Any scroll attempts
        counted towards a page turn are forgotten, because they were
        counted against a page that is about to stop being the current
        one.
        """
        self._extra_scroll_events = 0
        self._window.flip_page(number_of_pages, single_step=single_step)

    def _left_right_page_progress(self, number_of_pages: int = 1,
                                  single_step: bool = False) -> None:
        """Turn <number_of_pages> towards the right of the book.

        A book read left to right has its next page on the right, so a
        positive <number_of_pages> goes forward; in manga mode the book
        reads the other way and the same number goes back.  This is what
        the ALT and arrow bindings want, and what a sideways turn of the
        wheel wants: the reader asks for the page in a direction on
        screen rather than for the next or previous one.
        """
        self._flip_page(-number_of_pages if self._window.is_manga_mode
                        else number_of_pages, single_step=single_step)

    def _execute_command(self, cmdindex: int) -> None:
        """ Execute an external command. cmdindex should be an integer from 0 to 9,
        representing the command that should be executed. """
        manager = openwith.OpenWithManager()
        commands = [cmd for cmd in manager.get_commands() if not cmd.is_separator()]
        if len(commands) > cmdindex:
            commands[cmdindex].execute(self._window)


# vim: expandtab:sw=4:ts=4
