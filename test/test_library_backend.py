"""Tests for the library database schema itself."""

import os
import tempfile
import unittest

from . import get_testfile_path

from mcomix import constants
from mcomix.i18n import _
from mcomix import last_read_page
from mcomix.library import backend
from mcomix.library import backend_types


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


class BooksOutsideRecentTest(unittest.TestCase):

    """Which books the watch list scan counts as already in the library.

    A book filed nowhere but in "Recent" is there because it was opened
    once, not because it was collected, so a scan still treats it as new
    and files it under the collection the directory is watched for. The
    scan used to work this out by asking every book which collections it
    was in, which is a query per book.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        self.shelf = self.library.add_collection('Shelf')

    def tearDown(self):
        self.library.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def _add_book(self, name, collections):
        cursor = self.library._con.execute(
            '''insert into book (name, path, pages, format, size)
               values (?, ?, ?, ?, ?)''',
            (name, '/books/%s' % name, 20, 1, 1))
        book = cursor.lastrowid
        cursor.close()
        for collection in collections:
            self.library._con.execute(
                'insert into contain (collection, book) values (?, ?)',
                (collection, book))
        return '/books/%s' % name

    def test_the_four_ways_a_book_can_be_filed(self):
        collected = self._add_book('collected.cbz', [self.shelf])
        both = self._add_book(
            'both.cbz', [self.shelf, constants.COLLECTION_RECENT])
        self._add_book('read.cbz', [constants.COLLECTION_RECENT])
        loose = self._add_book('loose.cbz', [])

        self.assertEqual(
            sorted([collected, both, loose]),
            sorted(self.library.get_paths_of_books_outside_recent()),
            'a book that is only in Recent counts as already held, or a '
            'book that is filed somewhere else does not')


class BookPathsInCollectionTest(unittest.TestCase):

    """The ids and paths of a collection's books in one statement."""

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        self.shelf = self.library.add_collection('Shelf')
        self.other = self.library.add_collection('Other')
        for name, collection in (('one.cbz', self.shelf),
                                 ('two.cbz', self.shelf),
                                 ('three.cbz', self.other)):
            cursor = self.library._con.execute(
                '''insert into book (name, path, pages, format, size)
                   values (?, ?, ?, ?, ?)''',
                (name, '/books/%s' % name, 20, 1, 1))
            self.library._con.execute(
                'insert into contain (collection, book) values (?, ?)',
                (collection, cursor.lastrowid))
            cursor.close()

    def tearDown(self):
        self.library.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def test_it_names_the_same_books_as_the_id_query(self):
        for collection in (None, self.shelf, self.other):
            self.assertEqual(
                self.library.get_books_in_collection(collection),
                [id for id, path in
                 self.library.get_book_paths_in_collection(collection)],
                msg='collection %r' % (collection,))

    def test_it_carries_the_paths(self):
        self.assertEqual(
            ['/books/one.cbz', '/books/two.cbz'],
            [path for id, path in
             self.library.get_book_paths_in_collection(self.shelf)])


class TransactionTest(unittest.TestCase):

    """The context manager that makes a loop of writes one transaction."""

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

    def test_the_block_runs_in_a_transaction(self):
        self.assertIsNone(self.library._con.isolation_level)
        with self.library.transaction():
            self.assertEqual('IMMEDIATE', self.library._con.isolation_level)
        self.assertIsNone(self.library._con.isolation_level)

    def test_nesting_leaves_the_outer_transaction_in_charge(self):
        with self.library.transaction():
            with self.library.transaction():
                self.assertEqual('IMMEDIATE',
                                 self.library._con.isolation_level)
            self.assertEqual('IMMEDIATE', self.library._con.isolation_level,
                             'the inner block committed the outer one')
        self.assertIsNone(self.library._con.isolation_level)

    def test_an_error_still_commits_what_was_written(self):
        # Auto-commit kept everything written before the error, and
        # taking the whole loop as one transaction must not change that.
        with self.assertRaises(ZeroDivisionError):
            with self.library.transaction():
                self.library.add_collection('Shelf')
                1 / 0

        self.assertIsNone(self.library._con.isolation_level)
        self.assertIsNotNone(self.library.get_collection_by_name('Shelf'))


class TableExistsTest(unittest.TestCase):

    """_table_exists() decides whether the file has a schema at all.

    It used to paste the name into "pragma table_info(%s)", where the
    argument is part of the statement, so a name that is not a bare
    identifier was a syntax error out of a question that has a "no".
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

    def test_a_table_that_is_there(self):
        for table in ('book', 'collection', 'contain', 'info',
                      'watchlist', 'recent'):
            self.assertTrue(self.library._table_exists(table), msg=table)

    def test_a_table_that_is_not(self):
        self.assertFalse(self.library._table_exists('shelf'))

    def test_a_name_that_is_not_an_identifier(self):
        self.assertFalse(self.library._table_exists("x'); drop table book; --"))
        self.assertTrue(self.library._table_exists('book'),
                        'the book table did not survive the question')


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


class MovedBookTest(unittest.TestCase):

    """A book that MComix has moved keeps its row, and its row keeps up.

    The library stores a book by its path, so a move that left the row
    alone would point it at a file that is not there any more - and
    everything that hangs off the row's id, the thumbnail, the
    collections it is in and the page it was read to, would be lost with
    it.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.backend = backend.LibraryBackend()
        self.path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.assertTrue(self.backend.add_book(self.path))
        self.book = self.backend.get_book_by_path(self.path)

    def tearDown(self):
        self.backend.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def test_the_row_follows_the_file(self):
        moved = os.path.join(os.path.dirname(self.path), 'elsewhere.zip')

        self.assertTrue(self.backend.update_book_path(self.path, moved))

        self.assertIsNone(self.backend.get_book_by_path(self.path))
        self.assertEqual(self.backend.get_book_by_path(moved).id,
                         self.book.id)

    def test_the_book_is_renamed_with_its_file(self):
        moved = os.path.join(os.path.dirname(self.path), 'elsewhere.zip')

        self.backend.update_book_path(self.path, moved)

        self.assertEqual(self.backend.get_book_by_path(moved).name,
                         'elsewhere.zip')

    def test_a_book_that_is_not_in_the_library_moves_nothing(self):
        self.assertFalse(self.backend.update_book_path('/nowhere/book.zip',
                                                       '/elsewhere/book.zip'))
        self.assertIsNotNone(self.backend.get_book_by_path(self.path))

    def test_a_path_another_row_holds_is_not_taken_from_it(self):
        """The path column is unique.

        A row already standing where the file has landed is stale - no
        file was there, or the move would have been refused - but it is
        not this book's to throw away, so the update is refused instead.
        """
        other = get_testfile_path('archives', '02-TAR-Normal.tar')
        self.assertTrue(self.backend.add_book(other))

        self.assertFalse(self.backend.update_book_path(self.path, other))

        self.assertIsNotNone(self.backend.get_book_by_path(self.path))
        self.assertNotEqual(self.backend.get_book_by_path(other).id,
                            self.book.id)


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


class MissingBookTest(unittest.TestCase):

    """What the accessors answer for a book id that names no row.

    sqlite reports a row that is not there by returning None from
    fetchone(), not by raising, so the try/except these two used to
    carry never ran.  get_book_cover() went on to thumbnail the None it
    had been handed, and raised TypeError out of a drag handler that was
    written to expect None.
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

    def test_the_path_of_a_book_that_is_not_there_is_none(self):
        self.assertIsNone(self.library.get_book_path(4711))

    def test_the_cover_of_a_book_that_is_not_there_is_none(self):
        self.assertIsNone(self.library.get_book_cover(4711))

    def test_no_thumbnail_is_attempted_for_a_book_that_is_not_there(self):
        def refuse(path):
            raise AssertionError('thumbnailed a book that is not there: %r'
                                 % (path,))

        self.library.get_book_thumbnail = refuse
        self.assertIsNone(self.library.get_book_cover(4711))


class AddCollectionTest(unittest.TestCase):

    """What add_collection() answers with.

    It used to return True or False, and the first collection in a
    fresh library has id 1, so a caller that passed the answer on as a
    collection id worked by the accident of True == 1.  The library's
    own callers all wanted the id and looked it up again by name
    afterwards.
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

    def test_the_id_of_the_collection_added_is_returned(self):
        collection = self.library.add_collection('Shelf')
        self.assertEqual(self.library.get_collection_by_name('Shelf').id,
                         collection)

    def test_the_first_collection_added_steps_over_recent(self):
        # "Recent" holds id -2, so leaving sqlite to hand out the next
        # rowid would number the first real collection -1.
        self.assertEqual(1, self.library.add_collection('Shelf'))

    def test_later_collections_are_numbered_by_sqlite(self):
        first = self.library.add_collection('Shelf')
        second = self.library.add_collection('Another shelf')
        self.assertEqual(first + 1, second)

    def test_a_name_that_is_taken_is_reported(self):
        # The name column is unique, so the second insert raises and is
        # caught.
        self.library.add_collection('Shelf')
        self.assertIsNone(self.library.add_collection('Shelf'))


class DuplicateCollectionTest(unittest.TestCase):

    """What happens when the copy cannot be created.

    add_collection() reports a failure with None and the new
    collection's id otherwise, and duplication stops at the first.  It
    used to return a bool and be tested against None, which it never
    was: a failed insert carried on to look the copy up by name, find
    nothing, and file the books under that nothing - which the "insert
    or ignore" quietly dropped, since contain's collection column is
    "not null".  The duplication then reported success, and the library
    redisplayed the collections it already had rather than saying it
    could not make the copy.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        self.collection = self.library.add_collection('Shelf')
        self.library._con.execute(
            '''insert into book (name, path, pages, format, size)
               values (?, ?, ?, ?, ?)''',
            ('a', '/does/not/exist/a.cbz', 20, 1, 1))
        self.library.add_book_to_collection(
            self.library.get_book_by_path('/does/not/exist/a.cbz').id,
            self.collection)

    def tearDown(self):
        self.library.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def test_the_copy_holds_the_same_books(self):
        self.assertTrue(self.library.duplicate_collection(self.collection))
        copy = self.library.get_collection_by_name('Shelf (Copy)')
        self.assertIsNotNone(copy)
        self.assertEqual(self.library.get_books_in_collection(self.collection),
                         self.library.get_books_in_collection(copy.id))

    def test_a_collection_that_cannot_be_created_is_reported(self):
        self.library.add_collection = lambda name: None

        self.assertFalse(self.library.duplicate_collection(self.collection),
                         'a duplication that could not add its collection '
                         'reported success')


class CollectionTreeTest(unittest.TestCase):

    """Both walks over the collection tree ask the database once.

    Each of them used to run a query for every node it reached, so the
    number of statements grew with the tree rather than staying at one.
    Asserted as the statement count rather than as a duration, which is
    not reproducible.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        # Three levels branching two, so that a walk of the subtree
        # reaches 14 collections over depths a single query cannot be
        # mistaken for.
        self.root = self.library.add_collection('root')
        self.below = []
        level = [self.root]
        for depth in range(3):
            children = []
            for parent in level:
                for n in range(2):
                    child = self.library.add_collection(
                        'depth %d under %d, %d' % (depth, parent, n))
                    self.library.add_collection_to_collection(child, parent)
                    children.append(child)
            self.below += children
            level = children

    def tearDown(self):
        self.library.close()
        backend._backend = None
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def _counted(self, call):
        """Run <call> and return what it answered with the statements it
        ran to get there."""
        statements = []
        self.library._con.set_trace_callback(statements.append)
        try:
            return call(), statements
        finally:
            self.library._con.set_trace_callback(None)

    def test_the_backend_walks_the_subtree_in_one_statement(self):
        below, statements = self._counted(
            lambda: self.library.get_all_collections_in_collection(self.root))

        self.assertEqual(sorted(self.below), sorted(below))
        self.assertEqual(1, len(statements), statements)

    def test_a_collection_walks_its_subtree_in_one_statement(self):
        collection = self.library.get_collection_by_id(self.root)
        below, statements = self._counted(collection.get_all_collections)

        self.assertEqual(sorted(self.below),
                         sorted(found.id for found in below))
        self.assertEqual(1, len(statements), statements)

    def test_the_default_collection_walks_the_whole_library(self):
        below, statements = self._counted(
            backend_types.DefaultCollection.get_all_collections)

        # It stands for the library as a whole, so its subtree is every
        # collection there is: the root, everything under it, and the
        # Recent collection a fresh library is created with.
        self.assertEqual(sorted(self.below + [self.root,
                                              constants.COLLECTION_RECENT]),
                         sorted(found.id for found in below))
        self.assertEqual(1, len(statements), statements)


class AddBookStatementTest(unittest.TestCase):

    """add_book() describes to the listeners the book it just built.

    Filing it in a collection used to be given nothing but the id, so
    the row was read back to find out what it said: a fourth statement
    for every book of a batch, over a book the caller was holding.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.backend = backend.LibraryBackend()
        self.collection = self.backend.add_collection('files')
        self.path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.seen = []
        self.reported = []
        self.backend.book_added_to_collection += self._book_filed

    def tearDown(self):
        self.backend.close()
        backend._backend = None
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def _book_filed(self, book, collection):
        self.seen.append((book, collection))

    def _book_added(self, book):
        self.reported.append(book)

    def _counted(self, call):
        statements = []
        self.backend._con.set_trace_callback(statements.append)
        try:
            return call(), statements
        finally:
            self.backend._con.set_trace_callback(None)

    def test_a_new_book_is_filed_in_three_statements(self):
        # The lookup by path, the insert into Book, and the insert into
        # Contain.  Reading the book back was a fourth.
        added, statements = self._counted(
            lambda: self.backend.add_book(self.path, self.collection))

        self.assertTrue(added)
        self.assertEqual(3, len(statements), statements)

    def test_the_listeners_are_told_what_the_row_says(self):
        self.backend.add_book(self.path, self.collection)

        book = self.backend.get_book_by_path(self.path)
        self.assertEqual(
            [(book.id, book.name, book.path, book.pages, book.format,
              book.size, book.added, self.collection)],
            [(seen.id, seen.name, seen.path, seen.pages, seen.format,
              seen.size, seen.added, where) for seen, where in self.seen])

    def test_a_book_added_again_keeps_the_date_it_first_arrived(self):
        # The update branch has no date of its own to report: the row
        # holds the one the book arrived with, and only the lookup by
        # path can say what it is.
        self.backend.add_book(self.path, self.collection)
        first = self.backend.get_book_by_path(self.path)
        elsewhere = self.backend.add_collection('elsewhere')
        self.seen.clear()

        self.backend.add_book(self.path, elsewhere)

        self.assertEqual([(first.id, first.added, elsewhere)],
                         [(seen.id, seen.added, where)
                          for seen, where in self.seen])

    def test_the_date_reported_is_the_date_the_row_holds(self):
        # The column defaults to sqlite's current_timestamp, which is
        # UTC to the second; datetime.now().isoformat(), which this used
        # to report, is local time to the microsecond.
        self.backend.book_added += self._book_added

        self.backend.add_book(self.path, self.collection)

        book = self.backend.get_book_by_path(self.path)
        self.assertEqual([book.added],
                         [added.added for added in self.reported])


class CollectionTreeQueryTest(unittest.TestCase):

    """get_collection_tree() answers with the whole hierarchy at once."""

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        self.comics = self.library.add_collection('Comics')
        self.manga = self.library.add_collection('Manga')
        self.inner = self.library.add_collection('Inner')
        self.library.add_collection_to_collection(self.inner, self.comics)

    def tearDown(self):
        self.library.close()
        backend._backend = None
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def test_the_collections_are_grouped_by_the_one_above_them(self):
        self.assertEqual(
            {None: [(self.comics, 'Comics'), (self.manga, 'Manga'),
                    (constants.COLLECTION_RECENT, 'Recent')],
             self.comics: [(self.inner, 'Inner')]},
            self.library.get_collection_tree())

    def test_recent_is_named_by_its_translation(self):
        # The row holds RECENT, so that a library carried from one
        # language to another still finds the collection.
        root = self.library.get_collection_tree()[None]
        self.assertEqual(
            [_('Recent')],
            [name for id, name in root
             if id == constants.COLLECTION_RECENT])
