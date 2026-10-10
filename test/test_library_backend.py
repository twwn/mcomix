"""Tests for the library database schema itself."""

import datetime
import inspect
import os
import re
import shutil
import tempfile
import threading
import unittest
import unittest.mock

from sqlite3 import dbapi2

from . import get_testfile_path, posix_byte_names

from mcomix import constants
from mcomix import thumbnail_tools
from mcomix import tools
from mcomix.i18n import _
from mcomix import last_read_page
from mcomix.library import backend
from mcomix.library import backend_types
from mcomix.archive import password as archive_password


#: The one book of the libraries the upgrade tests write, as add_book()
#: stores a path: absolute, which on Windows begins with a drive.
_A_BOOK = os.path.abspath('/books/a.cbz')


class LibraryDatabaseTest(unittest.TestCase):

    """A LibraryBackend over a library of its own.

    Every path the backend can reach is repointed, not only the
    database: remove_book() deletes the book's cover out of
    LIBRARY_COVERS_PATH, and the upgrade to version 4 reads
    LASTPAGE_DATABASE_PATH and then unlinks it, so a test left on the
    real constants would take files out of the reader's own library.
    constants resolves all of them at import time, which is why setting
    the environment is not enough - see MComixTest in test/__init__.py,
    which does the same for the tests that need a window as well.
    """

    #: The constants pointed into the temporary library, and what each
    #: is called inside it.  DATA_DIR is the directory itself.
    REDIRECTED_PATHS = {
        'DATA_DIR': None,
        'LIBRARY_DATABASE_PATH': 'library.db',
        'LASTPAGE_DATABASE_PATH': 'lastreadpage.db',
        'LIBRARY_COVERS_PATH': 'library_covers',
        'THUMBNAIL_PATH': 'thumbnails',
    }

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix='mcomix-test-library.')
        self._saved_paths = {name: getattr(constants, name)
                             for name in self.REDIRECTED_PATHS}
        for name, leaf in self.REDIRECTED_PATHS.items():
            setattr(constants, name, self.tmp_dir if leaf is None
                    else os.path.join(self.tmp_dir, leaf))
        #: The database the backend under test will open.
        self.db = constants.LIBRARY_DATABASE_PATH

    def _archive(self):
        """A path that is really there, which the version 4 step
        requires of a book it is asked to carry over from the legacy
        database."""
        return get_testfile_path('archives', '01-ZIP-Normal.zip')

    def _write_database(self, version):
        """Write a library as the MComix that used <version> wrote it.

        Over an empty directory: every test here walks every version,
        one subtest each, and a subtest that fails still leaves its
        files behind.
        """
        for path in (self.db, constants.LASTPAGE_DATABASE_PATH):
            if os.path.exists(path):
                os.unlink(path)
        # Version 6 turned every "string" column into a "text" one, and
        # version 3 turned book.added from a date into a datetime.
        column = 'text' if version >= 6 else 'string'
        added = 'datetime default current_timestamp' if version >= 3 \
            else 'date default current_date'
        connection = dbapi2.connect(self.db, isolation_level=None)
        connection.execute(
            'create table book ('
            ' id integer primary key,'
            ' name {column},'
            ' path {column} unique,'
            ' pages integer,'
            ' format integer,'
            ' size integer,'
            ' added {added})'.format(column=column, added=added))
        connection.execute(
            'create table collection ('
            ' id integer primary key,'
            ' name {column} unique,'
            ' supercollection integer)'.format(column=column))
        connection.execute(
            'create table contain ('
            ' collection integer not null,'
            ' book integer not null,'
            ' primary key (collection, book))')
        # Version 8 added the index on contain (book).
        if version >= 8:
            connection.execute('create index contain_book on contain (book)')
        # Version 1 added the info table the version itself lives in;
        # before that there was nothing to read a version from.
        if version >= 1:
            connection.execute(
                'create table info ('
                ' key {column} primary key,'
                ' value {column})'.format(column=column))
            connection.execute(
                "insert into info (key, value) values ('version', ?)",
                (str(version),))
        # Version 2 added the watch list, version 4 its recursive flag.
        if version >= 2:
            recursive = ', recursive boolean not null' if version >= 4 else ''
            connection.execute(
                'create table watchlist ('
                ' path {column} primary key,'
                ' collection integer references collection (id)'
                ' on delete set null{recursive})'.format(
                    column=column, recursive=recursive))
        # Version 5 added the recent table and the collection that goes
        # with it; version 7 stopped translating that collection's name.
        if version >= 5:
            connection.execute(
                'create table recent ('
                ' book integer primary key,'
                ' page integer,'
                ' time_set datetime)')
            connection.execute(
                'insert into collection (id, name) values (?, ?)',
                (constants.COLLECTION_RECENT,
                 'RECENT' if version >= 7 else 'Recent'))
        # One book on one shelf, and one watched directory, so that the
        # steps which rebuild a table have rows to carry across.
        connection.execute(
            "insert into collection (id, name) values (1, 'Shelf')")
        connection.execute(
            'insert into book (id, name, path, pages, format, size)'
            " values (1, 'a.cbz', ?, 20, 1, 1)", (_A_BOOK,))
        connection.execute(
            'insert into contain (collection, book) values (1, 1)')
        if version >= 4:
            connection.execute(
                'insert into watchlist (path, collection, recursive)'
                " values ('/watched', 1, 1)")
        elif version >= 2:
            connection.execute(
                'insert into watchlist (path, collection)'
                " values ('/watched', 1)")
        connection.close()
        # What version 5 moved into the library: a page read, held in a
        # database of its own beside it.  Its path has to name a file
        # that is there, or the step drops the row as gone away.
        if version < 5:
            legacy = dbapi2.connect(constants.LASTPAGE_DATABASE_PATH,
                                    isolation_level=None)
            legacy.execute(
                'create table lastread ('
                ' path text primary key, page integer, time_set datetime)')
            legacy.execute(
                'insert into lastread (path, page, time_set)'
                " values (?, 7, '2020-01-01 00:00:00')", (self._archive(),))
            legacy.close()

    @staticmethod
    def _plan(connection, statement, parameters):
        return ' '.join(str(row) for row in connection.execute(
            'explain query plan ' + statement, parameters).fetchall())

    def tearDown(self):
        for name, path in self._saved_paths.items():
            setattr(constants, name, path)
        # The backend is a singleton, and a test that left one open
        # would hand it to the next one - pointed at a database that is
        # about to be removed.
        backend._backend = None
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


class RedirectedPathsTest(LibraryDatabaseTest):

    """What keeps the tests in this file off the reader's own library."""

    def test_every_path_is_inside_the_temporary_library(self):
        for name in self.REDIRECTED_PATHS:
            path = getattr(constants, name)
            self.assertTrue(path.startswith(self.tmp_dir),
                            '%s points at %s' % (name, path))

    def test_every_path_the_library_reads_is_one_of_them(self):
        """A path constant the backend reaches that the base class does
        not repoint would be resolved against the reader's own home."""
        reached = set()
        for module in (backend, last_read_page):
            reached.update(re.findall(r'constants\.([A-Z_]+(?:PATH|DIR))',
                                      inspect.getsource(module)))
        self.assertTrue(reached, 'the source was not searched')
        self.assertEqual(reached - set(self.REDIRECTED_PATHS), set())


@posix_byte_names
class PathNotUtf8Test(LibraryDatabaseTest):

    """A book whose path on disk is not UTF-8.

    The library stores paths as SQLite text, which is UTF-8, and Python
    hands such a path over with lone surrogates, which SQLite's binding
    refuses with UnicodeEncodeError.  Opening such a book asks for its
    last read page, and the error came out of that half way through
    opening it, which then never finished.
    """

    def setUp(self):
        super().setUp()
        self.path = os.fsdecode(os.path.join(
            os.fsencode(self.tmp_dir), 'B\xfccher.cbz'.encode('latin-1')))
        shutil.copy(self._archive(), self.path)
        self.library = backend.LibraryBackend()
        self.addCleanup(self.library.close)

    def test_it_is_not_in_the_library(self):
        self.assertIsNone(self.library.get_book_by_path(self.path))

    def test_it_is_not_added_to_it(self):
        self.assertFalse(self.library.add_book(self.path))
        self.assertIsNone(self.library.get_book_by_path(self.path))

    def test_its_last_page_is_neither_read_nor_kept(self):
        pages = last_read_page.LastReadPage(self.library)
        pages.set_enabled(True)
        self.assertIsNone(pages.get_page(self.path))
        with self.assertRaises(ValueError):
            pages.set_page(self.path, 2)


class RarSetTest(LibraryDatabaseTest):

    """A RAR book packed in volumes is one book, read from its first
    volume; the others list the rest of the set from the middle of a
    page on."""

    def setUp(self):
        super().setUp()
        self.volumes = []
        for part in (1, 2, 3):
            name = 'Multivolume.part%d.rar' % part
            path = os.path.join(self.tmp_dir, name)
            shutil.copy(get_testfile_path('archives', name), path)
            self.volumes.append(path)
        self.library = backend.LibraryBackend()
        self.addCleanup(self.library.close)

    def test_a_later_volume_is_not_added(self):
        for path in self.volumes[1:]:
            with self.subTest(path=os.path.basename(path)):
                self.assertFalse(self.library.add_book(path))
                self.assertIsNone(self.library.get_book_by_path(path))

    def test_the_first_volume_is_added_as_the_book(self):
        from mcomix.archive import rar, rar_external
        if not (rar.RarArchive.is_available()
                or rar_external.RarArchive.is_available()):
            self.skipTest('nothing here reads RAR')
        self.assertTrue(self.library.add_book(self.volumes[0]))
        self.assertEqual(4, self.library.get_book_by_path(
            self.volumes[0]).pages)


class NothingThereTest(LibraryDatabaseTest):

    """What the library answers about books and collections it does not
    hold, which is None or False rather than an error."""

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()
        self.addCleanup(self.library.close)

    def test_a_book_it_does_not_hold_has_no_cover(self):
        self.assertIsNone(self.library.get_book_cover(9999))

    def test_a_collection_it_does_not_hold_is_none(self):
        self.assertIsNone(self.library.get_collection_by_id(9999))

    def test_a_collection_it_does_not_hold_is_not_duplicated(self):
        before = self.library.get_all_collections()
        self.assertFalse(self.library.duplicate_collection(9999))
        self.assertEqual(before, self.library.get_all_collections())

    def test_no_collection_has_no_collections_under_it(self):
        """None stands for the whole library elsewhere in the backend,
        and is refused here rather than read as a collection."""
        with self.assertRaises(ValueError):
            self.library.get_all_collections_in_collection(None)

    @posix_byte_names
    def test_a_book_moved_to_a_name_it_cannot_hold_stays_where_it_was(self):
        """The row is left for "Clean up" to find gone, rather than the
        move raising half way through."""
        path = os.path.join(self.tmp_dir, 'Book.cbz')
        shutil.copy(self._archive(), path)
        self.assertTrue(self.library.add_book(path))
        unstorable = os.fsdecode(os.path.join(
            os.fsencode(self.tmp_dir), 'B\xfccher.cbz'.encode('latin-1')))
        self.assertFalse(self.library.update_book_path(path, unstorable))
        self.assertIsNotNone(self.library.get_book_by_path(path))

    def test_a_library_that_does_not_say_its_version_is_version_minus_one(self):
        self.library._con.execute("delete from info where key = 'version'")
        self.assertEqual(-1, self.library._library_version())


class ContainIndexTest(LibraryDatabaseTest):

    """remove_book() deletes from contain by book alone.

    contain's primary key is (collection, book), which such a lookup
    cannot use, so without an index of its own every removal scanned the
    whole table and removing books in bulk was quadratic in the size of
    the library.
    """

    def setUp(self):
        super().setUp()

    def tearDown(self):
        super().tearDown()

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


class UpgradeFromEveryVersionTest(LibraryDatabaseTest):

    """A library written by any MComix that ever wrote one still opens.

    _upgrade_database() applies one step per version in order, and each
    step is written against the schema the step before it left, so the
    only way to know a step still works is to hand it a database of the
    shape it expects.  The suite reached versions 7 and 8 - the two
    steps that are repairs rather than schema changes - and none of the
    five below them, which are the ones that rebuild tables and copy
    rows across.
    """

    def _upgraded(self, version):
        """Write a library of <version> and open it, which upgrades it."""
        self._write_database(version)
        return backend.LibraryBackend()

    def _done(self, library):
        """Let go of <library>, so that the next subtest opens its own."""
        library.close()

    def _versions(self, lowest=0):
        """Every version an upgrade can start from, lowest first."""
        return range(lowest, backend._LibraryBackend.DB_VERSION)

    def test_every_version_reaches_the_current_one(self):
        for version in self._versions():
            with self.subTest(version=version):
                library = self._upgraded(version)
                held = library._con.execute(
                    "select value from info where key = 'version'").fetchone()
                self.assertEqual(int(held),
                                 backend._LibraryBackend.DB_VERSION)
                self._done(library)

    def test_the_book_and_its_shelf_survive_every_version(self):
        for version in self._versions():
            with self.subTest(version=version):
                library = self._upgraded(version)
                book = library.get_book_by_path(_A_BOOK)
                self.assertIsNotNone(book, 'the book was lost')
                self.assertEqual(book.pages, 20)
                self.assertEqual(library.get_books_in_collection(1),
                                 [book.id])
                self._done(library)

    def test_every_version_ends_with_the_whole_schema(self):
        for version in self._versions():
            with self.subTest(version=version):
                library = self._upgraded(version)
                for table in ('book', 'collection', 'contain', 'info',
                              'watchlist', 'recent'):
                    self.assertTrue(library._table_exists(table),
                                    '%s is missing' % table)
                plan = self._plan(library._con,
                                  'delete from Contain where book = ?', (1,))
                self.assertNotIn('SCAN', plan, msg=plan)
                self.assertEqual(
                    library._con.execute(
                        'select name from collection where id = ?',
                        (constants.COLLECTION_RECENT,)).fetchone(),
                    'RECENT')
                self._done(library)

    def test_every_version_keeps_the_name_of_the_page_left_on(self):
        """Version 10 added the column that holds the name within its
        archive of the page a book was left on."""
        for version in self._versions():
            with self.subTest(version=version):
                library = self._upgraded(version)
                columns = [row[1] for row in library._con.execute(
                    'pragma table_info(recent)').fetchall()]
                self.assertIn('member', columns)
                self._done(library)

    def test_a_file_an_older_mcomix_opened_again_is_upgraded_again(self):
        """An older MComix writes its own version over a newer one it
        opens, and leaves the column there: the step finds it and does
        not add it a second time, which sqlite refuses."""
        library = self._upgraded(9)
        library._con.execute(
            "update info set value = '9' where key = 'version'")
        self._done(library)
        backend._backend = None
        library = backend.LibraryBackend()
        held = library._con.execute(
            "select value from info where key = 'version'").fetchone()
        self.assertEqual(int(held), backend._LibraryBackend.DB_VERSION)
        self._done(library)

    def test_a_watched_directory_survives_every_version_that_had_one(self):
        for version in self._versions(2):
            with self.subTest(version=version):
                library = self._upgraded(version)
                watched = library._con.execute(
                    'select path, collection, recursive from watchlist'
                ).fetchall()
                # The version 4 step cannot know whether a directory
                # written before the flag existed was meant to recurse,
                # so it says no; from 4 on the stored flag is kept.
                self.assertEqual(watched,
                                 [('/watched', 1, 1 if version >= 4 else 0)])
                self._done(library)

    def test_the_page_a_book_was_read_to_is_carried_into_the_library(self):
        """Version 4 moved the legacy lastreadpage.db into the library,
        filing each of its books in Recent, and deleted it."""
        for version in self._versions():
            with self.subTest(version=version):
                library = self._upgraded(version)
                book = library.get_book_by_path(self._archive())
                if version >= 5:
                    self.assertIsNone(
                        book, 'a version past the migration ran it anyway')
                    self._done(library)
                    continue
                self.assertIsNotNone(book, 'the read book was not carried')
                self.assertEqual(book.get_last_read_page(), 7)
                self.assertIn(book.id, library.get_books_in_collection(
                    constants.COLLECTION_RECENT))
                self._done(library)
                self.assertFalse(
                    os.path.exists(constants.LASTPAGE_DATABASE_PATH),
                    'the legacy database was left behind')


    def test_a_book_gone_is_dropped_and_one_the_library_has_is_kept(self):
        """Of the legacy rows, one names a file that is gone and is in
        no library, and one names the library's own a.cbz, whose file
        is gone as well: that one keeps its row and goes into Recent
        with its page, and the other is dropped rather than added."""
        self._write_database(3)
        legacy = dbapi2.connect(constants.LASTPAGE_DATABASE_PATH,
                                isolation_level=None)
        legacy.executemany(
            'insert into lastread (path, page, time_set) values (?, ?, ?)',
            [(_A_BOOK, 3, '2020-01-02 00:00:00'),
             ('/gone/b.cbz', 5, '2020-01-03 00:00:00')])
        legacy.close()
        library = backend.LibraryBackend()
        try:
            kept = library.get_book_by_path(_A_BOOK)
            self.assertEqual(1, kept.id)
            self.assertEqual(3, kept.get_last_read_page())
            self.assertIn(1, library.get_books_in_collection(
                constants.COLLECTION_RECENT))
            self.assertIsNone(library.get_book_by_path('/gone/b.cbz'))
        finally:
            self._done(library)


class InterruptedUpgradeTest(LibraryDatabaseTest):

    """An upgrade that stops part way through a table rebuild.

    Three of the nine steps rename a table aside, create the new one,
    copy the rows across and drop the original.  The connection is opened
    in auto-commit mode, so without a transaction the rename commits on
    its own - and _library_version() reads a database with no book table
    as one that is not there at all, answers -1, and has _create_tables()
    write an empty schema over the top.  The library then opens with no
    books in it and every one of them left in book_old, which nothing
    will ever read again.
    """

    class Interrupted(Exception):
        """Stands in for the process dying mid-upgrade."""

    def _interrupt(self, method):
        """Have <method> of the backend raise instead of running.

        Returns the callable that puts it back, for a test that goes on to
        open the library a second time; it is registered as a cleanup as
        well, so a test that does not need that can ignore it.
        """
        original = getattr(backend._LibraryBackend, method)

        def raising(_self, *args, **kwargs):
            raise self.Interrupted(method)

        def restore():
            setattr(backend._LibraryBackend, method, original)

        setattr(backend._LibraryBackend, method, raising)
        self.addCleanup(restore)
        return restore

    def _query(self, statement):
        """Run <statement> against the database file directly, on a
        connection of its own: the backend never finished opening.
        """
        connection = dbapi2.connect(self.db, isolation_level=None)
        try:
            return [row[0] for row in connection.execute(statement)]
        finally:
            connection.close()

    def _tables(self):
        return set(self._query(
            "select name from sqlite_master where type = 'table'"))

    def _books(self):
        return self._query('select name from book')

    def test_a_rebuild_that_stops_leaves_the_table_it_was_rebuilding(self):
        """Version 2 rebuilds book, so the step is entered with the
        reader's books in it: they have to still be there afterwards, and
        under the name the next attempt will look for."""
        self._write_database(2)
        self._interrupt('_create_table_book')

        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()

        self.assertIn('book', self._tables(),
                      'the book table was renamed away and not put back')
        self.assertNotIn('book_old', self._tables(),
                         'the rename outlived the step that made it')
        self.assertEqual(['a.cbz'], self._books())

    def test_the_upgrade_is_attempted_again_and_completes(self):
        """The version row is written last, so a stopped upgrade leaves
        the old version behind and the next open runs the steps again.
        That is only any use if the step left the table alone."""
        self._write_database(2)
        restore = self._interrupt('_create_table_book')
        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()
        backend._backend = None

        # The process starts again, with nothing raising this time.
        restore()
        library = backend.LibraryBackend()
        try:
            self.assertEqual(backend._LibraryBackend.DB_VERSION,
                             library._library_version())
            # The book the database was written with, and the one the
            # version 4 step carries over from the legacy lastreadpage.db
            # once it is reached - which the interrupted attempt never
            # was.
            self.assertEqual(['a.cbz', os.path.basename(self._archive())],
                             self._books())
        finally:
            library.close()

    def test_the_watchlist_rebuild_is_covered_too(self):
        """Version 3 rebuilds watchlist the same way."""
        self._write_database(3)
        self._interrupt('_create_table_watchlist')

        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()

        self.assertIn('watchlist', self._tables())
        self.assertNotIn('watchlist_old', self._tables())

    def test_the_second_half_of_a_two_table_step_cannot_be_lost(self):
        """Version 5 rebuilds book and then collection.  Stopping between
        the two used to leave a database holding the new book table and
        the old collection one, which is a shape no step is written
        against - and the retry would rebuild book a second time."""
        self._write_database(5)
        self._interrupt('_create_table_collection')

        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()

        tables = self._tables()
        self.assertIn('book', tables)
        self.assertIn('collection', tables)
        self.assertNotIn('book_old', tables,
                         'the first rebuild of the step was committed alone')
        self.assertNotIn('collection_old', tables)
        self.assertEqual(['a.cbz'], self._books())

    def test_a_rollback_leaves_no_transaction_open(self):
        """The upgrade runs from __init__(), so a connection left in a
        transaction would be handed to the caller that way and hold the
        database locked."""
        self._write_database(2)
        self._interrupt('_create_table_book')
        opened = []

        original = backend._LibraryBackend._library_version

        def remember(instance):
            opened.append(instance)
            return original(instance)

        backend._LibraryBackend._library_version = remember
        self.addCleanup(setattr, backend._LibraryBackend,
                        '_library_version', original)
        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()

        self.assertTrue(opened, 'the backend never opened its connection')
        self.assertFalse(opened[0]._con.in_transaction,
                         'the rollback left a transaction open')


class InterruptedCreationTest(LibraryDatabaseTest):

    """A brand-new library whose creation stops part way through.

    _create_tables() writes six tables, and the info table carrying the
    version row is the fourth of them.  Without a transaction each create
    committed by itself, so a creation that stopped after info left
    book, collection, contain and info behind - which _library_version()
    reads as a finished database at the current version.
    _upgrade_database() then had nothing to do, and the library opened
    that way every time afterwards, with no watchlist and no recent table
    and no path back.
    """

    class Interrupted(Exception):
        """Stands in for the process dying mid-creation."""

    def _interrupt(self, method):
        """Have <method> of the backend raise instead of running, and
        return the callable that puts it back."""
        original = getattr(backend._LibraryBackend, method)

        def raising(_self, *args, **kwargs):
            raise self.Interrupted(method)

        def restore():
            setattr(backend._LibraryBackend, method, original)

        setattr(backend._LibraryBackend, method, raising)
        self.addCleanup(restore)
        return restore

    #: Every table a finished library holds.
    TABLES = ('book', 'collection', 'contain', 'info', 'watchlist', 'recent')

    def _tables(self):
        connection = dbapi2.connect(self.db, isolation_level=None)
        try:
            return {row[0] for row in connection.execute(
                "select name from sqlite_master where type = 'table'")}
        finally:
            connection.close()

    def test_a_creation_that_stops_after_the_info_table_leaves_nothing(self):
        """Nothing rather than a database that says it is finished: the
        next open has to find a file it can tell is not there yet."""
        restore = self._interrupt('_create_table_watchlist')
        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()

        self.assertEqual(set(), self._tables())
        restore()
        backend._backend = None

        library = backend.LibraryBackend()
        try:
            for table in self.TABLES:
                self.assertTrue(library._table_exists(table),
                                '%s was not created on the second attempt'
                                % table)
        finally:
            library.close()

    def test_the_watch_list_works_after_a_stopped_creation(self):
        """What the half-created database broke.  The watch list is read
        whenever the library scans for new books, so this was not a
        corner the reader could avoid."""
        restore = self._interrupt('_create_table_watchlist')
        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()
        restore()
        backend._backend = None

        library = backend.LibraryBackend()
        try:
            self.assertEqual([], library.watchlist.get_watchlist())
            self.assertEqual([], library.get_paths_of_books_outside_recent())
        finally:
            library.close()

    def test_a_creation_that_stops_before_the_info_table_leaves_nothing(self):
        """The half that was self-healing before is covered as well, so
        that the transaction cannot be narrowed to the tables after
        info."""
        restore = self._interrupt('_create_table_contain')
        with self.assertRaises(self.Interrupted):
            backend.LibraryBackend()

        self.assertEqual(set(), self._tables())
        restore()
        backend._backend = None

        library = backend.LibraryBackend()
        try:
            for table in self.TABLES:
                self.assertTrue(library._table_exists(table))
        finally:
            library.close()


class CleanCollectionTransactionTest(LibraryDatabaseTest):

    """clean_collection() sweeps in one transaction, not thousands.

    The connection is opened in auto-commit mode, so without one each of
    the two deletes remove_book() runs commits by itself. Asserted as the
    transaction the removals happen inside rather than as a duration,
    which is not reproducible.
    """

    def setUp(self):
        super().setUp()
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
        super().tearDown()

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


class RemoveCollectionTest(LibraryDatabaseTest):

    """Removing a shelf touches four tables, and must do so atomically.

    The connection is opened in auto-commit mode, so without a
    transaction each of the four statements commits by itself.  A
    collection's id is its sqlite rowid and is handed out again as soon
    as the highest row is free, so a removal stopped between them leaves
    rows naming an id the next collection created will be given.
    """

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()
        with self.library.transaction():
            self.parent = self.library.add_collection('Parent')
            self.child = self.library.add_collection('Child')
            self.library.add_collection_to_collection(self.child, self.parent)
            self.other = self.library.add_collection('Other')
            cursor = self.library._con.execute(
                '''insert into book (name, path, pages, format, size)
                values ('b', '/does/not/exist.cbz', 1, 1, 1)''')
            self.book = cursor.lastrowid
            cursor.close()
            self.library.add_book_to_collection(self.book, self.parent)
            self.library.add_book_to_collection(self.book, self.other)
            self.library._con.execute(
                '''insert into watchlist (path, collection, recursive)
                values ('/watched', ?, 0)''', (self.parent,))

    def tearDown(self):
        self.library.close()
        super().tearDown()

    def _traced(self, collection):
        """Return every statement remove_collection() issues, the
        implicit BEGIN and the COMMIT included."""
        seen = []
        self.library._con.set_trace_callback(seen.append)
        try:
            self.library.remove_collection(collection)
        finally:
            self.library._con.set_trace_callback(None)
        return seen

    def test_the_whole_removal_is_one_transaction(self):
        seen = self._traced(self.parent)
        begins = [statement for statement in seen
                  if statement.startswith('BEGIN')]
        commits = [statement for statement in seen if statement == 'COMMIT']
        self.assertEqual(1, len(begins),
                         'not one transaction: %r' % seen)
        self.assertEqual(1, len(commits),
                         'not one transaction: %r' % seen)
        self.assertEqual('BEGIN', seen[0][:5], 'writes before the BEGIN')
        self.assertEqual('COMMIT', seen[-1], 'writes after the COMMIT')
        self.assertFalse(self.library._con.in_transaction,
                         'the removal left a transaction open')

    def test_the_row_naming_the_collection_goes_last(self):
        """Every row that points at the collection is cleared before the
        collection itself, so that a database interrupted at any
        statement never holds a reference to an id that is free."""
        seen = self._traced(self.parent)
        writes = [statement.split()[0].lower() + ' ' +
                  ('collection' if ' Collection ' in statement
                   or 'from Collection' in statement else 'other')
                  for statement in seen
                  if statement.split()[0].lower() in ('insert', 'update',
                                                      'delete')]
        self.assertEqual('delete collection', writes[-1],
                         'the collection row was not deleted last: %r' % seen)

    def test_a_caller_may_hold_the_transaction_itself(self):
        """The helpers do not nest, so a removal inside a caller's
        transaction must leave it open rather than commit it."""
        self.library.begin_transaction()
        self.library.remove_collection(self.other)
        self.assertTrue(self.library._con.in_transaction,
                        'the removal committed a transaction it did not open')
        self.library.end_transaction()

    def test_nothing_is_left_naming_the_removed_collection(self):
        self.library.remove_collection(self.parent)
        self.assertEqual(
            [], self.library._con.execute(
                'select book from contain where collection = ?',
                (self.parent,)).fetchall())
        self.assertEqual(
            [], self.library._con.execute(
                'select id from collection where supercollection = ?',
                (self.parent,)).fetchall())
        self.assertEqual(
            [], self.library._con.execute(
                'select path from watchlist where collection = ?',
                (self.parent,)).fetchall())
        self.assertEqual(
            [], self.library._con.execute(
                'select name from collection where id = ?',
                (self.parent,)).fetchall())

    def test_the_books_and_the_collection_under_it_survive(self):
        self.library.remove_collection(self.parent)
        self.assertEqual(
            self.book, self.library._con.execute(
                'select id from book').fetchone(),
            'the book went with the collection it was filed in')
        self.assertEqual(
            [self.book], self.library._con.execute(
                'select book from contain where collection = ?',
                (self.other,)).fetchall(),
            'the book lost a collection it was still in')
        self.assertIsNone(
            self.library._con.execute(
                'select supercollection from collection where id = ?',
                (self.child,)).fetchone(),
            'the collection under it was not moved to the root')


class BooksOutsideRecentTest(LibraryDatabaseTest):

    """Which books the watch list scan counts as already in the library.

    A book filed nowhere but in "Recent" is there because it was opened
    once, not because it was collected, so a scan still treats it as new
    and files it under the collection the directory is watched for. The
    scan used to work this out by asking every book which collections it
    was in, which is a query per book.
    """

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()
        self.shelf = self.library.add_collection('Shelf')

    def tearDown(self):
        self.library.close()
        super().tearDown()

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


class BookPathsInCollectionTest(LibraryDatabaseTest):

    """The ids and paths of a collection's books in one statement."""

    def setUp(self):
        super().setUp()
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
        super().tearDown()

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


class TransactionTest(LibraryDatabaseTest):

    """The context manager that makes a loop of writes one transaction."""

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()

    def tearDown(self):
        self.library.close()
        super().tearDown()

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


class TableExistsTest(LibraryDatabaseTest):

    """_table_exists() decides whether the file has a schema at all.

    It used to paste the name into "pragma table_info(%s)", where the
    argument is part of the statement, so a name that is not a bare
    identifier was a syntax error out of a question that has a "no".
    """

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()

    def tearDown(self):
        self.library.close()
        super().tearDown()

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


class ClearAllTest(LibraryDatabaseTest):

    """What LastReadPage.clear_all() may and may not remove."""

    def setUp(self):
        super().setUp()
        self.backend = backend.LibraryBackend()
        self.lastread = last_read_page.LastReadPage(self.backend)
        self.lastread.set_enabled(True)

    def tearDown(self):
        self.backend.close()
        super().tearDown()

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


class AddBookToCollectionTest(LibraryDatabaseTest):

    """What the listeners are told when a book is filed."""

    def setUp(self):
        super().setUp()
        self.backend = backend.LibraryBackend()
        self.seen = []
        self.backend.book_added_to_collection += self._book_filed

    def tearDown(self):
        self.backend.close()
        super().tearDown()

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


class MovedBookTest(LibraryDatabaseTest):

    """A book that MComix has moved keeps its row, and its row keeps up.

    The library stores a book by its path, so a move that left the row
    alone would point it at a file that is not there any more - and
    what hangs off the row's id, the collections it is in and the page
    it was read to, would be lost with it.  The cover is stored under
    the path instead, and follows on its own.
    """

    def setUp(self):
        super().setUp()
        self.backend = backend.LibraryBackend()
        self.path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.assertTrue(self.backend.add_book(self.path))
        self.book = self.backend.get_book_by_path(self.path)

    def tearDown(self):
        self.backend.close()
        super().tearDown()

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

    def test_the_cover_follows_the_file(self):
        """The cover is stored under a name made of the book's path: the
        one drawn before the move was left where nothing looks for it or
        removes it, and the archive was opened for another."""
        book = os.path.join(self.tmp_dir, 'book.zip')
        moved = os.path.join(self.tmp_dir, 'moved.zip')
        shutil.copy2(self.path, book)
        self.assertTrue(self.backend.add_book(book))
        self.assertIsNotNone(self.backend.get_book_thumbnail(book))
        covers = os.listdir(constants.LIBRARY_COVERS_PATH)
        self.assertEqual(1, len(covers))
        shutil.move(book, moved)

        self.assertTrue(self.backend.update_book_path(book, moved))

        with unittest.mock.patch.object(
                thumbnail_tools.Thumbnailer, '_create_thumbnail') as drawn:
            self.assertIsNotNone(self.backend.get_book_thumbnail(moved))
        drawn.assert_not_called()
        kept = os.listdir(constants.LIBRARY_COVERS_PATH)
        self.assertEqual(1, len(kept))
        self.assertNotEqual(covers, kept)

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


class RelocatedShelfTest(LibraryDatabaseTest):

    """A folder of books moved or renamed outside MComix left every one
    of them in the library under a path with no file at it (upstream
    feature requests 56 and 122)."""

    def setUp(self):
        super().setUp()
        self.backend = backend.LibraryBackend()
        self.old = os.path.join(self.tmp_dir, 'shelf')
        self.new = os.path.join(self.tmp_dir, 'elsewhere', 'comics')
        self.ids = {}
        for number, parts in enumerate((
                ('shelf', 'a.cbz'), ('shelf', 'sub', 'b.cbz'),
                ('shelf-old', 'c.cbz'), ('100%_x', 'd.cbz'),
                ('100abcx', 'e.cbz')), start=1):
            path = os.path.join(self.tmp_dir, *parts)
            self.backend._con.execute(
                'insert into book (id, name, path, pages, format, size)'
                ' values (?, ?, ?, 20, 1, 1)', (number, parts[-1], path))
            self.ids[parts[-1]] = number

    def tearDown(self):
        self.backend.close()
        super().tearDown()

    def _paths(self):
        return {name: os.path.relpath(path, self.tmp_dir).split(os.sep)
                for name, path in self.backend._con.execute(
                    'select name, path from book').fetchall()}

    def test_every_book_under_the_folder_follows_it(self):
        self.assertEqual(2, self.backend.relocate(self.old, self.new))
        self.assertEqual(
            {'a.cbz': ['elsewhere', 'comics', 'a.cbz'],
             'b.cbz': ['elsewhere', 'comics', 'sub', 'b.cbz'],
             # A folder whose name only starts the same is another folder.
             'c.cbz': ['shelf-old', 'c.cbz'],
             'd.cbz': ['100%_x', 'd.cbz'], 'e.cbz': ['100abcx', 'e.cbz']},
            self._paths())

    def test_what_hangs_off_a_book_comes_with_it(self):
        self.backend._con.execute(
            "insert into collection (id, name) values (7, 'Shelf')")
        self.backend._con.execute(
            'insert into contain (collection, book) values (7, 1)')
        self.backend._con.execute(
            'insert into recent (book, page, time_set) values'
            " (1, 12, '2026-01-01 00:00:00')")
        self.backend.relocate(self.old, self.new)
        moved = self.backend.get_book_by_path(
            os.path.join(self.new, 'a.cbz'))
        self.assertEqual(1, moved.id)
        self.assertEqual([7], self.backend._con.execute(
            'select collection from contain where book = 1').fetchall())
        self.assertEqual([12], self.backend._con.execute(
            'select page from recent where book = 1').fetchall())

    def test_a_folder_name_is_not_read_as_a_pattern(self):
        """% and _ are what LIKE matches anything with."""
        self.assertEqual(1, self.backend.relocate(
            os.path.join(self.tmp_dir, '100%_x'), self.new))
        self.assertEqual(['100abcx', 'e.cbz'], self._paths()['e.cbz'])
        self.assertEqual(['elsewhere', 'comics', 'd.cbz'],
                         self._paths()['d.cbz'])

    def test_a_book_the_library_holds_there_already_keeps_its_row(self):
        self.backend._con.execute(
            'insert into book (id, name, path, pages, format, size)'
            " values (9, 'a.cbz', ?, 20, 1, 1)",
            (os.path.join(self.new, 'a.cbz'),))
        self.assertEqual(1, self.backend.relocate(self.old, self.new))
        self.assertEqual(
            [(1, os.path.join(self.old, 'a.cbz')),
             (9, os.path.join(self.new, 'a.cbz'))],
            self.backend._con.execute(
                "select id, path from book where name = 'a.cbz'"
                ' order by id').fetchall())

    def test_the_watched_folders_follow_too(self):
        for path in (self.old, os.path.join(self.old, 'sub'),
                     os.path.join(self.tmp_dir, 'shelf-old')):
            self.backend._con.execute(
                'insert into watchlist (path, collection, recursive)'
                ' values (?, null, 1)', (path,))
        self.backend.relocate(self.old, self.new)
        self.assertEqual(
            sorted([self.new, os.path.join(self.new, 'sub'),
                    os.path.join(self.tmp_dir, 'shelf-old')]),
            sorted(path for path in self.backend._con.execute(
                'select path from watchlist').fetchall()))

    def _draw_covers(self):
        """Something stored as the cover of every book, saying whose."""
        covers = thumbnail_tools.Thumbnailer(
            dst_dir=constants.LIBRARY_COVERS_PATH)
        os.makedirs(constants.LIBRARY_COVERS_PATH, exist_ok=True)
        for book, path in self.backend._con.execute(
                'select id, path from book').fetchall():
            with open(covers._path_to_thumbpath(path), 'w') as cover:
                cover.write(str(book))
        return covers

    def _covers_by_book(self, covers):
        """What is stored as the cover of each book where it is now."""
        found = {}
        for book, path in self.backend._con.execute(
                'select id, path from book').fetchall():
            with open(covers._path_to_thumbpath(path)) as cover:
                found[book] = cover.read()
        return found

    def test_the_covers_follow_their_books(self):
        """They are stored under names made of the paths, so every one
        was left behind and drawn again from its archive."""
        covers = self._draw_covers()
        self.assertEqual(2, self.backend.relocate(self.old, self.new))
        self.assertEqual({book: str(book) for book in range(1, 6)},
                         self._covers_by_book(covers))
        self.assertEqual(5, len(os.listdir(constants.LIBRARY_COVERS_PATH)))

    def test_a_book_follows_to_where_another_has_just_been(self):
        """Into a folder of its own, or out of one into the folder
        above.  Taken in the order of their ids, the book that came to a
        place before the one there had left it stayed behind."""
        sub = os.path.join(self.old, 'sub')
        deeper = os.path.join(sub, 'sub')
        for old, new, before, after in (
                (self.old, sub, {6: self.old, 7: sub}, {6: sub, 7: deeper}),
                (sub, self.old, {6: deeper, 7: sub}, {6: sub, 7: self.old})):
            with self.subTest(old=old, new=new):
                self.backend._con.execute('delete from book')
                for number, folder in before.items():
                    self.backend._con.execute(
                        'insert into book (id, name, path, pages, format,'
                        " size) values (?, 'x.cbz', ?, 20, 1, 1)",
                        (number, os.path.join(folder, 'x.cbz')))
                covers = self._draw_covers()
                self.assertEqual(2, self.backend.relocate(old, new))
                self.assertEqual(
                    {number: os.path.join(folder, 'x.cbz')
                     for number, folder in after.items()},
                    dict(self.backend._con.execute(
                        'select id, path from book').fetchall()))
                # And its cover is not put over one that has yet to go.
                self.assertEqual({6: '6', 7: '7'},
                                 self._covers_by_book(covers))

    def test_nothing_to_follow_follows_nothing(self):
        self.assertEqual(0, self.backend.relocate(self.old, self.old))
        self.assertEqual(0, self.backend.relocate(
            os.path.join(self.tmp_dir, 'nowhere'), self.new))
        self.assertEqual(['shelf', 'a.cbz'], self._paths()['a.cbz'])

    def test_the_books_are_found_by_the_index_on_their_paths(self):
        old = tools.folder_prefix(self.old)
        plan = self._plan(
            self.backend._con,
            'select id, path from Book where path >= ? and path < ?',
            (old, old[:-1] + chr(ord(old[-1]) + 1)))
        self.assertIn('SEARCH', plan)
        self.assertNotIn('SCAN', plan)


class RelocatedPathTest(unittest.TestCase):

    def test_a_path_in_the_folder_is_in_the_new_one(self):
        old = os.path.join(os.sep, 'comics')
        new = os.path.join(os.sep, 'mnt', 'shelf')
        self.assertEqual(
            os.path.abspath(os.path.join(new, 'sub', 'a.cbz')),
            tools.relocated(os.path.abspath(os.path.join(old, 'sub', 'a.cbz')),
                            old, new))
        for elsewhere in (os.path.join(os.sep, 'comics-old', 'a.cbz'),
                          os.path.join(os.sep, 'comics'),
                          os.path.join(os.sep, 'other', 'comics', 'a.cbz')):
            self.assertIsNone(
                tools.relocated(os.path.abspath(elsewhere), old, new),
                elsewhere)


class RemovedBookTest(LibraryDatabaseTest):

    """remove_book() left the page the book was read to behind.

    The recent table is keyed by book id, and a book's id is its sqlite
    rowid, which is handed out again once the highest row is deleted.  A
    row left over from a removed book therefore belonged to whichever
    book was added next.
    """

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()

    def tearDown(self):
        self.library.close()
        super().tearDown()

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


class HalfWrittenDatabaseTest(LibraryDatabaseTest):

    """A file that holds an info table but not the tables it describes.

    _upgrade_database() renames a table, creates the new one and copies
    the rows across, and it writes the version last so that an upgrade
    which stops part way is attempted again.  Stopping between the
    rename and the create leaves a file whose book table is gone while
    its info table still names a version, and there is no reason the
    disk cannot fill or the power cannot go while a table is being
    rebuilt.
    """

    def setUp(self):
        super().setUp()
        connection = dbapi2.connect(self.db, isolation_level=None)
        # Everything a version 5 upgrade leaves behind when it stops
        # after renaming book out of the way.
        connection.execute("""create table info (
            key text primary key, value text)""")
        connection.execute(
            "insert into info (key, value) values ('version', '5')")
        connection.execute("""create table collection (
            id integer primary key, name text unique,
            supercollection integer)""")
        connection.execute("""create table contain (
            collection integer not null, book integer not null,
            primary key (collection, book))""")
        connection.close()

    def tearDown(self):
        super().tearDown()

    def test_the_library_opens_over_it(self):
        """The version row is already there, so writing the current one
        used to raise IntegrityError out of the constructor and the
        library could not be opened at all."""
        library = backend.LibraryBackend()
        try:
            version = library._con.execute(
                "select value from info where key = 'version'").fetchone()
        finally:
            library.close()
        self.assertEqual(int(version), backend._LibraryBackend.DB_VERSION)

    def test_the_tables_that_were_missing_are_created(self):
        library = backend.LibraryBackend()
        try:
            for table in ('book', 'collection', 'contain', 'info',
                          'watchlist', 'recent'):
                self.assertTrue(library._table_exists(table),
                                '%s was not created' % table)
        finally:
            library.close()


class MissingBookTest(LibraryDatabaseTest):

    """What the accessors answer for a book id that names no row.

    sqlite reports a row that is not there by returning None from
    fetchone(), not by raising, so the try/except these two used to
    carry never ran.  get_book_cover() went on to thumbnail the None it
    had been handed, and raised TypeError out of a drag handler that was
    written to expect None.
    """

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()

    def tearDown(self):
        self.library.close()
        super().tearDown()

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


class AddCollectionTest(LibraryDatabaseTest):

    """What add_collection() answers with.

    It used to return True or False, and the first collection in a
    fresh library has id 1, so a caller that passed the answer on as a
    collection id worked by the accident of True == 1.  The library's
    own callers all wanted the id and looked it up again by name
    afterwards.
    """

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()

    def tearDown(self):
        self.library.close()
        super().tearDown()

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


class DuplicateCollectionTest(LibraryDatabaseTest):

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
        super().setUp()
        self.library = backend.LibraryBackend()
        self.collection = self.library.add_collection('Shelf')
        self.library._con.execute(
            '''insert into book (name, path, pages, format, size)
               values (?, ?, ?, ?, ?)''',
            # As add_book() stores it: absolute, which on Windows begins
            # with a drive, and is what get_book_by_path() looks for.
            ('a', os.path.abspath('/does/not/exist/a.cbz'), 20, 1, 1))
        self.library.add_book_to_collection(
            self.library.get_book_by_path('/does/not/exist/a.cbz').id,
            self.collection)

    def tearDown(self):
        self.library.close()
        super().tearDown()

    def test_the_copy_holds_the_same_books(self):
        self.assertTrue(self.library.duplicate_collection(self.collection))
        copy = self.library.get_collection_by_name('Shelf (Copy)')
        self.assertIsNotNone(copy)
        self.assertEqual(self.library.get_books_in_collection(self.collection),
                         self.library.get_books_in_collection(copy.id))

    def test_a_second_copy_takes_a_name_of_its_own(self):
        """A collection's name is unique in the library, and the first
        copy has taken "Shelf (Copy)"."""
        self.assertTrue(self.library.duplicate_collection(self.collection))
        self.assertTrue(self.library.duplicate_collection(self.collection))
        self.assertIsNotNone(
            self.library.get_collection_by_name('Shelf (Copy) (Copy)'))

    def _book_in(self, name, collection):
        """File a book called <name> in <collection>, and answer its id."""
        self.library._con.execute(
            '''insert into book (name, path, pages, format, size)
               values (?, ?, ?, ?, ?)''',
            (name, os.path.abspath('/does/not/exist/%s.cbz' % name), 20, 1,
             1))
        book = self.library.get_book_by_path(
            '/does/not/exist/%s.cbz' % name).id
        self.library.add_book_to_collection(book, collection)
        return book

    def test_the_copy_shows_the_books_of_the_collections_under_it(self):
        """A collection shows the books of every collection under it as
        well as its own; the copy held only its own, and so showed
        fewer books than the collection it was a copy of."""
        inner = self.library.add_collection('Inner')
        self.library.add_collection_to_collection(inner, self.collection)
        self._book_in('b', inner)
        self.assertTrue(self.library.duplicate_collection(self.collection))
        copy = self.library.get_collection_by_name('Shelf (Copy)')
        original = self.library.get_collection_by_id(self.collection)
        self.assertEqual(sorted(book.id for book in original.get_books()),
                         sorted(book.id for book in copy.get_books()))
        self.assertEqual(self.library.get_all_collections_in_collection(
            copy.id), [], 'the copy took the collections under it along')

    def test_the_copy_is_put_beside_the_collection(self):
        """It went to the top of the library, wherever the collection
        was."""
        outer = self.library.add_collection('Outer')
        self.library.add_collection_to_collection(self.collection, outer)
        self.assertTrue(self.library.duplicate_collection(self.collection))
        copy = self.library.get_collection_by_name('Shelf (Copy)')
        self.assertEqual(outer, self.library.get_supercollection(copy.id))

    def test_a_collection_that_cannot_be_created_is_reported(self):
        self.library.add_collection = lambda name: None

        self.assertFalse(self.library.duplicate_collection(self.collection),
                         'a duplication that could not add its collection '
                         'reported success')


class CollectionTreeTest(LibraryDatabaseTest):

    """Both walks over the collection tree ask the database once.

    Each of them used to run a query for every node it reached, so the
    number of statements grew with the tree rather than staying at one.
    Asserted as the statement count rather than as a duration, which is
    not reproducible.
    """

    def setUp(self):
        super().setUp()
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
        super().tearDown()

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


class AddBookStatementTest(LibraryDatabaseTest):

    """add_book() describes to the listeners the book it just built.

    Filing it in a collection used to be given nothing but the id, so
    the row was read back to find out what it said: a fourth statement
    for every book of a batch, over a book the caller was holding.
    """

    def setUp(self):
        super().setUp()
        self.backend = backend.LibraryBackend()
        self.collection = self.backend.add_collection('files')
        self.path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        self.seen = []
        self.reported = []
        self.backend.book_added_to_collection += self._book_filed

    def tearDown(self):
        self.backend.close()
        super().tearDown()

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


class CollectionTreeQueryTest(LibraryDatabaseTest):

    """get_collection_tree() answers with the whole hierarchy at once."""

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()
        self.comics = self.library.add_collection('Comics')
        self.manga = self.library.add_collection('Manga')
        self.inner = self.library.add_collection('Inner')
        self.library.add_collection_to_collection(self.inner, self.comics)

    def tearDown(self):
        self.library.close()
        super().tearDown()

    def test_the_collections_are_grouped_by_the_one_above_them(self):
        self.assertEqual(
            {None: [(self.comics, 'Comics'), (self.manga, 'Manga'),
                    (constants.COLLECTION_RECENT, 'Recent')],
             self.comics: [(self.inner, 'Inner')]},
            self.library.get_collection_tree())

    def test_names_are_in_natural_order_whatever_their_case(self):
        # Upstream feature request 84: "Vol 10" came before "Vol 2", and
        # a name in lower case after every name in upper case.
        vol10 = self.library.add_collection('Vol 10')
        vol2 = self.library.add_collection('Vol 2')
        lower = self.library.add_collection('anthologies')
        expected = [lower, self.comics, self.manga,
                    constants.COLLECTION_RECENT, vol2, vol10]
        self.assertEqual(
            expected, [id for id, name in self.library.get_collection_tree()[None]])
        self.assertEqual(
            expected[:2] + [self.inner] + expected[2:],
            self.library.get_all_collections())

    def test_recent_is_named_by_its_translation(self):
        # The row holds RECENT, so that a library carried from one
        # language to another still finds the collection.
        root = self.library.get_collection_tree()[None]
        self.assertEqual(
            [_('Recent')],
            [name for id, name in root
             if id == constants.COLLECTION_RECENT])


class SharedConnectionTest(LibraryDatabaseTest):

    """Threads other than the main one read through the backend's one
    connection.

    The library's covers are drawn by a pool of worker threads, three by
    default, and each of them asks its book for the page it was left on;
    the watch list scan reads the library from a thread of its own.
    sqlite3 caches prepared statements per connection, and two threads
    running the same statement at once could step the same prepared one:
    a cover worker raised "bad parameter or other API misuse", and the
    cover it was drawing never arrived.
    """

    THREADS = 4
    ROUNDS = 1000

    def test_threads_reading_at_once_each_get_their_answer(self):
        library = backend.LibraryBackend()
        self.addCleanup(library.close)
        path = self._archive()
        self.assertTrue(library.add_book(path))
        book = library.get_book_by_path(path)
        book.set_last_read_page(3)
        wrong = []

        def read():
            try:
                for _round in range(self.ROUNDS):
                    page = book.get_last_read_page()
                    if page != 3:
                        wrong.append('page %r' % (page,))
                    found = library.get_book_by_id(book.id)
                    if found is None or found.path != path:
                        wrong.append('book %r' % (found,))
            except Exception as error:
                wrong.append('%s: %s' % (type(error).__name__, error))

        threads = [threading.Thread(target=read)
                   for _thread in range(self.THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual([], wrong[:3], '%d of %d reads went wrong' % (
            len(wrong), 2 * self.THREADS * self.ROUNDS))


class LastReadPageRewriteTest(LibraryDatabaseTest):

    """Where a book was left is never missing while it is written again.

    The cover workers read the page each book was left on while the main
    thread may be writing one, and the library's lock is taken a
    statement at a time.  The page was written as a delete and then an
    insert, so between the two the book had no page, and a cover drawn in
    that moment carried no tick for a book read to the end.
    """

    def test_no_statement_leaves_the_book_without_its_page(self):
        library = backend.LibraryBackend()
        self.addCleanup(library.close)
        path = self._archive()
        self.assertTrue(library.add_book(path))
        book = library.get_book_by_path(path)
        book.set_last_read_page(3)
        seen = []
        execute = library.execute

        def watched(statement, *args):
            changed = execute(statement, *args)
            seen.append(book.get_last_read_page())
            return changed

        when = datetime.datetime(2026, 9, 13, 5, 0, 0, 123456)
        with unittest.mock.patch.object(library, 'execute', watched):
            book.set_last_read_page(4, when)
        self.assertNotIn(None, seen)
        self.assertEqual(4, book.get_last_read_page())
        self.assertEqual(when, book.get_last_read_date())

    def test_no_page_still_removes_it(self):
        library = backend.LibraryBackend()
        self.addCleanup(library.close)
        path = self._archive()
        self.assertTrue(library.add_book(path))
        book = library.get_book_by_path(path)
        book.set_last_read_page(3)
        book.set_last_read_page(None)
        self.assertIsNone(book.get_last_read_page())
        self.assertIsNone(book.get_last_read_date())


class EncryptedBookTest(LibraryDatabaseTest):

    """Adding an encrypted archive to the library asks for no password,
    and the book is added all the same.

    The watch list adds whatever a directory holds, and each encrypted
    archive in it put up a password prompt on its way into the library.
    """

    def setUp(self):
        super().setUp()
        self.library = backend.LibraryBackend()
        self.asked = []

        def ask(archive, on_password):
            self.asked.append(archive)
            on_password(None)

        patcher = unittest.mock.patch.object(
            archive_password, 'ask_for_password', ask)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.library.close()
        super().tearDown()

    def test_encrypted_books_are_added_without_a_prompt(self):
        for name in ('Encrypted.zip', 'Encrypted.rar', 'Encrypted.7z',
                     'EncryptedHeader.rar', 'EncryptedHeader.7z'):
            with self.subTest(name):
                path = get_testfile_path('archives', name)
                self.assertTrue(self.library.add_book(path))
                self.assertIsNotNone(self.library.get_book_by_path(path))
        self.assertEqual([], self.asked)


class UnreadableDatabaseTest(LibraryDatabaseTest):

    """A library.db SQLite would not read stopped MComix before it had a
    window: the file handler opens the library as the window is built
    (upstream forum topic 768ea634)."""

    def _write(self, content):
        with open(constants.LIBRARY_DATABASE_PATH, 'wb') as fp:
            fp.write(content)

    def test_a_file_that_is_not_a_database_is_kept_and_replaced(self):
        self._write(b'not a database ' * 512)
        with self.assertLogs('mcomix', level='ERROR'):
            library = backend.LibraryBackend()
        try:
            self.assertTrue(library._table_exists('book'))
            self.assertEqual([], library.get_books_in_collection())
        finally:
            library.close()
        with open(constants.LIBRARY_DATABASE_PATH + '.broken', 'rb') as fp:
            self.assertTrue(fp.read().startswith(b'not a database'))
        # The new file is a library of its own, which the next start
        # opens without a word.
        backend.LibraryBackend().close()

    def test_a_damaged_database_is_kept_and_replaced(self):
        """A file whose header is SQLite's and whose pages are not."""
        library = backend.LibraryBackend()
        library.close()
        with open(constants.LIBRARY_DATABASE_PATH, 'r+b') as fp:
            fp.seek(100)
            fp.write(b'\xff' * 4000)
        with self.assertLogs('mcomix', level='ERROR'):
            library = backend.LibraryBackend()
        try:
            self.assertTrue(library._table_exists('book'))
        finally:
            library.close()
        self.assertTrue(os.path.isfile(
            constants.LIBRARY_DATABASE_PATH + '.broken'))

    def test_a_database_that_cannot_be_opened_is_left_alone(self):
        """Nothing is wrong with what is in the way, so nothing is
        moved, and the library lasts as long as MComix runs."""
        os.makedirs(constants.LIBRARY_DATABASE_PATH)
        with self.assertLogs('mcomix', level='ERROR'):
            library = backend.LibraryBackend()
        try:
            library.add_collection('Kept in memory')
            self.assertIsNotNone(
                library.get_collection_by_name('Kept in memory'))
        finally:
            library.close()
        self.assertTrue(os.path.isdir(constants.LIBRARY_DATABASE_PATH))
        self.assertFalse(os.path.exists(
            constants.LIBRARY_DATABASE_PATH + '.broken'))
