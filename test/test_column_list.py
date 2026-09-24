"""The rows-and-columns list behind MComix' several list dialogs.

This is what a Gtk.TreeView over a Gtk.ListStore was. What the store
kept in numbered columns is a plain attribute on a row here, and what a
cell renderer drew is an ordinary widget, so the things worth pinning
are the ones the TreeView did for itself: reading a row back, selecting
one, and answering which row is under the pointer.
"""

import unittest.mock

from gi.repository import Gdk, Gtk, Pango

from . import MComixTest, pump

from mcomix import column_list


class ColumnListViewTest(MComixTest):

    NAMES = ('one', 'two', 'three')

    def setUp(self):
        super().setUp()
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
        super().tearDown()

    def _settle(self):
        for _ in range(20):
            pump()
            self.scroller.allocate(400, 300, -1, None)

    def _names(self):
        return [row.name for row in self.view.each_row()]

    def _present(self, view):
        """Put <view> on screen, so that it draws cells to look at."""
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(view)
        window = Gtk.Window()
        window.set_default_size(400, 300)
        window.set_child(scroller)
        window.present()
        self.addCleanup(window.destroy)
        for _ in range(20):
            pump()
            scroller.allocate(400, 300, -1, None)
        return window

    def _cell_at(self, position, view=None):
        """A cell of the row drawn at <position>, whichever column."""
        for cell in self._drawn_cells(self.view if view is None else view):
            if cell.position == position:
                return cell
        return None

    @staticmethod
    def _drawn_cells(view):
        """Every text cell <view> has on screen."""
        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, column_list._TextCell):
                    found.append(child)
                walk(child)
                child = child.get_next_sibling()

        walk(view)
        return found

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

    def test_unselecting_does_not_need_the_selections_own_unselect_all(self):
        """GTK 4.14's Gtk.SingleSelection has no unselect_all(), and the
        one it inherits does nothing there; the row stayed selected."""
        with unittest.mock.patch.object(Gtk.SingleSelection, 'unselect_all',
                                        lambda selection: False):
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

    def test_a_drag_is_refused_while_a_heading_is_sorting(self):
        """A drag moves a row in the store, which is not what is shown.

        The positions a cell carries are the ones the view draws it at;
        a heading that is sorting puts the rows in an order of its own,
        so those are not the store's any more and a drop would move
        whichever row happened to sit at that number.
        """
        view = column_list.ColumnListView()
        column = view.add_text_column('Name', 'name',
                                      sort_key=lambda row: row.name)
        view.set_rows(column_list.Row(name=name) for name in self.NAMES)
        view.set_reorderable(True)
        view.sort_by(column, descending=True)
        self._present(view)
        self.assertEqual([row.name for row in view.each_row()],
                         ['two', 'three', 'one'])

        dropped = self._cell_at(2, view)
        self.assertIsNotNone(dropped, 'no cell was drawn to drop onto')
        self.assertIsNone(view._reorder_prepare(None, 0.0, 0.0, dropped))
        self.assertFalse(
            view._reorder_drop(None, 'application/x-mcomix-row-position:0',
                               0.0, 0.0, dropped))
        self.assertEqual([row.name for row in view.each_row()],
                         ['two', 'three', 'one'])
        view.sort_by(None)
        pump()
        self.assertEqual([row.name for row in view.each_row()],
                         list(self.NAMES))

    def test_a_drag_is_allowed_again_once_nothing_is_sorting(self):
        view = column_list.ColumnListView()
        column = view.add_text_column('Name', 'name',
                                      sort_key=lambda row: row.name)
        view.set_rows(column_list.Row(name=name) for name in self.NAMES)
        view.set_reorderable(True)
        view.sort_by(column, descending=True)
        view.sort_by(None)
        self._present(view)

        dropped = self._cell_at(2, view)
        self.assertIsNotNone(dropped, 'no cell was drawn to drop onto')
        self.assertIsNotNone(view._reorder_prepare(None, 0.0, 0.0, dropped))
        self.assertTrue(
            view._reorder_drop(None, 'application/x-mcomix-row-position:0',
                               0.0, 0.0, dropped))
        self.assertEqual([row.name for row in view.each_row()],
                         ['two', 'three', 'one'])

    def test_a_cell_says_where_it_sits_now_not_where_it_was_bound(self):
        """GTK does not bind a cell again for rows removed before it, so
        a position remembered from the last bind named whichever row had
        moved into that place - and a drop after a removal moved it."""
        self.view.set_reorderable(True)
        self.view.remove_row(next(self.view.each_row()))
        self._settle()
        self.assertEqual(self._names(), ['two', 'three'])
        cell = self._cell_at(0)
        self.assertIsNotNone(cell, 'no cell was drawn where the first row is')
        self.assertTrue(self.view._reorder_drop(
            None, 'application/x-mcomix-row-position:1', 0.0, 0.0, cell))
        self.assertEqual(self._names(), ['three', 'two'])

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
            self.assertEqual(cell.label.props.accelerator, '<Control>a')
            # An action nothing is bound to shows nothing, not the hint
            # a cell puts up while it waits for a combination.
            self.assertEqual(cell.label.props.disabled_text, '')
            # Nothing is taken until the cell has been clicked.
            self.assertFalse(
                cell._pressed(None, Gdk.KEY_b, 0, Gdk.ModifierType.CONTROL_MASK))
            cell.emit('clicked')
            self.assertEqual(cell.label.props.disabled_text,
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
            self.assertEqual(cells[0].label.props.accelerator, '')
            self.assertTrue(cells[1].get_sensitive())
        finally:
            window.destroy()
            pump()

    def test_an_accelerator_cell_is_the_same_width_whatever_it_shows(self):
        """A Gtk.ColumnView asks the cells that are on screen how wide
        the column should be, where a Gtk.TreeView asked the whole
        model, so a cell that measured what it holds made the column a
        different width every time the list was scrolled - and a
        Gtk.ShortcutLabel, which cannot be drawn narrower than the key
        caps it holds, took that width out of the column beside it."""
        window = Gtk.Window()
        box = Gtk.Box()
        window.set_child(box)
        window.present()
        try:
            pump()
            empty = column_list._AccelCell()
            long = column_list._AccelCell()
            # Four caps cannot be drawn under their minimum widths,
            # whatever the desktop's language calls them.
            long.accelerator = '<Control><Shift><Alt>a'
            long._show()
            for cell in (empty, long):
                box.append(cell)
            pump()
            self.assertEqual(
                empty.measure(Gtk.Orientation.HORIZONTAL, -1)[1],
                long.measure(Gtk.Orientation.HORIZONTAL, -1)[1])
            # What does not fit is cut off, and spelled out instead.
            self.assertIsNone(empty.get_tooltip_text())
            self.assertEqual(
                long.get_tooltip_text(),
                Gtk.accelerator_get_label(
                    *Gtk.accelerator_parse('<Control><Shift><Alt>a')[1:]))
        finally:
            window.destroy()
            pump()

    @staticmethod
    def _cap_widths(label):
        """How wide each key cap of a shortcut label wants to be."""
        wanted = []
        child = label.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label) \
                    and 'keycap' in child.get_css_classes():
                wanted.append(child.measure(Gtk.Orientation.HORIZONTAL, -1)[1])
            child = child.get_next_sibling()
        return wanted

    @staticmethod
    def _caps(label):
        """What each key cap of a shortcut label says."""
        said = []
        child = label.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label) \
                    and 'keycap' in child.get_css_classes():
                said.append(child.get_text())
            child = child.get_next_sibling()
        return said

    def test_a_key_with_a_sign_on_it_is_drawn_as_that_sign(self):
        """A Gtk.ShortcutLabel spells out Page Up, Backspace and Tab,
        which are the longest things in a column of shortcuts."""
        cell = column_list._AccelCell()
        for accelerator, sign in (('Page_Up', '\u21de'),
                                  ('BackSpace', '\u232b'),
                                  ('Tab', '\u21e5'),
                                  ('Menu', '\u2630'),
                                  ('Print', '\u2399'),
                                  ('<Control><Shift>Home', '\u21f1')):
            cell.accelerator = accelerator
            cell._show()
            self.assertEqual(self._caps(cell.label)[-1], sign)

    def test_the_caps_are_not_joined_up_with_plusses(self):
        """Keys drawn as keys read as keys held down together, and the
        plusses are a third of the width of a short shortcut."""
        cell = column_list._AccelCell()
        cell.accelerator = '<Control><Shift>Page_Up'
        cell._show()
        joined = []
        child = cell.label.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label) \
                    and 'dim-label' in child.get_css_classes():
                joined.append(child.get_visible())
            child = child.get_next_sibling()
        self.assertTrue(joined, 'the label drew no joiners to drop')
        self.assertFalse(any(joined))

    def test_the_modifiers_but_shift_keep_the_names_they_are_given(self):
        """Ctrl and Alt are printed as words, and are left as words."""
        cell = column_list._AccelCell()
        cell.accelerator = '<Control><Alt>Page_Up'
        cell._show()
        caps = self._caps(cell.label)
        self.assertEqual(len(caps), 3)
        self.assertEqual(
            caps[:2],
            [Gtk.accelerator_get_label(0, Gdk.ModifierType.CONTROL_MASK),
             Gtk.accelerator_get_label(0, Gdk.ModifierType.ALT_MASK)])

    def test_shift_is_drawn_as_the_sign_printed_on_it(self):
        """It is the widest of the modifiers in several languages -
        German spells it "Umschalt" - and the only one a keyboard puts
        a sign on rather than a word."""
        cell = column_list._AccelCell()
        cell.accelerator = '<Control><Shift>Page_Up'
        cell._show()
        caps = self._caps(cell.label)
        self.assertEqual(len(caps), 3)
        self.assertEqual(caps[0], '\u21e7')
        self.assertEqual(
            caps[1], Gtk.accelerator_get_label(0, Gdk.ModifierType.CONTROL_MASK))

    def test_a_modifier_is_drawn_no_wider_than_what_it_says(self):
        """GTK asks for fifty pixels for every modifier cap, whatever
        is printed on it, to line the modifiers of one shortcut up
        under those of the next.  Here they stand one to a row, with
        nothing to line up with."""
        cell = column_list._AccelCell()
        cell.accelerator = '<Control>a'
        cell._show()
        drawn = self._cap_widths(cell.label)
        asked = self._cap_widths(Gtk.ShortcutLabel(accelerator='<Control>a'))
        self.assertEqual(len(drawn), 2)
        self.assertLess(drawn[0], asked[0])
        # The key beside it is untouched: GTK asks nothing for that one.
        self.assertEqual(drawn[1], asked[1])

    def test_a_key_of_the_numeric_keypad_keeps_the_mark_that_is_its_own(self):
        """The mark is what tells it from the key of the same name, so
        the sign is drawn with the mark rather than instead of it - and
        the key is left spelled out where the two cannot be told apart,
        which is the case in Spanish, Polish and Japanese."""
        cell = column_list._AccelCell()
        for accelerator, sign in (('KP_Page_Up', '\u21de'),
                                  ('KP_Page_Down', '\u21df'),
                                  ('KP_Home', '\u21f1'),
                                  ('KP_Right', '\u2192')):
            cell.accelerator = accelerator
            cell._show()
            drawn = self._caps(cell.label)[-1]
            spelled = Gtk.ShortcutLabel(accelerator=accelerator)
            spelled_out = self._caps(spelled)[-1]
            if not spelled_out.endswith(')'):
                self.assertEqual(drawn, spelled_out)
                continue
            self.assertTrue(drawn.startswith(sign), drawn)
            self.assertTrue(drawn.endswith(')'), drawn)
            self.assertLess(len(drawn), len(spelled_out))

    def test_the_plain_key_of_that_name_is_drawn_as_the_sign_alone(self):
        """Nothing marks it, because there is nothing to tell it from."""
        cell = column_list._AccelCell()
        cell.accelerator = 'Page_Down'
        cell._show()
        self.assertEqual(self._caps(cell.label)[-1], '\u21df')

    def test_an_accelerator_is_drawn_at_the_size_its_caps_come_to(self):
        """The cell asks for one width whatever it holds; the shortcut
        in it is drawn at its own, rather than stretched to fill the
        cell out."""
        window = Gtk.Window()
        box = Gtk.Box()
        window.set_child(box)
        window.present()
        try:
            pump()
            cell = column_list._AccelCell()
            cell.accelerator = '<Control>a'
            cell._show()
            box.append(cell)
            pump()
            wanted = cell.label.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            self.assertTrue(wanted, 'the shortcut was not drawn at all')
            # More room than the caps need, as a wide column would give.
            cell.allocate(wanted * 3,
                          cell.measure(Gtk.Orientation.VERTICAL, -1)[1],
                          -1, None)
            pump()
            self.assertEqual(cell.label.get_width(), wanted)
        finally:
            window.destroy()
            pump()

    def test_a_shortcut_too_wide_for_its_cell_is_cut_in_whole_letters(self):
        """Clipping alone cut through whatever letter fell on the edge
        of the cell.  The caps ellipsize instead, so what is dropped is
        dropped as text, and the tooltip spells the shortcut out."""
        window = Gtk.Window()
        box = Gtk.Box()
        window.set_child(box)
        window.present()
        try:
            pump()
            cell = column_list._AccelCell()
            # Four caps cannot be drawn under their minimum widths.
            cell.accelerator = '<Control><Shift><Alt>a'
            cell._show()
            box.append(cell)
            pump()
            room = cell.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            self.assertGreater(
                cell.label.measure(Gtk.Orientation.HORIZONTAL, -1)[1], room,
                'the shortcut fits, and says nothing about one that does not')
            cell.allocate(room, cell.measure(Gtk.Orientation.VERTICAL, -1)[1],
                          -1, None)
            pump()
            self.assertLessEqual(cell.label.get_width(), room)
            child = cell.label.get_first_child()
            ellipsized = []
            while child is not None:
                if isinstance(child, Gtk.Label) \
                        and 'keycap' in child.get_css_classes():
                    ellipsized.append(child.get_ellipsize())
                child = child.get_next_sibling()
            self.assertTrue(ellipsized, 'the label drew no caps')
            self.assertTrue(all(mode == Pango.EllipsizeMode.END
                                for mode in ellipsized))
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
