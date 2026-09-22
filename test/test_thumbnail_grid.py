"""The grid widget behind the archive editor and the library.

This is what a Gtk.IconView was. Two of the things that view did for
itself are hand-written here and so are worth pinning: selecting more
than one entry, which is the Gtk.MultiSelection the model is wrapped in,
and reordering by dragging, which is a drag source and a drop target on
every cell.
"""

import time

from gi.repository import GdkPixbuf, Gtk

from . import MComixTest, pump

from mcomix import thumbnail_list


class ThumbnailGridViewTest(MComixTest):

    NAMES = ('one', 'two', 'three', 'four', 'five')

    def setUp(self):
        super().setUp()
        self.asked = []
        self.view = thumbnail_list.ThumbnailGridView()
        self.view.generate_thumbnail = self._generate
        self.view.set_thumbnail_size(48)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_child(self.view)
        self.window = Gtk.Window()
        self.window.set_default_size(400, 400)
        self.window.set_child(self.scroller)
        self.window.present()
        pump()
        self.view.set_items(
            thumbnail_list.ThumbnailItem(name, tooltip=name)
            for name in self.NAMES)
        self._settle()

    def tearDown(self):
        self.view.stop_update()
        # A window left on screen is answered by whatever looks for one
        # next.
        self.window.destroy()
        pump()
        super().tearDown()

    def _generate(self, uid):
        self.asked.append(uid)
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                      32, 48)
        pixbuf.fill(0x336699ff)
        return pixbuf

    def _settle(self):
        for _ in range(20):
            pump()
            self.scroller.allocate(400, 400, -1, None)

    def _order(self):
        return [item.uid for item in self.view.each_item()]

    # -- What is in it ----------------------------------------------------

    def test_the_entries_are_the_ones_that_were_set(self):
        self.assertEqual(self._order(), list(self.NAMES))

    def test_an_entry_can_be_added_to_the_end(self):
        self.view.append_item(thumbnail_list.ThumbnailItem('six'))
        self.assertEqual(self._order(), list(self.NAMES) + ['six'])

    def test_a_thumbnail_is_asked_for(self):
        self.assertTrue(self.asked, 'nothing was asked for at all')

    # -- Reordering -------------------------------------------------------

    def test_moving_an_entry_later_puts_it_where_it_was_dropped(self):
        self.assertTrue(self.view.move_item(0, 2))
        self.assertEqual(self._order(),
                         ['two', 'three', 'one', 'four', 'five'])

    def test_moving_an_entry_earlier_puts_it_where_it_was_dropped(self):
        self.assertTrue(self.view.move_item(3, 1))
        self.assertEqual(self._order(),
                         ['one', 'four', 'two', 'three', 'five'])

    def test_moving_an_entry_onto_itself_changes_nothing(self):
        self.assertFalse(self.view.move_item(2, 2))
        self.assertEqual(self._order(), list(self.NAMES))

    def test_moving_from_or_to_nowhere_changes_nothing(self):
        self.assertFalse(self.view.move_item(-1, 2))
        self.assertFalse(self.view.move_item(0, len(self.NAMES)))
        self.assertEqual(self._order(), list(self.NAMES))

    def test_a_drop_carrying_something_else_is_refused(self):
        cell = next(iter(self.view._each_cell()))
        self.assertFalse(
            self.view._reorder_drop(None, 'text/plain:0', 0.0, 0.0, cell))
        self.assertFalse(
            self.view._reorder_drop(None, 'application/x-mcomix-thumbnail'
                                    '-position:nowhere', 0.0, 0.0, cell))
        self.assertEqual(self._order(), list(self.NAMES))

    def test_the_drag_carries_the_position_it_started_from(self):
        cell = next(iter(self.view._each_cell()))
        provider = self.view._reorder_prepare(None, 0.0, 0.0, cell)
        self.assertIsNotNone(provider)

    def test_a_cell_says_where_it_sits_now_not_where_it_was_bound(self):
        """GTK does not bind a cell again for entries removed before it,
        so a position remembered from the last bind was as many places
        along as there were entries removed - which is where the archive
        editor's right click and its reordering drag both landed."""
        self.view.remove_positions([0, 1])
        self._settle()
        self.assertEqual(self._order(), ['three', 'four', 'five'])
        self.assertEqual([cell.position for cell in self.view._each_cell()],
                         [0, 1, 2])

    def test_a_drop_after_a_removal_lands_on_the_cell_it_was_made_on(self):
        self.view.remove_positions([0, 1])
        self._settle()
        cell = next(iter(self.view._each_cell()))
        self.assertTrue(self.view._reorder_drop(
            None, 'application/x-mcomix-thumbnail-position:2',
            0.0, 0.0, cell))
        self.assertEqual(self._order(), ['five', 'three', 'four'])

    def test_a_cell_showing_nothing_sits_nowhere(self):
        cell = next(iter(self.view._each_cell()))
        self.view.clear()
        self._settle()
        self.assertEqual(cell.position, -1)

    # -- Selection --------------------------------------------------------

    def test_nothing_is_selected_to_begin_with(self):
        self.assertEqual(self.view.get_selected_positions(), [])

    def test_selecting_one_entry_deselects_the_rest(self):
        self.view.select_only(1)
        self.view.select_only(3)
        self.assertEqual(self.view.get_selected_positions(), [3])

    def test_more_than_one_entry_can_be_selected(self):
        self.view.selection.select_item(0, True)
        self.view.selection.select_item(2, False)
        self.assertEqual(self.view.get_selected_positions(), [0, 2])

    def test_the_selected_entries_come_back_in_order(self):
        self.view.selection.select_item(3, True)
        self.view.selection.select_item(1, False)
        self.assertEqual([item.uid for item in self.view.get_selected_items()],
                         ['two', 'four'])

    def test_unselecting_leaves_nothing_selected(self):
        self.view.selection.select_item(0, True)
        self.view.unselect_all()
        self.assertEqual(self.view.get_selected_positions(), [])

    # -- Removal ----------------------------------------------------------

    def test_removing_several_entries_removes_those_and_no_others(self):
        # remove_positions() collects the items before it drops any of
        # them: removing the first would otherwise shift every position
        # after it and take the wrong ones.
        self.view.remove_positions([0, 2, 4])
        self.assertEqual(self._order(), ['two', 'four'])

    def test_removing_nothing_removes_nothing(self):
        self.view.remove_positions([])
        self.assertEqual(self._order(), list(self.NAMES))

    def test_removing_a_position_that_is_not_there_is_ignored(self):
        self.view.remove_positions([99, -1, 1])
        self.assertEqual(self._order(),
                         ['one', 'three', 'four', 'five'])

    def test_clearing_empties_the_grid(self):
        self.view.clear()
        self.assertEqual(self._order(), [])

    # -- Sorting ----------------------------------------------------------

    @staticmethod
    def _by_uid():
        return Gtk.CustomSorter.new(
            lambda left, right, data: (left.uid > right.uid)
            - (left.uid < right.uid))

    def test_a_sorter_decides_the_order_the_entries_are_shown_in(self):
        self.view.set_sorter(self._by_uid())
        self.assertEqual(self._order(), sorted(self.NAMES))

    def test_taking_the_sorter_away_restores_the_order_they_were_added_in(self):
        self.view.set_sorter(self._by_uid())
        self.view.set_sorter(None)
        self.assertEqual(self._order(), list(self.NAMES))

    def test_a_position_means_where_an_entry_is_shown_not_where_it_is_kept(self):
        self.view.set_sorter(self._by_uid())
        # 'five' sorts first; it was added fifth.
        self.assertEqual(self.view.get_item(0).uid, 'five')

    def test_removing_by_position_removes_what_is_shown_there(self):
        self.view.set_sorter(self._by_uid())
        # Sorted: five, four, one, three, two.
        self.view.remove_positions([0, 2])
        self.assertEqual(self._order(), ['four', 'three', 'two'])

    def test_the_selected_entries_are_read_in_shown_order_too(self):
        self.view.set_sorter(self._by_uid())
        self.view.selection.select_item(0, True)
        self.view.selection.select_item(1, False)
        self.assertEqual([item.uid for item in self.view.get_selected_items()],
                         ['five', 'four'])


class MovingAScrolledEntryTest(MComixTest):

    """Moving the entry that has the focus, far down a long grid.

    A click or a drag gives the entry under the pointer the keyboard
    focus, and taking the focused entry out of the model made GTK focus
    another and scroll back to the top: every page moved in the archive
    editor threw the view back to page one.
    """

    def setUp(self):
        super().setUp()
        self.view = thumbnail_list.ThumbnailGridView()
        self.view.generate_thumbnail = lambda uid: None
        self.view.set_thumbnail_size(48)
        self.view.set_reorderable(True)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.view)
        self.window = Gtk.Window()
        self.window.set_default_size(300, 300)
        self.window.set_child(scroller)
        self.window.present()
        self.view.set_items(thumbnail_list.ThumbnailItem(uid)
                            for uid in range(200))
        self._settle()
        self.adjustment = scroller.get_vadjustment()
        self.adjustment.set_value(self.adjustment.get_upper() / 2)
        self._settle()

    def tearDown(self):
        self.view.release()
        self.window.destroy()
        super().tearDown()

    @staticmethod
    def _settle():
        # The scroll happens when the view is next laid out, which is a
        # frame away rather than an idle one.
        for _ in range(25):
            pump()
            time.sleep(0.02)

    def _focused_cell(self):
        cells = [cell for cell in self.view._each_cell()
                 if cell.get_mapped()
                 and cell.compute_bounds(self.window)[1].get_y() > 0]
        cell = min(cells, key=lambda cell: cell.position)
        # The cell's list item is what a click focuses.
        cell.get_parent().grab_focus()
        return cell.position

    def test_the_view_stays_where_the_entry_was_dropped(self):
        position = self._focused_cell()
        before = self.adjustment.get_value()

        self.assertTrue(self.view.move_item(position, position + 4))
        self._settle()

        self.assertEqual(self.adjustment.get_value(), before)

    def test_the_moved_entry_keeps_the_focus(self):
        position = self._focused_cell()
        moved = self.view.get_item(position)

        self.view.move_item(position, position + 4)
        self._settle()

        focused = self.window.get_focus()
        self.assertIsNotNone(focused)
        self.assertIs(self.view.get_item(focused.get_first_child().position),
                      moved)

# vim: expandtab:sw=4:ts=4
