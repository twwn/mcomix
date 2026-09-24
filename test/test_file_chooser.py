""" The file chooser dialog, which GTK4 leaves MComix to assemble. """

import os
import types
import unittest.mock

from gi.repository import Gdk, Gio, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import file_chooser_base_dialog
from mcomix import main
from mcomix.archive import password as archive_password
from mcomix.dialog import Response
from mcomix.preferences import prefs


class FileChooserTest(MComixTest):

    def setUp(self):
        super().setUp()
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
        super().tearDown()

    # -- Walking from the search box into what it found -------------------

    def test_the_search_box_and_the_list_of_files_are_both_found(self):
        """Both are GTK's own, inside the Gtk.FileChooserWidget, and the
        filter dropdown has a search box and a list of its own that are
        not them."""
        self.assertIsInstance(self.dialog._search, Gtk.SearchEntry)
        self.assertIsInstance(self.dialog._listing, Gtk.ColumnView)
        self.assertIsNone(self.dialog._search.get_ancestor(Gtk.Popover))
        self.assertIsNone(self.dialog._listing.get_ancestor(Gtk.Popover))

    def test_down_from_the_search_box_takes_the_first_file_it_found(self):
        """The arrows used to stay in the box, so the only way to a
        result was the mouse."""
        wait_for(lambda: self.dialog._listing.get_model().get_n_items())
        self.assertTrue(self.dialog._into_the_list(Gdk.KEY_Down))
        selected = self.dialog._listing.get_model().get_selection()
        self.assertFalse(selected.is_empty())
        self.assertEqual(selected.get_minimum(), 0)

    def test_down_does_nothing_where_nothing_was_found(self):
        self.dialog._listing.set_model(None)
        self.assertFalse(self.dialog._into_the_list(Gdk.KEY_Down))

    def test_only_the_down_arrow_leaves_the_search_box(self):
        wait_for(lambda: self.dialog._listing.get_model().get_n_items())
        self.assertFalse(self.dialog._into_the_list(Gdk.KEY_Right))

    def test_up_off_the_top_of_the_list_goes_back_to_the_search_box(self):
        wait_for(lambda: self.dialog._listing.get_model().get_n_items())
        self.dialog._listing.get_model().select_item(0, True)
        self.assertTrue(self.dialog._back_to_the_search(Gdk.KEY_Up))

    def test_up_anywhere_else_in_the_list_is_the_row_above(self):
        """Which is what the list does with it itself."""
        wait_for(lambda: self.dialog._listing.get_model().get_n_items() > 1)
        self.dialog._listing.get_model().select_item(1, True)
        self.assertFalse(self.dialog._back_to_the_search(Gdk.KEY_Up))

    def test_the_dialog_border_is_not_a_transparent_strip(self):
        # Margins on a toplevel fall outside what it paints.
        self.assertEqual(self.dialog.get_margin_top(), 0)
        self.assertEqual(self.dialog.get_margin_end(), 0)

    def test_the_dialog_has_a_transient_parent(self):
        # It shows itself as it is built, so a parent set by the caller
        # afterwards arrived after the mapping GTK warns about.
        self.assertIs(self.dialog.get_transient_for(), self.window)

    def test_a_chooser_with_no_parent_takes_the_main_window(self):
        from mcomix import file_chooser_simple_dialog
        dialog = file_chooser_simple_dialog.SimpleFileChooserDialog()
        # GTK starts loading the folder once the loop turns, and a
        # chooser destroyed before then reports the cancelled load in
        # an error dialog of GTK's own, which outlives the chooser.
        pump()
        try:
            self.assertIs(dialog.get_transient_for(), self.window)
        finally:
            dialog.destroy()
            pump()

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
        # Without the dialog's own answer to them: the first would close
        # it, and a closed dialog's buttons let go of it.
        self.dialog.handler_block_by_func(self.dialog._response)
        try:
            for button in self.dialog._buttons:
                button.emit('clicked')
        finally:
            self.dialog.handler_unblock_by_func(self.dialog._response)
        self.assertIn(Response.CANCEL, answered)
        self.assertIn(Response.OK, answered)

    def test_a_remembered_filter_that_is_gone_falls_back_to_all_files(self):
        """The preference is an index into a list built afresh from
        what MComix can open, so one written by a build with more
        formats in it names nothing here.  What this pins is that the
        index is caught: GTK selects the first filter of its own accord,
        so the fallback shows only by the dialog opening at all."""
        from mcomix import file_chooser_main_dialog
        prefs['last filter in main filechooser'] = 999
        self._module._close_main_filechooser_dialog()
        pump()
        file_chooser_main_dialog.open_main_filechooser_dialog(None, self.window)
        pump()
        dialog = file_chooser_main_dialog._main_filechooser_dialog
        self.assertEqual(dialog.filechooser.get_filter().get_name(),
                         'All files')

    # -- Opening what was chosen --------------------------------------------

    def test_one_file_chosen_opens_its_directory(self):
        self.dialog.files_chosen(
            [get_testfile_path('images', 'portrait-no-exif.png')])
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 1))
        self.assertIsNone(self._module._main_filechooser_dialog)

    def test_several_files_chosen_open_those_alone(self):
        """Choosing several restricts the book to them, rather than to
        the directory the first is in."""
        chosen = [get_testfile_path('images', name)
                  for name in ('portrait-no-exif.png', 'red.png')]
        self.dialog.files_chosen(chosen)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0))
        pump()
        self.assertEqual(2, self.window.imagehandler.get_number_of_pages())

    def test_the_filter_files_were_opened_with_is_remembered(self):
        images = self.dialog.list_filters().index(
            next(f for f in self.dialog.list_filters()
                 if f.get_name() == 'All images'))
        self.dialog.filechooser.set_filter(self.dialog.list_filters()[images])
        self.dialog.files_chosen(
            [get_testfile_path('images', 'portrait-no-exif.png')])
        self.assertEqual(images, prefs['last filter in main filechooser'])

    def test_choosing_nothing_only_closes_it(self):
        self.dialog.files_chosen([])
        pump()
        self.assertIsNone(self._module._main_filechooser_dialog)
        self.assertFalse(self.window.filehandler.file_loaded)

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

    def test_closing_the_chooser_stops_the_preview_poll(self):
        """Nothing announces a change of selection, so the preview is
        polled every 200 ms.  The timer was dropped from the window's
        'destroy' signal, which GTK4 emits when the last reference to
        the window goes rather than when it is destroyed - and the
        handler is a method of the window, so the closure held a
        reference and the poll went on reading a destroyed chooser for
        the rest of the session."""
        self.assertIsNotNone(self.dialog._preview_timer)
        self._module._close_main_filechooser_dialog()
        pump()
        self.assertIsNone(self.dialog._preview_timer,
                          'the preview poll is still running')

    def test_choosing_a_file_hands_it_on(self):
        # get_filenames() is not in GTK4, and it was what the response
        # asked for, so Open and a double click both did nothing at all.
        chosen = []
        self.dialog.files_chosen = chosen.extend
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.dialog.filechooser.set_file(Gio.File.new_for_path(path))
        wait_for(lambda: self.dialog.filechooser.get_file() is not None)
        self.dialog.response(Response.OK)
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

    def test_a_picture_is_previewed_turned_as_it_is_shown(self):
        """The picture is 210 pixels wide and 297 high, and its Exif
        data turns it a quarter when it is read; the preview showed it
        as it is stored."""
        prefs['auto rotate from exif'] = True
        path = get_testfile_path('images', 'landscape-exif-270-rotation.jpg')
        self.dialog.filechooser.set_file(Gio.File.new_for_path(path))
        wait_for(lambda: self.dialog._preview_image.get_paintable() is not None)
        paintable = self.dialog._preview_image.get_paintable()
        self.assertIsNotNone(paintable, 'the preview never appeared')
        self.assertGreater(paintable.get_intrinsic_width(),
                           paintable.get_intrinsic_height())
    def test_a_file_that_will_not_load_is_previewed_as_one(self):
        """A picture or a book whose thumbnail could not be made left
        the preview empty, with no name under it, as though nothing
        were selected, while the library and the thumbnail bar show the
        picture that says the image would not load."""
        # Both written first: a file made after the chooser has listed
        # its folder is not there to be selected until it notices.
        broken = {'broken.jpg': b'not an image',
                  'broken.cbz': b'PK\x03\x04garbage'}
        for name, body in broken.items():
            with open(os.path.join(self.tmp_dir, name), 'wb') as damaged:
                damaged.write(body)
        for name in broken:
            with self.subTest(name):
                path = os.path.join(self.tmp_dir, name)
                self.dialog._preview_image.set_paintable(None)
                self.dialog.filechooser.set_file(Gio.File.new_for_path(path))
                wait_for(lambda: self.dialog._namelabel.get_text() == name)
                paintable = self.dialog._preview_image.get_paintable()
                self.assertIsNotNone(paintable, 'the preview stayed empty')
                self.assertEqual(self.dialog._namelabel.get_text(), name)

    def test_under_the_preview_a_picture_says_its_size_in_pixels(self):
        path = get_testfile_path('images', 'blue.png')
        self.dialog.filechooser.set_file(Gio.File.new_for_path(path))
        self.assertTrue(wait_for(
            lambda: self.dialog._detailslabel.get_text() == '100x100 px',
            seconds=10), repr(self.dialog._detailslabel.get_text()))


# vim: expandtab:sw=4:ts=4


class _Library(Gtk.Window):

    """The library window, as far as its file chooser asks."""

    #: The collection the library is showing.
    SHOWN = 7

    def __init__(self):
        super().__init__()
        self.added = []
        self.collection_area = types.SimpleNamespace(
            get_current_collection=lambda: self.SHOWN)

    def add_books(self, paths, collection):
        self.added.append((paths, collection))


class LibraryFileChooserTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.library = _Library()
        pump()
        from mcomix import file_chooser_library_dialog
        self._module = file_chooser_library_dialog

    def tearDown(self):
        self._module.close_library_filechooser_dialog()
        self.library.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _open(self):
        self._module.open_library_filechooser_dialog(self.library)
        pump()
        return self._module._library_filechooser_dialog

    def test_takes_no_filter_out_of_the_chooser(self):
        """GTK 4.22's remove_filter() frees the filter it takes out while
        the chooser's own list and PyGObject still refer to it; the
        chooser took out "All files", and the next garbage collection
        crashed MComix with a segmentation fault."""
        with unittest.mock.patch.object(Gtk.FileChooserWidget,
                                        'remove_filter') as remove:
            self._open()
        remove.assert_not_called()

    def test_all_files_is_not_offered(self):
        names = [f.get_name() for f in self._open().list_filters()]
        self.assertEqual(names[0], 'All archives')
        self.assertNotIn('All files', names)

    def test_it_opens_on_all_archives(self):
        self.assertEqual(self._open().filechooser.get_filter().get_name(),
                         'All archives')

    def test_a_remembered_filter_it_does_not_have_opens_all_archives(self):
        for remembered in (0, 999):
            prefs['last filter in library filechooser'] = remembered
            self.assertEqual(
                self._open().filechooser.get_filter().get_name(),
                'All archives')
            self._module.close_library_filechooser_dialog()
            pump()

    def test_books_go_into_the_collection_on_show(self):
        dialog = self._open()
        dialog.files_chosen(['/books/one.cbz'])
        pump()
        self.assertEqual([(['/books/one.cbz'], _Library.SHOWN)],
                         self.library.added)

    def test_the_filter_books_were_added_with_is_the_one_it_opens_on(self):
        """The index was written into the list without "All files" and
        read back from the list with it, so the chooser opened on the
        filter before the one last used - or, after "All archives", on
        "All files", which is not in the chooser at all."""
        for position in range(3):
            dialog = self._open()
            chosen = dialog.list_filters()[position]
            dialog.filechooser.set_filter(chosen)
            dialog.files_chosen(['/books/one.cbz'])
            pump()
            self.assertEqual(
                self._open().filechooser.get_filter().get_name(),
                chosen.get_name())
            self._module.close_library_filechooser_dialog()
            pump()


class FileDetailsTest(MComixTest):

    """What the file chooser's preview says about a file, below its name
    and size."""

    def setUp(self):
        super().setUp()
        self.asked = []

        def ask(archive, on_password):
            self.asked.append(archive)
            on_password(None)

        patcher = unittest.mock.patch.object(
            archive_password, 'ask_for_password', ask)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_picture_gives_its_size_in_pixels(self):
        self.assertEqual('100x100 px', file_chooser_base_dialog.file_details(
            get_testfile_path('images', 'blue.png')))

    def test_a_book_gives_its_page_count_and_kind(self):
        """The four pictures, not the comment beside them."""
        self.assertEqual('4 pages, ZIP archive',
                         file_chooser_base_dialog.file_details(
                             get_testfile_path('archives',
                                               '01-ZIP-Normal.zip')))

    def test_a_book_whose_listing_is_encrypted_gives_its_kind_alone(self):
        """Its names cannot be read without the password, which the
        preview does not ask for."""
        details = file_chooser_base_dialog.file_details(
            get_testfile_path('archives', 'EncryptedHeader.7z'))
        self.assertEqual([], self.asked)
        self.assertNotIn('page', details)

    def test_a_file_mcomix_does_not_read_gives_nothing(self):
        path = os.path.join(self.tmp_dir, 'notes.txt')
        with open(path, 'w') as notes:
            notes.write('nothing to see')
        self.assertEqual('', file_chooser_base_dialog.file_details(path))
