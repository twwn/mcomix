"""page_rotations.py - The turn a reader has given each page."""

import json
import os

from mcomix import constants
from mcomix import log
from mcomix import tools
from mcomix.i18n import _

#: What has been read from or written to the file, with the file's path:
#: the data folder is read when the store is first used, not at import.
_loaded: "tuple[str, dict[str, dict[str, int]]] | None" = None


def _path() -> str:
    return os.path.join(constants.DATA_DIR, 'page_rotations.json')


def _pages() -> dict[str, dict[str, int]]:
    """Every remembered turn: book, then page within it, to degrees."""
    global _loaded
    path = _path()
    if _loaded is not None and _loaded[0] == path:
        return _loaded[1]
    pages: dict[str, dict[str, int]] = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as fd:
                stored = json.load(fd)
            if isinstance(stored, dict):
                pages = {
                    book: {page: degrees for page, degrees in turns.items()
                           if isinstance(degrees, int)
                           and degrees in (90, 180, 270)}
                    for book, turns in stored.items()
                    if isinstance(book, str) and isinstance(turns, dict)}
        except (OSError, ValueError) as error:
            log.debug('%s: %s', path, error)
            log.warning(_('! Could not read %s'), path)
    _loaded = (path, pages)
    return pages


def rotation(book: str, page: str) -> int:
    """The turn given to <page> of <book>, in degrees clockwise; 0 where
    none was."""
    return _pages().get(book, {}).get(page, 0)


def remember(book: str, page: str, degrees: int) -> None:
    """Keep <degrees> as the turn of <page> of <book>; 0 forgets it."""
    pages = _pages()
    turns = pages.setdefault(book, {})
    if degrees % 360:
        turns[page] = degrees % 360
    else:
        turns.pop(page, None)
        if not turns:
            del pages[book]
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tools.atomic_write(path) as fd:
            json.dump(pages, fd, ensure_ascii=False, indent=0)
    except OSError as error:
        log.warning(_('! Could not save %(file)s to %(directory)s: %(error)s'),
                    {'file': os.path.basename(path),
                     'directory': os.path.dirname(path), 'error': error})
