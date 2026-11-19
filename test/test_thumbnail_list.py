"""The list widget behind the thumbnail sidebar.

A row says for itself when it is bound, which is what replaced asking a
Gtk.TreeView for its visible range - a question it answered with None
until it had been laid out, so the code around it kept a timer that
asked again up to forty times before giving up.

How many rows a list binds is GTK's business and cannot be measured
here: under Xvfb a plain Gtk.ListView with no MComix in it binds every
row of a two hundred row model, so nothing below asserts that only what
is on screen is asked for.  A grid binds some thirty rows of the most
columns it may have, which ThumbnailGridViewTest holds to the columns
it lays out.
"""

import threading
import time

from gi.repository import GdkPixbuf, Gtk

from . import MComixTest, pump, wait_for

from mcomix import thumbnail_list
from mcomix import properties_page


def _cover():
    """What a test's generate_thumbnail makes of every entry."""
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 48)
    pixbuf.fill(0x336699ff)
    return pixbuf


class _ViewTest(MComixTest):

    """A thumbnail view in a scrolled window of its own, which the test
    presents when it is ready; stopped and closed after the test."""

    def _build(self, view, width):
        """Make <view> self.view, at thumbnails of 64 pixels, in a window
        <width> wide and 400 high."""
        self._width = width
        self.view = view
        self.view.set_thumbnail_size(64)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_child(self.view)
        self.window = Gtk.Window()
        self.window.set_default_size(width, 400)
        self.window.set_child(self.scroller)

    def tearDown(self):
        self.view.stop_update()
        # A window left on screen is answered by whatever looks for one
        # next.
        self.window.destroy()
        pump()
        super().tearDown()

    def _settle(self):
        """Give the view frames to lay itself out in, at its window's
        width.

        A queued allocation runs from the frame clock, so draining what
        is pending is not enough: the rows are bound only once the view
        has been given its size.
        """
        for _ in range(40):
            pump()
            self.scroller.allocate(self._width, 400, -1, None)

    def _drawn(self):
        """Wait for every bound entry to have its thumbnail."""
        return wait_for(lambda: all(item.thumbnail is not None
                                    for item in self.view._bound), seconds=10)


class ThumbnailListViewTest(_ViewTest):

    #: More rows than any window in a test can show at once.
    ROWS = 200

    def setUp(self):
        super().setUp()
        self.asked = []
        view = thumbnail_list.ThumbnailListView()
        view.generate_thumbnail = self._generate
        self._build(view, 300)
        self.window.present()
        pump()

    def _generate(self, uid):
        self.asked.append(uid)
        return _cover()

    def _fill(self):
        self.view.set_pages(range(1, self.ROWS + 1))
        self._settle()

    def test_a_small_thumbnail_is_not_enlarged_to_fill_its_cell(self):
        """CONTAIN drew a 3 by 3 page 27 times over in an 82 pixel
        cell of the thumbnail bar, and the properties dialog's picture
        46 times; a Gtk.TreeView drew a thumbnail at its own size."""
        cell = thumbnail_list._ThumbnailCell(Gtk.Orientation.HORIZONTAL)
        for picture in (cell.picture, properties_page._Page()._thumb):
            self.assertEqual(Gtk.ContentFit.SCALE_DOWN,
                             picture.get_content_fit())

    def test_every_row_is_asked_for_at_most_once(self):
        self._fill()
        # A worker thread asks, once the cells are bound; on a loaded
        # runner it has not always been reached by the time the list has
        # settled.  Let the list settle again afterwards, so a row queued
        # twice has the time to be asked for twice.
        self.assertTrue(wait_for(lambda: self.asked),
                        'nothing was asked for at all')
        self._settle()
        self.assertEqual(len(self.asked), len(set(self.asked)),
                         'the same row was queued more than once')

    def test_a_thumbnail_on_its_way_is_not_asked_for_again(self):
        """Made, and waiting for the main loop to hand it over: the
        sidebar asks again for every row without a thumbnail each time
        a page comes out of the archive, and made the same page's
        thumbnail up to ten times while opening a book."""
        self._fill()
        self.assertTrue(wait_for(lambda: self.asked))
        self._settle()
        # A thumbnail still being made, or made and not yet handed over,
        # is on its way: refresh() rightly passes over its row, and one
        # row short of all of them was asked for (200 != 199).
        self.assertTrue(wait_for(lambda: all(
            item.thumbnail is not None for item in self.view._bound)
            and not self.view._coming))
        rows = list(self.view._bound)
        for item in rows:
            item.thumbnail = None
        del self.asked[:]
        self.view.refresh()

        def made_without_the_main_loop():
            # Not wait_for(): the main loop must not turn, or the
            # thumbnails made would be handed over.  An order is held
            # until its worker is done with it.
            end = time.monotonic() + 5
            while time.monotonic() < end and self.view._thread._orders_set:
                time.sleep(0.01)
            return len(self.asked)
        self.assertEqual(len(rows), made_without_the_main_loop())
        self.view.refresh()
        self.assertEqual(len(rows), made_without_the_main_loop())
        # Nor by a cell bound again meanwhile.
        for item in rows:
            self.view._ask_soon(item)
        self.view._ask_for_unasked()
        self.assertEqual(len(rows), made_without_the_main_loop())
        self._settle()
        self.assertEqual(len(rows), len(self.asked))
        self.assertTrue(all(item.thumbnail is not None for item in rows))

    def test_a_row_is_asked_for_as_soon_as_the_rows_are_there(self):
        # set_pages() binds the rows that fit from inside the splice, so
        # the list has to be taking orders before it, not after: it used
        # to clear the stop flag afterwards and turn all of them away.
        # They are asked for once the main loop turns.
        self.view.set_pages(range(1, self.ROWS + 1))
        self.assertTrue(wait_for(lambda: self.asked, seconds=5),
                        'the rows were bound while the list was stopped')

    def test_the_rows_bound_together_are_asked_for_after_and_in_order(self):
        """Asked for as each was bound, the first thumbnails were made
        while the rest were still being bound, which slowed both."""
        # One worker, so that the thumbnails are made in the order asked:
        # several finish in whatever order they like.
        self.view._thread._max_threads = 1
        self.view.set_pages(range(1, self.ROWS + 1))
        self.assertEqual([], self.asked)
        # Ten of them, not the first only: what the worker had reached by
        # the first said nothing of the order of the rest.
        self.assertTrue(wait_for(lambda: len(self.asked) >= 10, seconds=5))
        self.assertEqual(sorted(self.asked[:10]), self.asked[:10])
        self.assertEqual(1, self.asked[0])

    def test_a_row_gone_before_it_was_asked_for_is_not_asked_for(self):
        self.view.set_pages(range(1, self.ROWS + 1))
        self.view.clear()
        pump()
        self.assertEqual([], self.asked)

    def test_a_thumbnail_that_arrives_reaches_its_item(self):
        self._fill()
        wait_for(lambda: self.view.store.get_item(0).thumbnail is not None,
                 seconds=10)
        self.assertIsNotNone(self.view.store.get_item(0).thumbnail)

    def test_the_picture_of_a_bound_row_shows_the_thumbnail(self):
        self._fill()
        self.assertTrue(wait_for(
            lambda: self.view.store.get_item(0).thumbnail is not None,
            seconds=10))
        self._settle()
        paintables = [row.picture.get_paintable()
                      for row in self.view._each_cell()]
        self.assertTrue([p for p in paintables if p is not None],
                        'no row on screen is showing anything')

    def _first_cell(self):
        """The cell showing the first row, once its thumbnail is there."""
        self._fill()
        item = self.view.store.get_item(0)
        self.assertTrue(wait_for(lambda: item.thumbnail is not None,
                                 seconds=10))
        self._settle()
        for cell in self.view._each_cell():
            if cell.position == 0:
                return item, cell
        self.fail('the first row is not on screen')

    def test_a_badge_is_drawn_on_the_thumbnail_and_taken_off_again(self):
        item, cell = self._first_cell()
        badge = item.thumbnail
        item.badge = badge
        shown = cell.picture.get_paintable()
        self.assertIsInstance(shown, thumbnail_list._Badged)
        self.assertIs(shown.thumbnail, item.thumbnail)
        item.badge = None
        self.assertIs(cell.picture.get_paintable(), item.thumbnail)

    def test_a_badged_thumbnail_takes_up_the_room_of_the_thumbnail(self):
        """The badge goes on the picture: the picture is laid out as it
        would be without it."""
        item, cell = self._first_cell()
        item.badge = item.thumbnail
        shown = cell.picture.get_paintable()
        self.assertEqual((item.thumbnail.get_width(),
                          item.thumbnail.get_height()),
                         (shown.get_intrinsic_width(),
                          shown.get_intrinsic_height()))

    def test_nothing_is_asked_for_before_there_are_rows(self):
        pump(100)
        self.assertEqual(self.asked, [])

    def test_stopping_updates_stops_asking(self):
        self._fill()
        self.view.stop_update()
        asked = len(self.asked)
        for position in range(self.view.store.get_n_items()):
            self.view._ask_for(self.view.store.get_item(position))
        pump(100)
        self.assertEqual(len(self.asked), asked,
                         'a stopped list went on making thumbnails')

    def test_new_entries_do_not_wait_for_a_thumbnail_being_made(self):
        """They are set on the main thread, so the window stood still for
        as long as it took.  What was only waiting goes with its entry."""
        self.view._thread._max_threads = 1
        entered, go_on, done = (threading.Event() for _ in range(3))
        self.addCleanup(go_on.set)

        def parked(uid):
            entered.set()
            go_on.wait(10)
            done.set()
            return self._generate(uid)

        self.view.generate_thumbnail = parked
        self._fill()
        self.assertTrue(wait_for(entered.is_set, seconds=10))
        fresh = [thumbnail_list.ThumbnailItem(uid)
                 for uid in range(self.ROWS + 1, 2 * self.ROWS + 1)]
        self.view.set_items(fresh)
        self.assertFalse(done.is_set(), 'the main thread waited for it')
        go_on.set()
        self._settle()
        self.assertTrue(wait_for(lambda: fresh[0].thumbnail is not None,
                                 seconds=10))
        self.assertEqual(len([uid for uid in self.asked if uid <= self.ROWS]),
                         1, 'thumbnails of the old entries went on being made')

    def test_clearing_empties_the_store(self):
        self._fill()
        self.view.clear()
        self.assertEqual(self.view.store.get_n_items(), 0)


class ThumbnailsOnScreenFirstTest(_ViewTest):

    """A grid binds some thirty rows for the few it shows, and after a
    jump it binds the ones it shows last."""

    #: Far more entries than the grid binds at once.
    ITEMS = 2500

    def setUp(self):
        super().setUp()
        self.asked = []
        view = thumbnail_list.ThumbnailGridView()
        view.generate_thumbnail = self._generate
        # One worker makes the thumbnails in the order they wait in.
        view._thread._max_threads = 1
        self._build(view, 600)
        self.window.present()
        #: Set, a thumbnail being made waits for go_on.
        self.parking = False
        self.entered, self.go_on = threading.Event(), threading.Event()
        self.addCleanup(self.go_on.set)
        self.items = [thumbnail_list.ThumbnailItem(uid)
                      for uid in range(self.ITEMS)]
        self.view.set_items(self.items)
        self._settle()
        self.assertTrue(self._drawn())

    def tearDown(self):
        # Before the view's workers are stopped, which waits for them.
        self.go_on.set()
        super().tearDown()

    def _generate(self, uid):
        self.asked.append(uid)
        if self.parking:
            self.entered.set()
            self.go_on.wait(10)
        return _cover()

    def _jump(self, share):
        """Scroll to <share> of the way down, in one step."""
        adjustment = self.scroller.get_vadjustment()
        adjustment.set_value(
            (adjustment.get_upper() - adjustment.get_page_size()) * share)
        self._settle()

    def _on_screen(self):
        """The positions of the cells in view.  An entry's uid is its
        position here."""
        height = self.scroller.get_height()
        seen = set()
        for cell in self.view._each_cell():
            found, bounds = cell.compute_bounds(self.scroller)
            if found and cell.get_mapped() and bounds.get_y() < height \
                    and bounds.get_y() + bounds.get_height() > 0:
                seen.add(cell.position)
        return seen

    def test_after_a_jump_what_is_on_screen_is_asked_for_first(self):
        """In the order bound, the covers in view of a library scrolled
        to its middle came after those of the rows above them."""
        del self.asked[:]
        self._jump(0.5)
        self.assertTrue(self._drawn())
        seen = self._on_screen()
        self.assertGreater(len(seen), 6)
        self.assertGreater(len(self.asked), 4 * len(seen),
                           'the grid bound little more than it shows')
        self.assertIn(self.asked[0], seen)
        # The scroll bar says which rows are in view to within one.
        columns = self.view.get_max_columns()
        self.assertLess(max(self.asked.index(uid) for uid in seen),
                        len(seen) + 2 * columns)

    def test_what_waits_for_a_cell_that_has_gone_is_not_made(self):
        """A library scrolled on while its first covers were being read
        made all of those before the first of the ones in view."""
        self.parking = True
        self._jump(0.3)
        self.assertTrue(wait_for(self.entered.is_set, seconds=10))
        in_flight = self.asked[-1]
        self._jump(1.0)
        del self.asked[:]
        self.go_on.set()
        self.assertTrue(self._drawn())
        bound = {item.uid for item in self.view._bound}
        self.assertTrue(self.asked)
        self.assertEqual(set(), set(self.asked) - bound - {in_flight})

    def test_a_thumbnail_made_again_off_screen_is_made_when_it_is_shown(self):
        item = self.items[5]
        self._jump(1.0)
        self.assertTrue(self._drawn())
        self.assertNotIn(item, self.view._bound)
        del self.asked[:]
        was = item.thumbnail
        self.view.redraw_item(item)
        # Kept for when it is shown, not handed to the worker: once the
        # worker holds no order, nothing for it can still be on its way.
        self.assertIn(item, self.view._stale)
        pump()
        self.assertTrue(wait_for(lambda: not self.view._thread._orders_set,
                                 seconds=5))
        self.assertNotIn(5, self.asked, 'made for no cell to show it')
        self._jump(0.0)
        self.assertTrue(wait_for(lambda: item.thumbnail is not was,
                                 seconds=10))
        self.assertEqual(1, self.asked.count(5))

    def test_a_thumbnail_to_be_made_again_is_when_its_cell_went_first(self):
        """What waits for a cell that has gone is not made, but one that
        was to replace a thumbnail must not be forgotten for that."""
        first, second = self.items[3], self.items[5]
        was = second.thumbnail
        del self.asked[:]
        self.parking = True
        self.view.redraw_item(first)
        self.assertTrue(wait_for(self.entered.is_set, seconds=10))
        self.view.redraw_item(second)
        self._jump(1.0)
        self.assertNotIn(second, self.view._bound)
        self.go_on.set()
        self.assertTrue(self._drawn())
        self.assertNotIn(5, self.asked)
        self._jump(0.0)
        self.assertTrue(wait_for(lambda: second.thumbnail is not was,
                                 seconds=10))
        self.assertEqual(1, self.asked.count(5))

    def test_an_entry_shown_again_is_still_made_as_it_was_to_be(self):
        """An entry shown again keeps its cell, and GTK does not bind
        it again: what it was waiting for when the entries were
        replaced, it would wait for forever."""
        first, second = self.items[3], self.items[4]
        was = second.thumbnail
        self.parking = True
        self.view.redraw_item(first)
        self.assertTrue(wait_for(self.entered.is_set, seconds=10))
        # Waits behind the first, which is parked.
        self.view.redraw_item(second)
        self.view.set_items(self.items)
        self._settle()
        self.go_on.set()
        self.assertTrue(wait_for(lambda: second.thumbnail is not was,
                                 seconds=10))

    def test_an_entry_shown_again_is_made_again_when_it_is_shown(self):
        item = self.items[5]
        self._jump(1.0)
        self.assertTrue(self._drawn())
        self.assertNotIn(item, self.view._bound)
        was = item.thumbnail
        self.view.redraw_item(item)
        self.view.set_items(self.items)
        # GTK puts the view back where it was once the entries are in.
        self._settle()
        self._jump(0.0)
        self.assertTrue(wait_for(lambda: item.thumbnail is not was,
                                 seconds=10))


class ThumbnailsAtHandTest(_ViewTest):

    """An owner that holds some thumbnails already hands them over as
    their cells are bound, rather than through a worker.

    A collection drawn again in the library had every cover in memory,
    and still showed every cell blank for a frame or more while the
    workers looked them up and handed them back."""

    ITEMS = 400

    def setUp(self):
        super().setUp()
        self.asked = []
        #: The uids thumbnail_at_hand() was asked about.
        self.looked_up = []
        view = thumbnail_list.ThumbnailGridView()
        view.generate_thumbnail = self._generate
        view.thumbnail_at_hand = self._at_hand
        self._build(view, 600)
        self.window.present()
        self._settle()
        self.items = [thumbnail_list.ThumbnailItem(uid)
                      for uid in range(self.ITEMS)]

    def _generate(self, uid):
        self.asked.append(uid)
        return _cover()

    def _at_hand(self, item):
        """Even uids are at hand."""
        self.looked_up.append(item.uid)
        return _cover() if item.uid % 2 == 0 else None

    def test_a_thumbnail_at_hand_is_shown_as_its_cell_is_bound(self):
        self.view.set_items(self.items)
        # The cells that fit are bound inside the splice: before the main
        # loop has turned, those at hand show their thumbnails already.
        bound = list(self.view._bound)
        self.assertTrue(bound)
        for item in bound:
            self.assertEqual(item.uid % 2 == 0, item.thumbnail is not None,
                             item.uid)
        self._settle()
        self.assertTrue(self._drawn())
        self.assertTrue(self.asked)
        self.assertEqual([], [uid for uid in self.asked if uid % 2 == 0],
                         'a thumbnail at hand was made on a worker')
        cells = {cell.position: cell for cell in self.view._each_cell()}
        self.assertIsNotNone(cells[0].picture.get_paintable())

    def test_a_thumbnail_to_be_made_again_is_not_taken_from_at_hand(self):
        """What the owner holds may be what is to be replaced."""
        self.view.set_items(self.items)
        self._settle()
        self.assertTrue(self._drawn())
        item = self.items[4]
        was = item.thumbnail
        del self.asked[:], self.looked_up[:]
        # Off screen, so that it is made when it is next bound.
        adjustment = self.scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_upper())
        self._settle()
        self.assertNotIn(item, self.view._bound)
        self.view.redraw_item(item)
        adjustment.set_value(0)
        self._settle()
        self.assertTrue(wait_for(lambda: item.thumbnail is not was,
                                 seconds=10))
        self.assertEqual([4], [uid for uid in self.asked if uid == 4])
        self.assertNotIn(4, self.looked_up)

    def test_a_stopped_view_takes_nothing_from_at_hand(self):
        """As one turns away the thumbnails it asked for: what the owner
        holds may have gone with it."""
        self.view.stop_update()
        # Filled behind the stopped view's back, the store binds cells
        # all the same.
        self.view.store.splice(0, 0, self.items)
        self._settle()
        self.assertTrue(self.view._bound)
        self.assertEqual([], self.looked_up)


class ThumbnailGridViewTest(_ViewTest):

    #: More entries than any window in a test can show at once, and
    #: more than GTK's thirty rows of the most columns a grid allows.
    ITEMS = 2500

    def setUp(self):
        super().setUp()
        view = thumbnail_list.ThumbnailGridView()
        view.generate_thumbnail = lambda uid: None
        self._build(view, 600)

    def _settle(self, width=600):
        """Lay the grid out <width> wide until what it lays out holds
        from one allocation to the next.

        Each allocation of a grid wider than its window costs some 30
        ms, so a fixed forty of them made the widest step over a second
        long; the columns hold after the first.
        """
        seen = []

        def steady():
            pump()
            self.scroller.allocate(width, 400, -1, None)
            seen.append((self.view.get_max_columns(), self._columns()))
            return len(seen) >= 3 and seen[-1] == seen[-2] == seen[-3]
        self.assertTrue(wait_for(steady), seen)

    def _fill(self):
        self.view.set_items(thumbnail_list.ThumbnailItem(uid)
                            for uid in range(self.ITEMS))

    def _columns(self):
        """How many cells the grid lays out side by side."""
        tops: dict[float, set[float]] = {}
        for cell in self.view._each_cell():
            bounds = cell.get_parent().compute_bounds(self.view)
            if bounds[0] and cell.get_width() > 0:
                tops.setdefault(round(bounds[1].get_y()), set()).add(
                    round(bounds[1].get_x()))
        return len(tops[min(tops)])

    def test_entries_shown_before_the_grid_is_laid_out_bind_few_cells(self):
        """GTK binds every entry of some thirty rows of the most columns
        the grid may have; at 64 that was the first 1,920 entries, all
        asked for at once, before the grid had a size."""
        self._fill()
        self.assertLessEqual(len(self.view._bound), 40)

    def test_the_grid_binds_rows_of_the_columns_it_lays_out(self):
        self.window.present()
        self._fill()
        self._settle()
        columns = self._columns()
        self.assertGreater(columns, 1)
        self.assertLess(len(self.view._bound), columns * 40)

    def test_as_many_columns_are_laid_out_as_the_width_holds(self):
        """The most columns is never what stops the grid: it lays out
        one fewer than it is allowed, at every width."""
        self.window.present()
        self._fill()
        for width in (600, 1500, 300):
            self._settle(width)
            self.assertEqual(self.view.get_max_columns() - 1,
                             self._columns(), width)


# vim: expandtab:sw=4:ts=4
