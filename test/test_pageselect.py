"""The page selector, which previews the page it would go to.

The preview is made on a worker thread and comes back through a
callback, and the thumbnail it comes back with is None for a page the
extractor has not reached yet.
"""

import os

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix import pageselect
from mcomix.dialog import Response
from mcomix.preferences import prefs


class PageselectTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)
        self.dialog = pageselect.Pageselector(self.window)
        pump()

    def tearDown(self):
        self.dialog._stop_thumbnailing()
        for window in Gtk.Window.list_toplevels():
            if window.get_visible():
                window.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def test_the_selector_covers_every_page(self):
        adjustment = self.dialog._selector_adjustment
        self.assertEqual(adjustment.get_lower(), 1)
        self.assertEqual(adjustment.get_upper(),
                         self.window.imagehandler.get_number_of_pages())

    def test_the_preview_is_not_enlarged_past_its_own_size(self):
        self.assertEqual(Gtk.ContentFit.SCALE_DOWN,
                         self.dialog._image_preview.get_content_fit())

    def test_a_page_that_is_not_available_leaves_the_preview_empty(self):
        """A page the extractor has not reached has no thumbnail, and
        handing None to Gdk.Texture raised instead of showing nothing."""
        self.dialog._thumbnail_page = 1
        self.dialog._thumbnail_finished(1, None)
        self.assertIsNone(self.dialog._image_preview.get_paintable())

    def test_a_thumbnail_that_was_made_is_shown(self):
        pixbuf = self.window.imagehandler.get_thumbnail(1, width=64,
                                                        height=64)
        self.assertIsNotNone(pixbuf)
        self.dialog._thumbnail_page = 1
        self.dialog._thumbnail_finished(1, pixbuf)
        self.assertIsNotNone(self.dialog._image_preview.get_paintable())

    def test_closing_the_selector_stops_the_worker(self):
        """The worker is not a daemon, so a dialog that leaves it
        running leaves terminate_program() waiting for it at exit.  It
        was stopped from the window's 'destroy' signal, which GTK4 emits
        when the last reference to the window goes rather than when it
        is destroyed - and the handler is a method of the window, so the
        closure held a reference and the signal never came."""
        self.dialog._update_thumbnail(1)
        wait_for(lambda: self.dialog._thread._threads, seconds=20)
        self.dialog.response(Response.CANCEL)
        pump()
        self.assertEqual(self.dialog._thread._threads, [],
                         'the preview worker is still running')

    def test_a_thumbnail_for_a_page_left_behind_is_dropped(self):
        """The preview is asked for again on every change, and an answer
        for the page before it must not overwrite the one on screen."""
        pixbuf = self.window.imagehandler.get_thumbnail(1, width=64,
                                                        height=64)
        self.dialog._thumbnail_page = 2
        self.dialog._thumbnail_finished(2, pixbuf)
        shown = self.dialog._image_preview.get_paintable()
        self.assertIsNotNone(shown)
        self.dialog._thumbnail_finished(1, None)
        self.assertIs(self.dialog._image_preview.get_paintable(), shown)


    def _type(self, text):
        spinner = self.dialog._page_spinner
        spinner.set_text(text)
        spinner.emit('changed')

    def test_a_page_number_typed_is_previewed_at_once(self):
        self._type('3')
        self.assertEqual(3, self.dialog._selector_adjustment.get_value())
        self.assertEqual(3, self.dialog._thumbnail_page)

    def test_a_number_past_the_last_page_or_not_a_number_is_left(self):
        for text in ('9', '0', 'x'):
            with self.subTest(text=text):
                self._type(text)
                self.assertEqual(
                    1, self.dialog._selector_adjustment.get_value())

    def test_moving_the_selector_previews_the_page_it_is_moved_to(self):
        self.dialog._selector_adjustment.set_value(2)
        self.assertEqual(2, self.dialog._thumbnail_page)

    def test_the_size_it_is_given_is_remembered(self):
        self.dialog.set_default_size(420, 360)
        self.assertTrue(wait_for(
            lambda: prefs['pageselector width'] == self.dialog.get_width()
            and self.dialog.get_width() > 0, seconds=5))
        self.assertEqual(self.dialog.get_height(),
                         prefs['pageselector height'])


# vim: expandtab:sw=4:ts=4
