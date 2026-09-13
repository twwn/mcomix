import contextlib
import unittest
from unittest import mock
import tempfile
import shutil
import os

from . import get_testfile_path

from mcomix import constants
from mcomix.library import backend
from mcomix.library import backend_types


class CollectionTest(unittest.TestCase):

    def setUp(self):
        # Database file
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)

        # Initialize library (path must be patched for testing)
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()

        # Initialize database
        self.library.add_collection("Test")
        self.library.add_collection("Subtest")
        test_col = self.library.get_collection_by_name("Test")
        sub_col = self.library.get_collection_by_name("Subtest")
        test_col.add_collection(sub_col)
        # There is also a collection Recent that is added by default!

        # Add first two archives to no collection, remaining two
        # to subcollections.
        directory = get_testfile_path('archives')
        zip_archive = str(os.path.join(directory, '01-ZIP-Normal.zip'))
        tar_archive = str(os.path.join(directory, '02-TAR-Normal.tar'))
        rar_archive = str(os.path.join(directory, '03-RAR-Normal.rar'))
        sz_archive = str(os.path.join(directory, '04-7Z-Normal.7z'))

        self.library.add_book(zip_archive, None)
        self.library.add_book(tar_archive, None)
        self.library.add_book(rar_archive, test_col.id)
        self.library.add_book(sz_archive, sub_col.id)

    def tearDown(self):
        self.library.close()
        # Remove singleton instance
        backend._backend = None
        os.unlink(self.db)

    def test_get_books_default(self):
        default_col = backend_types.DefaultCollection

        # All books
        books = default_col.get_books()
        self.assertEqual(len(books), 4)
        # Only RAR
        books = default_col.get_books('rar')
        self.assertEqual(len(books), 1)
        # No matches
        books = default_col.get_books('NOMATCH')
        self.assertEqual(len(books), 0)

    def test_get_books_normal_collection(self):
        test_col = self.library.get_collection_by_name("Test")

        # Two books should be stored (including subcollections)
        self.assertEqual(len(test_col.get_books()), 2)
        # Only RAR
        self.assertEqual(len(test_col.get_books('rar')), 1)
        # ZIP shouldn't be included
        self.assertEqual(len(test_col.get_books('zip')), 0)

    def test_a_book_in_a_collection_and_its_subcollection_is_listed_once(self):
        """The books were collected one collection at a time and the
        lists added together, so a book filed in both a collection and
        one under it came back twice - and the library drew two covers
        for it."""
        test_col = self.library.get_collection_by_name("Test")
        sub_col = self.library.get_collection_by_name("Subtest")
        rar = self.library.get_book_by_path(
            os.path.join(get_testfile_path('archives'), '03-RAR-Normal.rar'))
        self.library.add_book_to_collection(rar.id, sub_col.id)

        books = test_col.get_books()

        self.assertEqual(len(books), 2)
        self.assertEqual(len(set(book.id for book in books)), 2)

    def test_a_filter_still_only_reaches_this_collection(self):
        """The collection used to be named in the join and the filter in
        the WHERE clause; with both in the WHERE clause an unparenthesised
        OR would hand back every book in the library whose path matched."""
        test_col = self.library.get_collection_by_name("Test")
        self.assertEqual([book.name for book in test_col.get_books('rar')],
                         ['03-RAR-Normal.rar'])
        self.assertEqual(test_col.get_books('zip'), [])

    def test_get_book_with_attribs(self):
        books = backend_types.DefaultCollection.get_books('zip')

        self.assertEqual(len(books), 1)

        zipbook = books[0]
        self.assertEqual(zipbook.id, 1)
        self.assertEqual(zipbook.pages, 4)

    def test_add_subcollection_normal_collection(self):
        test_col = self.library.get_collection_by_name("Test")

        self.library.add_collection("New test")
        new_col = self.library.get_collection_by_name("New test")
        test_col.add_collection(new_col)

        self.assertIsNone(test_col.supercollection, None)
        self.assertEqual(new_col.supercollection, test_col.id)

    def test_get_collections_default(self):
        col = backend_types.DefaultCollection
        root_collections = col.get_collections()

        self.assertEqual(len(root_collections), 2)
        self.assertEqual(root_collections[1].name, "Test")

    def test_get_collections_normal_collection(self):
        col = self.library.get_collection_by_name("Test")
        root_collections = col.get_collections()

        self.assertEqual(len(root_collections), 1)
        self.assertEqual(root_collections[0].name, "Subtest")

    def test_equal(self):
        test_col1 = self.library.get_collection_by_name("Test")
        test_col2 = self.library.get_collection_by_name("Test")
        other = 123

        self.assertEqual(test_col1, test_col2)
        self.assertNotEqual(test_col1, other)

    def test_get_all_collections(self):
        all_cols = backend_types.DefaultCollection.get_all_collections()
        self.assertEqual(len(all_cols), 3)

        col = self.library.get_collection_by_name("Test")
        subcol = self.library.get_collection_by_name("Subtest")
        self.library.add_collection("New test")
        new_col = self.library.get_collection_by_name("New test")
        subcol.add_collection(new_col)

        self.assertEqual(len(backend_types.DefaultCollection.get_all_collections()), 4)
        self.assertEqual(len(col.get_all_collections()), 2)

    def test_get_default_collection(self):
        collection = self.library.get_collection_by_id(None)
        self.assertEqual(collection, backend_types.DefaultCollection)


class BackendObjectTest(unittest.TestCase):

    """Which backend a row read out of the library talks through."""

    @staticmethod
    def _book():
        return backend_types._Book(1, 'name', '/path', 3, 0, 0, '')

    def test_a_row_asks_for_the_one_backend_by_default(self):
        given = object()
        with mock.patch.object(backend, 'LibraryBackend', return_value=given):
            self.assertIs(given, self._book().get_backend())

    def test_a_row_that_was_given_a_backend_talks_through_that_one(self):
        """The library's migration hands each book the backend that is
        still opening: it runs from _LibraryBackend.__init__(), so
        asking LibraryBackend() for one would start building a second
        and never stop."""
        book = self._book()
        given = object()
        book.set_backend(given)
        with mock.patch.object(backend, 'LibraryBackend',
                               side_effect=AssertionError(
                                   'LibraryBackend() was asked for one')):
            self.assertIs(given, book.get_backend())

    def test_giving_one_row_a_backend_leaves_the_others_asking(self):
        book = self._book()
        book.set_backend(object())
        other = object()
        with mock.patch.object(backend, 'LibraryBackend', return_value=other):
            self.assertIs(other, self._book().get_backend())


class WatchListEntryTest(unittest.TestCase):

    def test_invalid_dir(self):
        tmpdir = tempfile.mkdtemp(prefix='library_types.')
        entry = backend_types._WatchListEntry(os.path.join(tmpdir, "invalid-directory"), False, None)
        self.assertFalse(entry.is_valid())
        self.assertIsInstance(entry.get_new_files([]), list)
        self.assertEqual(len(entry.get_new_files([])), 0)
        shutil.rmtree(tmpdir)

    def test_valid_dir(self):
        tmpdir = os.path.abspath(tempfile.mkdtemp(prefix='library_types.'))
        directory = get_testfile_path('archives')
        available = ['01-ZIP-Normal.zip', '02-TAR-Normal.tar']
        others = ['03-RAR-Normal.rar', '04-7Z-Normal.7z']
        for entry_list in (available, others):
            for n, entry in enumerate(entry_list):
                src = os.path.join(directory, entry)
                dst = os.path.join(tmpdir, entry)
                shutil.copy(src, dst)
                entry_list[n] = dst

        entry = backend_types._WatchListEntry(tmpdir, True, None)
        new_files = entry.get_new_files(available)
        new_files.sort()

        self.assertIsInstance(new_files, list)
        self.assertEqual(new_files, others)

        shutil.rmtree(tmpdir)


class WatchListTest(unittest.TestCase):

    """Looking a watched directory up by the path the caller happens to
    have.

    add_directory() stores normpath(abspath(path)), so a lookup that
    only normalises matches nothing for a path that is relative - the
    watch list dialog's own entries are absolute, but nothing in the
    signature says a caller's has to be.
    """

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        # realpath so that chdir() below lands on the name that was
        # stored: getcwd() reports a directory with its symlinks
        # resolved, and abspath() does not resolve any.
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix='library_types.'))
        self.watched = os.path.join(self.tmpdir, 'comics')
        os.makedirs(self.watched)
        self.library.watchlist.add_directory(self.watched)

    def tearDown(self):
        self.library.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)
        shutil.rmtree(self.tmpdir)

    def test_an_absolute_path_finds_the_entry(self):
        entry = self.library.watchlist.get_watchlist_entry(self.watched)
        self.assertEqual(self.watched, entry.directory)

    def test_a_relative_path_finds_the_entry(self):
        with contextlib.chdir(self.tmpdir):
            entry = self.library.watchlist.get_watchlist_entry('comics')
        self.assertEqual(self.watched, entry.directory)

    def test_a_directory_that_is_not_watched_is_an_error(self):
        with self.assertRaises(ValueError):
            self.library.watchlist.get_watchlist_entry(self.tmpdir)


class CollectionBooksPlanTest(unittest.TestCase):

    """The books of a collection are found without sorting them twice.

    Collecting them with a join and a DISTINCT costs a temporary B-tree
    for the DISTINCT and another for the ordering, whatever the size of
    the library; the membership test needs neither.  Asserted as the
    query plan rather than as a duration, which is not reproducible.

    Whether the planner also scans book depends on how many collections
    are named at once and is not reproducible at a size the suite can
    afford: at 40,000 books across six collections the join scans it and
    the subquery does not, and with one collection neither does at any
    size.  The temporary B-trees are the part that holds everywhere.
    """

    #: Enough rows that sqlite's planner has something to choose
    #: between; on a four-row table every plan costs the same.
    BOOKS = 2000

    def setUp(self):
        fp, self.db = tempfile.mkstemp('.db', 'mcomix-test')
        os.close(fp)
        self._saved_path = constants.LIBRARY_DATABASE_PATH
        constants.LIBRARY_DATABASE_PATH = self.db
        self.library = backend.LibraryBackend()
        connection = self.library._con
        connection.execute('begin')
        connection.execute(
            "insert into collection (id, name) values (500, 'Plans')")
        for index in range(1, self.BOOKS + 1):
            connection.execute(
                '''insert into book (id, name, path, pages, format, size)
                values (?, ?, ?, 1, 1, 1)''',
                (index, 'b%d.cbz' % index, '/does/not/exist/%d.cbz' % index))
        for index in range(1, 6):
            connection.execute(
                'insert into contain (collection, book) values (500, ?)',
                (index,))
        connection.execute('commit')
        connection.execute('analyze')

    def tearDown(self):
        self.library.close()
        constants.LIBRARY_DATABASE_PATH = self._saved_path
        os.unlink(self.db)

    def _plan_of_get_books(self, filter_string=None):
        """The plan of the statement get_books() actually runs."""
        collection = self.library.get_collection_by_id(500)
        statements = []
        original = self.library.fetchall

        def watched(sql, *args):
            statements.append((sql, args[0] if args else ()))
            return original(sql, *args)

        self.library.fetchall = watched
        try:
            collection.get_books(filter_string)
        finally:
            self.library.fetchall = original
        sql, parameters = statements[-1]
        return ' '.join(str(row) for row in self.library._con.execute(
            'explain query plan ' + sql, parameters).fetchall())

    def test_a_collection_is_read_without_a_temporary_b_tree(self):
        plan = self._plan_of_get_books()
        self.assertNotIn('TEMP B-TREE', plan,
                         'get_books() sorts the books itself: %s' % plan)
        self.assertIn('SEARCH book', plan,
                      'get_books() no longer searches by id: %s' % plan)

    def test_a_filtered_collection_is_read_the_same_way(self):
        # The filter is a LIKE with a leading wildcard, which no index
        # serves - but it applies to the books the collection holds,
        # not to the library.
        plan = self._plan_of_get_books('999')
        self.assertNotIn('TEMP B-TREE', plan,
                         'a filtered get_books() sorts them itself: %s' % plan)

# vim: expandtab:sw=4:ts=4


class CollectionHashTest(unittest.TestCase):

    """A collection is hashable, and hashes as the id it equals.

    _Collection defines __eq__, which removes the inherited __hash__
    unless the class puts one back.
    """

    def test_a_collection_can_go_in_a_set(self):
        collection = backend_types._Collection(3, 'Shelf')
        self.assertIn(collection, {collection})

    def test_two_collections_with_one_id_are_one_key(self):
        self.assertEqual(1, len({backend_types._Collection(3, 'Shelf'),
                                 backend_types._Collection(3, 'Shelf')}))

    def test_a_collection_hashes_as_its_id(self):
        # __eq__ answers True for the bare id as well, so a dictionary
        # keyed by either finds the other.
        collection = backend_types._Collection(3, 'Shelf')
        self.assertEqual({collection: 'x'}[3], 'x')

    def test_the_default_collection_is_hashable(self):
        self.assertEqual(hash(None),
                         hash(backend_types.DefaultCollection))
