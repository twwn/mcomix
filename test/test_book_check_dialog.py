""""Select books > Books that cannot be read in full..." in the library
(mcomix.library.book_check_dialog), from the command to the books it
selects."""

import errno
import os
import shutil
import threading
import unittest.mock
import zipfile

from gi.repository import Gtk

from . import (damage_member, get_testfile_path, label_texts, line_art_png,
               pump, refuse_passwords, stop_on_the_second, wait_for)
from .test_library_dialog import _LibraryWindowTest
from mcomix.library import book_check
from mcomix.library import book_check_dialog
from mcomix.preferences import prefs


class BookCheckDialogTest(_LibraryWindowTest):

    """A sound book, a damaged one and an encrypted one."""

    def setUp(self):
        super().setUp()
        self.library = self._open_all()
        self.asked = refuse_passwords(self)
        self.sound = self._book('sound.cbz')
        self.damaged = self._book('damaged.cbz')
        damage_member(self.damaged, '02.png')
        self.encrypted = os.path.join(self.tmp_dir, 'encrypted.zip')
        shutil.copy(get_testfile_path('archives', 'Encrypted.zip'),
                    self.encrypted)

    def _book(self, name):
        path = os.path.join(self.tmp_dir, name)
        with zipfile.ZipFile(path, 'w') as book:
            for number in (1, 2, 3):
                book.writestr('%02d.png' % number, line_art_png())
        return path

    def _started(self, *paths):
        """Hold <paths> in the library, give the command and answer with
        its window."""
        self._held(self.library, *paths)
        self.library.book_area.check_books()
        found, = [window for window in Gtk.Window.list_toplevels()
                  if isinstance(window, book_check_dialog.BookCheckDialog)]
        self.addCleanup(found.destroy)
        return found

    def _checked(self, *paths):
        found = self._started(*paths)
        self.assertTrue(wait_for(lambda: found.finished, seconds=20))
        pump()
        return found

    def test_the_books_that_cannot_be_read_are_listed(self):
        found = self._checked(self.sound, self.damaged, self.encrypted)
        self.assertEqual({self.damaged: book_check.Fault.DAMAGED,
                          self.encrypted: book_check.Fault.ENCRYPTED},
                         {path: checked.fault
                          for path, checked in found.found.items()})
        self.assertEqual([], self.asked)
        texts = '\n'.join(label_texts(found))
        self.assertIn('2 books cannot be read in full.', texts)
        self.assertIn('damaged - 1 file cannot be read', texts)
        self.assertNotIn('sound.cbz', texts)

    def test_they_are_selected_in_the_library(self):
        found = self._checked(self.sound, self.damaged, self.encrypted)
        found.response(book_check_dialog._SELECT)
        pump()
        self.assertEqual(
            sorted([self.damaged, self.encrypted]),
            sorted(item.path for item in
                   self.library.book_area._selected_items()))

    def test_every_book_sound(self):
        found = self._checked(self.sound)
        self.assertEqual({}, found.found)
        self.assertIn('Every book can be read in full.',
                      found._status.get_text())
        self.assertIsNone(found.get_widget_for_response(
            book_check_dialog._SELECT))

    def test_a_book_not_there_is_left_to_its_own_entry(self):
        """"Books whose file is not there" selects those."""
        self._held(self.library, self.damaged)
        os.remove(self.damaged)
        found = self._checked()
        self.assertEqual({}, found.found)

    def test_a_disk_that_fails_is_not_the_book(self):
        def full(path, stop):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        self.enterContext(unittest.mock.patch.object(book_check, 'check',
                                                     full))
        found = self._checked(self.damaged)
        self.assertEqual({}, found.found)
        self.assertEqual([self.damaged], list(found.unchecked))
        self.assertIn('1 book could not be checked: see the log.',
                      found._status.get_text())

    def test_stop_lists_what_was_found(self):
        """One book at a time, and the second held until Stop."""
        self.enterContext(unittest.mock.patch.dict(prefs,
                                                   {'max threads': 1}))
        go = threading.Event()
        checked = book_check.check
        reads = []

        def check(path, stop):
            reads.append(path)
            if len(reads) == 2:
                go.wait(10)
            return checked(path, stop)
        self.enterContext(unittest.mock.patch.object(book_check, 'check',
                                                     check))
        found = self._started(self.damaged, self.sound, self.encrypted)
        stop_on_the_second(found, reads, go)
        self.assertEqual([self.damaged], list(found.found))
        self.assertIn('Stopped with 2 books not yet read.',
                      found._status.get_text())
