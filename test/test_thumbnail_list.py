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

from gi.repository import GdkPixbuf, Gtk

from . import MComixTest, pump, wait_for

from mcomix import thumbnail_list


class ThumbnailListViewTest(MComixTest):

    #: More rows than any window in a test can show at once.
    ROWS = 200

    def setUp(self):
        super().setUp()
        self.asked = []
        self.view = thumbnail_list.ThumbnailListView()
        self.view.generate_thumbnail = self._generate
        self.view.set_thumbnail_size(64)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_child(self.view)
        self.window = Gtk.Window()
        self.window.set_default_size(300, 400)
        self.window.set_child(self.scroller)
        self.window.present()
        pump()

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
        """Give the list frames to lay itself out in.

        A queued allocation runs from the frame clock, so draining what
        is pending is not enough: the rows are bound only once the view
        has been given its size.
        """
        for _ in range(40):
            pump()
            self.scroller.allocate(300, 400, -1, None)

    def _fill(self):
        self.view.set_pages(range(1, self.ROWS + 1))
        self._settle()

    def test_a_small_thumbnail_is_not_enlarged_to_fill_its_cell(self):
        """CONTAIN drew a 3 by 3 page 27 times over in an 82 pixel
        cell of the thumbnail bar, and the properties dialog's picture
        46 times; a Gtk.TreeView drew a thumbnail at its own size."""
        from mcomix import properties_page
        cell = thumbnail_list._ThumbnailCell(Gtk.Orientation.HORIZONTAL)
        for picture in (cell.picture, properties_page._Page()._thumb):
            self.assertEqual(Gtk.ContentFit.SCALE_DOWN,
                             picture.get_content_fit())

    def test_every_row_is_asked_for_at_most_once(self):
        self._fill()
        self.assertTrue(self.asked, 'nothing was asked for at all')
        self.assertEqual(len(self.asked), len(set(self.asked)),
                         'the same row was queued more than once')

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
        self.view.set_pages(range(1, self.ROWS + 1))
        self.assertEqual([], self.asked)
        self.assertTrue(wait_for(lambda: self.asked, seconds=5))
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

# vim: expandtab:sw=4:ts=4


class ThumbnailGridViewTest(MComixTest):

    #: More entries than any window in a test can show at once, and
    #: more than GTK's thirty rows of the most columns a grid allows.
    ITEMS = 2500

    def setUp(self):
        super().setUp()
        self.view = thumbnail_list.ThumbnailGridView()
        self.view.generate_thumbnail = lambda uid: None
        self.view.set_thumbnail_size(64)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_child(self.view)
        self.window = Gtk.Window()
        self.window.set_default_size(600, 400)
        self.window.set_child(self.scroller)

    def tearDown(self):
        self.view.stop_update()
        self.window.destroy()
        pump()
        super().tearDown()

    def _settle(self):
        for _ in range(40):
            pump()
            self.scroller.allocate(600, 400, -1, None)

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
        self._settle()
        for width in (600, 1500, 300):
            for _ in range(40):
                pump()
                self.scroller.allocate(width, 400, -1, None)
            self.assertEqual(self.view.get_max_columns() - 1,
                             self._columns(), width)
