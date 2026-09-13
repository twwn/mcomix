# -*- coding: utf-8 -*-

"""Tests for the library database schema itself."""

import os
import tempfile
import unittest

from . import get_testfile_path

from mcomix import constants
from mcomix import last_read_page
from mcomix.library import backend


class ContainIndexTest(unittest.TestCase):

    """remove_book() deletes from contain by book alone.

    contain's primary key is (collection, book), which such a lookup
    cannot use, so without an index of its own every removal scanned the
    whole table and removing books in bulk was quadratic in the size of
    the library.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db

    def tearDown(self):
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    @staticmethod
    def _plan(connection, statement, parameters):
        return ' '.join(str(row) for row in connection.execute(
            'explain query plan ' + statement, parameters).fetchall())

    def test_removal_by_book_does_not_scan(self):
        library = backend.LibraryBackend()
        try:
            plan = self._plan(library._con,
                              'delete from Contain where book = ?', (1,))
        finally:
            library.close()
        self.assertNotIn('SCAN', plan,
                         msg='remove_book() scans contain: %s' % plan)

    def test_index_survives_upgrade_from_version_7(self):
        # A database written by an older MComix has the table but not the
        # index, and only the version upgrade can add it.
        library = backend.LibraryBackend()
        library._con.execute('drop index if exists contain_book')
        library._con.execute("update info set value = '7' where key = 'version'")
        library.close()

        library = backend.LibraryBackend()
        try:
            plan = self._plan(library._con,
                              'delete from Contain where book = ?', (1,))
            version = library._con.execute(
                "select value from info where key = 'version'").fetchone()
        finally:
            library.close()
        self.assertNotIn('SCAN', plan,
                         msg='upgrade left contain unindexed: %s' % plan)
        self.assertEqual(int(version), backend._LibraryBackend.DB_VERSION)
# vim: expandtab:sw=4:ts=4

class ClearAllTest(unittest.TestCase):

    """What LastReadPage.clear_all() may and may not remove."""

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.backend = backend.LibraryBackend()
        self.lastread = last_read_page.LastReadPage(self.backend)
        self.lastread.set_enabled(True)

    def tearDown(self):
        self.backend.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    @staticmethod
    def _archive(name):
        return get_testfile_path('archives', name)

    def _in_library(self, path):
        return self.backend.get_book_by_path(path) is not None

    def test_removes_book_whose_recent_entry_was_already_cleared(self):
        # Closing an archive on page 1 clears its "recent" entry but
        # leaves it in the Recent collection.  Such a book used to be
        # skipped here while losing its collection anyway, so it stayed
        # in the library forever, belonging to nothing.
        path = self._archive('01-ZIP-Normal.zip')
        self.lastread.set_page(path, 5)
        self.lastread.clear_page(path)

        self.lastread.clear_all()

        self.assertFalse(self._in_library(path),
                         msg='a book read and then closed on page 1 '
                             'survived clearing the recent list')

    def test_keeps_book_that_is_in_another_collection(self):
        path = self._archive('02-TAR-Normal.tar')
        self.lastread.set_page(path, 5)
        self.backend.add_collection('Favourites')
        self.backend.add_book_to_collection(
            self.backend.get_book_by_path(path).id,
            self.backend.get_collection_by_name('Favourites').id)

        self.lastread.clear_all()

        self.assertTrue(self._in_library(path),
                        msg='clearing the recent list removed a book '
                            'that is filed in a collection')

    def test_keeps_book_that_is_in_no_collection(self):
        # add_book(path, None) is how the library takes a book without
        # filing it, so "in no collection" is a legitimate state and not
        # something to be tidied away.
        path = self._archive('03-RAR-Normal.rar')
        self.backend.add_book(path, None)

        self.lastread.clear_all()

        self.assertTrue(self._in_library(path),
                        msg='clearing the recent list removed a book that '
                            'was added to the library without a collection')


