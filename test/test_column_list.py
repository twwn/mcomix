# -*- coding: utf-8 -*-

"""The rows-and-columns list behind MComix' several list dialogs.

This is what a Gtk.TreeView over a Gtk.ListStore was. What the store
kept in numbered columns is a plain attribute on a row here, and what a
cell renderer drew is an ordinary widget, so the things worth pinning
are the ones the TreeView did for itself: reading a row back, selecting
one, and answering which row is under the pointer.
"""

from gi.repository import Gdk, Gtk

from . import MComixTest, pump

from mcomix import column_list


class ColumnListViewTest(MComixTest):

    NAMES = ('one', 'two', 'three')

    def setUp(self):
        super(ColumnListViewTest, self).setUp()
        self.view = column_list.ColumnListView()
        self.view.add_text_column('Name', 'name', expand=True)
        self.view.add_text_column('Size', 'size')
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_child(self.view)
        self.window = Gtk.Window()
        self.window.set_default_size(400, 300)
        self.window.set_child(self.scroller)
        self.window.present()
        pump()
        self.view.set_rows(column_list.Row(name=name, size=str(len(name)))
                           for name in self.NAMES)
        self._settle()

    def tearDown(self):
        # A window left on screen is answered by whatever looks for one
        # next.
        self.window.destroy()
        pump()
        super(ColumnListViewTest, self).tearDown()

    def _settle(self):
        for _ in range(20):
            pump()
            self.scroller.allocate(400, 300, -1, None)

    def _names(self):
        return [row.name for row in self.view.each_row()]

    def _cells(self):
        """The text of every cell that is on screen, whatever column."""
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.Label):
                    found.append(child.get_text())
                walk(child)
                child = child.get_next_sibling()

        walk(self.view)
        return found

    # -- What is in it ----------------------------------------------------

    def test_the_rows_are_the_ones_that_were_set(self):
        self.assertEqual(self._names(), list(self.NAMES))

    def test_setting_rows_again_replaces_the_ones_that_were_there(self):
        self.view.set_rows([column_list.Row(name='only', size='4')])
        self.assertEqual(self._names(), ['only'])

    def test_a_row_can_be_added_to_the_end(self):
        self.view.append_row(column_list.Row(name='four', size='4'))
        self.assertEqual(self._names(), list(self.NAMES) + ['four'])

    def test_a_row_can_be_taken_out(self):
        row = self.view.get_row(1)
        self.assertTrue(self.view.remove_row(row))
        self.assertEqual(self._names(), ['one', 'three'])

    def test_taking_out_a_row_that_is_not_there_says_so(self):
        self.assertFalse(self.view.remove_row(column_list.Row(name='no')))
        self.assertEqual(self._names(), list(self.NAMES))

    def test_clearing_empties_the_list(self):
        self.view.clear()
        self.assertEqual(self._names(), [])

    # -- What it draws ----------------------------------------------------

    def test_a_column_shows_the_attribute_it_was_given(self):
        cells = self._cells()
        for name in self.NAMES:
            self.assertIn(name, cells)

    def test_a_row_that_changed_redraws_itself(self):
        row = self.view.get_row(0)
        row.name = 'renamed'
        row.changed()
        self._settle()
        self.assertIn('renamed', self._cells())

    def test_a_column_can_read_the_text_off_the_row_itself(self):
        view = column_list.ColumnListView()
        view.add_text_column('Shouted', 'name',
                             text=lambda row: row.name.upper())
        view.set_rows([column_list.Row(name='quiet')])
        self.assertEqual([row.name for row in view.each_row()], ['quiet'])

    # -- Selection --------------------------------------------------------

    def test_nothing_is_selected_to_begin_with(self):
        """A Gtk.SingleSelection selects the first row on its own.

        A Gtk.TreeView did not, and the dialogs built on this one ask
        whether anything is selected to decide what their buttons do.
        """
        self.assertIsNone(self.view.get_selected_row())

    def test_selecting_a_row_by_identity_finds_it(self):
        row = self.view.get_row(2)
        self.assertTrue(self.view.select_row(row))
        self.assertIs(self.view.get_selected_row(), row)

    def test_selecting_a_row_that_is_not_shown_says_so(self):
        self.assertFalse(self.view.select_row(column_list.Row(name='no')))

    def test_selecting_one_row_deselects_the_one_before(self):
        self.view.select_only(0)
        self.view.select_only(2)
        self.assertEqual(self.view.get_selected_positions(), [2])

    def test_unselecting_leaves_nothing_selected(self):
        self.view.select_only(1)
        self.view.unselect_all()
        self.assertEqual(self.view.get_selected_positions(), [])

    def test_more_than_one_row_can_be_selected_where_that_was_asked_for(self):
        view = column_list.ColumnListView(multiple=True)
        view.add_text_column('Name', 'name')
        view.set_rows(column_list.Row(name=name) for name in self.NAMES)
        view.selection.select_item(0, True)
        view.selection.select_item(2, False)
        self.assertEqual(view.get_selected_positions(), [0, 2])

    # -- Where the pointer is ---------------------------------------------

    def test_no_row_is_under_a_point_outside_the_list(self):
        self.assertIsNone(self.view.row_at(-10.0, -10.0))

    def test_the_row_under_a_point_is_the_one_drawn_there(self):
        found = [self.view.row_at(20.0, y) for y in range(0, 200, 5)]
        found = [row for row in found if row is not None]
        self.assertTrue(found, 'no row was found anywhere in the list')
        self.assertIn(found[0], list(self.view.each_row()))

    # -- Reordering -------------------------------------------------------

    def test_moving_a_row_later_puts_it_where_it_was_dropped(self):
        self.assertTrue(self.view.move_row(0, 2))
        self.assertEqual(self._names(), ['two', 'three', 'one'])

    def test_moving_a_row_earlier_puts_it_where_it_was_dropped(self):
        self.assertTrue(self.view.move_row(2, 0))
        self.assertEqual(self._names(), ['three', 'one', 'two'])

    def test_moving_a_row_onto_itself_changes_nothing(self):
        self.assertFalse(self.view.move_row(1, 1))
        self.assertEqual(self._names(), list(self.NAMES))

    def test_moving_from_or_to_nowhere_changes_nothing(self):
        self.assertFalse(self.view.move_row(-1, 1))
        self.assertFalse(self.view.move_row(0, len(self.NAMES)))
        self.assertEqual(self._names(), list(self.NAMES))

    def test_a_drop_carrying_something_else_is_refused(self):
        self.view.set_reorderable(True)
        cells = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, column_list._TextCell):
                    cells.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(self.view)
        self.assertTrue(cells, 'no cell was drawn to drop onto')
        cell = cells[0]
        self.assertFalse(
            self.view._reorder_drop(None, 'text/plain:0', 0.0, 0.0, cell))
        self.assertFalse(
            self.view._reorder_drop(None, 'application/x-mcomix-row-position'
                                    ':nowhere', 0.0, 0.0, cell))
        self.assertEqual(self._names(), list(self.NAMES))

    # -- Finding a row by typing ------------------------------------------

    def test_typing_the_first_letters_of_a_name_selects_that_row(self):
        self.view.set_search_attribute('name')
        self.assertTrue(self.view._search_typed(None, ord('t'), 0,
                                                Gdk.ModifierType(0)))
        self.assertTrue(self.view._search_typed(None, ord('h'), 0,
                                                Gdk.ModifierType(0)))
        self.assertEqual([row.name for row in self.view.get_selected_rows()],
                         ['three'])

    def test_typing_something_no_row_starts_with_selects_nothing(self):
        self.view.set_search_attribute('name')
        self.assertFalse(self.view._search_typed(None, ord('z'), 0,
                                                 Gdk.ModifierType(0)))
        self.assertEqual(self.view.get_selected_rows(), [])

    def test_a_shortcut_is_left_to_whoever_wants_it(self):
        self.view.set_search_attribute('name')
        self.assertFalse(self.view._search_typed(
            None, ord('t'), 0, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(self.view.get_selected_rows(), [])

    # -- Rows under rows --------------------------------------------------

    def test_a_tree_shows_only_the_top_level_until_it_is_expanded(self):
        view = column_list.ColumnListView(tree=True)
        view.add_text_column('Name', 'name')
        view.set_rows([column_list.Row(
            name='group', children=[column_list.Row(name='under')])])
        self.assertEqual([row.name for row in view.each_row()], ['group'])
        view.expand_all()
        self.assertEqual([row.name for row in view.each_row()],
                         ['group', 'under'])

    def test_a_row_with_no_children_is_not_expandable(self):
        view = column_list.ColumnListView(tree=True)
        view.add_text_column('Name', 'name')
        view.set_rows([column_list.Row(name='alone')])
        view.expand_all()
        self.assertEqual([row.name for row in view.each_row()], ['alone'])

    def test_a_row_of_a_tree_is_read_back_without_its_wrapper(self):
        """A Gtk.TreeListModel hands out a Gtk.TreeListRow around each
        row, which is not what any caller wants back."""
        view = column_list.ColumnListView(tree=True)
        view.add_text_column('Name', 'name')
        row = column_list.Row(name='group', children=[])
        view.set_rows([row])
        self.assertIs(view.get_row(0), row)

    # -- Shortcuts --------------------------------------------------------

    def test_an_accelerator_column_reports_what_was_pressed(self):
        view = column_list.ColumnListView()
        rebound = []
        view.add_accel_column('Key', 'key',
                              lambda row, accel: rebound.append((row, accel)))
        row = column_list.Row(key='<Control>a')
        view.set_rows([row])
        window = Gtk.Window()
        window.set_child(view)
        window.present()
        try:
            for _ in range(20):
                pump()
                view.allocate(400, 300, -1, None)
            cells = []

            def walk(widget):
                child = widget.get_first_child()
                while child is not None:
                    if isinstance(child, column_list._AccelCell):
                        cells.append(child)
                    walk(child)
                    child = child.get_next_sibling()

            walk(view)
            self.assertTrue(cells, 'the column drew no cell')
            cell = cells[0]
            # The shortcut is drawn as the keyboard names it, which is
            # what a Gtk.CellRendererAccel drew.
            self.assertEqual(
                cell.label.get_text(),
                Gtk.accelerator_get_label(*Gtk.accelerator_parse('<Control>a')[1:]))
            # Nothing is taken until the cell has been clicked.
            self.assertFalse(
                cell._pressed(None, Gdk.KEY_b, 0, Gdk.ModifierType.CONTROL_MASK))
            cell.emit('clicked')
            self.assertEqual(cell.label.get_text(),
                             column_list._ASK_FOR_ONE_HINT)
            self.assertTrue(
                cell._pressed(None, Gdk.KEY_b, 0, Gdk.ModifierType.CONTROL_MASK))
            self.assertEqual(rebound, [(row, '<Control>b')])
            # Backspace clears it, escape leaves it alone.
            cell.emit('clicked')
            self.assertTrue(cell._pressed(None, Gdk.KEY_BackSpace, 0,
                                          Gdk.ModifierType(0)))
            self.assertEqual(rebound[-1], (row, None))
            cell.emit('clicked')
            self.assertTrue(cell._pressed(None, Gdk.KEY_Escape, 0,
                                          Gdk.ModifierType(0)))
            self.assertEqual(len(rebound), 2)
        finally:
            window.destroy()
            pump()

    def test_a_row_that_takes_no_shortcut_holds_the_column_open_anyway(self):
        """A group heading stands over the actions under it and has no
        shortcut of its own, so its cell is empty and cannot be pressed.

        It is not hidden, though: a Gtk.ColumnView sizes a column from
        the cells that are on screen, and a hidden cell asks for no
        width, so a list showing only headings drew its shortcut
        columns too narrow even for their own headings.
        """
        view = column_list.ColumnListView()
        view.add_accel_column('Key', 'key', lambda row, accel: None,
                              bindable=lambda row: row.key is not None)
        view.set_rows([column_list.Row(key=None),
                       column_list.Row(key='<Control>a')])
        window = Gtk.Window()
        window.set_child(view)
        window.present()
        try:
            for _ in range(20):
                pump()
                view.allocate(400, 300, -1, None)
            cells = []

            def walk(widget):
                child = widget.get_first_child()
                while child is not None:
                    if isinstance(child, column_list._AccelCell):
                        cells.append(child)
                    walk(child)
                    child = child.get_next_sibling()

            walk(view)
            self.assertEqual(len(cells), 2, 'the column drew the wrong cells')
            self.assertTrue(cells[0].get_visible())
            self.assertFalse(cells[0].get_sensitive())
            self.assertEqual(cells[0].label.get_text(), '')
            self.assertTrue(cells[1].get_sensitive())
        finally:
            window.destroy()
            pump()

    def test_an_accelerator_cell_is_the_same_width_whatever_it_shows(self):
        """A Gtk.ColumnView asks the cells that are on screen how wide
        the column should be, where a Gtk.TreeView asked the whole
        model, so a cell that measured what it holds made the column a
        different width every time the list was scrolled - and a column
        of Gtk.ShortcutLabels, which cannot be drawn narrower than the
        key caps they hold, took that width out of the column beside
        it."""
        window = Gtk.Window()
        box = Gtk.Box()
        window.set_child(box)
        window.present()
        try:
            pump()
            empty = column_list._AccelCell()
            long = column_list._AccelCell()
            long.accelerator = '<Control><Shift>Page_Up'
            long._show()
            for cell in (empty, long):
                box.append(cell)
            pump()
            self.assertEqual(
                empty.measure(Gtk.Orientation.HORIZONTAL, -1)[1],
                long.measure(Gtk.Orientation.HORIZONTAL, -1)[1])
        finally:
            window.destroy()
            pump()

    # -- Checkboxes and choices -------------------------------------------

    def test_a_toggle_column_reports_the_click_with_the_row_it_was_in(self):
        view = column_list.ColumnListView()
        toggled = []
        view.add_toggle_column('On', 'on',
                               lambda row, state: toggled.append((row, state)))
        row = column_list.Row(on=False)
        view.set_rows([row])
        window = Gtk.Window()
        window.set_child(view)
        window.present()
        try:
            for _ in range(20):
                pump()
                view.allocate(400, 300, -1, None)
            boxes = []

            def walk(widget):
                child = widget.get_first_child()
                while child is not None:
                    if isinstance(child, Gtk.CheckButton):
                        boxes.append(child)
                    walk(child)
                    child = child.get_next_sibling()

            walk(view)
            self.assertTrue(boxes, 'the column drew no checkbox')
            boxes[0].set_active(True)
            self.assertEqual(toggled, [(row, True)])
        finally:
            window.destroy()
            pump()

# vim: expandtab:sw=4:ts=4
