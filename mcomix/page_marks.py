"""page_marks.py - What a reader has said of single pages of a book.

A page to pass over when turning the pages, such as an advertisement
or a blank side.  The marks are kept apart from the book, which is not
changed by them, under the names page_identity() gives: the archive and
the file's name within it.
"""

import json
import os

from mcomix import constants
from mcomix import log
from mcomix import tools
from mcomix.i18n import _

#: The page is passed over when the pages are turned.
SKIP = 'skip'

#: Every mark there is; anything else in the file is dropped on reading.
_MARKS = frozenset({SKIP})

#: What has been read from or written to the file, with the file's path:
#: the data folder is read when the store is first used, not at import.
_loaded: "tuple[str, dict[str, dict[str, list[str]]]] | None" = None


def _path() -> str:
    return os.path.join(constants.DATA_DIR, 'page_marks.json')


def _books() -> dict[str, dict[str, list[str]]]:
    """Every mark: book, then page within it, to the marks it carries."""
    global _loaded
    path = _path()
    if _loaded is not None and _loaded[0] == path:
        return _loaded[1]
    books: dict[str, dict[str, list[str]]] = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as fd:
                stored = json.load(fd)
            if isinstance(stored, dict):
                for book, pages in stored.items():
                    if not isinstance(book, str) or not isinstance(pages, dict):
                        continue
                    kept = {page: sorted(_MARKS.intersection(marks))
                            for page, marks in pages.items()
                            if isinstance(marks, list)
                            and all(isinstance(mark, str) for mark in marks)}
                    kept = {page: marks for page, marks in kept.items()
                            if marks}
                    if kept:
                        books[book] = kept
        except (OSError, ValueError) as error:
            log.debug('%s: %s', path, error)
            log.warning(_('! Could not read %s'), path)
    _loaded = (path, books)
    return books


def marked(book: str, page: str, mark: str) -> bool:
    """Whether <page> of <book> carries <mark>."""
    return mark in _books().get(book, {}).get(page, ())


def any_marked(book: str, mark: str) -> bool:
    """Whether any page of <book> carries <mark>."""
    return any(mark in marks for marks in _books().get(book, {}).values())


def mark(book: str, page: str, mark: str, on: bool) -> None:
    """Put <mark> on <page> of <book>, or take it off."""
    books = _books()
    pages = books.setdefault(book, {})
    marks = set(pages.get(page, ()))
    if on:
        marks.add(mark)
    else:
        marks.discard(mark)
    if marks:
        pages[page] = sorted(marks)
    else:
        pages.pop(page, None)
    if not pages:
        del books[book]
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tools.atomic_write(path) as fd:
            json.dump(books, fd, ensure_ascii=False, indent=0)
    except OSError as error:
        log.warning(_('! Could not save %(file)s to %(directory)s: %(error)s'),
                    {'file': os.path.basename(path),
                     'directory': os.path.dirname(path), 'error': error})
