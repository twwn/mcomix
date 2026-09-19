"""backend_types.py - The things the library database holds.

A book, a collection and a watched directory, a class each, with the
default collection that stands for the whole library beside them.  None
of them holds more than the row it was built from: which collections a
book is in, which books a collection holds, what has turned up in a
watched directory, are all queries made when they are asked for, through
the one backend that mcomix.library.backend hands out.
"""

import os
import threading
import traceback
import datetime

from mcomix import callback
from mcomix import archive_tools
from mcomix import log
from mcomix.i18n import _

from collections.abc import Sequence
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library.backend import _LibraryBackend


class _BackendObject:

    """Something that reads and writes through the library backend.

    It fetches the backend rather than being handed one, so that a row
    read out of the library can go on asking the library questions
    without anything having to carry it around.
    """

    #: The backend to use in place of the one LibraryBackend() hands
    #: out, for a caller that has one to give.  The library's own
    #: migration is the case that needs it: it runs while
    #: _LibraryBackend.__init__() is still on the stack, so
    #: LibraryBackend() would start building a second backend and
    #: recurse without end.
    _backend: "_LibraryBackend | None" = None

    def get_backend(self) -> '_LibraryBackend':
        if self._backend is not None:
            return self._backend
        # Deferred: mcomix.library.backend imports this module, so it
        # cannot be imported at the top of it.
        from mcomix.library.backend import LibraryBackend
        return LibraryBackend()

    def set_backend(self, backend: '_LibraryBackend') -> None:
        """Read and write through <backend> rather than through the one
        LibraryBackend() hands out."""
        self._backend = backend


class _Book(_BackendObject):
    """One book in the library: a row of the book table."""

    def __init__(self, id: int, name: str, path: str, pages: int,
                 format: int, size: int, added: str) -> None:
        """The row the library keeps for one book.

        <name> is the base name of <path>, <format> one of the archive
        formats in constants, <size> the size of the file in bytes, and
        <added> when the book was added, as the text sqlite stores it
        in rather than as a datetime.
        """

        self.id = id
        self.name = name
        self.path = path
        self.pages = pages
        self.format = format
        self.size = size
        self.added = added

    def get_collections(self) -> list['_Collection']:
        """The collections this book is filed in.

        A book filed in none of them is in the library all the same, so
        the answer is then the default collection, which stands for the
        library as a whole.
        """
        rows = self.get_backend().fetchall(
            '''SELECT id, name, supercollection FROM collection
               JOIN contain on contain.collection = collection.id
               WHERE contain.book = ?''', (self.id,))
        if rows:
            return [_Collection(*row) for row in rows]
        else:
            return [DefaultCollection]

    def get_last_read_page(self) -> int | None:
        """The page this book was left on.

        None if it has no row in the recent table: it was never read, or
        it was last closed on page 1, which the file handler clears
        rather than stores.
        """
        # The connection's row factory unwraps a one column row, so this
        # is the page itself rather than a row holding it.
        row = self.get_backend().fetchone(
            '''SELECT page FROM recent WHERE book = ?''', (self.id,))
        if row is None:
            return None
        return int(row)

    def get_last_read_date(self) -> datetime.datetime | None:
        """When this book was last read, or None if it has no row in the
        recent table.

        The time is stored as text, and comes back through whichever of
        the two formats below it was written in.
        """
        date = self.get_backend().fetchone(
            """SELECT time_set FROM recent WHERE book = ?""", (self.id,))

        if date:
            try:
                return datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                # A time that falls on a whole second is written without
                # a fractional part, by isoformat() below and by the
                # sqlite3 adapter that used to write these rows alike.
                return datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        else:
            return None

    def set_last_read_page(self, page: int | None,
                           time: datetime.datetime | None = None) -> None:
        """Remember <page> as where this book was left, at <time>.

        A <page> of None removes what was remembered instead, and a
        <time> of None is now.  Pages count from 1, and anything below
        that is not a page: it raises ValueError.
        """

        if page is not None and page < 1:
            # Page 1 is stored like any other page.  It is the file
            # handler, closing a book, that clears the row instead of
            # writing it, so that the position every book starts at
            # costs the library nothing.
            raise ValueError('Invalid page (must start from 1)')

        if page is None:
            self.get_backend().execute(
                '''DELETE FROM recent WHERE book = ?''', (self.id,))
            return

        if not time:
            time = datetime.datetime.now()
        # sqlite3's implicit datetime adapter is deprecated since
        # Python 3.12; write the same text it used to produce, which
        # is what get_last_read_date() reads back.
        written = time.isoformat(sep=' ') \
            if isinstance(time, datetime.datetime) else time
        # One statement, which book being the primary key makes a
        # replacement of the row that was there.  A delete and then an
        # insert left the book with no page in between, and the cover
        # workers read it while this writes it: a cover drawn then had
        # no tick for a book read to the end.
        self.get_backend().execute(
            '''INSERT OR REPLACE INTO recent (book, page, time_set)
               VALUES (?, ?, ?)''', (self.id, page, written))


class _Collection(_BackendObject):
    """One collection of books: a row of the collection table.

    Collections are handed out by the backend and by the queries here
    rather than built by hand, since an id that names no row makes a
    collection every query of which answers nothing.
    """

    def __init__(self, id: int, name: str,
                 supercollection: 'int | None' = None) -> None:
        """The row the library keeps for one collection.

        <supercollection> is the id of the collection this one sits
        under, or None for one at the root of the tree.
        """

        #: The default collection stands for every book and has no row of
        #: its own, so it carries no id.
        self.id: int | None = id
        self.name = name
        self.supercollection = supercollection

    def __eq__(self, other: object) -> bool:
        """A collection is its id, and equals that bare id as well.

        The backend deals in ids where this module deals in collections,
        and the two meet in comparisons such as the one in
        _scan_for_new_files_thread() below.
        """
        if isinstance(other, _Collection):
            return self.id == other.id
        elif isinstance(other, int):
            return self.id == other
        else:
            return False

    def __hash__(self) -> int:
        """The hash of the id, so that a collection and the bare id it
        compares equal to also land in the same bucket.

        Defining __eq__ without this would leave the class unhashable,
        which is not what a row of a table wants to be.
        """
        return hash(self.id)

    def get_books(self, filter_string: str | None = None) -> list['_Book']:
        """ Returns all books that are part of this collection,
        including subcollections.

        One statement over every collection at once rather than one per
        collection with the answers added together, which is what made a
        book filed in both a collection and one under it come back once
        for each - and the library draw a cover for each of them.  The
        membership test does the work: a book is in the answer or it is
        not, however many of the collections hold it.

        Written as a subquery rather than as a join with DISTINCT
        because the plans differ.  The join needs a temporary B-tree for
        the DISTINCT and another for the ordering, at every library size
        measured; this builds the list of ids once and searches book by
        rowid, and needs neither.  Once several collections are named at
        once the join also scans book: at 40,000 books across six
        collections it takes 53.50ms against 22.85ms.

        The ordering used to be an accident of the loop - grouped by
        collection - and is now the order the books were added, which is
        what the library's "All books" has always shown.
        """

        collections = [self] + self.get_all_collections()
        sql = '''SELECT book.id, book.name, book.path, book.pages,
                        book.format, book.size, book.added
                 FROM book
                 WHERE book.id IN (SELECT book FROM contain
                                   WHERE collection IN (%s))
              ''' % ', '.join('?' * len(collections))

        sql_args: "list[str | int | None]" = [collection.id
                                              for collection in collections]
        if filter_string:
            # Parenthesised: AND binds tighter than OR, so without them
            # a matching path would answer for the whole library.
            sql += ''' AND (book.name LIKE '%' || ? || '%'
                            OR book.path LIKE '%' || ? || '%') '''
            sql_args += [filter_string, filter_string]
        sql += ' ORDER BY book.id'

        rows = self.get_backend().fetchall(sql, sql_args)

        return [_Book(*cols) for cols in rows]

    def get_collections(self) -> list['_Collection']:
        """ Returns a list of all direct subcollections of this instance. """

        result = self.get_backend().fetchall('''SELECT id, name, supercollection
                FROM collection
                WHERE supercollection = ?
                ORDER by name''', [self.id])

        return [_Collection(*row) for row in result]

    def get_all_collections(self) -> list['_Collection']:
        """Every collection under this one, at any depth, in no
        particular order.

        Walked by the database rather than here, which is one statement
        instead of one for every node of the subtree.  The anchor of the
        recursion matches on IS rather than on =, so that the
        DefaultCollection, whose id is None, starts from the collections
        at the root and this reads the whole library.
        """

        rows = self.get_backend().fetchall(
            '''WITH RECURSIVE subtree(id, name, supercollection) AS (
                   SELECT id, name, supercollection FROM collection
                   WHERE supercollection IS ?
                 UNION ALL
                   SELECT collection.id, collection.name,
                          collection.supercollection
                   FROM collection
                   JOIN subtree ON collection.supercollection = subtree.id)
               SELECT id, name, supercollection FROM subtree''', (self.id,))

        return [_Collection(*row) for row in rows]

    def add_collection(self, subcollection: '_Collection') -> None:
        """Make <subcollection> a child of this collection."""

        self.get_backend().execute('''UPDATE collection
                SET supercollection = ?
                WHERE id = ?''', (self.id, subcollection.id))
        subcollection.supercollection = self.id


class _DefaultCollection(_Collection):
    """The library as a whole, in the shape of a collection.

    It has no row of its own and so no id, and its queries go over the
    book table rather than over the contain table, which is what makes
    it show a book that is filed nowhere as readily as one that is.
    """

    def __init__(self) -> None:

        self.id = None
        self.name = _("All books")
        self.supercollection = None

    def get_books(self, filter_string: str | None = None) -> list['_Book']:
        """Every book in the library, or the ones whose name or path
        <filter_string> occurs in."""
        sql = '''SELECT book.id, book.name, book.path, book.pages, book.format,
                        book.size, book.added
                 FROM book
              '''

        sql_args = []
        if filter_string:
            sql += ''' WHERE book.name LIKE '%' || ? || '%' '''
            sql_args.append(filter_string)
            sql += ''' OR book.path LIKE '%' || ? || '%' '''
            sql_args.append(filter_string)

        rows = self.get_backend().fetchall(sql, sql_args)

        return [_Book(*cols) for cols in rows]

    def add_collection(self, subcollection: '_Collection') -> None:
        """Move <subcollection> to the root of the tree, out of whatever
        collection it was under."""

        assert subcollection is not DefaultCollection, "Cannot change DefaultCollection"

        self.get_backend().execute('''UPDATE collection
                SET supercollection = NULL
                WHERE id = ?''', (subcollection.id,))
        subcollection.supercollection = None

    def get_collections(self) -> list['_Collection']:
        """ Returns a list of all root collections. """

        result = self.get_backend().fetchall('''SELECT id, name, supercollection
                FROM collection
                WHERE supercollection IS NULL
                ORDER by name''')

        return [_Collection(*row) for row in result]


DefaultCollection = _DefaultCollection()


class _WatchList:
    """The directories the library watches for new books.

    The backend holds one of these as its watchlist attribute.  It only
    reports what it finds, through new_files_found(); adding the books
    is the library window's part.
    """

    def __init__(self, backend: '_LibraryBackend') -> None:
        self.backend = backend

    def add_directory(self, path: str,
                      collection: '_Collection' = DefaultCollection,
                      recursive: bool = False) -> None:
        """Watch <path>, filing what turns up there in <collection>.

        The path is the primary key of the table, so watching a
        directory that is watched already changes nothing, not even the
        collection it was filed under.
        """

        directory = os.path.normpath(os.path.abspath(path))
        sql = """INSERT OR IGNORE INTO watchlist (path, collection, recursive)
                 VALUES (?, ?, ?)"""
        self.backend.execute(sql, [directory, collection.id, recursive])

    def get_watchlist(self) -> list['_WatchListEntry']:
        """Every watched directory.

        A left join because an entry need not name a collection: the
        backend sets the column to NULL when the collection it named is
        removed, and such an entry files what it finds nowhere.
        """

        sql = """SELECT watchlist.path,
                        watchlist.recursive,
                        collection.id, collection.name,
                        collection.supercollection
                 FROM watchlist
                 LEFT JOIN collection ON watchlist.collection = collection.id"""

        entries = [self._result_row_to_watchlist_entry(row)
                   for row in self.backend.fetchall(sql)]

        return entries

    def get_watchlist_entry(self, path: str) -> '_WatchListEntry':
        """The entry watching <path>, matched as add_directory() stored
        it, which is to say absolute.

        Raises ValueError if the directory is not watched.
        """
        sql = """SELECT watchlist.path,
                        watchlist.recursive,
                        collection.id, collection.name,
                        collection.supercollection
                 FROM watchlist
                 LEFT JOIN collection ON watchlist.collection = collection.id
                 WHERE watchlist.path = ?"""

        directory = os.path.normpath(os.path.abspath(path))
        result = self.backend.fetchone(sql, (directory, ))

        if result:
            return self._result_row_to_watchlist_entry(result)
        else:
            raise ValueError("Watchlist entry doesn't exist")

    def scan_for_new_files(self) -> None:
        """Start looking for new files in the watched directories.

        The scan runs in a thread of its own and this returns at once.
        Each watched directory is reported through new_files_found()
        when it has been walked, and scan_finished() says when the last
        of them has been.
        """
        thread = threading.Thread(target=self._scan_for_new_files_thread)
        thread.name += '-scan_for_new_files'
        thread.start()

    def _scan_for_new_files_thread(self) -> None:
        """The body of the scan thread."""
        try:
            # A book that is in no collection but "Recent" is in the
            # library only because it was read once, so it still counts
            # as new: the scan will add it to the collection the
            # directory is watched for.
            existing_books = self.backend.get_paths_of_books_outside_recent()
            for entry in self.get_watchlist():
                new_files = entry.get_new_files(existing_books)
                self.new_files_found(new_files, entry)
        except Exception as error:
            # Nothing joins this thread to take an exception from it, so
            # it is logged, as the other threads' failures are.
            log.error(_('! Could not scan for new books: %s'), error)
            log.debug('Traceback:\n%s', traceback.format_exc())
        finally:
            # Whatever went wrong walking a directory, the scan is over
            # and whoever is showing that it is running has to be told.
            self.scan_finished()

    def _result_row_to_watchlist_entry(  # type: ignore[explicit-any]  # a row holds whatever the query selected
            self, row: Sequence[Any]) -> '_WatchListEntry':
        """Build an entry from a row of path, recursive flag, and the
        three columns of the collection joined to it.

        A row whose collection is NULL is an entry that files what it
        finds in no collection, which is what the default collection
        amounts to here: it has no id to file anything under.
        """
        collection_id = row[2]
        if collection_id:
            collection = _Collection(*row[2:])
        else:
            collection = DefaultCollection

        return _WatchListEntry(row[0], row[1], collection)

    @callback.Callback
    def new_files_found(self, paths: Sequence[str],
                        watchentry: '_WatchListEntry') -> None:
        """Called with the files a scan of <watchentry> turned up.

        <paths> may be empty, since a watched directory is reported on
        whether it held anything new or not.  The body does nothing: the
        point of the call is the listeners the Callback decorator runs
        afterwards, in the main thread rather than in the scan thread
        this is called from.
        """
        pass

    @callback.Callback
    def scan_finished(self) -> None:
        """Called when the last watched directory has been walked.

        The listeners run in the main thread, after those of every
        new_files_found() the scan made: both are handed to the main
        thread through the same idle queue, which keeps them in the
        order they were called in.  The body does nothing, for the same
        reason new_files_found()'s does.
        """
        pass


class _WatchListEntry(_BackendObject):
    """ A watched directory. """

    def __init__(self, directory: str, recursive: bool,
                 collection: '_Collection') -> None:
        self.directory = os.path.normpath(os.path.abspath(directory))
        self.recursive = bool(recursive)
        #: Emptied by remove(), which leaves the entry describing nothing.
        self.collection: '_Collection | None' = collection

    def get_new_files(self, filelist: Sequence[str]) -> list[str]:
        """The archives in the watched directory that are not in
        <filelist>.

        A directory that has gone away holds nothing new, rather than
        being an error.
        """

        if not self.is_valid():
            return []

        old_files = frozenset(os.path.abspath(path) for path in filelist)

        if not self.recursive:
            available_files = frozenset(os.path.join(self.directory, filename)
                                        for filename in os.listdir(self.directory)
                                        if archive_tools.is_archive_file(filename))
        else:
            # A list of its own rather than the name the branch above
            # binds to a frozenset: one of the two would have to answer
            # to append(), and a frozenset does not.
            found = []
            for dirpath, dirnames, filenames in os.walk(self.directory):
                for filename in filter(archive_tools.is_archive_file, filenames):
                    found.append(os.path.join(dirpath, filename))

            available_files = frozenset(found)

        return list(available_files.difference(old_files))

    def is_valid(self) -> bool:
        """ Check if the watched directory is a valid directory and exists. """
        return os.path.isdir(self.directory)

    def remove(self) -> None:
        """ Removes this entry from the watchlist, deleting its associated
        path from the database. """
        sql = """DELETE FROM watchlist WHERE path = ?"""
        self.get_backend().execute(sql, (self.directory,))

        self.directory = ""
        self.collection = None

    def set_collection(self, new_collection: '_Collection') -> None:
        """ Updates the collection associated with this watchlist entry. """
        if new_collection != self.collection:
            sql = """UPDATE watchlist SET collection = ? WHERE path = ?"""
            self.get_backend().execute(sql, (new_collection.id, self.directory))
            self.collection = new_collection

    def set_recursive(self, recursive: bool) -> None:
        """ Enables or disables recursive scanning. """
        if recursive != self.recursive:
            sql = """UPDATE watchlist SET recursive = ? WHERE path = ?"""
            self.get_backend().execute(sql, (recursive, self.directory))
            self.recursive = recursive


# vim: expandtab:sw=4:ts=4
