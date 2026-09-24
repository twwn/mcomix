"""backend.py - The comic book library, as a sqlite database.

One connection, in auto-commit mode, to a file holding a table of books,
a table of collections, the contain table that files one in the other,
the recent table of where a book was left, and a watchlist of
directories to look in for more.  A book's id is its sqlite rowid, which
sqlite hands out again as soon as the highest row is free.

The schema is versioned: DB_VERSION below is what this code expects, and
_upgrade_database() brings an older file up to it a version at a time.
"""

import contextlib
import os
import threading

from collections.abc import Iterator, Sequence
from typing import Any, TYPE_CHECKING

from mcomix import archive_tools
from mcomix.archive import password as archive_password
from mcomix import constants
from mcomix import thumbnail_tools
from mcomix import log
from mcomix import callback
from mcomix.library import backend_types
from mcomix import i18n
from mcomix.i18n import _
# Only for importing legacy data from last-read module
from mcomix import last_read_page

from sqlite3 import dbapi2

if TYPE_CHECKING:
    from gi.repository import GdkPixbuf


def storable(path: str) -> bool:
    """Whether the library can hold a book at <path>.

    Paths are SQLite text, which is UTF-8, and a name on disk need not
    be: Python hands one that is not over with lone surrogates, which
    SQLite's binding refuses with UnicodeEncodeError.  Such a book is
    read like any other; it is only not in the library, and so has no
    last read page kept for it either.
    """
    try:
        path.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


class _LibraryBackend:

    """The library database, and the statements run against it.

    There is one of these, handed out by LibraryBackend() at the foot of
    this module.  The types in backend_types reach it that way rather
    than being handed it, which is how a book fetched from the library
    can go on asking the library questions.
    """

    #: Current version of the library database structure.
    # See method _upgrade_database() for changes between versions.
    DB_VERSION = 10

    def __init__(self) -> None:

        def row_factory(cursor: dbapi2.Cursor, row: tuple[Any, ...]) -> Any:  # type: ignore[explicit-any]  # a row holds whatever the query selected
            """Return rows as sequences only when they have more than
            one element.
            """
            if len(row) == 1:
                return row[0]
            return row

        self._con = dbapi2.connect(constants.LIBRARY_DATABASE_PATH,
                                   check_same_thread=False, isolation_level=None)
        self._con.row_factory = row_factory
        #: Held from running a statement to closing its cursor.  Threads
        #: other than the main one read the library through this same
        #: connection - the cover workers ask each book for the page it
        #: was left on, and the watch list scan reads the paths of the
        #: books - and sqlite3 caches prepared statements per connection,
        #: so two threads running one statement at once could step the
        #: same prepared one between them: that raised "bad parameter or
        #: other API misuse", or answered None for a row that was there.
        #: Everything below goes through execute(), fetchone(), fetchall()
        #: or the transaction methods, which take it.  Only the schema
        #: code run from here reaches the connection directly, since no
        #: other thread can hold a backend that LibraryBackend() has not
        #: handed out yet.
        self._lock = threading.Lock()

        self.watchlist = backend_types._WatchList(self)

        version = self._library_version()
        self._upgrade_database(version, _LibraryBackend.DB_VERSION)

    def get_books_in_collection(self, collection: int | None = None) -> list[int]:
        """Return a sequence with all the books in <collection>, or *ALL*
        books if <collection> is None.
        """
        return self._books_in_collection('id', collection)

    def get_book_paths_in_collection(
            self, collection: int | None = None) -> "list[tuple[int, str]]":
        """The id and path of every book in <collection>, or of every
        book in the library if <collection> is None.

        For a caller that wants both and would otherwise ask for the ids
        and then look each path up on its own, which is one statement
        per book.
        """
        return self._books_in_collection('id, path', collection)

    def _books_in_collection(self, columns: str,  # type: ignore[explicit-any]  # the rows hold whichever columns were asked for
                             collection: int | None = None) -> list[Any]:
        """<columns> of the book table, for the books in <collection>.

        The connection's row factory unwraps a row of one column, so a
        single column comes back as a list of values and several as a
        list of tuples.
        """
        if collection is None:
            return self.fetchall('select %s from Book' % columns)
        # One statement over the collection and everything under it,
        # rather than one each with the answers added together, which
        # named a book filed in both a collection and one under it once
        # for each.  clean_collection() survived that - its second
        # removal finds no path and does nothing - at the cost of
        # looking the book up again, and any other caller would act on
        # it twice.
        collections = [collection] + \
            self.get_all_collections_in_collection(collection)
        sql = '''select %s from Book
            where id in (select book from Contain
                         where collection in (%s))''' \
            % (columns, ', '.join('?' * len(collections)))
        return self.fetchall(sql + ' order by id', list(collections))

    def get_book_by_path(self, path: str) -> backend_types._Book | None:
        """Return the book at <path>, or None if the library has no
        book there.

        The path is made absolute first: that is the form add_book()
        stores, and the column it is looked up in is unique.
        """

        path = os.path.abspath(path)
        if not storable(path):
            return None

        book = self.fetchone('''select id, name, path, pages, format,
                                       size, added
                                from book where path = ?''', (path,))

        if book:
            return backend_types._Book(*book)
        else:
            return None

    def get_book_by_id(self, id: int) -> backend_types._Book | None:
        """Return the book with <id>, or None if the library has no
        such book."""

        book = self.fetchone('''select id, name, path, pages, format,
                                       size, added
                                from book where id = ?''', (id,))

        if book:
            return backend_types._Book(*book)
        else:
            return None

    def get_book_cover(self, book: int) -> "GdkPixbuf.Pixbuf | None":
        """Return a pixbuf with a thumbnail of the cover of <book>, or
        None if the cover can not be fetched.

        A book that is not in the library has no cover to fetch, which
        is one of the ways this answers None rather than an error.
        """
        path = self.get_book_path(book)
        if path is None:
            return None

        return self.get_book_thumbnail(path)

    def get_book_path(self, book: int) -> str | None:
        """Return the filesystem path to <book>, or None if <book> isn't
        in the library.
        """
        path: str | None = self.fetchone('''select path from Book
            where id = ?''', (book,))

        if path is None:
            log.error(_('! Non-existent book #%i'), book)

        return path

    def get_paths_of_books_outside_recent(self) -> list[str]:
        """The path of every book that is in the library for a reason
        other than having been read once.

        A book filed nowhere but in "Recent" got there by being opened,
        not by being collected, so the watch list scan counts it as new
        and files it properly when it turns up again.  Asked as one
        statement because the alternative is a query per book: at 40,000
        books the scan spent 173.6ms working this out a collection list
        at a time, against 31.3ms here.
        """
        paths: list[str] = self.fetchall('''select path from Book
            where id not in (select book from Contain
                             group by book
                             having count(*) = 1
                                and min(collection) = ?)''',
                                         (constants.COLLECTION_RECENT,))
        return paths

    def get_book_thumbnail(self, path: str) -> "GdkPixbuf.Pixbuf | None":
        """ Returns a pixbuf with a thumbnail of the cover of the book at <path>,
        or None, if no thumbnail could be generated. """

        # Use the maximum image size allowed by the library, so that thumbnails
        # might be downscaled, but never need to be upscaled (and look ugly).
        thumbnailer = thumbnail_tools.Thumbnailer(dst_dir=constants.LIBRARY_COVERS_PATH,
                                                  store_on_disk=True,
                                                  archive_support=True,
                                                  size=(constants.MAX_LIBRARY_COVER_SIZE,
                                                        constants.MAX_LIBRARY_COVER_SIZE),
                                                  cover_orientation_required=True)
        thumb = thumbnailer.thumbnail(path)

        if thumb is None:
            log.warning(_('! Could not get cover for book "%s"'), path)
        return thumb

    def get_all_collections_in_collection(self, collection: int) -> list[int]:
        """Return every collection under <collection>, including the
        ones under those, in no particular order.

        Walked by the database rather than here: the tree cost a query
        for every node in it, which over a library of 340 collections
        was 85 statements and 1.00ms for a subtree of 84, against one
        statement and 0.09ms.  SQLite builds itself a covering index on
        supercollection for the recursive step, so only the anchor reads
        the table through.  The recursion ends because a collection is
        only ever put under one the library already holds, so the
        supercollection edges cannot make a cycle.

        A <collection> of None means the whole library elsewhere in this
        class; here it is not a collection at all and raises ValueError.
        """

        if collection is None:
            raise ValueError("Collection must not be <None>")

        return self.fetchall('''with recursive subtree(id) as (
                select id from Collection where supercollection = ?
                union all
                select Collection.id from Collection
                    join subtree on Collection.supercollection = subtree.id)
            select id from subtree''', (collection,))

    def get_collection_tree(self) -> dict[int | None, list[tuple[int, str]]]:
        """Every collection in the library, as the id and name of each
        one grouped by the collection it sits under.

        The collections at the root are under None.  Each group is in
        the order the sidebar draws it, which is by name with "Recent"
        under its translation rather than under the RECENT the row
        holds.

        The sidebar built its tree by asking for the collections under
        each one it had found and then for the name of each of those, so
        drawing it cost two statements per collection and one per
        parent - 683 over a library of 340 collections, against one
        here.
        """
        recent = (constants.COLLECTION_RECENT, _('Recent'))
        rows = self.fetchall('''select supercollection, id,
                case when id = ? then ? else name end
            from Collection
            order by case when id = ? then ? else name end''',
                             recent + recent)
        tree: dict[int | None, list[tuple[int, str]]] = {}
        for supercollection, id, name in rows:
            tree.setdefault(supercollection, []).append((id, name))
        return tree

    def get_all_collections(self) -> list[int]:
        """Return a sequence with all collections (flattened hierarchy).

        Sorted alphabetically by collection name, with "Recent" under
        its translated name rather than under the RECENT it is stored
        as.
        """
        return self.fetchall('''select id from Collection
            order by case when id = ? then ? else name end''',
                             (constants.COLLECTION_RECENT, _('Recent')))

    def get_collection_name(self, collection: int | None) -> str | None:
        """Return the name field of the <collection>, or None if the
        collection does not exist.  No collection has None for an id, so
        that is one of the ways of not existing.

        "Recent" is stored under the untranslated name RECENT and comes
        back translated, which is what the case expression is for.
        """
        name: str | None = self.fetchone('''select case when id = ? then ? else name end from Collection
            where id = ?''', (constants.COLLECTION_RECENT, _('Recent'), collection,))
        return name

    def get_collection_by_name(self, name: str) -> backend_types._Collection | None:
        """Return the collection called <name>, or None if no such
        collection exists. Names are unique, so at most one such collection
        can exist.
        """
        result = self.fetchone('''select id, name, supercollection
            from collection
            where name = ?''', (name,))
        if result:
            return backend_types._Collection(*result)
        else:
            return None

    def get_collection_by_id(self, id: int) -> backend_types._Collection | None:
        """Return the collection with <id>, or None if there is none.

        Two ids are answered without asking the database.  None and
        COLLECTION_ALL are both the default collection, which stands for
        the whole library and has no row of its own; COLLECTION_RECENT
        has a row, but it holds the untranslated name RECENT, so the
        collection is built here with the translation instead.
        """
        if id is None or id == constants.COLLECTION_ALL:
            return backend_types.DefaultCollection
        elif id == constants.COLLECTION_RECENT:
            return backend_types._Collection(constants.COLLECTION_RECENT, _('Recent'))
        else:
            result = self.fetchone('''select id, name, supercollection
                from collection
                where id = ?''', (id,))

            if result:
                return backend_types._Collection(*result)
            else:
                return None

    def get_recent_collection(self) -> backend_types._Collection:
        """The "Recent" collection, which a book is filed in when it is
        read.

        Never None: get_collection_by_id() builds this one rather than
        looking it up, and the assertion is what says so to the type
        checker.
        """
        collection = self.get_collection_by_id(constants.COLLECTION_RECENT)
        assert collection is not None
        return collection

    def get_supercollection(self, collection: int) -> int | None:
        """Return the supercollection of <collection>."""
        supercollection: int | None = self.fetchone('''select supercollection from Collection
            where id = ?''', (collection,))
        return supercollection

    def collection_is_within(self, collection: int,
                             ancestor: int | None) -> bool:
        """Whether <collection> is <ancestor> or one of the collections
        under it, at any depth.  "All books", the ancestor None or
        COLLECTION_ALL, holds every collection there is."""
        if ancestor is None or ancestor == constants.COLLECTION_ALL:
            return True
        seen: set[int] = set()
        walk: int | None = collection
        while walk is not None and walk not in seen:
            if walk == ancestor:
                return True
            seen.add(walk)
            walk = self.get_supercollection(walk)
        return False

    def add_book(self, path: str, collection: int | None = None) -> bool:
        """Add the archive at <path> to the library. If <collection> is
        not None, it is the collection that the books should be put in.
        Return True if the book was successfully added (or was already
        added).
        """
        path = os.path.abspath(path)
        if not storable(path):
            log.warning('Not adding "%s" to the library: its name is not '
                        'UTF-8, which is what the library stores',
                        i18n.to_display_string(path))
            return False
        name = os.path.basename(path)
        # The library lists what it is given, and what a watched
        # directory holds, on the reader's behalf: an encrypted archive
        # is not asked the password of.  One whose very listing is
        # encrypted is still a book, of pages not yet known.
        with archive_password.never_asked() as withheld:
            try:
                info = archive_tools.get_archive_info(path)
            except Exception:
                # A handler that gives up on no password may say so by
                # raising, as libunrar does over an encrypted listing.
                if not withheld.wanted:
                    raise
                info = None
        if info is None and withheld.wanted:
            mime = archive_tools.archive_mime_type(path)
            if mime is not None:
                info = (mime, 0, os.stat(path).st_size)
        if info is None:
            return False
        format, pages, size = info

        # Thumbnail for the newly added book will be generated once it
        # is actually needed with get_book_thumbnail().
        # The date the book was added comes back with the id, so that a
        # book that is in the library already can be described to the
        # collection listeners without being read a second time.
        old = self.fetchone('''select id, added from Book
            where path = ?''', (path,))
        try:
            if old is not None:
                self.execute('''update Book set
                    name = ?, pages = ?, format = ?, size = ?
                    where path = ?''', (name, pages, format, size, path))
                book_id, added = old
                book = backend_types._Book(book_id, name, path, pages,
                                           format, size, added)
            else:
                # The date the row is stamped with comes back with the
                # id it was given.  Reporting datetime.now() instead put
                # a local time in ISO format where the column holds UTC
                # in sqlite's, so the library sorted a book by "Date
                # added" against a date no other book had.
                book_id, added = self.fetchone('''insert into Book
                    (name, path, pages, format, size)
                    values (?, ?, ?, ?, ?)
                    returning id, added''', (name, path, pages, format, size))
                book = backend_types._Book(book_id, name, path, pages,
                                           format, size, added)
                self.book_added(book)

            if collection is not None:
                self._file_book(book_id, collection, book)

            return True
        except dbapi2.Error:
            log.error(_('! Could not add book "%s" to the library'), path)
            return False

    def update_book_path(self, old_path: str, new_path: str) -> bool:
        """Follow the book at <old_path>, which is now at <new_path>.

        The library stores a book by its path, so a book MComix has
        moved itself would otherwise be left pointing at a file that is
        not there any more.  Its thumbnail, its collections and where it
        was last read all hang off the row's id, so all of them come
        with it.

        Returns whether a row was moved: False if the book was not in
        the library, and False if a row holds <new_path> already - the
        path column is unique, and a stale row there is not this book's
        to throw away.
        """
        old_path = os.path.abspath(old_path)
        new_path = os.path.abspath(new_path)
        if not (storable(old_path) and storable(new_path)):
            # Not in the library, or a name it cannot hold: the row
            # stays where it was, for "Clean up" to find gone.
            return False
        try:
            changed = self.execute('''update Book set path = ?, name = ?
                where path = ?''', (new_path, os.path.basename(new_path),
                                    old_path))
            return changed > 0
        except dbapi2.Error:
            log.error(_('! Could not move book "%s" in the library'), old_path)
            return False

    @callback.Callback
    def book_added(self, book: backend_types._Book) -> None:
        """Called when add_book() has put a book in the library that was
        not there before.

        Re-adding a book that is there already updates its row and says
        nothing.  The body does nothing either: the point of the call is
        the listeners the Callback decorator runs afterwards.
        """
        pass

    @callback.Callback
    def book_added_to_collection(self, book: backend_types._Book, collection_id: int) -> None:
        """Called when a book has been filed in a collection.

        Only for a book that is really there: add_book_to_collection()
        will file an id that names no row, and stays quiet when it does.
        Like book_added(), the body is empty and the listeners are the
        point.
        """
        pass

    def add_collection(self, name: str) -> int | None:
        """Add a new collection called <name>, and return its id.

        None if it could not be added, which a name that is taken is
        the usual reason for: the name column is unique.
        """
        try:
            # The Recent pseudo collection initializes the lowest rowid
            # with -2, meaning that instead of starting from 1,
            # auto-incremental will start from -1. Avoid this.
            maxid = self.fetchone('''select max(id) from collection''')
            if maxid is not None and maxid < 1:
                collection: int = self.fetchone('''insert into collection
                    (id, name) values (?, ?) returning id''', (1, name))
            else:
                collection = self.fetchone('''insert into Collection
                    (name) values (?) returning id''', (name,))
            return collection
        except dbapi2.Error:
            log.error(_('! Could not add collection "%s"'), name)
        return None

    def add_book_to_collection(self, book: int, collection: int) -> None:
        """Put the book with id <book> into <collection>.

        The listeners take the book itself, so a caller with nothing but
        the id pays for a read of the row; add_book() has just built the
        book and hands it over instead.
        """
        self._file_book(book, collection, None)

    def _file_book(self, book: int, collection: int,
                   added: backend_types._Book | None) -> None:
        """Put the book with id <book> into <collection>, and tell the
        listeners about it.

        <added> is that book where the caller already holds it, and None
        where the row has to be read back to find out what it says.
        """
        try:
            self.execute('''insert into Contain
                (collection, book) values (?, ?)''', (collection, book))
            if added is None:
                added = self.get_book_by_id(book)
            # Contain has no foreign key on book, so an id that names no
            # row inserts happily; the listeners take a book, not a hole.
            if added is not None:
                self.book_added_to_collection(added, collection)
        except dbapi2.DatabaseError:  # E.g. book already in collection.
            pass
        except dbapi2.Error:
            log.error(_('! Could not add book %(book)s to collection %(collection)s'),
                      {"book": book, "collection": collection})

    def add_collection_to_collection(self, subcollection: int, supercollection: int | None) -> None:
        """Put <subcollection> into <supercollection>, or put
        <subcollection> in the root if <supercollection> is None.
        """
        if supercollection is None:
            self.execute('''update Collection
                set supercollection = NULL
                where id = ?''', (subcollection,))
        else:
            self.execute('''update Collection
                set supercollection = ?
                where id = ?''', (supercollection, subcollection))

    def rename_collection(self, collection: int, name: str) -> bool:
        """Rename the <collection> to <name>. Return True if the renaming
        was successful.
        """
        try:
            self.execute('''update Collection set name = ?
                where id = ?''', (name, collection))
            return True
        except dbapi2.DatabaseError:  # E.g. name taken.
            pass
        except dbapi2.Error:
            log.error(_('! Could not rename collection to "%s"'), name)
        return False

    def duplicate_collection(self, collection: int) -> bool:
        """Duplicate <collection> as a new collection beside it, holding
        the books it shows, and say whether that worked.

        A collection shows the books of every collection under it as
        well as its own, so the copy is filed with all of them - flat,
        rather than with copies of the collections under it, whose names
        would all have to change, a name being unique in the library.
        It goes under the collection the original is under, as a file
        manager puts a copy beside the file it was made from.
        """
        name = self.get_collection_name(collection)
        if name is None:  # Original collection does not exist.
            return False
        copy_name = name + ' ' + _('(Copy)')
        while self.get_collection_by_name(copy_name):
            copy_name = copy_name + ' ' + _('(Copy)')
        shown = [collection] + self.get_all_collections_in_collection(
            collection)
        with self.transaction():
            copy = self.add_collection(copy_name)
            if copy is None:  # Could not create the new.
                return False
            supercollection = self.get_supercollection(collection)
            if supercollection is not None:
                self.add_collection_to_collection(copy, supercollection)
            self.execute('''insert or ignore into Contain (collection, book)
                select ?, book from Contain
                where collection in (%s)''' % ','.join('?' * len(shown)),
                         [copy] + shown)
        return True

    def clean_collection(self, collection: int | None = None) -> int:
        """ Removes files from <collection> that no longer exist. If <collection>
        is None, all collections are cleaned. Returns the number of deleted books. """
        # The paths come back with the ids rather than being looked up
        # one at a time, which was a statement per book in the library.
        books = self.get_book_paths_in_collection(collection)
        deleted = 0
        # A sweep of a real library runs the two deletes remove_book()
        # makes thousands of times; take the lot as one transaction.
        with self.transaction():
            for id, path in books:
                if path and not os.path.isfile(path):
                    self.remove_book(id)
                    deleted += 1

        return deleted

    def remove_book(self, book: int) -> None:
        """Remove the <book> from the library."""
        path = self.get_book_path(book)
        if path is not None:
            thumbnailer = thumbnail_tools.Thumbnailer(dst_dir=constants.LIBRARY_COVERS_PATH)
            thumbnailer.delete(path)
        self.execute('delete from Book where id = ?', (book,))
        self.execute('delete from Contain where book = ?', (book,))
        # A book's id is its sqlite rowid, which is handed out again as
        # soon as the highest row is free, so a page left behind here
        # belongs to whichever book is added next.
        self.execute('delete from Recent where book = ?', (book,))

    def remove_collection(self, collection: int) -> None:
        """Remove the <collection> from the library.

        The books in it are not removed, only their membership of it, and
        a collection under it is moved to the root rather than going with
        its parent - so nothing a reader has added to the library is lost
        by removing a shelf it was on.

        All of it is one transaction.  A collection's id is its sqlite
        rowid, which is handed out again as soon as the highest row is
        free, so an interrupted removal that had deleted the Collection
        row but not yet cleared the rows naming it would give the next
        collection created the deleted one's books and children - the
        same hazard the version 8 upgrade step repairs for books.  The
        references go first for the same reason: the row that names the
        collection is the last thing to go, so there is no moment at
        which the rows pointing at it outlive it.
        """
        with self.transaction():
            self.execute('''update watchlist set collection = NULL
                where collection = ?''', (collection,))
            self.execute('delete from Contain where collection = ?',
                         (collection,))
            self.execute('''update Collection set supercollection = NULL
                where supercollection = ?''', (collection,))
            self.execute('delete from Collection where id = ?',
                         (collection,))

    def remove_book_from_collection(self, book: int, collection: int) -> None:
        """Remove <book> from <collection>."""
        self.execute('''delete from Contain
            where book = ? and collection = ?''', (book, collection))

    def execute(self, statement: str,
                parameters: "Sequence[str | int | float | bytes | None]" = ()
                ) -> int:
        """Run <statement>, and return how many rows it changed.

        For a statement whose rows nobody reads; fetchone() and
        fetchall() are for those that answer with some.  All three
        hold the lock from running the statement to closing its cursor,
        so that no cursor outlives the call - see __init__().
        """
        with self._lock:
            cursor = self._con.execute(statement, parameters)
            try:
                return cursor.rowcount
            finally:
                cursor.close()

    def fetchone(self, statement: str,  # type: ignore[explicit-any]  # a row holds whatever the query selected
                 parameters: "Sequence[str | int | float | bytes | None]" = ()
                 ) -> Any:
        """Run <statement>, and return the first row it answers with, or
        None if it answers with none.

        The connection's row factory unwraps a row of one column, so a
        single column comes back as the value itself.
        """
        with self._lock:
            cursor = self._con.execute(statement, parameters)
            try:
                return cursor.fetchone()
            finally:
                cursor.close()

    def fetchall(self, statement: str,  # type: ignore[explicit-any]  # as fetchone()
                 parameters: "Sequence[str | int | float | bytes | None]" = ()
                 ) -> list[Any]:
        """Run <statement>, and return every row it answers with, each
        unwrapped as fetchone() says."""
        with self._lock:
            cursor = self._con.execute(statement, parameters)
            try:
                return cursor.fetchall()
            finally:
                cursor.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Run the statements in the block as one transaction.

        The connection is in auto-commit mode, so without this every
        statement is a transaction of its own - which on a real
        filesystem is a journal write and an fsync each. Any loop that
        writes a row per book wants this around it.

        Nesting does nothing: the outermost block is the transaction.
        The commit happens whether the block raised or not, because
        what was written before an error stays written, which is what
        auto-commit did.
        """
        if self._con.isolation_level is not None:
            # A caller further out is already holding one.
            yield
            return

        self.begin_transaction()
        try:
            yield
        finally:
            self.end_transaction()

    @contextlib.contextmanager
    def _migration(self) -> Iterator[None]:
        """Run one upgrade step as an all-or-nothing transaction.

        The steps that rebuild a table rename the original aside, create
        the new one, copy the rows across and drop the original.  In
        auto-commit mode each of those four commits by itself, so an
        upgrade that stops after the rename leaves a database with no
        book table and a book_old holding every row - and
        _library_version() reads a missing book table as a database that
        is not there yet, answers -1, and has _create_tables() write an
        empty schema over the top.  The library then opens and reports no
        books at all, every one of them still in book_old where nothing
        will ever look again.

        transaction() is deliberately not this, on two counts.  It
        commits whether the block raised or not, because a bulk write
        that stops half way has written what it wrote, which is what
        auto-commit would have done, whereas a schema that stops half way
        is not usable.  And it opens the transaction by setting
        isolation_level, which the sqlite3 module acts on only for
        insert, update, delete and replace: an alter, create or drop runs
        outside the transaction it looks as though it is in, and survives
        the rollback.  Every statement here is one of those, so the BEGIN
        is issued by hand.

        This does not nest, and does not need to - the upgrade runs from
        __init__(), on a connection no caller has yet seen.
        """
        self._con.execute('begin immediate')
        try:
            yield
        except BaseException:
            self._con.rollback()
            raise
        else:
            self._con.commit()

    def begin_transaction(self) -> None:
        """ Normally, the connection is in auto-commit mode. Calling
        this method will switch to transactional mode, automatically
        starting a transaction when a DML statement is used. """
        with self._lock:
            self._con.isolation_level = 'IMMEDIATE'

    def end_transaction(self) -> None:
        """ Commits any changes to the database and switches back
        to auto-commit mode. """
        with self._lock:
            self._con.commit()
            self._con.isolation_level = None

    def close(self) -> None:
        """Commit changes and close the connection.

        The singleton goes with it, so that the next LibraryBackend()
        call opens the database again rather than handing out a closed
        connection.
        """
        with self._lock:
            self._con.commit()
            self._con.close()

        global _backend
        _backend = None

    def _table_exists(self, table: str) -> bool:
        """Whether <table> exists in the database.

        Asked of sqlite_master rather than of "pragma table_info",
        whose argument is part of the statement and so has to be
        pasted into it: a name that is not a bare identifier made that
        a syntax error rather than an answer.
        """
        cursor = self._con.execute("""select 1 from sqlite_master
            where type = 'table' and name = ?""", (table,))
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists

    def _library_version(self) -> int:
        """Which version of the schema the database file holds.

        The version is a row of the info table.  A file without the
        book, collection and contain tables has not been created yet and
        answers -1; one that has them but no info table was written by
        Comix, before the version was recorded, and answers 0.  An info
        table with no version row is a file this cannot place, and
        answers -1 as well, which has the tables created over it - every
        create is "if not exists", so whichever tables are there
        survive, and the version row is written to the current version
        whether or not one was already held.
        """

        # Check if Comix' tables exist
        tables = ('book', 'collection', 'contain')
        for table in tables:
            if not self._table_exists(table):
                return -1

        if self._table_exists('info'):
            cursor = self._con.cursor()
            version = cursor.execute('''select value from info
                where key = 'version' ''').fetchone()
            cursor.close()

            if not version:
                log.warning(_('Could not determine library database version!'))
                return -1
            else:
                return int(version)
        else:
            # Comix database format
            return 0

    def _create_tables(self) -> None:
        """Create the tables a library needs, as one transaction.

        All six or none of them, because the info table is written in the
        middle of the list and is what says the database is complete.  A
        creation that stopped after it left book, collection, contain and
        info behind, which _library_version() reads as a finished version
        9 database - so _upgrade_database() found nothing to do, and the
        library opened every time thereafter with no watchlist and no
        recent table, raising "no such table: watchlist" out of the watch
        list on each attempt and never repairing itself.
        """
        with self._migration():
            self._create_table_book()
            self._create_table_collection()
            self._create_table_contain()
            self._create_table_info()
            self._create_table_watchlist()
            self._create_table_recent()

    def _upgrade_database(self, from_version: int, to_version: int) -> None:
        """Bring the database from <from_version> up to <to_version>.

        Each step is written against the schema the step before it left,
        so they are applied in order and a file of any age arrives at
        the current one.  A <from_version> of -1 is a database that is
        not there yet, and is created at the current version instead of
        being upgraded.

        The version is written last, so an upgrade that stops part way is
        attempted again next time; every step is safe to run twice, which
        is what makes that work.  A step that rebuilds a table is one
        transaction on its own, so a stop inside one leaves the table it
        was rebuilding alone rather than half rebuilt - see _migration().
        """

        if from_version == -1:
            self._create_tables()
            return

        if from_version != to_version:
            upgrades = list(range(from_version, to_version))
            log.info(_("Upgrading library database version from %(from)d to %(to)d."),
                     {"from": from_version, "to": to_version})

            if 0 in upgrades:
                # Upgrade from Comix database structure to DB version 1
                # (Added table 'info')
                self._create_table_info()

            if 1 in upgrades:
                # Upgrade to database structure version 2.
                # (Added table 'watchlist' for storing auto-add directories)
                self._create_table_watchlist()

            if 2 in upgrades:
                # Changed 'added' field in 'book' from date to datetime.
                with self._migration():
                    self._con.execute('''alter table book rename to book_old''')
                    self._create_table_book()
                    self._con.execute('''insert into book
                        (id, name, path, pages, format, size, added)
                        select id, name, path, pages, format, size, datetime(added)
                        from book_old''')
                    self._con.execute('''drop table book_old''')

            if 3 in upgrades:
                # Added field 'recursive' to table 'watchlist'
                with self._migration():
                    self._con.execute('''alter table watchlist rename to watchlist_old''')
                    self._create_table_watchlist()
                    self._con.execute('''insert into watchlist
                        (path, collection, recursive)
                        select path, collection, 0 from watchlist_old''')
                    self._con.execute('''drop table watchlist_old''')

            if 4 in upgrades:
                # Added table 'recent' to store recently viewed book information and
                # create a collection (-2, Recent).
                #
                # Not a _migration(): the migration deletes the legacy
                # lastreadpage.db when it has carried its rows over, and
                # no rollback brings a deleted file back, so a stopped
                # upgrade would lose the pages that were already moved
                # along with the file they came from.  Committing as it
                # goes is safe instead, because the step can be run
                # again: _init_database() recreates the legacy file when
                # it is not there, and the second run finds it empty and
                # moves nothing.
                self._create_table_recent()
                lastread = last_read_page.LastReadPage(self)
                lastread.migrate_database_to_library(constants.COLLECTION_RECENT)

            if 5 in upgrades:
                # Changed all 'string' columns into 'text' columns.  Both
                # rebuilds are one step and so one transaction: a
                # database holding the new book table and the old
                # collection one is a shape no step is written against.
                with self._migration():
                    self._con.execute('''alter table book rename to book_old''')
                    self._create_table_book()
                    self._con.execute('''insert into book
                        (id, name, path, pages, format, size, added)
                        select id, name, path, pages, format, size, added from book_old''')
                    self._con.execute('''drop table book_old''')

                    self._con.execute('''alter table collection rename to collection_old''')
                    self._create_table_collection()
                    self._con.execute('''insert into collection
                        (id, name, supercollection)
                        select id, name, supercollection from collection_old''')
                    self._con.execute('''drop table collection_old''')

            if 6 in upgrades:
                # Non-localized name for Recent collection
                self._con.execute('''update collection set name = ? where id = ?''',
                                  ('RECENT', constants.COLLECTION_RECENT))

            if 7 in upgrades:
                # Added an index on contain (book); see
                # _create_index_contain_book().
                self._create_index_contain_book()

            if 8 in upgrades:
                # remove_book() used to leave the removed book's row in
                # recent behind, and a book's id is its sqlite rowid,
                # which is handed out again as soon as the highest row
                # is free: those rows belong to whichever book was added
                # next.  Nothing tells them apart from a live one after
                # the fact, so every recent row naming a book that is
                # gone goes.  This is a repair rather than a schema
                # change - a database written before it is readable by
                # an MComix that has it, and the other way round - and
                # it costs 1.5ms over 20,000 recent rows.
                self._con.execute('''delete from recent
                    where book not in (select id from book)''')

            if 9 in upgrades:
                # The name within its archive of the page a book was
                # left on, which finds that page wherever a change of
                # sort order has put it.  An older MComix leaves the
                # column alone and writes rows without it, so a file it
                # has opened says version 9 again with the column
                # already there: added only where it is missing.
                columns = [row[1] for row in self._con.execute(
                    '''pragma table_info(recent)''').fetchall()]
                if 'member' not in columns:
                    self._con.execute(
                        '''alter table recent add column member text''')

            self._con.execute('''update info set value = ? where key = 'version' ''',
                              (str(_LibraryBackend.DB_VERSION),))

    def _create_table_book(self) -> None:
        self._con.execute('''create table if not exists book (
            id integer primary key,
            name text,
            path text unique,
            pages integer,
            format integer,
            size integer,
            added datetime default current_timestamp)''')

    def _create_table_collection(self) -> None:
        self._con.execute('''create table if not exists collection (
            id integer primary key,
            name text unique,
            supercollection integer)''')

    def _create_table_contain(self) -> None:
        self._con.execute('''create table if not exists contain (
            collection integer not null,
            book integer not null,
            primary key (collection, book))''')
        self._create_index_contain_book()

    def _create_index_contain_book(self) -> None:
        """Index the second half of contain's primary key.

        That key is (collection, book), which a lookup by book alone
        cannot use, so 'delete from Contain where book = ?' - one of the
        two statements remove_book() runs - scanned the whole table.
        Removing books in bulk was therefore quadratic in the size of
        the library.
        """
        self._con.execute('''create index if not exists contain_book
            on contain (book)''')

    def _create_table_info(self) -> None:
        self._con.execute('''create table if not exists info (
            key text primary key,
            value text)''')
        # "or replace", because the table may already hold a version
        # row: a file whose info table outlived the tables it describes
        # is placed at -1 and has the whole schema created over it, and a
        # plain insert raised IntegrityError there and left the library
        # unopenable.  The current version is the right answer in that
        # case - the tables that were missing have just been created at
        # it - and it is what the row holds on every other path here.
        self._con.execute('''insert or replace into info
            (key, value) values ('version', ?)''',
                          (str(_LibraryBackend.DB_VERSION),))

    def _create_table_watchlist(self) -> None:
        self._con.execute('''create table if not exists watchlist (
            path text primary key,
            collection integer references collection (id) on delete set null,
            recursive boolean not null)''')

    def _create_table_recent(self) -> None:
        self._con.execute('''create table if not exists recent (
            book integer primary key,
            page integer,
            time_set datetime,
            member text)''')
        self._con.execute('''insert or ignore into collection (id, name)
            values (?, ?)''', (constants.COLLECTION_RECENT, 'RECENT'))


_backend: "_LibraryBackend | None" = None


def LibraryBackend() -> _LibraryBackend:
    """The one library backend, opened on the first call.

    Everything that touches the library goes through this, so that there
    is a single connection to the database file rather than one per
    caller.
    """
    global _backend
    if _backend is not None:
        return _backend
    else:
        _backend = _LibraryBackend()
        return _backend

# vim: expandtab:sw=4:ts=4
