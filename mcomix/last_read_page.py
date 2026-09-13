"""last_read_page.py - The page a book was left on.

Where the reader stopped in a book is kept in the library database, in
a row of table "recent" beside the book's own row, and the book itself
is filed in the library's "Recent" collection.  Opening that book again
offers to carry on from the stored page.

None of it happens while the "store recent file info" preference is
off, which is what the enabled flag stands for.  The two methods that
count and clear what was stored earlier ignore that flag, because the
preferences dialog reaches for them exactly when the preference has
just been turned off.

The module also carries a one-time migration.  Before the library grew
its "recent" table, the last read page lived in a standalone SQLite
database of its own, lastreadpage.db; upgrading a library from before
that moves what the old file holds into the library and deletes it.
"""

import datetime
import os
from typing import TYPE_CHECKING

from mcomix import log
from mcomix import constants
from mcomix.i18n import _

# This import is only used for legacy data that is imported
# into the library at upgrade.
from sqlite3 import dbapi2

if TYPE_CHECKING:
    # Delayed: the library backend imports this module for the migration.
    from mcomix.library.backend import _LibraryBackend


class LastReadPage:
    """ Stores the page a book was left on, and hands it back when the
    book is opened again.

    A book read to its last page counts as finished: the page is still
    stored, but get_page() answers None for it, so the book opens at the
    beginning again rather than at its final page.

    While enabled is false, every method that reads or writes the page
    of one book does nothing, which spares each caller from testing the
    preference itself.  count() and clear_all() work either way, since
    what they are for is disposing of what was stored while it was on.
    """

    def __init__(self, backend: '_LibraryBackend') -> None:
        #: While false, the methods that read or write the page of one
        #: book do nothing.
        self.enabled = False
        self.backend = backend

    def set_enabled(self, enabled: bool) -> None:
        """ Follows the "store recent file info" preference. """
        self.enabled = enabled

    def _recent_collection_id(self) -> int:
        """ The id of the "Recent" collection.  Only the default
        collection, which stands for every book and has no row of its
        own, carries no id. """
        collection_id = self.backend.get_recent_collection().id
        assert collection_id is not None
        return collection_id

    def count(self) -> int:
        """ How many books have a stored page.  Answers whether or not
        this is enabled, because the preferences dialog asks it just
        after the preference has been turned off. """

        cursor = self.backend.execute("""SELECT COUNT(*) FROM recent""")
        # The connection's row factory unwraps a one column row, so this
        # is the count itself rather than a row holding it.
        count = cursor.fetchone()
        cursor.close()

        return int(count)

    def set_page(self, path: str, page: int) -> None:
        """ Stores <page> as the last read page of the book at <path>,
        adding the book to the library if it is not there yet and filing
        it in the "Recent" collection either way.  Raises ValueError
        when the book cannot be added, which is what a file that has
        gone away comes to. """
        if not self.enabled:
            return

        full_path = os.path.abspath(path)
        book = self.backend.get_book_by_path(full_path)

        if not book:
            self.backend.add_book(full_path, self._recent_collection_id())
            book = self.backend.get_book_by_path(full_path)

            if not book:
                raise ValueError("Book doesn't exist")
        else:
            self.backend.add_book_to_collection(
                book.id, self._recent_collection_id())

        book.set_last_read_page(page)

    def clear_page(self, path: str) -> None:
        """ Forgets the page stored for the book at <path>.  The book
        keeps its row in the library and its place in the "Recent"
        collection; only the stored page goes. """
        if not self.enabled:
            return

        full_path = os.path.abspath(path)
        book = self.backend.get_book_by_path(full_path)

        if book:
            book.set_last_read_page(None)

    def clear_all(self) -> None:
        """ Empties the "Recent" collection and the stored pages that go
        with it, taking with them the books that are in the library only
        because they were read.  Works whether or not this is enabled:
        the preferences dialog offers it when the preference has just
        been turned off. """

        # Collect books whose only collection is "Recent". Those are in
        # the library solely because they were read, so they go with the
        # information about having read them.
        #
        # Membership alone decides, not an entry in table "recent" as
        # well.  Closing an archive on page 1 clears that entry
        # (file_handler) without touching the book or its membership, so
        # such a book would not be collected here, and the statement
        # below would still remove it from "Recent", leaving a row in
        # "book" that belongs to no collection and that nothing removes.
        #
        # A database written by an older version may hold rows left
        # behind that way, and they cannot be cleaned up: a book in no
        # collection is also what add_book(path, None) creates, which is
        # how the library adds a book without filing it.
        sql = """SELECT c.book FROM contain c
                 JOIN (SELECT book FROM contain
                       GROUP BY book HAVING COUNT(*) = 1
                      ) t ON t.book = c.book
                 WHERE c.collection = ?"""
        recent_collection = self._recent_collection_id()
        cursor = self.backend.execute(sql, (recent_collection,))
        books = cursor.fetchall()
        cursor.close()

        # The connection is in auto-commit mode, so without a transaction
        # around them each of the statements below is committed on its
        # own, three per book removed.  _BookArea's two bulk removals
        # and the library's bulk add wrap their loops for the same
        # reason.
        with self.backend.transaction():
            for book in books:
                self.backend.remove_book(book)
            cursor = self.backend.execute("""DELETE FROM recent""")
            cursor.close()
            cursor = self.backend.execute(
                """DELETE FROM contain WHERE collection = ?""",
                (recent_collection,))
            cursor.close()

    def get_page(self, path: str) -> int | None:
        """ The page to carry on from in the book at <path>, or None
        when there is none: the book was never opened, or it was read to
        the end and starts over from the beginning. """
        if not self.enabled:
            return None

        full_path = os.path.abspath(path)
        book = self.backend.get_book_by_path(full_path)
        if book:
            page = book.get_last_read_page()
            if page is not None and page < book.pages:
                return page
            else:
                # If the last read page was the last in the book,
                # start from scratch.
                return None
        else:
            return None

    def get_date(self, path: str) -> datetime.datetime | None:
        """ When the stored page of the book at <path> was set, or None
        if no page is stored. """
        if not self.enabled:
            return None

        full_path = os.path.abspath(path)
        book = self.backend.get_book_by_path(full_path)
        if book:
            return book.get_last_read_date()
        else:
            return None

    def migrate_database_to_library(self, recent_collection: int) -> None:
        """ Moves what the legacy lastreadpage.db holds into the
        library, filing each of its books in <recent_collection>, and
        deletes the old database afterwards.  A book whose file has gone
        away is dropped; one the library already has keeps the row it
        has and only gains the collection.

        The library backend runs this once, while upgrading a database
        to version 4, the version that added table "recent".  The old
        file is opened through _init_database(), which creates it when
        it is not there, so an upgrade of a library that never had one
        moves nothing and then deletes the file it has just made. """

        database = self._init_database(constants.LASTPAGE_DATABASE_PATH)

        if database:
            cursor = database.execute('''SELECT path, page, time_set
                                         FROM lastread''')
            rows = cursor.fetchall()
            cursor.close()
            database.close()

            for path, page, time_set in rows:
                book = self.backend.get_book_by_path(path)

                if not book:
                    # The path doesn't exist in the library yet
                    if not os.path.exists(path):
                        # File might no longer be available
                        continue

                    self.backend.add_book(path, recent_collection)
                    book = self.backend.get_book_by_path(path)

                    if not book:
                        # The book could not be added
                        continue
                else:
                    # The book exists, move into recent collection
                    self.backend.add_book_to_collection(book.id, recent_collection)

                # Set recent info on retrieved book.  The library
                # is still opening - this runs from the upgrade step in
                # _LibraryBackend.__init__() - so the book is given the
                # backend rather than left to ask LibraryBackend() for
                # one, which would start building a second.
                book.set_backend(self.backend)
                book.set_last_read_page(page, time_set)

            try:
                os.unlink(constants.LASTPAGE_DATABASE_PATH)
            except OSError as error:
                log.error(_('! Could not remove file "%s"'),
                          constants.LASTPAGE_DATABASE_PATH)
                log.info('Error was: %s', error)

    def _init_database(self, dbfile: str) -> dbapi2.Connection:
        """ Opens the legacy database at <dbfile>, creating the file and
        the one table it holds if they are not there. """
        db = dbapi2.connect(dbfile, isolation_level=None)
        sql = """CREATE TABLE IF NOT EXISTS lastread (
            path TEXT PRIMARY KEY,
            page INTEGER,
            time_set DATETIME
        )"""
        cursor = db.execute(sql)
        cursor.close()

        return db

# vim: expandtab:sw=4:ts=4
