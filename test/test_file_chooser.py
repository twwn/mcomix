""" The file chooser dialog, which GTK4 leaves MComix to assemble. """

import os
import shutil
import types
import unittest.mock

from gi.repository import Gdk, Gio, GLib, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import image_tools
from mcomix import file_chooser_base_dialog
from mcomix import main
from mcomix import widgets
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
        # Alphabetical order put ANI, APM and APNG ahead of JPEG and PNG.
        # Which formats there are depends on the gdk-pixbuf: the one on
        # Ubuntu 26.04, which decodes through glycin, offers no ANI.
        names = [f.get_name() for f in self.dialog.list_filters()]
        for kind, common in (
                ('archives', file_chooser_base_dialog._COMMON_ARCHIVES),
                ('images', file_chooser_base_dialog._COMMON_IMAGES)):
            with self.subTest(kind):
                offered = [name.removesuffix(' ' + kind) for name in names
                           if name.endswith(' ' + kind)
                           and not name.startswith('All ')]
                known = [name for name in common if name in offered]
                self.assertIn(common[0], known)
                self.assertEqual(
                    offered,
                    known + sorted(set(offered) - set(known)))

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
        self._select(path)
        self.dialog.response(Response.OK)
        self.assertEqual(chosen, [path])

    def _select(self, path):
        """Select the file <path> in the chooser, and wait until the
        chooser says it is selected.

        set_file() into a folder the chooser has not listed yet moves to
        the folder first, and on GitHub's Windows runner the folder's
        first file was what ended up selected: the preview went on to
        describe 01-JPG-Indexed.jpg, "1x1 px", for blue.png.  Waiting
        for any file to be selected did not tell the two apart.
        """
        chooser = self.dialog.filechooser
        chooser.set_file(Gio.File.new_for_path(path))
        self.assertTrue(
            wait_for(lambda: widgets.chooser_paths(chooser) == [path],
                     seconds=10),
            'the chooser selected %r, not %r'
            % (widgets.chooser_paths(chooser), path))

    def _choose(self, path):
        """Select <path> and answer Open, keeping what is handed on."""
        chosen = []
        self.dialog.files_chosen = chosen.extend
        self._select(path)
        self.dialog.response(Response.OK)
        return chosen

    def test_the_folder_a_file_was_chosen_in_is_remembered(self):
        prefs['store recent file info'] = True
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.assertEqual([path], self._choose(path))
        self.assertEqual(os.path.dirname(path),
                         prefs['path of last browsed in filechooser'])

    def test_without_a_file_history_no_folder_is_remembered(self):
        """"Store information about recently opened files" off keeps
        where the reader has been browsing out of the preferences too:
        the chooser opens in the home folder next time."""
        prefs['store recent file info'] = False
        prefs['path of last browsed in filechooser'] = self.tmp_dir
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.assertEqual([path], self._choose(path))
        self.assertEqual(constants.HOME_DIR,
                         prefs['path of last browsed in filechooser'])

    def _reopened_in(self):
        """Close the chooser, open it again with no book open, and
        answer with the folder it shows."""
        self._module._close_main_filechooser_dialog()
        pump()
        self._module.open_main_filechooser_dialog(None, self.window)
        pump()
        self.dialog = self._module._main_filechooser_dialog
        wait_for(lambda: self.dialog.filechooser.get_current_folder()
                 is not None)
        return self.dialog.filechooser.get_current_folder().get_path()

    def test_it_opens_where_the_reader_last_browsed(self):
        browsed = os.path.join(self.tmp_dir, 'browsed')
        os.makedirs(browsed)
        prefs['store recent file info'] = True
        prefs['path of last browsed in filechooser'] = browsed
        self.assertEqual(browsed, self._reopened_in())

    def test_without_a_file_history_it_opens_in_the_home_folder(self):
        """A folder remembered before the history was turned off is
        not where it opens either."""
        browsed = os.path.join(self.tmp_dir, 'browsed')
        os.makedirs(browsed)
        prefs['store recent file info'] = False
        prefs['path of last browsed in filechooser'] = browsed
        self.assertEqual(os.path.realpath(constants.HOME_DIR),
                         os.path.realpath(self._reopened_in()))

    def test_a_double_click_on_a_file_opens_it(self):
        chosen = []
        self.dialog.files_chosen = chosen.extend
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self._select(path)
        self.dialog._activated(None, 1, 0.0, 0.0)
        self.assertEqual([], chosen, 'a single click opened the file')
        self.dialog._activated(None, 2, 0.0, 0.0)
        self.assertEqual([path], chosen)

    def test_a_folder_chosen_hands_on_the_files_in_it(self):
        """In order, and only those the filter on show lets through."""
        folder = os.path.join(self.tmp_dir, 'book')
        os.makedirs(folder)
        # Enough pages that the order the folder lists them in is not
        # the natural one by chance.
        pages = ['page %d.png' % number for number in range(1, 13)]
        for name in reversed(pages[::2] + pages[1::2]):
            shutil.copy(get_testfile_path('images', 'blue.png'),
                        os.path.join(folder, name))
        with open(os.path.join(folder, 'notes.txt'), 'w') as notes:
            notes.write('Scanned at 600 dpi.\n')
        chosen = []
        self.dialog.files_chosen = chosen.extend
        self.dialog.filechooser.set_file(Gio.File.new_for_path(folder))
        wait_for(lambda: self.dialog.filechooser.get_file() is not None)
        # Chosen after the folder: GTK takes the filter away when
        # set_file() is given a folder.
        self.dialog.filechooser.set_filter(next(
            f for f in self.dialog.list_filters()
            if f.get_name() == 'All images'))
        self.dialog.response(Response.OK)
        self.assertEqual([os.path.join(folder, name) for name in pages],
                         chosen)

    def test_a_selected_file_is_previewed(self):
        # The thumbnail arrives on a worker thread, and the callback that
        # takes it used to ask the chooser what was being previewed with
        # an API GTK4 had removed, so it never arrived at all.
        path = get_testfile_path('images', 'blue.png')
        self._select(path)
        wait_for(lambda: self.dialog._preview_image.get_paintable() is not None)
        self.assertIsNotNone(self.dialog._preview_image.get_paintable(),
                             'the preview never appeared')
        self.assertEqual(self.dialog._namelabel.get_text(), 'blue.png')
        self.assertTrue(self.dialog._sizelabel.get_text(),
                        'the preview says no file size')

    def test_choosing_a_folder_after_a_file_clears_the_preview(self):
        """Driven through what the selection poll calls rather than
        through the chooser: GTK 4.14's chooser, handed a folder by
        set_file(), put up a dialog of its own."""
        self.dialog._stop_previewing()
        self.dialog._previewed = get_testfile_path('images', 'blue.png')
        self.dialog._update_preview()
        self.assertTrue(wait_for(
            lambda: self.dialog._preview_image.get_paintable() is not None))
        self.dialog._previewed = get_testfile_path('archives')
        self.dialog._update_preview()
        self.assertIsNone(self.dialog._preview_image.get_paintable(),
                          'the file stayed previewed')
        self.assertEqual(('', '', ''),
                         (self.dialog._namelabel.get_text(),
                          self.dialog._sizelabel.get_text(),
                          self.dialog._detailslabel.get_text()))

    def test_a_file_gone_before_its_preview_came_is_shown_with_no_size(self):
        path = os.path.join(self.tmp_dir, 'gone.png')
        self.dialog._stop_previewing()
        self.dialog._previewed = path
        self.dialog._preview_thumbnail_finished(
            path, image_tools.missing_image_icon(16, 16))
        self.assertEqual('gone.png', self.dialog._namelabel.get_text())
        self.assertEqual('', self.dialog._sizelabel.get_text())

    def test_what_is_found_out_about_a_file_no_longer_previewed_is_dropped(self):
        path = get_testfile_path('images', 'blue.png')
        self.dialog._stop_previewing()
        self.dialog._previewed = get_testfile_path('images', 'red.png')
        self.dialog._details_found(path, '100 x 100')
        self.assertIsNone(self.dialog._details)
        self.assertEqual('', self.dialog._detailslabel.get_text())

    def test_a_picture_is_previewed_turned_as_it_is_shown(self):
        """The picture is 210 pixels wide and 297 high, and its Exif
        data turns it a quarter when it is read; the preview showed it
        as it is stored."""
        prefs['auto rotate from exif'] = True
        path = get_testfile_path('images', 'landscape-exif-270-rotation.jpg')
        self._select(path)
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
        # Both written first, into a folder the chooser has not listed:
        # a file made after the chooser has listed its folder is not
        # there to be selected until it notices, which took GTK 4.14 on
        # GitHub longer than the wait.
        folder = os.path.join(self.tmp_dir, 'damaged')
        os.mkdir(folder)
        broken = {'broken.jpg': b'not an image',
                  'broken.cbz': b'PK\x03\x04garbage'}
        for name, body in broken.items():
            with open(os.path.join(folder, name), 'wb') as damaged:
                damaged.write(body)
        for name in broken:
            with self.subTest(name):
                path = os.path.join(folder, name)
                self.dialog._preview_image.set_paintable(None)
                self._select(path)
                self.assertTrue(wait_for(
                    lambda: self.dialog._namelabel.get_text() == name))
                paintable = self.dialog._preview_image.get_paintable()
                self.assertIsNotNone(paintable, 'the preview stayed empty')
                self.assertEqual(self.dialog._namelabel.get_text(), name)

    def test_the_preview_writes_the_size_as_the_list_beside_it_does(self):
        """GTK's list of files says "1.0 MB" of a file of a million
        bytes, and the preview under it said "976.6 KiB"."""
        path = os.path.join(self.tmp_dir, 'million.cbz')
        with open(path, 'wb') as book:
            book.write(b'PK\x03\x04'.ljust(1000000, b'\x00'))
        self._select(path)
        wait_for(lambda: self.dialog._namelabel.get_text() == 'million.cbz',
                 seconds=10)
        # GLib.format_size() is what GtkFileChooserWidget writes the
        # sizes in its list with.
        self.assertEqual(GLib.format_size(1000000),
                         self.dialog._sizelabel.get_text())

    def test_under_the_preview_a_picture_says_its_size_in_pixels(self):
        path = get_testfile_path('images', 'blue.png')
        self._select(path)
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

    def _books_in_folder(self, filter_name):
        """What adding a folder of books finds under <filter_name>."""
        folder = os.path.join(self.tmp_dir, 'books')
        os.makedirs(os.path.join(folder, 'deeper'))
        for name in ('LOUD.CBZ', 'quiet.cbz', 'rar.cbr', 'seven.CB7',
                     os.path.join('deeper', 'more.cbz'), 'notes.txt'):
            with open(os.path.join(folder, name), 'wb') as book:
                book.write(b'PK\x03\x04')
        dialog = self._open()
        chosen, = [f for f in dialog.list_filters()
                   if f.get_name() == filter_name]
        found = dialog.collect_files_from_subdir(
            folder, chosen, dialog.should_open_recursive())
        return sorted(os.path.relpath(path, folder) for path in found)

    def test_a_folder_added_as_zip_archives_brings_its_zip_books(self):
        """Python's mimetypes, which the walk asked, reads the system's
        mime.types files; one of them here calls .cbz a RAR comic.  So
        LOUD.CBZ, whose upper-case name no "*.cbz" matched, was left
        behind, although the chooser listed it under that filter."""
        self.assertEqual(
            ['LOUD.CBZ', os.path.join('deeper', 'more.cbz'), 'quiet.cbz'],
            self._books_in_folder('ZIP archives'))

    def test_a_name_in_capitals_is_taken_where_its_type_is_not_known(self):
        """GIO on Windows has no MIME type for .cbz or .cb7, so there the
        filter's own rules decide, and "*.cbz" matched lower case only:
        the chooser and the walk over a folder both left LOUD.CBZ out."""
        dialog = self._open()
        for filter_name, name in (('ZIP archives', 'LOUD.CBZ'),
                                  ('7z archives', 'seven.CB7'),
                                  ('All archives', 'LOUD.CBZ')):
            with self.subTest(filter_name=filter_name):
                chosen, = [f for f in dialog.list_filters()
                           if f.get_name() == filter_name]
                info = Gio.FileInfo()
                info.set_display_name(name)
                info.set_content_type('application/octet-stream')
                self.assertTrue(chosen.match(info))

    def test_a_folder_added_as_rar_archives_brings_no_zip_books(self):
        self.assertEqual(['rar.cbr'],
                         self._books_in_folder('RAR archives'))

    def test_a_folder_added_as_all_archives_brings_every_book(self):
        self.assertEqual(
            ['LOUD.CBZ', os.path.join('deeper', 'more.cbz'), 'quiet.cbz',
             'rar.cbr', 'seven.CB7'],
            self._books_in_folder('All archives'))


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

    def test_an_encrypted_book_whose_names_are_readable_is_counted(self):
        """A zip wants the password for its pages but not for its names,
        and was given its kind alone, as a book with an encrypted listing
        is."""
        self.assertEqual('4 pages, ZIP archive',
                         file_chooser_base_dialog.file_details(
                             get_testfile_path('archives', 'Encrypted.zip')))
        self.assertEqual([], self.asked)

    def test_a_file_mcomix_does_not_read_gives_nothing(self):
        path = os.path.join(self.tmp_dir, 'notes.txt')
        with open(path, 'w') as notes:
            notes.write('nothing to see')
        self.assertEqual('', file_chooser_base_dialog.file_details(path))
