"""book_check.py - Whether every file of a book can be read.

What "Select books > Books that cannot be read in full..." asks of each
book on show.  The library knows only what it read when the book was
added: a book damaged since, or one whose damage lies past its listing,
shows only once every file of it is read, which is what this does.
"""

import dataclasses
import enum
import os
import tempfile
import threading

from mcomix import archive_packer
from mcomix import archive_tools
from mcomix import log
from mcomix import tools
from mcomix.archive import archive_base
from mcomix.archive import password as archive_password
from mcomix.i18n import _


class Fault(enum.Enum):
    """What is wrong with a book."""
    NOT_AN_ARCHIVE = enum.auto()
    NO_READER = enum.auto()
    ENCRYPTED = enum.auto()
    DAMAGED = enum.auto()

    def describe(self) -> str:
        """The fault as it is named after a book's name."""
        if self is Fault.NOT_AN_ARCHIVE:
            return _('damaged, or not an archive')
        if self is Fault.NO_READER:
            return _('nothing installed here reads the format')
        if self is Fault.ENCRYPTED:
            return _('encrypted')
        return _('damaged')


@dataclasses.dataclass(frozen=True)
class Checked:
    """A book that cannot be read in full: why, and for a damaged one,
    the files of it that cannot be read, to why."""
    fault: Fault
    unreadable: dict[str, str] = dataclasses.field(default_factory=dict)


class Stopped(Exception):
    """The check was stopped before the book was read through."""


def check(path: str, stop: threading.Event) -> Checked | None:
    """How the book at <path> cannot be read in full, or None where
    every file of it reads.

    Every file is unpacked, and each is deleted again as it comes out.
    No password is asked for: a book that wants one is encrypted.  A
    later volume of a split archive is read with its first, and a book
    whose file is not there is no book to read ("Books whose file is
    not there" selects those): both answer None.  Raises Stopped where
    <stop> was set, and OSError where the disk, not the book, failed.
    """
    if not os.path.isfile(path) or archive_tools.is_later_volume(path):
        return None
    archive_type = archive_tools.archive_mime_type(path)
    if archive_type is None:
        return Checked(Fault.NOT_AN_ARCHIVE)
    archive = archive_tools.get_archive_handler(path, archive_type)
    if archive is None:
        return Checked(Fault.NO_READER)
    if stop.is_set():
        raise Stopped()
    directory = tempfile.mkdtemp(prefix='mcomix-check.',
                                 dir=archive_packer.working_folder())
    try:
        return _read_through(path, archive, directory, stop)
    finally:
        archive.close()
        tools.remove_tree(directory)


def _read_through(path: str, archive: archive_base.BaseArchive,
                  directory: str, stop: threading.Event) -> Checked | None:
    with archive_password.never_asked() as withheld:

        def fatal(error: Exception) -> None:
            if withheld.wanted or _the_disk(error):
                raise error

        came_out: set[str] = set()

        def unpacked(name: str) -> None:
            if stop.is_set():
                raise Stopped()
            file = os.path.join(directory, name)
            if os.path.isfile(file):
                came_out.add(name)
                tools.remove_file(file)

        try:
            names = [name for name in archive.list_contents()
                     if not name.endswith('/')]
            unreadable = archive_tools.extract_each(
                archive, names, directory, unpacked, fatal)
        except Stopped:
            raise
        except Exception as error:
            if withheld.wanted:
                return Checked(Fault.ENCRYPTED)
            if _the_disk(error):
                raise
            log.debug('"%s" cannot be read: %s', path, error)
            return Checked(Fault.NOT_AN_ARCHIVE)
    if withheld.wanted:
        return Checked(Fault.ENCRYPTED)
    for name in names:
        if name not in came_out and name not in unreadable:
            unreadable[name] = 'nothing came out of it'
    if unreadable:
        return Checked(Fault.DAMAGED, unreadable)
    return None


def _the_disk(error: Exception) -> bool:
    """Whether <error> is the disk's or the system's, not the book's."""
    return isinstance(error, OSError) \
        and error.errno in archive_tools.NOT_THE_FILE

# vim: expandtab:sw=4:ts=4
