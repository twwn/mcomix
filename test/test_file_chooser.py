# -*- coding: utf-8 -*-

""" The file chooser dialog, which GTK4 leaves MComix to assemble. """

import os

from gi.repository import Gio, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import file_chooser_base_dialog
from mcomix import main


class FileChooserTest(MComixTest):

    def setUp(self):
        super(FileChooserTest, self).setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()
        from mcomix import file_chooser_main_dialog
        self._module = file_chooser_main_dialog
        file_chooser_main_dialog.open_main_filechooser_dialog(None, self.window)
        pump()
        self.dialog = file_chooser_main_dialog._main_filechooser_dialog

    def tearDown(self):
        self._module._close_main_filechooser_dialog()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super(FileChooserTest, self).tearDown()

    def test_the_dialog_border_is_not_a_transparent_strip(self):
        # Margins on a toplevel fall outside what it paints.
        self.assertEqual(self.dialog.get_margin_top(), 0)
        self.assertEqual(self.dialog.get_margin_end(), 0)

    def test_the_preview_keeps_one_size(self):
        # It scaled whatever it was given to whatever room it had, so a
        # thumbnail came out blurred and moved with the dialog.
        picture = self.dialog._preview_image
        self.assertEqual(picture.get_content_fit(), Gtk.ContentFit.SCALE_DOWN)
        self.assertEqual(picture.get_size_request(),
                         (self.dialog._preview_size,
                          self.dialog._preview_size))

    def test_the_preview_follows_the_screen(self):
        from mcomix import preview
        base = file_chooser_base_dialog
        size, pixels = base.preview_size(self.dialog)
        self.assertGreaterEqual(size, base._PREVIEW_SIZE)
        self.assertLessEqual(size,
                             base._PREVIEW_SIZE * preview._MAX_FACTOR)
        # Rendered from at least as many pixels as it is drawn with, so
        # a scaled screen does not get a blurred one.
        self.assertGreaterEqual(pixels, size)
        self.assertEqual(pixels % size, 0)

    def test_the_preview_is_rendered_for_the_screen_it_is_drawn_on(self):
        self.assertEqual(self.dialog._preview_pixels,
                         self.dialog._preview_size
                         * max(1, self.dialog.get_scale_factor()))

    def test_the_preview_column_keeps_its_width(self):
        # An ellipsized label still asks for room for all of its text, so
        # the column - and the file list beside it - moved every time the
        # name under the preview changed, or a file with no preview was
        # picked.
        import shutil
        long_name = 'a-really-quite-extremely-long-file-name-for-testing.png'
        shutil.copy(get_testfile_path('images', 'blue.png'),
                    os.path.join(self.tmp_dir, long_name))
        with open(os.path.join(self.tmp_dir, 'notes.txt'), 'w') as handle:
            handle.write('not an image')
        column = self.dialog._preview_image.get_parent()

        def select(path, expected):
            self.dialog.filechooser.set_file(Gio.File.new_for_path(path))
            wait_for(lambda: self.dialog._namelabel.get_text() == expected)
            pump()
            return column.get_width()

        widths = {
            'short name': select(get_testfile_path('images', 'blue.png'),
                                 'blue.png'),
            'long name': select(os.path.join(self.tmp_dir, long_name),
                                long_name),
            'no preview': select(os.path.join(self.tmp_dir, 'notes.txt'), ''),
        }
        self.assertEqual(len(set(widths.values())), 1,
                         'the preview column changed width: %r' % (widths,))

    def _filter_menu(self):
        return self.dialog._descendant(self.dialog.filechooser, Gtk.DropDown)

    def test_the_filter_and_the_buttons_share_a_row(self):
        # The chooser keeps its filter in an action bar of its own and a
        # Gtk.Dialog keeps its buttons in another, so they came out on
        # two rows stacked against the bottom right corner.
        menu = self._filter_menu()
        self.assertIsNotNone(menu, 'the chooser has no filter menu')
        self.assertTrue(self.dialog._buttons, 'the dialog has no buttons')
        pump()

        def bounds(widget):
            ok, rectangle = widget.compute_bounds(self.dialog)
            self.assertTrue(ok)
            return rectangle

        row = bounds(menu)
        for button in self.dialog._buttons:
            self.assertAlmostEqual(bounds(button).origin.y, row.origin.y,
                                   delta=6,
                                   msg='a button is not on the filter row')
            self.assertGreater(bounds(button).origin.x, row.origin.x,
                               'the filter should come before the buttons')

    def test_the_buttons_still_answer(self):
        answered = []
        self.dialog.connect('response', lambda _d, r: answered.append(r))
        for button in self.dialog._buttons:
            button.emit('clicked')
        self.assertIn(Gtk.ResponseType.CANCEL, answered)
        self.assertIn(Gtk.ResponseType.OK, answered)

    def test_the_group_filters_come_first(self):
        names = [f.get_name() for f in self.dialog.list_filters()]
        self.assertEqual(names[:3], ['All files', 'All archives',
                                     'All images'])

    def test_the_formats_a_reader_opens_come_before_the_rest(self):
        names = [f.get_name() for f in self.dialog.list_filters()]
        # Alphabetical order put ANI, APM and APNG ahead of JPEG and PNG.
        for earlier, later in (('ZIP archives', 'LHA archives'),
                               ('JPEG images', 'ANI images'),
                               ('PNG images', 'BMP images')):
            self.assertLess(names.index(earlier), names.index(later),
                            '%s should come before %s' % (earlier, later))

    def test_choosing_a_file_hands_it_on(self):
        # get_filenames() is not in GTK4, and it was what the response
        # asked for, so Open and a double click both did nothing at all.
        chosen = []
        self.dialog.files_chosen = chosen.extend
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.dialog.filechooser.set_file(Gio.File.new_for_path(path))
        wait_for(lambda: self.dialog.filechooser.get_file() is not None)
        self.dialog.response(Gtk.ResponseType.OK)
        self.assertEqual(chosen, [path])

    def test_a_selected_file_is_previewed(self):
        # The thumbnail arrives on a worker thread, and the callback that
        # takes it used to ask the chooser what was being previewed with
        # an API GTK4 had removed, so it never arrived at all.
        path = get_testfile_path('images', 'blue.png')
        self.dialog.filechooser.set_file(Gio.File.new_for_path(path))
        wait_for(lambda: self.dialog._preview_image.get_paintable() is not None)
        self.assertIsNotNone(self.dialog._preview_image.get_paintable(),
                             'the preview never appeared')
        self.assertEqual(self.dialog._namelabel.get_text(), 'blue.png')
        self.assertTrue(self.dialog._sizelabel.get_text(),
                        'the preview says no file size')

# vim: expandtab:sw=4:ts=4
