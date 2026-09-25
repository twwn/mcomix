"""The view menu's turns, flips, automatic rotation, stretch and zoom.

Each of them sets a preference and draws the page again; none of them
ran in a test.  What is checked is what the page was drawn with after
each: the transform draw_image() records for the page, and the size the
page is shown at.
"""

import os

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import keybindings
from mcomix import main
from mcomix.preferences import prefs
from mcomix.transform import Transform


class ViewActionsTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        keybindings._manager = None
        self.window = main.MainWindow()
        main.set_main_window(self.window)

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _open(self, name):
        """Open the picture <name> from the test images, on its own page."""
        self.window.filehandler.open_file(get_testfile_path('images', name))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 1))
        pump()

    def _activate(self, name):
        self.window.actiongroup.get_action(name).activate()
        pump()

    def _transform(self):
        return self.window.transforms[0]

    def _shown_size(self):
        paintable = self.window.images[0].get_paintable()
        return paintable.get_intrinsic_width(), paintable.get_intrinsic_height()

    def test_the_turns_add_up_and_the_page_is_drawn_turned(self):
        self._open('portrait-no-exif.png')
        self.assertEqual(Transform.ID, self._transform())
        for action, rotation in (('rotate_90', 90), ('rotate_180', 270),
                                 ('rotate_270', 180)):
            with self.subTest(action=action):
                self._activate(action)
                self.assertEqual(rotation, prefs['rotation'])
                self.assertEqual(Transform.from_rotation(rotation),
                                 self._transform())

    def test_each_flip_turns_its_own_preference_over(self):
        self._open('portrait-no-exif.png')
        self._activate('flip_horiz')
        self.assertEqual((True, False), (prefs['horizontal flip'],
                                         prefs['vertical flip']))
        self.assertEqual(Transform.from_flips(True, False), self._transform())
        self._activate('flip_vert')
        self.assertEqual((True, True), (prefs['horizontal flip'],
                                        prefs['vertical flip']))
        self.assertEqual(Transform.from_flips(True, True), self._transform())
        self._activate('flip_horiz')
        self.assertEqual(Transform.from_flips(False, True), self._transform())

    def test_automatic_rotation_turns_only_the_pages_it_names(self):
        self._open('portrait-no-exif.png')
        for action, value, rotation in (
                ('rotate_90_width', constants.AUTOROTATE_WIDTH_90, 0),
                ('rotate_90_height', constants.AUTOROTATE_HEIGHT_90, 90),
                ('rotate_270_height', constants.AUTOROTATE_HEIGHT_270, 270),
                ('no_autorotation', constants.AUTOROTATE_NEVER, 0)):
            with self.subTest(action=action):
                self._activate(action)
                self.assertEqual(value, prefs['auto rotate depending on size'])
                self.assertEqual(Transform.from_rotation(rotation),
                                 self._transform())

    def test_stretch_enlarges_a_page_smaller_than_the_room_for_it(self):
        prefs['stretch'] = False
        prefs['fit to size width other'] = 400
        prefs['fit to size height other'] = 400
        self._open('blue.png')
        self._activate('fit_size_mode')
        self.assertEqual((100, 100), self._shown_size())
        self._activate('stretch')
        self.assertTrue(prefs['stretch'])
        self.assertEqual((400, 400), self._shown_size())
        self._activate('stretch')
        self.assertFalse(prefs['stretch'])
        self.assertEqual((100, 100), self._shown_size())

    def test_zooming_in_and_out_and_back_to_the_original_size(self):
        self._open('blue.png')
        self._activate('fit_manual_mode')
        original = self._shown_size()
        self._activate('zoom_in')
        larger = self._shown_size()
        self.assertGreater(larger[0], original[0])
        self._activate('zoom_in')
        self.assertGreater(self._shown_size()[0], larger[0])
        self._activate('zoom_out')
        self.assertEqual(larger, self._shown_size())
        self._activate('zoom_original')
        self.assertEqual(original, self._shown_size())


# vim: expandtab:sw=4:ts=4
