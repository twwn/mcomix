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


class CleanCollectionTransactionTest(unittest.TestCase):

    """clean_collection() sweeps in one transaction, not thousands.

    The connection is opened in auto-commit mode, so without one each of
    the two deletes remove_book() runs commits by itself. Asserted as the
    transaction the removals happen inside rather than as a duration,
    which is not reproducible.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        self.library.begin_transaction()
        for index in range(8):
            cursor = self.library._con.execute(
                '''insert into book (name, path, pages, format, size)
                values (?, ?, ?, ?, ?)''',
                ('b%d' % index, '/does/not/exist/%d.cbz' % index, 1, 1, 1))
            self.library._con.execute(
                'insert or ignore into contain (collection, book) values (?, ?)',
                (1, cursor.lastrowid))
        self.library.end_transaction()

    def tearDown(self):
        self.library.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def test_a_book_in_a_collection_and_one_under_it_is_named_once(self):
        """The books were collected one collection at a time and the
        lists added together, so a book filed in both came back twice.
        The sweep survives that - the second removal finds no path and
        does nothing - but it looks the book up all over again, and any
        other caller would act on it twice."""
        connection = self.library._con
        connection.execute(
            "insert into collection (id, name) values (2, 'Under')")
        connection.execute(
            'update collection set supercollection = 1 where id = 2')
        # Every book is in collection 1 already; put the first in the
        # one under it as well.
        first = connection.execute(
            'select min(book) from contain where collection = 1').fetchone()
        connection.execute(
            'insert into contain (collection, book) values (2, ?)', (first,))

        books = self.library.get_books_in_collection(1)

        self.assertEqual(8, len(books))
        self.assertEqual(8, len(set(books)))

    def test_the_whole_sweep_is_one_transaction(self):
        inside = []
        original = self.library.remove_book

        def watched(book):
            # After the deletes, not before: sqlite3 holds the BEGIN back
            # until a statement actually needs it, so the first removal
            # has not opened one yet when it is entered.
            original(book)
            inside.append(self.library._con.in_transaction)

        self.library.remove_book = watched
        removed = self.library.clean_collection(1)
        self.assertEqual(8, removed, 'the sweep removed the wrong books')
        self.assertTrue(inside, 'nothing was removed, so nothing was measured')
        self.assertTrue(all(inside),
                        'removals committed one at a time: %r' % inside)
        self.assertFalse(self.library._con.in_transaction,
                         'the sweep left a transaction open')

    def test_a_caller_may_hold_the_transaction_itself(self):
        # collection_area does not, but the helpers do not nest, so the
        # sweep has to leave an outer one alone rather than commit it.
        self.library.begin_transaction()
        self.library.clean_collection(1)
        self.assertTrue(self.library._con.in_transaction,
                        'the sweep committed a transaction it did not open')
        self.library.end_transaction()


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




class AddBookToCollectionTest(unittest.TestCase):

    """What the listeners are told when a book is filed."""

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.backend = backend.LibraryBackend()
        self.seen = []
        self.backend.book_added_to_collection += self._book_filed

    def tearDown(self):
        self.backend.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def _book_filed(self, book, collection):
        # Record the book itself rather than reading it: a listener that
        # touches a None book raises, and the callback machinery logs
        # that failure rather than letting it out.
        self.seen.append((book, collection))

    def test_a_book_that_exists_is_reported(self):
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        collection = self.backend.add_collection('files')
        self.assertTrue(self.backend.add_book(path))
        book = self.backend.get_book_by_path(path)
        self.seen.clear()

        self.backend.add_book_to_collection(book.id, collection)

        self.assertEqual([(book.id, collection)],
                         [(seen.id, where) for seen, where in self.seen])

    def test_a_book_id_naming_no_row_is_not_reported(self):
        # Contain carries no foreign key on book, so an id that names no
        # row is inserted happily and the lookup that follows finds
        # nothing.  The listeners used to be handed that nothing.
        collection = self.backend.add_collection('files')

        self.backend.add_book_to_collection(4711, collection)

        self.assertEqual([], self.seen)


class RemovedBookTest(unittest.TestCase):

    """remove_book() left the page the book was read to behind.

    The recent table is keyed by book id, and a book's id is its sqlite
    rowid, which is handed out again once the highest row is deleted.  A
    row left over from a removed book therefore belonged to whichever
    book was added next.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()

    def tearDown(self):
        self.library.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def _add_book(self, name):
        """A row in book, without an archive to read it out of."""
        cursor = self.library._con.execute(
            '''insert into book (name, path, pages, format, size)
            values (?, ?, ?, ?, ?)''',
            (name, '/does/not/exist/%s.cbz' % name, 20, 1, 1))
        return cursor.lastrowid

    def _recent_rows(self):
        return self.library._con.execute(
            'select book, page from recent order by book').fetchall()

    def test_removing_a_book_forgets_the_page_it_was_read_to(self):
        book = self._add_book('read')
        self.library.get_book_by_id(book).set_last_read_page(7)
        self.assertEqual([(book, 7)], self._recent_rows())

        self.library.remove_book(book)

        self.assertEqual([], self._recent_rows(),
                         'the removed book kept its page')

    def test_the_next_book_added_does_not_inherit_that_page(self):
        removed = self._add_book('read')
        self.library.get_book_by_id(removed).set_last_read_page(7)
        self.library.remove_book(removed)

        # sqlite hands out the highest rowid again once it is free, so
        # the next book is the removed one's id all over again.
        added = self._add_book('fresh')
        self.assertEqual(removed, added,
                         'sqlite did not reuse the id, so nothing is proved')
        self.assertIsNone(
            self.library.get_book_by_id(added).get_last_read_page(),
            'a newly added book opened where another one was left off')

    def test_a_database_written_before_the_fix_is_swept_on_open(self):
        """Rows an older MComix left behind still name the next book
        added, so the version upgrade clears them out."""
        book = self._add_book('read')
        self.library.get_book_by_id(book).set_last_read_page(7)
        # A second book first, so that it keeps an id of its own: the
        # removed book's id is free, and set_last_read_page() would
        # otherwise write over the very row under test.
        kept = self._add_book('kept')
        self.library.get_book_by_id(kept).set_last_read_page(3)
        self.assertNotEqual(book, kept)
        # What remove_book() used to leave: the book gone, its page not.
        self.library._con.execute('delete from book where id = ?', (book,))
        self.library._con.execute(
            "update info set value = '8' where key = 'version'")
        self.library.close()

        self.library = backend.LibraryBackend()

        self.assertEqual([(kept, 3)], self._recent_rows(),
                         'the sweep took the wrong rows, or none')
        version = self.library._con.execute(
            "select value from info where key = 'version'").fetchone()
        self.assertEqual(int(version), backend._LibraryBackend.DB_VERSION)
