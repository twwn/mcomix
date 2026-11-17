"""page_rotations.py - The turn a reader has given each page."""

from mcomix import book_store


def _read(stored: dict[object, object]) -> dict[str, dict[str, int]]:
    """Every remembered turn: book, then page within it, to degrees."""
    return {
        book: {page: degrees for page, degrees in turns.items()
               if isinstance(degrees, int)
               and degrees in (90, 180, 270)}
        for book, turns in stored.items()
        if isinstance(book, str) and isinstance(turns, dict)}


_store = book_store.PageStore('page_rotations.json', _read)


def rotation(book: str, page: str) -> int:
    """The turn given to <page> of <book>, in degrees clockwise; 0 where
    none was."""
    return _store.books().get(book, {}).get(page, 0)


def remember(book: str, page: str, degrees: int) -> None:
    """Keep <degrees> as the turn of <page> of <book>; 0 forgets it."""
    pages = _store.books()
    turns = pages.setdefault(book, {})
    if degrees % 360:
        turns[page] = degrees % 360
    else:
        turns.pop(page, None)
        if not turns:
            del pages[book]
    _store.save()


#: Keep the turns of the book at <old> for it at <new>, where it has
#: been moved to.
follow = _store.follow
#: Keep the turns of every book in <old_folder> for it in <new_folder>,
#: where the folder has been moved to, and say how many books that was.
relocate = _store.relocate
#: Keep the turns of <book> for its pages under the names they have now.
rename_pages = _store.rename_pages
