"""webp_books.py - Storing the PNG pages of books as lossless WebP.

The library's "Make pages smaller without loss..." writes each book it is given
again, with every PNG page a lossless WebP where
archive_packer.webp_instead() finds one smaller and the same pixel for
pixel.  Everything else in the archive goes back as it was, under the
name it had, and a page made a WebP changes only its extension.  That
is where it differs from a save, which numbers the pages anew and adds
a ComicInfo.xml: here nothing changes that the reader did not ask for.

"Shrink oversized pages..." writes books again the same way, with each
page over the limit shrunk (mcomix.page_shrink) instead, and moves the
book as it was to the trash: that one loses detail.  survey() first
tells which books it would change, and by how much.

Nothing here touches GTK: convert() runs on a thread of its own, and
what it answers with is the caller's to bring to the stores kept by a
page's name (file_actions.follow_pages()), on the main thread.
"""

import contextlib
import os
import tempfile
import threading
from dataclasses import dataclass, field

from gi.repository import GLib

from mcomix import archive_packer
from mcomix import archive_tools
from mcomix import constants
from mcomix import i18n
from mcomix import image_tools
from mcomix import log
from mcomix import page_shrink
from mcomix import portability
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

#: The formats MComix writes only with a program it does not install
#: (archive_packer.can_write()), to that program's name.
_WRITTEN_BY_PROGRAM = {constants.SEVENZIP: '7z', constants.RAR: 'rar'}


class Skipped(Exception):

    """A book left as it was, and why, in words for the reader;
    <damaged> where that is that its file could not be read."""

    def __init__(self, reason: str, damaged: bool = False) -> None:
        super().__init__(reason)
        self.damaged = damaged


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
    #: The files within the archive that could not be read, and so were
    #: left out of it, by name, to why.
    left_out: dict[str, str] = field(default_factory=dict)


def _ignore_progress(done: float) -> None:
    pass


@dataclass(frozen=True)
class Surveyed:

    """A book with pages over the limit, as survey() found it."""

    #: How many of its pages are over the limit.
    pages: int
    #: The archive's size in bytes, and roughly how many shrinking its
    #: pages would save.
    size: int
    saved: int


#: How many of a book's pages over the limit survey() shrinks to tell
#: what shrinking all of them would save: the first, the last and one
#: between, spread through the book as its pages are.
_SAMPLES = 3


def _opened(path: str
            ) -> tuple[archive_base.BaseArchive, int, "str | None"]:
    """The archive handler for the book at <path>, its format, and why
    a book with pages to change could not be written, if it could not.
    Raises Skipped for a book that is left alone whatever it holds."""
    if archive_tools.is_later_volume(path) \
            or len(archive_tools.volume_set(path)) > 1:
        # TRANSLATORS: Why a book was left as it was, after "3 books left as
        # they were: ". So are the others here and "open in the main window".
        raise Skipped(_('split into volumes'))
    archive_type = archive_tools.archive_mime_type(path)
    if archive_type is None:
        raise Skipped(_('damaged, or not an archive'), damaged=True)
    unwritable = None
    if not archive_packer.can_write(archive_type):
        program = _WRITTEN_BY_PROGRAM.get(archive_type)
        if program is None:
            raise Skipped(_('a format MComix does not write: %s')
                          % archive_tools.describe(path, archive_type))
        # Told only of a book that has PNG pages: one that has none,
        # such as a book done before, has nothing to write either way.
        unwritable = _('the %s program that writes the format is not '
                       'installed') % program
    archive = archive_tools.get_archive_handler(path, archive_type)
    if archive is None:
        raise Skipped(_('nothing installed here reads the format'))
    return archive, archive_type, unwritable


def survey(path: str, shrink: page_shrink.Shrink, stop: threading.Event,
           progress: Callable[[float], None] = _ignore_progress
           ) -> Surveyed:
    """How many pages of the archive at <path> are over the limit of
    <shrink>, and roughly how much room shrinking them would save, told
    by shrinking a few of them (_SAMPLES).  Nothing is written.

    For a thread of its own, as convert(), and raising what it raises
    but OSError for a write; Skipped too for a book with no page over
    the limit."""
    archive, _archive_type, unwritable = _opened(path)
    directory = tempfile.mkdtemp(prefix='mcomix-shrink-survey.',
                                 dir=archive_packer.working_folder())
    book = os.path.join(directory, 'book')
    try:
        try:
            pages = _unpack(archive, book, stop, progress, unwritable,
                            any_page=True)[0]
        finally:
            archive.close()
        over = [file for file in (os.path.join(book, name) for name in pages)
                if _over(file, shrink.limit)]
        if not over:
            # TRANSLATORS: Why a book was left as it was, as the others.
            raise Skipped(_('no page over the limit'))
        step = -(-len(over) // _SAMPLES)
        sampled = (over[::step] + over[-1:])[:_SAMPLES] \
            if len(over) > _SAMPLES else over
        before = after = 0
        for number, file in enumerate(dict.fromkeys(sampled)):
            if stop.is_set():
                raise archive_packer.Cancelled()
            shrunk = page_shrink.shrink_instead(file, directory,
                                                '%d.webp' % number, shrink)
            before += os.path.getsize(file)
            after += os.path.getsize(shrunk if shrunk is not None else file)
        over_bytes = sum(os.path.getsize(file) for file in over)
        return Surveyed(len(over), os.stat(path).st_size,
                        round(over_bytes * (1 - after / before))
                        if before else 0)
    finally:
        tools.remove_tree(directory)


def _over(file: str, limit: int) -> bool:
    """Whether the picture <file> is over <limit>, told by its size as
    its header gives it; False for what Pillow does not read."""
    from PIL import Image

    try:
        with Image.open(file) as picture:
            size = picture.size
    except Exception:
        return False
    return page_shrink.scaled_size(*size, limit) is not None


def convert(path: str, stop: threading.Event,
            progress: Callable[[float], None] = _ignore_progress,
            shrink: "page_shrink.Shrink | None" = None) -> Converted:
    """Store the PNG pages of the archive at <path> as lossless WebP;
    or, given <shrink>, the pages over its limit shrunk, the archive as
    it was going to the trash.

    For a thread of its own: it unpacks the whole book and encodes each
    PNG page.  <stop>, once set, stops it before the next file, and
    <progress> is called with how much of the book is done, from 0 to 1.

    A file in the archive that cannot be read, being damaged, is left
    out of it, and named in what is answered: the rest of the book is
    not lost with it.

    Raises Skipped for a book it leaves alone, archive_packer.Cancelled
    where <stop> was set, and OSError where reading or writing failed;
    the archive is as it was in all three.
    """
    archive, archive_type, unwritable = _opened(path)
    if shrink is not None and tools.trash_refuses(path):
        archive.close()
        raise Skipped(_('the trash takes no files from its folder'))
    before = os.stat(path).st_size
    directory = tempfile.mkdtemp(prefix='mcomix-webp-book.',
                                 dir=archive_packer.working_folder())
    target = path
    try:
        try:
            pages, others, left_out = _unpack(
                archive, directory, stop, progress, unwritable,
                any_page=shrink is not None)
        finally:
            archive.close()
        if shrink is not None:
            # Written beside the book, which goes to the trash once the
            # new one is whole and takes its place.
            fd, target = tempfile.mkstemp(
                suffix=os.path.splitext(path)[1],
                prefix=archive_tools.WORKING_PREFIX,
                dir=os.path.dirname(tools.replaced_path(path)))
            os.close(fd)

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
                target, list(page_files), [], carried_files=files(others),
                archive_type=archive_type, permissions_from=path,
                page_names=page_files, waiting=wait,
                webp_pages=shrink is None, shrink=shrink,
                add_comic_info=False, only_converted=True)
        except archive_packer.Unchanged:
            raise Skipped(_('no page made smaller')) from None
        if target != path:
            book = tools.replaced_path(path)
            try:
                tools.move_to_trash(book)
            except GLib.Error as error:
                raise Skipped(_('the trash refused it: %s')
                              % error.message) from None
            # The book as it was is in the trash: the new one is all that
            # is left in its folder, kept where it was written if it
            # cannot take the book's name.
            written_to, target = target, path
            try:
                portability.rename_once_closed(os.replace, written_to, book)
            except OSError as failure:
                log.warning('"%s" went to the trash, but "%s", written in '
                            'its place, could not take its name: %s',
                            i18n.to_display_string(book),
                            i18n.to_display_string(written_to), failure)
                raise
        progress(1.0)
        for name, why in left_out.items():
            log.warning('Left "%s" out of "%s": it could not be read: %s',
                        i18n.to_display_string(name),
                        i18n.to_display_string(path), why)
        return Converted({_member(page_files[file]): _member(name)
                          for file, name in written.items()},
                         before, os.stat(path).st_size, left_out)
    finally:
        tools.remove_tree(directory)
        if target != path:
            # Stopped, or failed, before the new book took the old one's
            # place.
            with contextlib.suppress(FileNotFoundError):
                tools.remove_file(target)


def _member(name: str) -> str:
    """<name>, as the archive was listed or written on this system, as
    MComix keeps a member's name."""
    return name.replace(os.sep, '/')


def _unpack(archive: archive_base.BaseArchive,
            directory: str, stop: threading.Event,
            progress: Callable[[float], None],
            unwritable: "str | None" = None, any_page: bool = False
            ) -> tuple[list[str], list[str], dict[str, str]]:
    """Unpack everything <archive> holds into <directory>, and answer
    with the names of its pages, sorted, of everything else, and of the
    files that could not be read, to why.

    <unwritable>, where given, says why a book with PNG pages cannot be
    written: such a book is skipped for it once listed.  <any_page>
    has a book with any page at all count as such, as one to shrink.

    A file that cannot be read is left out (archive_tools.extract_each);
    a failure that is the disk's and not the file's (archive_tools.NOT_THE_FILE)
    fails the book instead.

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
            if withheld.wanted:
                # A 7z whose names are encrypted too lists nothing
                # without the password, which would read as a book
                # without pages.
                raise Skipped(_('encrypted'))
            if any(archive_tools.is_archive_file(name) for name in names):
                raise Skipped(_('archives inside'))
            pages = [name for name in names
                     if image_tools.is_image_file(name)
                     and not archive_tools.is_finder_file(name)]
            if any_page:
                if not pages:
                    raise Skipped(_('no page over the limit'))
            elif not any(archive_packer.may_shrink(name) for name in pages):
                raise Skipped(_('no PNG, GIF or JPEG pages'))
            if unwritable is not None:
                raise Skipped(unwritable)
            done = 0

            def unpacked(name: str) -> None:
                nonlocal done
                if stop.is_set():
                    raise archive_packer.Cancelled()
                done += 1
                progress(_UNPACKING * done / len(names))

            left_out = archive_tools.extract_each(
                archive, names, directory, unpacked,
                lambda error: _raise_unless_the_file(error, withheld.wanted))
        except (Skipped, archive_packer.Cancelled):
            raise
        except Exception as error:
            if withheld.wanted:
                raise Skipped(_('encrypted')) from error
            if isinstance(error, OSError):
                # A full disk, say, told as the system tells it.
                raise
            raise OSError(str(error)) from error
    if withheld.wanted:
        raise Skipped(_('encrypted'))
    for name in names:
        if name not in left_out \
                and not os.path.isfile(os.path.join(directory, name)):
            left_out[name] = 'nothing came out of it'
    for name in left_out:
        # What came out of a damaged file before it failed is no file.
        with contextlib.suppress(FileNotFoundError):
            tools.remove_file(os.path.join(directory, name))
    pages = [name for name in pages if name not in left_out]
    tools.alphanumeric_sort(pages)
    listed = set(pages)
    return pages, [name for name in names
                   if name not in listed and name not in left_out], left_out


def _raise_unless_the_file(error: Exception, encrypted: bool) -> None:
    """Raise what <error> tells of the book, unless it says only
    that the file being unpacked could not be read."""
    if encrypted:
        raise Skipped(_('encrypted')) from error
    if isinstance(error, OSError) \
            and error.errno in archive_tools.NOT_THE_FILE:
        raise error

# vim: expandtab:sw=4:ts=4
