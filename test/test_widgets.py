"""The helpers for widgets whose API changed in GTK4.

popup_at() is the one with something to get wrong: a Gtk.Menu was
popped up at the pointer with an event, and a Gtk.PopoverMenu is
parented to a widget and pointed at a rectangle in that widget's
coordinates - which is not the widget the pointer was over.
"""

from gi.repository import Gio, Gtk

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


# vim: expandtab:sw=4:ts=4
