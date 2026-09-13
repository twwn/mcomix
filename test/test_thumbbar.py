"""The thumbnail sidebar, which makes its thumbnails as they come on screen.

It was a Gtk.TreeView of cell renderers, all deprecated in GTK 4.10, and
had to be asked which rows were visible - a question it answered with
None until it had been laid out, so a timer asked again up to forty
times. A Gtk.ListView binds a row when it comes on screen, and that is
now what says which thumbnails to make.
"""

import os


from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix.preferences import prefs


class ThumbnailSidebarTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['show thumbnails'] = True
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        self.sidebar = self.window.thumbnailsidebar
        # The archive is listed on a worker thread, so the page count is
        # zero for a while after the window is built. Waiting on the
        # count rather than pumping a fixed number of rounds is what
        # keeps this from racing the extractor.
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)

    def tearDown(self):
        # Only terminate_program() stops the worker threads, and a GTK4
        # toplevel that is never destroyed goes on taking part in the
        # display's layout.
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump(2000)
        super().tearDown()

    def _pages(self):
        return self.window.imagehandler.get_number_of_pages()

    def _items(self):
        store = self.sidebar._list.store
        return [store.get_item(index) for index in range(store.get_n_items())]

    def test_there_is_a_row_for_every_page(self):
        self.sidebar.load_thumbnails()
        self.assertEqual(len(self._items()), self._pages())

    def test_the_rows_are_numbered_from_one(self):
        self.sidebar.load_thumbnails()
        self.assertEqual([item.uid for item in self._items()],
                         list(range(1, self._pages() + 1)))

    def test_a_thumbnail_is_made_for_what_is_on_screen(self):
        # The point of the port: nothing asks which rows are visible.
        # Binding a row is the question and the answer at once.
        self.sidebar.load_thumbnails()
        wait_for(lambda: any(item.thumbnail is not None
                             for item in self._items()), seconds=20)
        made = [item for item in self._items() if item.thumbnail is not None]
        self.assertTrue(made, 'no thumbnail was made for the visible rows')

    def test_a_thumbnail_is_a_texture_of_the_size_that_was_asked_for(self):
        self.sidebar.load_thumbnails()
        wait_for(lambda: self._items()[0].thumbnail is not None, seconds=20)
        thumbnail = self._items()[0].thumbnail
        # The border adds two pixels to the size the preference names.
        limit = self.sidebar._pixbuf_size
        self.assertLessEqual(max(thumbnail.get_width(),
                                 thumbnail.get_height()), limit)

    def test_clearing_drops_every_row(self):
        self.sidebar.load_thumbnails()
        self.assertTrue(self._items())
        self.sidebar.clear()
        self.assertEqual(self._items(), [])

    def test_loading_twice_does_not_double_the_rows(self):
        self.sidebar.load_thumbnails()
        self.sidebar.load_thumbnails()
        self.assertEqual(len(self._items()), self._pages())

    def test_the_selected_row_follows_the_page(self):
        self.sidebar.load_thumbnails()
        self.window.set_page(2)
        wait_for(lambda: self.sidebar._list.get_selected_row() == 1,
                 seconds=20)
        self.assertEqual(self.sidebar._list.get_selected_row(), 1)

    def test_activating_a_row_turns_to_that_page(self):
        self.sidebar.load_thumbnails()
        self.sidebar._row_activated(self.sidebar._list, 2)
        wait_for(lambda: self.window.imagehandler.get_current_page() == 3,
                 seconds=20)
        self.assertEqual(self.window.imagehandler.get_current_page(), 3)

    def test_page_numbers_are_shown_only_when_the_preference_says_so(self):
        prefs['show page numbers on thumbnails'] = False
        self.sidebar.toggle_page_numbers_visible()
        self.assertFalse(self.sidebar._list._labels_visible)
        prefs['show page numbers on thumbnails'] = True
        self.sidebar.toggle_page_numbers_visible()
        self.assertTrue(self.sidebar._list._labels_visible)

    def test_a_sidebar_shown_after_the_file_makes_its_thumbnails(self):
        """Hiding the sidebar stops it making thumbnails, and showing it
        again has to start it.

        The rows are set while it is hidden - a page change does that -
        so load_thumbnails() has nothing left to do and never cleared
        the flag, and hiding does not unbind the cells that were on
        screen, so nothing ever asked for their thumbnails again. The
        sidebar stayed empty until the next archive was opened.

        The preference is what the redraw reads to decide whether the
        sidebar is shown, which is how the user reaches this.
        """
        self.sidebar.load_thumbnails()
        wait_for(lambda: any(item.thumbnail is not None
                             for item in self._items()), seconds=20)

        prefs['show thumbnails'] = False
        self.window.draw_image()
        pump()
        self.assertFalse(self.sidebar.get_visible())
        for item in self._items():
            item.thumbnail = None

        prefs['show thumbnails'] = True
        self.window.draw_image()
        pump()
        wait_for(lambda: any(item.thumbnail is not None
                             for item in self._items()), seconds=20)
        self.assertTrue(
            [item for item in self._items() if item.thumbnail is not None],
            'the sidebar made no thumbnails after being shown again')

    def test_resizing_reloads_at_the_new_size(self):
        self.sidebar.load_thumbnails()
        prefs['thumbnail size'] = prefs['thumbnail size'] * 2
        self.sidebar.resize()
        self.assertEqual(self.sidebar._list._thumbnail_width,
                         self.sidebar._pixbuf_size)
        self.assertEqual(len(self._items()), self._pages())

# vim: expandtab:sw=4:ts=4
