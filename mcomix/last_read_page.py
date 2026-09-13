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
    """ Automatically stores the last page the user read for all book files,
    and restores the page the next time the archive is opened. When the book
    is finished, the page will be cleared.

    If L{enabled} is set to C{false}, all methods will do nothing. This
    simplifies code in other places, as it does not have to check each time
    if the preference option to store pages automatically is enabled.
    """

    def __init__(self, backend: '_LibraryBackend') -> None:
        """ Constructor.
        @param backend: Library backend instance.
        """
        #: If disabled, all methods will be no-ops.
        self.enabled = False
        #: Library backend.
        self.backend = backend

    def set_enabled(self, enabled: bool) -> None:
        """ Enables (or disables) all functionality of this module.
        @type enabled: bool
        """
        self.enabled = enabled

    def _recent_collection_id(self) -> int:
        """ The id of the "Recent" collection.  Only the default
        collection, which stands for every book and has no row of its
        own, carries no id. """
        collection_id = self.backend.get_recent_collection().id
        assert collection_id is not None
        return collection_id

    def count(self) -> int:
        """ Number of stored book/page combinations. This method is
        not affected by setting L{enabled} to false.
        @return: The number of entries stored by this module. """

        cursor = self.backend.execute("""SELECT COUNT(*) FROM recent""")
        # The connection's row factory unwraps a one column row, so this
        # is the count itself rather than a row holding it.
        count = cursor.fetchone()
        cursor.close()

        return int(count)

    def set_page(self, path: str, page: int) -> None:
        """ Sets C{page} as last read page for the book at C{path}.
        @param path: Path to book. Raises ValueError if file doesn't exist.
        @param page: Page number.
        """
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
        """ Removes stored page for book at C{path}.
        @param path: Path to book.
        """
        if not self.enabled:
            return

        full_path = os.path.abspath(path)
        book = self.backend.get_book_by_path(full_path)

        if book:
            book.set_last_read_page(None)

    def clear_all(self) -> None:
        """ Removes all stored books from the library's 'Recent' collection,
        and removes all information from the recent table. This method is
        not affected by setting L{enabled} to false. """

        # Collect books whose only collection is "Recent". Those are in
        # the library solely because they were read, so they go with the
        # information about having read them.
        #
        # This used to require an entry in table "recent" as well, which
        # let books leak. Closing an archive on page 1 clears that entry
        # (file_handler) without touching the book or its membership, so
        # such a book was not collected here - and the statement below
        # then removed it from "Recent" anyway, leaving a row in "book"
        # belonging to no collection at all, which nothing ever removes.
        #
        # Those leaked rows cannot be cleaned up retroactively: a book in
        # no collection is also what add_book(path, None) creates, which
        # is how the library adds a book without filing it, so the two
        # are indistinguishable after the fact.
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
        # wrap their loops for the same reason.
        self.backend.begin_transaction()
        try:
            for book in books:
                self.backend.remove_book(book)
            cursor = self.backend.execute("""DELETE FROM recent""")
            cursor.close()
            cursor = self.backend.execute(
                """DELETE FROM contain WHERE collection = ?""",
                (recent_collection,))
            cursor.close()
        finally:
            # Leaving the connection in transactional mode would make
            # every later write wait for an explicit commit that never
            # comes.
            self.backend.end_transaction()

    def get_page(self, path: str) -> int | None:
        """ Gets the last read page for book at C{path}.

        @param path: Path to book.
        @return: Page that was last read, or C{None} if the book
                 wasn't opened before.
        """
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
        """ Gets the date at which the page for path was set.

        @param path: Path to book.
        @return: C{datetime} object, or C{None} if no page was set.
        """
        if not self.enabled:
            return None

        full_path = os.path.abspath(path)
        book = self.backend.get_book_by_path(full_path)
        if book:
            return book.get_last_read_date()
        else:
            return None

    def migrate_database_to_library(self, recent_collection: int) -> None:
        """ Moves all information saved in the legacy database
        constants.LASTPAGE_DATABASE_PATH into the library,
        and deleting the old database. """

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

                # Set recent info on retrieved book
                # XXX: If the book calls get_backend during migrate_database,
                # the library isn't constructed yet and breaks in an
                # endless recursion.
                book.get_backend = lambda: self.backend  # type: ignore[method-assign]
                book.set_last_read_page(page, time_set)

            try:
                os.unlink(constants.LASTPAGE_DATABASE_PATH)
            except OSError as error:
                log.error(_('! Could not remove file "%s"'),
                          constants.LASTPAGE_DATABASE_PATH)
                log.info('Error was: %s', error)

    def _init_database(self, dbfile: str) -> dbapi2.Connection:
        """ Creates or opens new SQLite database at C{dbfile}, and initalizes
        the required table(s).

        @param dbfile: Database file name. This file needn't exist.
        @return: Open SQLite database connection.
        """
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
