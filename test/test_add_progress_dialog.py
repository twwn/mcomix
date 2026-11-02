"""Adding a batch of books to the library.

The dialog is the only bulk write in the library that used to run
outside a transaction, and the connection commits every statement by
itself, so each of add_book()'s three writes was a journal write and an
fsync of its own.
"""

import os
import shutil

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump

from mcomix import constants
from mcomix.archive import rar
from mcomix.archive import rar_external
from mcomix.dialog import Response
from mcomix.library import add_progress_dialog
from mcomix.library import backend as backend_module


class _StubLibrary(Gtk.Window):

    """Enough of _LibraryDialog for the progress dialog to sit on."""

    def __init__(self, library_backend):
        super().__init__()
        self.backend = library_backend
        self.messages = []

    def set_status_message(self, message):
        self.messages.append(message)


class AddProgressDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.backend = backend_module.LibraryBackend()
        self.collection = self.backend.add_collection('Shelf')
        self.library = _StubLibrary(self.backend)
        # add_book() reads the archive to learn its format, pages and
        # size; what is under test is the writing that follows.
        self.isolation_levels = []
        real_add_book = self.backend.add_book

        def add_book(path, collection=None):
            self.isolation_levels.append(self.backend._con.isolation_level)
            return real_add_book(path, collection)

        self.backend.add_book = add_book
        self.paths = [os.path.join(self.tmp_dir, '%d.cbz' % n)
                      for n in range(4)]

    def tearDown(self):
        for window in Gtk.Window.list_toplevels():
            if window.get_visible():
                window.destroy()
        pump()
        self.backend.close()
        backend_module._backend = None
        super().tearDown()

    def _add(self, paths):
        dialog = add_progress_dialog._AddLibraryProgressDialog(
            self.library, paths, self.collection)
        pump()
        return dialog

    def test_the_whole_batch_is_one_transaction(self):
        self._add(self.paths)

        self.assertEqual(['IMMEDIATE'] * len(self.paths),
                         self.isolation_levels,
                         'the books were added one commit at a time')

    def test_the_connection_is_left_in_auto_commit_mode(self):
        self._add(self.paths)

        self.assertIsNone(self.backend._con.isolation_level,
                          'the library would wait for a commit that never '
                          'comes for the rest of the session')

    def test_the_books_are_committed(self):
        # The transaction has to be closed rather than left open or
        # rolled back, so the books are looked for afterwards.
        archives = []
        for name in ('one.cbz', 'two.cbz'):
            path = os.path.join(self.tmp_dir, name)
            shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                        path)
            archives.append(path)

        self._add(archives)

        self.assertFalse(self.backend._con.in_transaction)
        self.assertEqual(
            archives,
            sorted(book.path for book in
                   [self.backend.get_book_by_path(p) for p in archives]),
            'the books the dialog added are not in the library')

    def test_a_damaged_book_does_not_stop_the_rest(self):
        """A tar archive broken off halfway raised out of add_book(), and
        so out of the loop: the books after it were never added, and the
        progress dialog stayed on screen."""
        with open(get_testfile_path('archives', '02-TAR-Normal.tar'),
                  'rb') as whole:
            data = whole.read()
        damaged = os.path.join(self.tmp_dir, 'damaged.tar')
        with open(damaged, 'wb') as book:
            book.write(data[:len(data) // 2])
        after = os.path.join(self.tmp_dir, 'after.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), after)

        self._add([damaged, after])

        self.assertIsNone(self.backend.get_book_by_path(damaged))
        self.assertIsNotNone(self.backend.get_book_by_path(after),
                             'the book after the damaged one was not added')
        self.assertFalse(
            [window for window in Gtk.Window.list_toplevels()
             if isinstance(window, add_progress_dialog._AddLibraryProgressDialog)
             and window.get_visible()],
            'the progress dialog stayed up')

    def _damaged(self, name):
        path = os.path.join(self.tmp_dir, name)
        with open(path, 'wb') as book:
            book.write(b'not a book')
        return path

    def test_the_reader_is_told_which_books_were_not_added(self):
        good = os.path.join(self.tmp_dir, 'good.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), good)

        self._add([self._damaged('bad.cbz'), good])

        self.assertEqual(
            ['Could not add 1 book to the library: bad.cbz'],
            self.library.messages)

    def test_a_long_list_is_not_named_in_full(self):
        self._add([self._damaged('%d.cbz' % n) for n in range(5)])

        self.assertEqual(
            ['Could not add 5 books to the library: 0.cbz, 1.cbz, 2.cbz, …'],
            self.library.messages)

    def test_books_all_added_leave_the_status_bar_alone(self):
        good = os.path.join(self.tmp_dir, 'good.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), good)

        self._add([good])

        self.assertEqual([], self.library.messages)

    def test_the_later_volumes_of_a_set_are_not_missed(self):
        """They are left out on purpose, and the set is there through
        its first volume."""
        if not (rar.RarArchive.is_available()
                or rar_external.RarArchive.is_available()):
            self.skipTest('nothing here reads RAR')
        paths = []
        for part in (1, 2, 3):
            name = 'Multivolume.part%d.rar' % part
            paths.append(os.path.join(self.tmp_dir, name))
            shutil.copy(get_testfile_path('archives', name), paths[-1])

        self._add(paths)

        self.assertEqual([], self.library.messages)

    def test_stopping_still_says_what_was_not_added(self):
        real = self.backend.add_book
        damaged, after = self._damaged('bad.cbz'), self._damaged('after.cbz')

        def add_book_then_stop(path, collection=None):
            added = real(path, collection)
            for window in Gtk.Window.list_toplevels():
                if isinstance(window,
                              add_progress_dialog._AddLibraryProgressDialog):
                    window.response(Response.CLOSE)
            return added

        self.backend.add_book = add_book_then_stop

        self._add([damaged, after])

        self.assertEqual(
            ['Could not add 1 book to the library: bad.cbz'],
            self.library.messages)
