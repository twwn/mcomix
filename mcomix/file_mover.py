"""file_mover.py - Moving the opened file, or the archive it is in,
into another directory."""

import errno
import os
import shutil


def same_file_system(path: str, directory: str) -> bool:
    """Whether <path> and <directory> live on the same file system.

    Two paths that do share one are moved between by a rename, which
    costs nothing whatever the file weighs; two that do not are moved by
    copying the whole of it and removing the original.
    """
    return os.stat(path).st_dev == os.stat(directory).st_dev


def check_room_for(path: str, directory: str) -> None:
    """Raise ENOSPC if <path> will not fit in <directory>.

    Only a move that crosses file systems needs room at all: within one
    the file is renamed and not a byte of it is written again.  Across
    them shutil.move() copies the file and unlinks the original
    afterwards, so the whole of it has to fit at the far end before any
    of it is given up at the near one.  Letting the copy run into a full
    disk works - it raises, and the half-written file is removed - but
    only after however long it takes to write a book, and with the disk
    full in the meantime.
    """
    if same_file_system(path, directory):
        return
    if os.path.getsize(path) > shutil.disk_usage(directory).free:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), directory)


def move_file(path: str, directory: str) -> str:
    """Move <path> into <directory>, and return where it now is.

    Raises FileExistsError if <directory> holds a file of that name
    already: a move is not a way to overwrite one, and shutil.move()
    would replace it without a word.  Raises OSError for anything else
    that goes wrong on the way - no room at the far end, or a directory
    that will not be written to - having moved nothing.
    """
    target = os.path.join(directory, os.path.basename(path))
    if os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), target)
    check_room_for(path, directory)
    shutil.move(path, target)
    return target

# vim: expandtab:sw=4:ts=4
