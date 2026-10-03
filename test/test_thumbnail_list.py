"""The list widget behind the thumbnail sidebar.

A row says for itself when it is bound, which is what replaced asking a
Gtk.TreeView for its visible range - a question it answered with None
until it had been laid out, so the code around it kept a timer that
asked again up to forty times before giving up.

How many rows are bound is GTK's business and cannot be measured here:
under Xvfb a plain Gtk.ListView with no MComix in it binds every row of
a two hundred row model, so nothing below asserts that only what is on
screen is asked for.
"""

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
        self.view.set_pages(range(1, self.ROWS + 1))
        self.assertTrue(self.asked,
                        'the rows were bound while the list was stopped')

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

    def test_clearing_empties_the_store(self):
        self._fill()
        self.view.clear()
        self.assertEqual(self.view.store.get_n_items(), 0)

# vim: expandtab:sw=4:ts=4
