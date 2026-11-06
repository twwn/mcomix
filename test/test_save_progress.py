"""Saving a book that takes a while: the dialog, Cancel, and what has to
wait for the save.

The book is a copy of the four-page test archive.  The packer is slowed
down to a file every so often, so that the save outlasts the moment
save_progress waits before it shows anything - which the tests shorten
as well.
"""

import os
import shutil
import threading
import unittest.mock

from gi.repository import GLib, Gtk

from . import (MComixTest, fresh_bookmarks_store, get_testfile_path, pump,
               wait_for)

from mcomix import archive_packer
from mcomix import constants
from mcomix import icons
from mcomix import keybindings
from mcomix import main
from mcomix import message_dialog
from mcomix import save_progress
from mcomix.dialog import Response


def _progress_dialogs():
    return [window for window in Gtk.Window.list_toplevels()
            if isinstance(window, save_progress._SaveProgressDialog)
            and window.get_visible()]


class LongSaveTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        keybindings._manager = None
        fresh_bookmarks_store()
        self.shelf = os.path.join(self.tmp_dir, 'shelf')
        os.makedirs(self.shelf)
        self.book = os.path.join(self.shelf, 'book.zip')
        shutil.copyfile(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                        self.book)
        self.window = main.MainWindow(open_path=self.book)
        main.set_main_window(self.window)
        images = self.window.imagehandler
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.file_loaded
            and images.get_number_of_pages() == 4
            and all(images.page_is_available(page) for page in range(1, 5)),
            seconds=20))
        with open(self.book, 'rb') as fp:
            self.before = fp.read()
        quiet = unittest.mock.patch.object(save_progress, 'QUIET_SECONDS', 0)
        quiet.start()
        self.addCleanup(quiet.stop)
        # Each file waits for the test to let it in.
        self.go_on = threading.Event()
        self.addCleanup(self.go_on.set)
        add = archive_packer._ZipWriter.add

        def held_add(writer, path, name):
            self.go_on.wait(10)
            add(writer, path, name)

        slow = unittest.mock.patch.object(archive_packer._ZipWriter, 'add',
                                          held_add)
        slow.start()
        self.addCleanup(slow.stop)
        with unittest.mock.patch.object(self.window.file_actions,
                                        'offer_to_save'):
            self.assertTrue(self.window.file_actions.remove_pages({1}))
        pump()

    def tearDown(self):
        self.go_on.set()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        fresh_bookmarks_store()
        super().tearDown()

    def _while_saving(self, step):
        """Run <step> from the main loop once the dialog is up."""
        def look():
            if not _progress_dialogs():
                return GLib.SOURCE_CONTINUE
            step(_progress_dialogs()[0])
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(20, look)

    def _answer_what_the_close_asks(self):
        """A saved book is still asked about on closing (a lead of its
        own): answer that it may close."""
        def answer():
            for dialog in self._message_dialogs():
                dialog.response(Response.NO)
            return GLib.SOURCE_CONTINUE
        source = GLib.timeout_add(20, answer)
        self.addCleanup(GLib.source_remove, source)

    def _message_dialogs(self):
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_visible()]

    def test_a_long_save_shows_its_progress_and_keeps_the_window_drawn(self):
        seen = {}

        def step(dialog):
            seen['window sensitive'] = self.window.get_sensitive()
            seen['transient for'] = dialog.get_transient_for()
            seen['saving'] = save_progress.saving()
            self.go_on.set()

        self._while_saving(step)
        self.assertTrue(self.window.file_actions.save_archive())
        self.assertEqual({'window sensitive': False,
                          'transient for': self.window,
                          'saving': True}, seen,
                         'the main loop did not run during the save')
        self.assertFalse(save_progress.saving())
        self.assertTrue(self.window.get_sensitive())
        self.assertEqual([], _progress_dialogs())
        with open(self.book, 'rb') as fp:
            self.assertNotEqual(self.before, fp.read())

    def test_cancel_keeps_the_archive_and_says_nothing_went_wrong(self):
        def step(dialog):
            dialog.response(Response.CANCEL)
            self.go_on.set()

        self._while_saving(step)
        self.assertFalse(self.window.file_actions.save_archive())
        pump()
        with open(self.book, 'rb') as fp:
            self.assertEqual(self.before, fp.read(),
                             'the archive was written over')
        self.assertEqual(['book.zip'], os.listdir(self.shelf))
        self.assertEqual([], self._message_dialogs(),
                         'a stopped save was reported as failed')
        self.assertTrue(self.window.file_actions.has_unsaved_changes(),
                        'the changes went with the save')
        self.assertTrue(self.window.get_sensitive())

    def test_closing_the_dialog_stops_the_save_and_waits_for_it(self):
        seen = []

        def step(dialog):
            dialog.close()
            seen.append(dialog.get_visible())
            self.go_on.set()

        self._while_saving(step)
        self.assertFalse(self.window.file_actions.save_archive())
        self.assertEqual([True], seen,
                         'the dialog went before the save had stopped')
        with open(self.book, 'rb') as fp:
            self.assertEqual(self.before, fp.read())

    def test_a_close_asked_for_during_the_save_waits_for_it(self):
        """The pages being packed are the files the book was extracted
        to, and closing it removes them."""
        seen = []

        def step(dialog):
            self.window.filehandler.close_file()
            seen.append(self.window.filehandler.file_loaded)
            self.go_on.set()

        self._while_saving(step)
        self.assertTrue(self.window.file_actions.save_archive())
        self.assertEqual([True], seen, 'the book closed under the save')
        self._answer_what_the_close_asks()
        self.assertTrue(wait_for(
            lambda: not self.window.filehandler.file_loaded))

    def test_a_book_handed_over_during_the_save_opens_after_it(self):
        other = os.path.join(self.tmp_dir, 'other.zip')
        shutil.copyfile(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                        other)
        seen = []

        def step(dialog):
            self.window.open_from_outside([other])
            seen.append(self.window.filehandler.get_path_to_base())
            self.go_on.set()

        self._while_saving(step)
        self.assertTrue(self.window.file_actions.save_archive())
        self.assertEqual([self.book], seen, 'the book closed under the save')
        self._answer_what_the_close_asks()
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.get_path_to_base() == other,
            seconds=10))

    def test_a_save_on_closing_that_is_stopped_keeps_the_book_open(self):
        closed = []

        def step(dialog):
            dialog.response(Response.CANCEL)
            self.go_on.set()

        self._while_saving(step)
        self.window.file_actions._closing_answered(
            Response.YES, lambda: closed.append(True))
        self.assertEqual([], closed, 'the book closed after Cancel')
        self.assertTrue(self.window.filehandler.file_loaded)
        with open(self.book, 'rb') as fp:
            self.assertEqual(self.before, fp.read())

    def test_save_as_from_the_editor_can_be_cancelled_as_well(self):
        from mcomix import edit_dialog
        self.window.file_actions.forget_changes()
        edit_dialog.open_dialog(None, self.window)
        editor = edit_dialog._dialog
        self.assertIsNotNone(editor)
        self.addCleanup(edit_dialog.close_dialog)
        target = os.path.join(self.shelf, 'copy.cbz')
        seen = []

        def step(dialog):
            seen.append((self.window.get_sensitive(), editor.get_sensitive(),
                         dialog.get_transient_for() is editor))
            dialog.response(Response.CANCEL)
            self.go_on.set()

        self._while_saving(step)
        editor._pack_archive(target)
        pump()
        self.assertEqual([(False, False, True)], seen)
        self.assertFalse(os.path.exists(target))
        self.assertEqual(['book.zip'], os.listdir(self.shelf))
        self.assertIs(edit_dialog._dialog, editor,
                      'the editor closed after Cancel')
        self.assertTrue(editor.get_sensitive())
        self.assertTrue(self.window.get_sensitive())
        self.assertEqual([], self._message_dialogs())


# vim: expandtab:sw=4:ts=4
