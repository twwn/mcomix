"""webp_books.py - Storing the PNG pages of books as lossless WebP.

The library's "Store PNG pages as WebP..." writes each book it is given
again, with every PNG page a lossless WebP where
archive_packer.webp_instead() finds one smaller and the same pixel for
pixel.  Everything else in the archive goes back as it was, under the
name it had, and a page made a WebP changes only its extension.  That
is where it differs from a save, which numbers the pages anew and adds
a ComicInfo.xml: here nothing changes that the reader did not ask for.

Nothing here touches GTK: convert() runs on a thread of its own, and
what it answers with is the caller's to bring to the stores kept by a
page's name (file_actions.follow_pages()), on the main thread.
"""

import os
import tempfile
import threading
from dataclasses import dataclass

from mcomix import archive_packer
from mcomix import archive_tools
from mcomix import image_tools
from mcomix import tools
from mcomix.archive import archive_base
from mcomix.archive import password as archive_password
from mcomix.i18n import _

from collections.abc import Callable

#: The share of a book's progress that unpacking it stands for; making
#: the WebPs and writing the archive are the rest.
_UNPACKING = 0.2

#: How often the progress of the writing is passed on, in seconds.
_TICK = 0.1


class Skipped(Exception):

    """A book left as it was, and why, in words for the reader."""


@dataclass(frozen=True)
class Converted:

    """A book written again with WebP pages."""

    #: The name of each page within the archive, to the name it has now:
    #: written with "/" whatever the system, as the stores kept by a
    #: page's name hold it (file_handler.member_of()).
    renamed: dict[str, str]
    #: The archive's size in bytes before and after.
    before: int
    after: int


def _ignore_progress(done: float) -> None:
    pass


def convert(path: str, stop: threading.Event,
            progress: Callable[[float], None] = _ignore_progress
            ) -> Converted:
    """Store the PNG pages of the archive at <path> as lossless WebP.

    For a thread of its own: it unpacks the whole book and encodes each
    PNG page.  <stop>, once set, stops it before the next file, and
    <progress> is called with how much of the book is done, from 0 to 1.

    Raises Skipped for a book it leaves alone, archive_packer.Cancelled
    where <stop> was set, and OSError where reading or writing failed;
    the archive is as it was in all three.
    """
    if archive_tools.is_later_volume(path) \
            or len(archive_tools.volume_set(path)) > 1:
        # TRANSLATORS: Why a book was left as it was, after "3 books left as
        # they were: ". So are the others here and "open in the main window".
        raise Skipped(_('split into volumes'))
    archive_type = archive_tools.archive_mime_type(path)
    if archive_type is None or not archive_packer.can_write(archive_type):
        raise Skipped(_('a format MComix cannot write here'))
    archive = archive_tools.get_archive_handler(path, archive_type)
    if archive is None:
        raise Skipped(_('a format MComix cannot write here'))
    before = os.stat(path).st_size
    directory = tempfile.mkdtemp(
        prefix='tmp.webp-book.', dir=os.path.dirname(os.path.abspath(path)))
    try:
        try:
            pages, others = _unpack(archive, directory, stop, progress)
        finally:
            archive.close()

        def files(names: list[str]) -> dict[str, str]:
            return {os.path.join(directory, name): name for name in names}

        page_files = files(pages)

        def wait(packer: archive_packer.Packer) -> None:
            while not packer.finished(_TICK):
                if stop.is_set():
                    packer.stop()
                written, total = packer.progress()
                if total:
                    progress(_UNPACKING + (1 - _UNPACKING) * written / total)

        try:
            written = archive_packer.write_archive(
                path, list(page_files), [], carried_files=files(others),
                archive_type=archive_type, permissions_from=path,
                page_names=page_files, waiting=wait, webp_pages=True,
                add_comic_info=False, only_converted=True)
        except archive_packer.Unchanged:
            raise Skipped(_('no page smaller as WebP')) from None
        progress(1.0)
        return Converted({_member(page_files[file]): _member(name)
                          for file, name in written.items()},
                         before, os.stat(path).st_size)
    finally:
        tools.remove_tree(directory)


def _member(name: str) -> str:
    """<name>, as the archive was listed or written on this system, as
    MComix keeps a member's name."""
    return name.replace(os.sep, '/')


def _unpack(archive: archive_base.BaseArchive,
            directory: str, stop: threading.Event,
            progress: Callable[[float], None]
            ) -> tuple[list[str], list[str]]:
    """Unpack everything <archive> holds into <directory>, and answer
    with the names of its pages, sorted, and of everything else.

    The library never asks for a password, and neither does this: an
    encrypted book is skipped.  So is one with archives inside it, which
    MComix reads as if their pages were the book's own and would write
    back so, and one without a page that could become a WebP, before
    anything is unpacked.
    """
    with archive_password.never_asked() as withheld:
        try:
            names = [name for name in archive.list_contents()
                     if not name.endswith('/')]
            if any(archive_tools.is_archive_file(name) for name in names):
                raise Skipped(_('archives inside'))
            pages = [name for name in names
                     if image_tools.is_image_file(name)
                     and not archive_tools.is_finder_file(name)]
            if not any(os.path.splitext(name)[1].lower() == '.png'
                       for name in pages):
                raise Skipped(_('no PNG pages'))
            for count, _name in enumerate(
                    archive.iter_extract(names, directory), start=1):
                if stop.is_set():
                    raise archive_packer.Cancelled()
                progress(_UNPACKING * count / len(names))
        except (Skipped, archive_packer.Cancelled):
            raise
        except Exception as error:
            if withheld.wanted:
                raise Skipped(_('encrypted')) from error
            raise OSError(str(error)) from error
    if withheld.wanted:
        raise Skipped(_('encrypted'))
    missing = [name for name in names
               if not os.path.isfile(os.path.join(directory, name))]
    if missing:
        raise OSError('%d of its files could not be unpacked, the first '
                      '"%s"' % (len(missing), missing[0]))
    tools.alphanumeric_sort(pages)
    listed = set(pages)
    return pages, [name for name in names if name not in listed]

# vim: expandtab:sw=4:ts=4
