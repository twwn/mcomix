"""reading_directions.py - The way round a reader chose to read a book.

Manga mode is a window toggle, and what it was last set to is what a
book opens in.  A shelf that holds manga beside western comics then
reads every other book the wrong way round.  The direction a reader
sets with the toggle is therefore also kept for the book it was set on,
under the book's path: the archive, or the folder of pictures that was
opened, and that book reads so whenever it is opened again.
"""

import json
import os

from mcomix import constants
from mcomix import log
from mcomix import tools
from mcomix.i18n import _

#: What has been read from or written to the file, with the file's path:
#: the data folder is read when the store is first used, not at import.
_loaded: "tuple[str, dict[str, bool]] | None" = None


def _path() -> str:
    return os.path.join(constants.DATA_DIR, 'reading_directions.json')


def _books() -> dict[str, bool]:
    """Every remembered direction: book to whether it reads right to
    left."""
    global _loaded
    path = _path()
    if _loaded is not None and _loaded[0] == path:
        return _loaded[1]
    books: dict[str, bool] = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as fd:
                stored = json.load(fd)
            if isinstance(stored, dict):
                books = {book: right_to_left
                         for book, right_to_left in stored.items()
                         if isinstance(book, str)
                         and isinstance(right_to_left, bool)}
        except (OSError, ValueError) as error:
            log.debug('%s: %s', path, error)
            log.warning(_('! Could not read %s'), path)
    _loaded = (path, books)
    return books


def direction(book: str) -> "bool | None":
    """Whether <book> was set to read right to left; None where it was
    never set either way."""
    return _books().get(book)


def remember(book: str, right_to_left: bool) -> None:
    """Keep the direction <book> was set to."""
    books = _books()
    if books.get(book) is right_to_left:
        return
    books[book] = right_to_left
    _save(books)


def follow(old: str, new: str) -> None:
    """Keep the direction of the book at <old> for it at <new>, where it
    has been moved to."""
    books = _books()
    if old in books:
        books[new] = books.pop(old)
        _save(books)


def relocate(old_folder: str, new_folder: str) -> int:
    """Keep the direction of every book in <old_folder> for it in
    <new_folder>, where the folder has been moved to, and say how many
    books that was."""
    books = _books()
    moved = {book: target for book in books
             if (target := tools.relocated(book, old_folder, new_folder))
             is not None and target not in books}
    for book, target in moved.items():
        books[target] = books.pop(book)
    if moved:
        _save(books)
    return len(moved)


def _save(books: dict[str, bool]) -> None:
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tools.atomic_write(path) as fd:
            json.dump(books, fd, ensure_ascii=False, indent=0)
    except OSError as error:
        log.warning(_('! Could not save %(file)s to %(directory)s: %(error)s'),
                    {'file': os.path.basename(path),
                     'directory': os.path.dirname(path), 'error': error})

# vim: expandtab:sw=4:ts=4
