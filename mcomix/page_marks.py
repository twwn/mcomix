"""page_marks.py - What a reader has said of single pages of a book.

A page to pass over when turning the pages, such as an advertisement
or a blank side, and a page to show on its own where two are shown side
by side.  The marks are kept apart from the book, which is not changed
by them, under the names page_identity() gives: the archive and the
file's name within it.
"""

from mcomix import book_store

#: The page is passed over when the pages are turned.
SKIP = 'skip'
#: The page is shown on its own in double page mode, as a wide page is.
ALONE = 'alone'

#: Every mark there is; anything else in the file is dropped on reading.
_MARKS = frozenset({SKIP, ALONE})


def _read(stored: dict[object, object]) -> dict[str, dict[str, list[str]]]:
    """Every mark: book, then page within it, to the marks it carries."""
    books: dict[str, dict[str, list[str]]] = {}
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
    return books


_store = book_store.PageStore('page_marks.json', _read)


def marked(book: str, page: str, mark: str) -> bool:
    """Whether <page> of <book> carries <mark>."""
    return mark in _store.books().get(book, {}).get(page, ())


def any_marked(book: str, mark: str) -> bool:
    """Whether any page of <book> carries <mark>."""
    return any(mark in marks for marks in _store.books().get(book, {}).values())


def mark(book: str, page: str, mark: str, on: bool) -> None:
    """Put <mark> on <page> of <book>, or take it off."""
    books = _store.books()
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
    _store.save()


#: Keep the marks of the book at <old> for it at <new>, where it has
#: been moved to.
follow = _store.follow
#: Keep the marks of every book in <old_folder> for it in <new_folder>,
#: where the folder has been moved to, and say how many books that was.
relocate = _store.relocate
#: Keep the marks of <book> for its pages under the names they have now.
rename_pages = _store.rename_pages
