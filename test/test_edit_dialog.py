# -*- coding: utf-8 -*-

"""The archive editor, and the Save As chooser it opens.

The note under the file list was a Gtk.FileChooser extra widget, which
GTK4 does not have: setting it raised AttributeError and took the whole
Save As branch with it.
"""

import os
import unittest.mock

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import edit_dialog
from mcomix import file_chooser_simple_dialog
from mcomix import icons
from mcomix import main
from mcomix import message_dialog


class EditArchiveDialogTest(MComixTest):

    def setUp(self):
        super(EditArchiveDialogTest, self).setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)
        self.dialog = edit_dialog._EditArchiveDialog(self.window)
        pump()

    def tearDown(self):
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, file_chooser_simple_dialog.
                          SimpleFileChooserDialog):
                window.destroy()
        self.dialog.destroy()
        edit_dialog._close_dialog()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super(EditArchiveDialogTest, self).tearDown()

    def _chooser(self):
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, file_chooser_simple_dialog.
                          SimpleFileChooserDialog):
                return window
        return None

    def test_a_page_with_no_path_is_left_out_of_the_image_area(self):
        """The page count is read once and the paths one at a time, so a
        book closed in between leaves pages that answer with no path at
        all - and os.path.basename() does not take None."""
        area = self.dialog._image_area
        handler = self.window.imagehandler
        pages = handler.get_number_of_pages()
        self.assertGreater(pages, 1, 'the fixture archive has too few pages')
        real = handler.get_path_to_page

        def gone(page=None):
            return None if page == 1 else real(page)

        handler.get_path_to_page = gone
        try:
            area.fetch_images()
        finally:
            handler.get_path_to_page = real

        self.assertEqual(len(area.get_file_listing()), pages - 1,
                         'the page with no path was not left out')

    def _packing_dialogs(self):
        """Every message dialog standing over this window."""
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_transient_for() is self.window]

    def test_a_failed_load_gives_the_window_its_cursor_back(self):
        """The wait cursor is set on the main window rather than on the
        editor, so anything getting out of the loading left the whole
        program pointing at it, with an editor that could neither save
        nor import."""
        def refuse():
            raise OSError(5, 'Input/output error')

        with unittest.mock.patch.object(self.dialog._image_area,
                                        'fetch_images', refuse):
            with self.assertRaises(OSError):
                self.dialog._load_original_files()
        pump()
        self.assertIsNone(self.window._main_layout.get_cursor(),
                          'the window was left pointing at a wait cursor')
        self.assertTrue(self.dialog._save_button.get_sensitive())
        self.assertTrue(self.dialog._import_button.get_sensitive())

    def test_a_load_that_finishes_leaves_no_cursor_behind_either(self):
        self.dialog._load_original_files()
        pump()
        self.assertIsNone(self.window._main_layout.get_cursor())
        self.assertTrue(self.dialog._save_button.get_sensitive())

    def test_a_save_that_fails_partway_says_so_and_lets_go(self):
        """Only the temporary file was guarded.  A failure at the rename
        over the old archive, or at the permissions on the new one,
        escaped into the signal handler that asked for the save and left
        the dialog insensitive under a wait cursor."""
        target = os.path.join(self.tmp_dir, 'saved.cbz')
        standing = len(self._packing_dialogs())

        def refuse(*args, **kwargs):
            raise OSError(13, 'Permission denied')

        with unittest.mock.patch('os.rename', refuse):
            self.dialog._pack_archive(target)
        pump()

        try:
            self.assertEqual(len(self._packing_dialogs()), standing + 1,
                             'the failure was not reported')
            self.assertFalse(os.path.exists(target),
                             'a broken archive was left under the real name')
            self.assertEqual([name for name in os.listdir(self.tmp_dir)
                              if name.startswith('tmp.')], [],
                             'the temporary archive was left behind')
        finally:
            # A dialog left standing is answered by whichever test goes
            # looking for one next.
            for dialog in self._packing_dialogs():
                dialog.destroy()
            pump()

    def test_save_as_opens_a_chooser_saying_what_it_writes(self):
        self.dialog._response(self.dialog, constants.RESPONSE_SAVE_AS)
        pump()
        chooser = self._chooser()
        self.assertIsNotNone(chooser)
        self.assertEqual(chooser._note.get_text(),
                         'Archives are stored as ZIP files.')

    def test_save_as_offers_the_archive_under_a_name_of_its_own(self):
        self.dialog._response(self.dialog, constants.RESPONSE_SAVE_AS)
        pump()
        chooser = self._chooser()
        self.assertEqual(chooser.save_name, '01-ZIP-Normal.cbz')

    def test_import_opens_a_chooser_without_a_note(self):
        self.dialog._response(self.dialog, constants.RESPONSE_IMPORT)
        pump()
        chooser = self._chooser()
        self.assertIsNotNone(chooser)
        self.assertIsNone(chooser._note)


# vim: expandtab:sw=4:ts=4
