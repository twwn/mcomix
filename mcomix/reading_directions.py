"""reading_directions.py - The way round a reader chose to read a book.

Manga mode is a window toggle, and what it was last set to is what a
book opens in.  A shelf that holds manga beside western comics then
reads every other book the wrong way round.  The direction a reader
sets with the toggle is therefore also kept for the book it was set on,
under the book's path: the archive, or the folder of pictures that was
opened, and that book reads so whenever it is opened again.
"""

from mcomix import book_store


def _read(stored: dict[object, object]) -> dict[str, bool]:
    """Every remembered direction: book to whether it reads right to
    left."""
    return {book: right_to_left
            for book, right_to_left in stored.items()
            if isinstance(book, str)
            and isinstance(right_to_left, bool)}


_store = book_store.BookStore('reading_directions.json', _read)


def direction(book: str) -> "bool | None":
    """Whether <book> was set to read right to left; None where it was
    never set either way."""
    return _store.books().get(book)


def remember(book: str, right_to_left: bool) -> None:
    """Keep the direction <book> was set to."""
    books = _store.books()
    if books.get(book) is right_to_left:
        return
    books[book] = right_to_left
    _store.save()


#: Keep the direction of the book at <old> for it at <new>, where it
#: has been moved to.
follow = _store.follow
#: Keep the direction of every book in <old_folder> for it in
#: <new_folder>, where the folder has been moved to, and say how many
#: books that was.
relocate = _store.relocate

# vim: expandtab:sw=4:ts=4
