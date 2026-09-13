# -*- coding: utf-8 -*-

"""The archive editor, and the Save As chooser it opens.

The note under the file list was a Gtk.FileChooser extra widget, which
GTK4 does not have: setting it raised AttributeError and took the whole
Save As branch with it.
"""

import os

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import edit_dialog
from mcomix import file_chooser_simple_dialog
from mcomix import icons
from mcomix import main


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
