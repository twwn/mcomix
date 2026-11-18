"""Zooming with two fingers on a touchpad or a touch screen.

A pinch reports its scale against where the fingers first stood, so
the zoom it lands on is worked out from where the pinch began, in the
steps the zoom keys take.
"""

import unittest.mock

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import icons
from mcomix import main
from mcomix import zoom
from mcomix.preferences import prefs


class PinchTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.make_user_directories()
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.close_main_window()
        super().tearDown()

    def _pinch(self, *scales):
        self.window.pinch_started()
        for scale in scales:
            self.window.pinch_zoom(scale)
        self.window.pinch_ended()

    def test_spreading_the_fingers_to_twice_their_distance_doubles_the_page(self):
        self._pinch(1.5, 2.0)
        self.assertEqual(zoom.USER_ZOOM_LOG_SCALE1,
                         self.window.zoom.user_zoom_log)

    def test_bringing_them_together_zooms_out_from_where_it_was(self):
        self.window.zoom.zoom_in()
        self._pinch(0.5)
        self.assertEqual(1 - zoom.USER_ZOOM_LOG_SCALE1,
                         self.window.zoom.user_zoom_log)

    def test_a_second_pinch_goes_on_from_the_first(self):
        self._pinch(2.0)
        self._pinch(2.0)
        self.assertEqual(2 * zoom.USER_ZOOM_LOG_SCALE1,
                         self.window.zoom.user_zoom_log)

    def test_it_stops_where_the_zoom_keys_stop(self):
        self._pinch(1000.0)
        self.assertEqual(zoom.MAX_USER_ZOOM_LOG,
                         self.window.zoom.user_zoom_log)

    def test_the_page_is_drawn_again_only_when_the_step_changes(self):
        with unittest.mock.patch.object(self.window, 'draw_image') as draw:
            self._pinch(1.01, 1.02, 1.03, 2.0)
        self.assertEqual(1, draw.call_count)

    def test_a_pinch_that_never_began_does_nothing(self):
        self.window.pinch_zoom(2.0)
        self.assertEqual(zoom.IDENTITY_ZOOM_LOG,
                         self.window.zoom.user_zoom_log)

    def test_in_continuous_mode_it_widens_the_strip(self):
        prefs['continuous width'] = 50
        with unittest.mock.patch.object(type(self.window), 'is_continuous',
                                        new=True):
            self._pinch(1.5)
        self.assertEqual(75, prefs['continuous width'])
        self.assertEqual(zoom.IDENTITY_ZOOM_LOG,
                         self.window.zoom.user_zoom_log)

    def test_the_page_area_has_a_pinch_gesture(self):
        controllers = self.window.page_area.observe_controllers()
        kinds = [type(controllers.get_item(n))
                 for n in range(controllers.get_n_items())]
        self.assertIn(Gtk.GestureZoom, kinds)


# vim: expandtab:sw=4:ts=4
