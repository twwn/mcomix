"""The Enhance image dialog, which draws a histogram of the page shown."""

import os
from unittest import mock

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import enhance_dialog
from mcomix import histogram
from mcomix import icons
from mcomix import main
from mcomix.dialog import Response


class EnhanceDialogTest(MComixTest):

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
        pump()

    def tearDown(self):
        enhance_dialog._close_dialog()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _histograms_drawn_turning_a_page(self):
        with mock.patch.object(histogram, 'draw_histogram',
                               wraps=histogram.draw_histogram) as drawn:
            self.window.flip_page(+1)
            wait_for(self.window.imagehandler.page_is_available)
            pump()
        return drawn.call_count

    def test_an_open_dialog_draws_the_page_turned_to(self):
        enhance_dialog.open_dialog(None, self.window)
        pump()
        self.assertEqual(1, self._histograms_drawn_turning_a_page())

    def test_a_closed_dialog_draws_nothing_for_a_page_turned_to(self):
        """A dialog closed with OK was destroyed but stayed listening, and
        drew a histogram for every page turned for the rest of the
        session: one more for each time it had been opened."""
        for _time in range(2):
            enhance_dialog.open_dialog(None, self.window)
            pump()
            enhance_dialog._dialog.response(Response.OK)
            pump()
        self.assertEqual(0, self._histograms_drawn_turning_a_page())

        enhance_dialog.open_dialog(None, self.window)
        pump()
        self.assertEqual(1, self._histograms_drawn_turning_a_page())


# vim: expandtab:sw=4:ts=4
