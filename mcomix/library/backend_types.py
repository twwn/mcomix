""" Data class for library books and collections. """

import os
import threading
import datetime

from mcomix import callback
from mcomix import archive_tools
from mcomix.i18n import _

from collections.abc import Sequence
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library.backend import _LibraryBackend


class _BackendObject(object):

    def get_backend(self) -> '_LibraryBackend':
        # XXX: Delayed import to avoid circular import
        from mcomix.library.backend import LibraryBackend
        return LibraryBackend()


class _Book(_BackendObject):
    """ Library book instance. """

    def __init__(self, id: int, name: str, path: str, pages: int,
                 format: int, size: int, added: str) -> None:
        """ Creates a book instance.
        @param id: Book id
        @param name: Base name of the book
        @param path: Full path to the book
        @param pages: Number of pages
        @param format: One of the archive formats in L{constants}
        @param size: File size in bytes
        @param added: Datetime when book was added to library """

        self.id = id
        self.name = name
        self.path = path
        self.pages = pages
        self.format = format
        self.size = size
        self.added = added

    def get_collections(self) -> list['_Collection']:
        """ Gets a list of collections this book is part of. If it
        belongs to no collections, [DefaultCollection] is returned. """
        cursor = self.get_backend().execute(
            '''SELECT id, name, supercollection FROM collection
               JOIN contain on contain.collection = collection.id
               WHERE contain.book = ?''', (self.id,))
        rows = cursor.fetchall()
        if rows:
            return [_Collection(*row) for row in rows]
        else:
            return [DefaultCollection]

    def get_last_read_page(self) -> int | None:
        """ Gets the page of this book that was last read when the book was
        closed. Returns C{None} if no such page exists. """
        cursor = self.get_backend().execute(
            '''SELECT page FROM recent WHERE book = ?''', (self.id,))
        # The connection's row factory unwraps a one column row, so this
        # is the page itself rather than a row holding it.
        row = cursor.fetchone()
        cursor.close()
        if row is None:
            return None
        return int(row)

    def get_last_read_date(self) -> datetime.datetime | None:
        """ Gets the datetime the book was most recently read. Returns
        C{None} if no information was set, or a datetime object otherwise. """
        cursor = self.get_backend().execute(
            """SELECT time_set FROM recent WHERE book = ?""", (self.id,))
        date = cursor.fetchone()
        cursor.close()

        if date:
            try:
                return datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                # Certain operating systems do not store fractions
                return datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        else:
            return None

    def set_last_read_page(self, page: int | None,
                           time: datetime.datetime | None = None) -> None:
        """ Sets the page that was last read when the book was closed.
        Passing C{None} as argument clears the recent information.

        @param page: Page number, starting from 1 (page 1 throws ValueError)
        @param time: Time of reading. If None, current time is used. """

        if page is not None and page < 1:
            # Avoid wasting memory by creating a recently viewed entry when
            # an archive was opened on page 1.
            raise ValueError('Invalid page (must start from 1)')

        # Remove any old recent row for this book
        cursor = self.get_backend().execute(
            '''DELETE FROM recent WHERE book = ?''', (self.id,))
        # If a new page was passed, set it as recently read
        if page is not None:
            if not time:
                time = datetime.datetime.now()
            # sqlite3's implicit datetime adapter is deprecated since
            # Python 3.12; write the same text it used to produce, which
            # is what get_last_read_date() reads back.
            written = time.isoformat(sep=' ') \
                if isinstance(time, datetime.datetime) else time
            cursor.execute('''INSERT INTO recent (book, page, time_set)
                              VALUES (?, ?, ?)''',
                           (self.id, page, written))

        cursor.close()


class _Collection(_BackendObject):
    """ Library collection instance.
    This class should NOT be instianted directly, but only with methods from
    L{LibraryBackend} instead. """

    def __init__(self, id: int, name: str,
                 supercollection: 'int | None' = None) -> None:
        """ Creates a collection instance.
        @param id: Collection id
        @param name: Name of the collection
        @param supercollection: Parent collection, or C{None} """

        #: The default collection stands for every book and has no row of
        #: its own, so it carries no id.
        self.id: int | None = id
        self.name = name
        self.supercollection = supercollection

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _Collection):
            return self.id == other.id
        elif isinstance(other, int):
            return self.id == other
        else:
            return False

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

        cursor = self.get_backend().execute(sql, sql_args)
        rows = cursor.fetchall()
        cursor.close()

        return [ _Book(*cols) for cols in rows ]

    def get_collections(self) -> list['_Collection']:
        """ Returns a list of all direct subcollections of this instance. """

        cursor = self.get_backend().execute('''SELECT id, name, supercollection
                FROM collection
                WHERE supercollection = ?
                ORDER by name''', [self.id])
        result = cursor.fetchall()
        cursor.close()

        return [ _Collection(*row) for row in result ]

    def get_all_collections(self) -> list['_Collection']:
        """ Returns all collections that are subcollections of this instance,
        or subcollections of a subcollection of this instance. """

        to_search = [ self ]
        collections = [ ]
        # This assumes that the library is built like a tree, so no circular references.
        while len(to_search) > 0:
            collection = to_search.pop()
            subcollections = collection.get_collections()
            collections.extend(subcollections)
            to_search.extend(subcollections)

        return collections

    def add_collection(self, subcollection: '_Collection') -> None:
        """ Sets C{subcollection} as child of this collection. """

        self.get_backend().execute('''UPDATE collection
                SET supercollection = ?
                WHERE id = ?''', (self.id, subcollection.id))
        subcollection.supercollection = self.id


class _DefaultCollection(_Collection):
    """ Represents the default collection that books belong to if
    no explicit collection was specified. """

    def __init__(self) -> None:

        self.id = None
        self.name = _("All books")
        self.supercollection = None

    def get_books(self, filter_string: str | None = None) -> list['_Book']:
        """ Returns all books in the library """
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

        cursor = self.get_backend().execute(sql, sql_args)
        rows = cursor.fetchall()
        cursor.close()

        return [ _Book(*cols) for cols in rows ]

    def add_collection(self, subcollection: '_Collection') -> None:
        """ Removes C{subcollection} from any supercollections and moves
        it to the root level of the tree. """

        assert subcollection is not DefaultCollection, "Cannot change DefaultCollection"

        self.get_backend().execute('''UPDATE collection
                SET supercollection = NULL
                WHERE id = ?''', (subcollection.id,))
        subcollection.supercollection = None

    def get_collections(self) -> list['_Collection']:
        """ Returns a list of all root collections. """

        cursor = self.get_backend().execute('''SELECT id, name, supercollection
                FROM collection
                WHERE supercollection IS NULL
                ORDER by name''')
        result = cursor.fetchall()
        cursor.close()

        return [ _Collection(*row) for row in result ]


DefaultCollection = _DefaultCollection()


class _WatchList(object):
    """ Scans watched directories and updates the database when new books have
    been added. This object is part of the library backend, i.e.
    C{library.backend.watchlist}. """

    def __init__(self, backend: '_LibraryBackend') -> None:
        self.backend = backend

    def add_directory(self, path: str,
                      collection: '_Collection' = DefaultCollection,
                      recursive: bool = False) -> None:
        """ Adds a new watched directory. """

        directory = os.path.normpath(os.path.abspath(path))
        sql = """INSERT OR IGNORE INTO watchlist (path, collection, recursive)
                 VALUES (?, ?, ?)"""
        cursor = self.backend.execute(sql, [directory, collection.id, recursive])
        cursor.close()

    def get_watchlist(self) -> list['_WatchListEntry']:
        """ Returns a list of watched directories.
        @return: List of L{_WatchListEntry} objects. """

        sql = """SELECT watchlist.path,
                        watchlist.recursive,
                        collection.id, collection.name,
                        collection.supercollection
                 FROM watchlist
                 LEFT JOIN collection ON watchlist.collection = collection.id"""

        cursor = self.backend.execute(sql)
        entries = [self._result_row_to_watchlist_entry(row) for row in cursor.fetchall()]
        cursor.close()

        return entries

    def get_watchlist_entry(self, path: str) -> '_WatchListEntry':
        """ Returns a single watchlist entry, specified by C{path} """
        sql = """SELECT watchlist.path,
                        watchlist.recursive,
                        collection.id, collection.name,
                        collection.supercollection
                 FROM watchlist
                 LEFT JOIN collection ON watchlist.collection = collection.id
                 WHERE watchlist.path = ?"""

        cursor = self.backend.execute(sql, (os.path.normpath(path), ))
        result = cursor.fetchone()
        cursor.close()

        if result:
            return self._result_row_to_watchlist_entry(result)
        else:
            raise ValueError("Watchlist entry doesn't exist")

    def scan_for_new_files(self) -> None:
        """ Begins scanning for new files in the watched directories.
        When the scan finishes, L{new_files_found} will be called
        asynchronously. """
        thread = threading.Thread(target=self._scan_for_new_files_thread)
        thread.name += '-scan_for_new_files'
        thread.start()

    def _scan_for_new_files_thread(self) -> None:
        """ Executes the actual scanning operation in a new thread. """
        existing_books = [book.path for book in DefaultCollection.get_books()
                          # Also add book if it was only found in Recent collection
                          if book.get_collections() != [-2]]
        for entry in self.get_watchlist():
            new_files = entry.get_new_files(existing_books)
            self.new_files_found(new_files, entry)

    def _result_row_to_watchlist_entry(  # type: ignore[explicit-any]  # a row holds whatever the query selected
            self, row: Sequence[Any]) -> '_WatchListEntry':
        """ Converts the result of a SELECT statement to a WatchListEntry. """
        collection_id = row[2]
        if collection_id:
            collection = _Collection(*row[2:])
        else:
            collection = DefaultCollection

        return _WatchListEntry(row[0], row[1], collection)


    @callback.Callback
    def new_files_found(self, paths: Sequence[str],
                        watchentry: '_WatchListEntry') -> None:
        """ Called after scan_for_new_files finishes.
        @param paths: List of filenames for newly added files. This list
                      may be empty if no new files were found during the scan.
        @param watchentry: Watchentry for files/directory.
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
        """ Returns a list of files that are present in the watched directory,
        but not in the list of files passed in C{filelist}. """

        if not self.is_valid():
            return []

        old_files = frozenset([os.path.abspath(path) for path in filelist])

        if not self.recursive:
            available_files = frozenset([os.path.join(self.directory, filename)
                for filename in os.listdir(self.directory)
                if archive_tools.is_archive_file(filename)])
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
        cursor = self.get_backend().execute(sql, (self.directory,))
        cursor.close()

        self.directory = ""
        self.collection = None

    def set_collection(self, new_collection: '_Collection') -> None:
        """ Updates the collection associated with this watchlist entry. """
        if new_collection != self.collection:
            sql = """UPDATE watchlist SET collection = ? WHERE path = ?"""
            cursor = self.get_backend().execute(sql,
                    (new_collection.id, self.directory))
            cursor.close()
            self.collection = new_collection

    def set_recursive(self, recursive: bool) -> None:
        """ Enables or disables recursive scanning. """
        if recursive != self.recursive:
            sql = """UPDATE watchlist SET recursive = ? WHERE path = ?"""
            cursor = self.get_backend().execute(sql,
                    (recursive, self.directory))
            cursor.close()
            self.recursive = recursive


# vim: expandtab:sw=4:ts=4
