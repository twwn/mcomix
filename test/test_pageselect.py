# -*- coding: utf-8 -*-

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


class PageselectTest(MComixTest):

    def setUp(self):
        super(PageselectTest, self).setUp()
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
        super(PageselectTest, self).tearDown()

    def test_the_selector_covers_every_page(self):
        adjustment = self.dialog._selector_adjustment
        self.assertEqual(adjustment.get_lower(), 1)
        self.assertEqual(adjustment.get_upper(),
                         self.window.imagehandler.get_number_of_pages())

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


# vim: expandtab:sw=4:ts=4
