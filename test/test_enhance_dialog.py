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
from mcomix.preferences import prefs


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
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0,
            seconds=20))
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
            self.assertTrue(wait_for(
                self.window.imagehandler.page_is_available))
            pump()
        return drawn.call_count

    def test_an_open_dialog_draws_the_page_turned_to(self):
        enhance_dialog.open_dialog(None, self.window)
        pump()
        self.assertEqual(1, self._histograms_drawn_turning_a_page())

    def test_the_histogram_is_not_enlarged_with_the_dialog(self):
        from gi.repository import Gtk
        enhance_dialog.open_dialog(None, self.window)
        pump()
        self.assertEqual(Gtk.ContentFit.SCALE_DOWN,
                         enhance_dialog._dialog._hist_image.get_content_fit())

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

    def test_ctrl_i_with_the_dialog_open_is_not_undone_by_a_slider(self):
        """Ctrl+I inverts the colours through an action of its own; the
        dialog's checkbox did not follow it, and the next move of any
        slider set the colours back from the checkbox."""
        enhance_dialog.open_dialog(None, self.window)
        pump()
        dialog = enhance_dialog._dialog
        self.window.actiongroup.get_action('invert_color').activate()
        pump()
        self.assertTrue(self.window.enhancer.invert_color)
        self.assertTrue(dialog._invert_color_button.get_active())
        dialog._brightness_scale.set_value(0.5)
        pump()
        self.assertTrue(self.window.enhancer.invert_color)

    def test_the_dialog_follows_the_enhancer_only_while_it_is_open(self):
        enhance_dialog.open_dialog(None, self.window)
        pump()
        dialog = enhance_dialog._dialog
        dialog.response(Response.OK)
        pump()
        self.window.actiongroup.get_action('invert_color').activate()
        pump()
        self.assertFalse(dialog._invert_color_button.get_active())


    def test_ticking_invert_in_the_dialog_lets_ctrl_i_take_it_off(self):
        """The checkbox inverted the colours and left Ctrl+I's action
        off, so the next Ctrl+I turned it on over colours that were
        inverted already, and nothing changed on screen."""
        enhance_dialog.open_dialog(None, self.window)
        pump()
        enhance_dialog._dialog._invert_color_button.set_active(True)
        pump()
        self.assertTrue(self.window.enhancer.invert_color)
        self.window.actiongroup.get_action('invert_color').activate()
        pump()
        self.assertFalse(self.window.enhancer.invert_color)

    def test_save_keeps_the_values_for_the_next_start(self):
        enhance_dialog.open_dialog(None, self.window)
        pump()
        dialog = enhance_dialog._dialog
        dialog._brightness_scale.set_value(0.5)
        dialog._invert_color_button.set_active(True)
        pump()
        self.assertEqual(1.0, prefs['brightness'])
        dialog.response(Response.APPLY)
        pump()
        self.assertEqual(1.5, prefs['brightness'])
        self.assertTrue(prefs['invert color'])
        self.assertTrue(
            self.window.actiongroup.get_action('invert_color').get_active())

    def test_the_gamma_slider_sets_a_ratio_either_side_of_one(self):
        """The slider runs -1 to 1, as the others do; gamma is 2 to that
        power, so that halving and doubling lie as far from 1."""
        enhance_dialog.open_dialog(None, self.window)
        pump()
        dialog = enhance_dialog._dialog
        for position, gamma in ((1.0, 2.0), (-1.0, 0.5), (0.0, 1.0)):
            dialog._gamma_scale.set_value(position)
            pump()
            self.assertEqual(gamma, self.window.enhancer.gamma)
        dialog._gamma_scale.set_value(1.0)
        dialog.response(Response.APPLY)
        pump()
        self.assertEqual(2.0, prefs['gamma'])

    def test_revert_goes_back_to_the_values_last_saved(self):
        enhance_dialog.open_dialog(None, self.window)
        pump()
        dialog = enhance_dialog._dialog
        dialog._brightness_scale.set_value(0.5)
        dialog.response(Response.APPLY)
        dialog._brightness_scale.set_value(-0.5)
        dialog._invert_color_button.set_active(True)
        pump()
        self.assertEqual(0.5, self.window.enhancer.brightness)
        dialog.response(Response.REJECT)
        pump()
        self.assertEqual(1.5, self.window.enhancer.brightness)
        self.assertEqual(0.5, dialog._brightness_scale.get_value())
        self.assertFalse(self.window.enhancer.invert_color)
        self.assertFalse(
            self.window.actiongroup.get_action('invert_color').get_active())

    def test_reset_takes_every_enhancement_off_and_saves_nothing(self):
        """"Revert" said it reset to the defaults, and went back to the
        saved values: once a set had been saved, nothing in the dialog
        showed the pages as they are (upstream bug 70)."""
        enhance_dialog.open_dialog(None, self.window)
        pump()
        dialog = enhance_dialog._dialog
        dialog._brightness_scale.set_value(0.5)
        dialog._autocontrast_button.set_active(True)
        dialog._gamma_scale.set_value(-1.0)
        dialog.response(Response.APPLY)
        dialog._invert_color_button.set_active(True)
        pump()
        reset, = [button for button in widgets_in(dialog._button_row)
                  if button.get_label() == 'R_eset']
        reset.emit('clicked')
        pump()
        enhancer = self.window.enhancer
        self.assertEqual((1.0, 1.0, 1.0, 1.0, False, False, 1.0),
                         (enhancer.brightness, enhancer.contrast,
                          enhancer.saturation, enhancer.sharpness,
                          enhancer.autocontrast, enhancer.invert_color,
                          enhancer.gamma))
        self.assertEqual(0.0, dialog._gamma_scale.get_value())
        self.assertEqual(0.0, dialog._brightness_scale.get_value())
        self.assertFalse(dialog._autocontrast_button.get_active())
        self.assertFalse(
            self.window.actiongroup.get_action('invert_color').get_active())
        self.assertEqual(1.5, prefs['brightness'])
        self.assertTrue(prefs['auto contrast'])


    def _drawn(self, change):
        enhance_dialog.open_dialog(None, self.window)
        pump()
        with mock.patch.object(histogram, 'draw_histogram',
                               wraps=histogram.draw_histogram) as drawn:
            change(enhance_dialog._dialog)
            pump()
        return drawn

    def test_moving_a_slider_draws_the_page_as_enhanced(self):
        from mcomix import image_tools
        drawn = self._drawn(
            lambda dialog: dialog._invert_color_button.set_active(True))
        self.assertEqual(1, drawn.call_count)
        shown = image_tools.pixbuf_to_pil(drawn.call_args.args[0])
        page = image_tools.pixbuf_to_pil(image_tools.fit_in_rectangle(
            self.window.imagehandler.get_pixbufs(1)[0], 512, 512))
        # Inverted, each colour's count moves to the other end.
        counts = page.convert('RGB').histogram()
        inverted = [count for band in range(3)
                    for count in reversed(counts[band * 256:(band + 1) * 256])]
        self.assertNotEqual(counts, inverted)
        self.assertEqual(inverted, shown.convert('RGB').histogram())

    def test_the_logarithmic_scale_is_kept_and_drawn(self):
        prefs['histogram logarithmic'] = False
        drawn = self._drawn(
            lambda dialog: dialog._logarithmic_button.set_active(True))
        self.assertTrue(prefs['histogram logarithmic'])
        self.assertEqual(1, drawn.call_count)
        self.assertTrue(drawn.call_args.kwargs['logarithmic'])

def widgets_in(box):
    """The children of <box>, in order."""
    child = box.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()

class LogarithmicHistogramTest(MComixTest):

    def test_a_colour_few_pixels_have_still_shows(self):
        from PIL import Image
        from mcomix import image_tools
        im = Image.new('RGB', (100, 100), (255, 255, 255))
        im.putpixel((0, 0), (0, 0, 0))
        pixbuf = image_tools.pil_to_pixbuf(im)

        def column_of_black(logarithmic):
            drawn = image_tools.pixbuf_to_pil(
                histogram.draw_histogram(pixbuf, logarithmic=logarithmic))
            # The bar for 0 is the histogram's first column inside its
            # two-pixel frame; count what was drawn above the floor.
            return sum(1 for y in range(drawn.height)
                       if drawn.getpixel((3, y)) not in ((30, 30, 30),
                                                         (80, 80, 80),
                                                         (0, 0, 0)))

        self.assertEqual(0, column_of_black(False))
        self.assertGreater(column_of_black(True), 5)

# vim: expandtab:sw=4:ts=4
