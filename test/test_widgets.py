"""The helpers for widgets whose API changed in GTK4.

popup_at() is the one with something to get wrong: a Gtk.Menu was
popped up at the pointer with an event, and a Gtk.PopoverMenu is
parented to a widget and pointed at a rectangle in that widget's
coordinates - which is not the widget the pointer was over.
"""

from gi.repository import Gdk, Gio, Gtk

from . import MComixTest, pump

from mcomix import widgets


class PopupAtTest(MComixTest):

    def setUp(self):
        super().setUp()
        model = Gio.Menu()
        model.append('Something', 'app.something')
        self.popover = Gtk.PopoverMenu.new_from_model(model)
        self.window = Gtk.Window()
        self.window.set_default_size(400, 300)
        self.inner = Gtk.Box()
        self.inner.set_margin_start(50)
        self.inner.set_margin_top(30)
        self.inner.set_hexpand(True)
        self.inner.set_vexpand(True)
        self.window.set_child(self.inner)
        self.window.present()
        self._settle()

    def tearDown(self):
        self.popover.popdown()
        # Nothing in the window unparents a popover it did not add, and
        # GTK warns when a widget is finalized with one still attached.
        if self.popover.get_parent() is not None:
            self.popover.unparent()
        self.window.destroy()
        pump()
        super().tearDown()

    def _settle(self):
        for _ in range(20):
            pump()
            self.window.allocate(400, 300, -1, None)

    def test_it_points_at_the_place_the_pointer_was(self):
        self.popover.set_parent(self.inner)
        widgets.popup_at(self.popover, self.inner, 20.0, 40.0)
        area = self.popover.get_pointing_to()[1]
        self.assertEqual((area.x, area.y), (20, 40))

    def test_a_point_in_another_widget_is_translated_to_the_parent(self):
        """The main window's popup is parented to the window and pointed
        at by the layout area inside it, which starts further down and
        further in: untranslated, the menu opened away from the pointer.
        """
        self.popover.set_parent(self.window)
        widgets.popup_at(self.popover, self.inner, 20.0, 40.0)
        area = self.popover.get_pointing_to()[1]
        self.assertEqual((area.x, area.y), (70, 70))

    def test_it_parents_the_popover_where_it_has_none(self):
        widgets.popup_at(self.popover, self.inner, 10.0, 10.0)
        self.assertIs(self.popover.get_parent(), self.inner)

    def test_the_menu_opens_from_the_pointer_rather_than_around_it(self):
        """A popover is centred over what it points at and put above it,
        which is right for a bubble and wrong for a menu: the pointer
        ended up in the middle of it."""
        widgets.popup_at(self.popover, self.inner, 10.0, 10.0)
        self.assertEqual(self.popover.get_halign(), Gtk.Align.START)
        self.assertEqual(self.popover.get_position(),
                         Gtk.PositionType.BOTTOM)
        self.assertFalse(self.popover.get_has_arrow())


class EmptyTest(MComixTest):

    """empty(), which is what a box is cleared with in GTK4."""

    def _children(self, box):
        children, child = [], box.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def test_every_child_comes_out(self):
        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        for _ in range(4):
            box.append(Gtk.Label())
        self.assertEqual(len(self._children(box)), 4)
        widgets.empty(box)
        self.assertEqual(self._children(box), [])

    def test_a_box_that_is_already_empty_stays_that_way(self):
        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        widgets.empty(box)
        self.assertEqual(self._children(box), [])

    def test_what_comes_out_can_go_somewhere_else(self):
        """A child that is removed is unparented rather than destroyed."""
        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        label = Gtk.Label(label='Something')
        box.append(label)
        widgets.empty(box)
        self.assertIsNone(label.get_parent())
        other = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        other.append(label)
        self.assertEqual(self._children(other), [label])


class MenuClickTest(MComixTest):

    """Which mouse button a menu item was reached with.

    A Gio menu item hands its action nothing but its target, and GTK4
    activates an item on whichever button was pressed, so the middle
    click that opens a recent file in an MComix of its own is told from
    a plain one by the press that comes before the activation.
    """

    def setUp(self):
        super().setUp()
        entries = Gio.Menu()
        entries.append('Something', 'app.something')
        submenu = Gio.Menu()
        submenu.append_submenu('More', entries)
        self.model = Gio.Menu()
        self.model.append_submenu('Menu', submenu)
        self.window = Gtk.Window()
        self.menubar = Gtk.PopoverMenuBar.new_from_model(self.model)
        self.window.set_child(self.menubar)
        self.window.set_visible(True)
        pump()
        self.addCleanup(self.window.destroy)
        # A press left over from another test would be handed to the
        # first one here that asks.
        widgets.take_middle_click()

    def _watches(self):
        return [popover for popover in widgets._menu_popovers(self.menubar)
                if any(isinstance(controller, widgets._MenuClickGesture)
                       for controller in popover.observe_controllers())]

    def _popovers(self):
        return list(widgets._menu_popovers(self.menubar))

    def test_every_popover_is_watched_submenus_included(self):
        """A Gtk.PopoverMenu is a Gtk.Native with a surface of its own,
        so a press in a submenu reaches neither the window nor the
        popover the submenu hangs off: each needs its own watch."""
        self.assertGreater(len(self._popovers()), 1,
                           'the menu has no submenu to watch')
        widgets.watch_menu_clicks(self.menubar)
        self.assertEqual(self._watches(), self._popovers())

    def test_watching_twice_leaves_one_watch(self):
        """The menus are rebuilt whenever an accelerator changes, and
        the popovers that survive it must not collect a gesture each
        time."""
        widgets.watch_menu_clicks(self.menubar)
        widgets.watch_menu_clicks(self.menubar)
        for popover in self._popovers():
            gestures = [controller
                        for controller in popover.observe_controllers()
                        if isinstance(controller, widgets._MenuClickGesture)]
            self.assertEqual(len(gestures), 1)

    def test_a_new_model_is_watched_as_well(self):
        widgets.watch_menu_clicks(self.menubar)
        self.menubar.set_menu_model(self.model)
        pump()
        widgets.watch_menu_clicks(self.menubar)
        self.assertEqual(self._watches(), self._popovers())

    def test_nothing_is_a_middle_click_until_one_happens(self):
        self.assertFalse(widgets.take_middle_click())

    def test_a_middle_press_is_reported_once(self):
        """Taken rather than read: an item activated from the keyboard
        has no press of its own, and would otherwise be handed the
        answer belonging to the last one."""
        widgets._menu_button_pressed(Gdk.BUTTON_MIDDLE)
        self.assertTrue(widgets.take_middle_click())
        self.assertFalse(widgets.take_middle_click())

    def test_another_button_clears_what_a_middle_press_set(self):
        widgets._menu_button_pressed(Gdk.BUTTON_MIDDLE)
        widgets._menu_button_pressed(Gdk.BUTTON_PRIMARY)
        self.assertFalse(widgets.take_middle_click())

    def test_the_right_button_is_not_the_middle_one(self):
        widgets._menu_button_pressed(Gdk.BUTTON_SECONDARY)
        self.assertFalse(widgets.take_middle_click())


# vim: expandtab:sw=4:ts=4


class MenuKeyTest(MComixTest):

    """The keys that ask a widget for its context menu.

    A GTK3 widget was told by its popup-menu signal, which GTK emitted
    for the menu key and for Shift+F10 alike.  A GTK4 widget hears the
    keys itself, and the port heard only one of them.
    """

    def test_the_menu_key_asks_for_the_menu(self):
        self.assertTrue(widgets.menu_key(Gdk.KEY_Menu,
                                         Gdk.ModifierType(0)))

    def test_shift_and_f10_ask_for_the_menu(self):
        self.assertTrue(widgets.menu_key(Gdk.KEY_F10,
                                         Gdk.ModifierType.SHIFT_MASK))

    def test_f10_on_its_own_does_not(self):
        # F10 alone opens the menu bar, which is GTK's to answer.
        self.assertFalse(widgets.menu_key(Gdk.KEY_F10,
                                          Gdk.ModifierType(0)))

    def test_another_modifier_with_either_key_does_not(self):
        for keyval in (Gdk.KEY_Menu, Gdk.KEY_F10):
            self.assertFalse(widgets.menu_key(
                keyval, Gdk.ModifierType.CONTROL_MASK
                | Gdk.ModifierType.SHIFT_MASK))

    def test_a_lock_key_is_not_a_modifier_here(self):
        # Caps Lock and the pointer buttons are not part of what an
        # accelerator is compared on, and must not hide the shortcut.
        self.assertTrue(widgets.menu_key(
            Gdk.KEY_F10,
            Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.LOCK_MASK))
