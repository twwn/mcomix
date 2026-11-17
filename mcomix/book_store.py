"""book_store.py - What a reader has set for a book, kept apart from it.

The turns given to pages, the marks put on them and the direction a
book is read in are each kept in a JSON file of their own in the data
folder: the book's path to what was set for it.  The file is read when
the store is first used, not at import, and written again after each
change.  What is kept of a book follows it when the book, or a folder
it is in, is moved.
"""

import json
import os

from collections.abc import Callable, Collection, Mapping
from typing import Generic, TypeVar

from mcomix import constants
from mcomix import log
from mcomix import tools
from mcomix.i18n import _

#: What a store keeps for one book.
Kept = TypeVar('Kept')
#: What a store of pages keeps for one page of a book.
PageKept = TypeVar('PageKept')


class BookStore(Generic[Kept]):
    """What is kept for each book, by the book's path, in the file
    <name> of the data folder.

    <read> takes what the file holds, a dict, and gives back what is
    to be kept of it: anything of the wrong shape is dropped there, so
    that a file damaged or written by another version costs what it
    got wrong and nothing else.
    """

    def __init__(self, name: str,
                 read: "Callable[[dict[object, object]], dict[str, Kept]]"
                 ) -> None:
        self._name = name
        self._read = read
        #: What has been read from or written to the file, with the
        #: file's path.
        self._loaded: "tuple[str, dict[str, Kept]] | None" = None

    def path(self) -> str:
        """The file the store is kept in."""
        return os.path.join(constants.DATA_DIR, self._name)

    def books(self) -> dict[str, Kept]:
        """Every book something is kept for, to what is kept for it.
        A change to it is written by save()."""
        path = self.path()
        if self._loaded is not None and self._loaded[0] == path:
            return self._loaded[1]
        books: dict[str, Kept] = {}
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fd:
                    stored = json.load(fd)
                if isinstance(stored, dict):
                    books = self._read(stored)
            except (OSError, ValueError) as error:
                log.debug('%s: %s', path, error)
                log.warning(_('! Could not read %s'), path)
        self._loaded = (path, books)
        return books

    def forget(self) -> None:
        """Read the file again when the store is next used."""
        self._loaded = None

    def save(self) -> None:
        """Write what books() holds to the file."""
        books = self.books()
        path = self.path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with tools.atomic_write(path) as fd:
                json.dump(books, fd, ensure_ascii=False, indent=0)
        except OSError as error:
            log.warning(_('! Could not save %(file)s to %(directory)s: %(error)s'),
                        {'file': os.path.basename(path),
                         'directory': os.path.dirname(path), 'error': error})

    def follow(self, old: str, new: str) -> None:
        """Keep what was kept for the book at <old> for it at <new>,
        where it has been moved to."""
        books = self.books()
        if old in books:
            books[new] = books.pop(old)
            self.save()

    def relocate(self, old_folder: str, new_folder: str) -> int:
        """Keep what was kept for every book in <old_folder> for it in
        <new_folder>, where the folder has been moved to, and say how
        many books that was."""
        books = self.books()
        moved = {book: target for book in books
                 if (target := tools.relocated(book, old_folder, new_folder))
                 is not None and target not in books}
        for book, target in moved.items():
            books[target] = books.pop(book)
        if moved:
            self.save()
        return len(moved)


class PageStore(BookStore[dict[str, PageKept]]):
    """What is kept for single pages of each book, by the page's name
    within the book."""

    def rename_pages(self, book: str, renamed: "Mapping[str, str]",
                     pages: "Collection[str]") -> None:
        """Keep what was kept for the pages of <book> under the names
        they have now: <renamed> maps the name a page had to the one it
        has, and <pages> is every name the book now holds.

        A book written again has its pages numbered anew, so a page's
        name is another's old one as often as not: all of them are
        moved at once, and what was kept for a page the book no longer
        holds goes, rather than wait for a page that is one day called
        that.
        """
        stored = self.books()
        kept = stored.get(book)
        if kept is None:
            return
        moved = {renamed.get(page, page): value for page, value in kept.items()}
        moved = {page: value for page, value in moved.items() if page in pages}
        if moved == kept:
            return
        if moved:
            stored[book] = moved
        else:
            del stored[book]
        self.save()

# vim: expandtab:sw=4:ts=4
