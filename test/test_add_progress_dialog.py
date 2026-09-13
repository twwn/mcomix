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
from mcomix.library import add_progress_dialog
from mcomix.library import backend as backend_module


class _StubLibrary(Gtk.Window):

    """Enough of _LibraryDialog for the progress dialog to sit on."""

    def __init__(self, library_backend):
        super().__init__()
        self.backend = library_backend


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
