"""tools.py - Contains various helper functions."""

import bisect
import contextlib
import ctypes
import gc
import itertools
import math
import operator
import os
import re
import sys
import tempfile
import types
from functools import reduce
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from typing import Any, IO, Protocol, TypeVar

from gi.repository import Gio, GLib

Numeric = TypeVar('Numeric', int, float)
#: Whatever a vector happens to hold, where nothing is done to it.
T = TypeVar('T')


class SupportsLessThan(Protocol):
    """Anything that can be put in order, which needs only __lt__:
    Python answers a > b with b.__lt__(a) when a has no __gt__."""

    def __lt__(self, other: Any, /) -> bool: ...  # type: ignore[explicit-any]  # a protocol asking for object matches no real __lt__


Comparable = TypeVar('Comparable', bound=SupportsLessThan)

NUMERIC_REGEXP = re.compile(r"\d+|\D+")  # Split into numerics and characters


def cmp(a: Comparable, b: Comparable) -> int:
    """ Forward port of Python2's cmp function """
    return (b < a) - (a < b)


class AlphanumericSortKey:
    """ Compares two strings by their natural order (i.e. 1 before 10) """
    def __init__(self, filename: str) -> None:
        # isdecimal() rather than isdigit(), which is also true of the
        # superscripts and the circled numbers - "m²" in a page's name
        # made int() raise and the book could not be listed at all.
        # What the regular expression splits off as a number is exactly
        # what isdecimal() is true of.
        self.filename_parts: list[int | str] = [
            int(part) if part.isdecimal() else part
            for part in NUMERIC_REGEXP.findall(filename.lower())
        ]
        #: What decides between two names the parts cannot tell apart,
        #: such as "Page1" and "page01".
        self.filename = filename

    def __lt__(self, other: 'AlphanumericSortKey') -> bool:
        for left, right in itertools.zip_longest(self.filename_parts, other.filename_parts, fillvalue=''):
            if isinstance(left, int) and isinstance(right, int):
                if left != right:
                    return left < right
            else:
                # A run of digits against a run of letters, and any two
                # runs of letters, are put in order as text.
                left_text, right_text = str(left), str(right)
                if left_text != right_text:
                    return left_text < right_text

        # Names that differ only in case or in leading zeros are put in
        # order by the names themselves, so that the order of a book's
        # pages does not depend on the order they were listed in.
        return self.filename < other.filename


def alphanumeric_sort(filenames: list[str]) -> None:
    """Do an in-place alphanumeric sort of the strings in <filenames>,
    such that for an example "1.jpg", "2.jpg", "10.jpg" is a sorted
    ordering.
    """

    filenames.sort(key=AlphanumericSortKey)


def bin_search(lst: "list[Comparable]", value: Comparable) -> int:
    """Return the index of <value> in the sorted list <lst>.

    A <value> that is not in <lst> gives the one's complement of the
    index it would be inserted at, so the answer is negative exactly
    when the search failed, and ~answer still says where the value
    belongs.  The scroller reads it that way: a viewport position that
    falls between two grid points tells it which two.
    """

    index = bisect.bisect_left(lst, value)
    if index != len(lst) and lst[index] == value:
        return index
    else:
        return ~index


def get_home_directory() -> str:
    """The user's home directory: /home/username, or the profile folder
    on Windows.

    Where the file choosers open and save by default, and what a path
    in the "Move to" menu is written as "~" under.  On Windows this was
    the MComix folder in the profile, which held MComix' settings until
    they moved to %APPDATA% (preferences.migrate_home_config_path() moves
    it there), and was left naming a folder that is no longer there.
    """
    return os.path.expanduser('~')


def _xdg_base(variable: str, default: str) -> str:
    """The base directory $<variable> names, or <default> under the home
    directory.

    The base directory specification has a variable that is empty, or
    that names a relative path, ignored in favour of the default; taken
    as it was, an empty one put MComix' files under whatever directory
    it was started from.
    """
    value = os.environ.get(variable, '')
    if os.path.isabs(value):
        return value
    return os.path.join(get_home_directory(), default)


def get_config_directory() -> str:
    """Return the path to the MComix config directory. On UNIX, this will
    be $XDG_CONFIG_HOME/mcomix, on Windows it will be in %APPDATA%/MComix.

    See http://standards.freedesktop.org/basedir-spec/latest/ for more
    information on the $XDG_CONFIG_HOME environmental variable.
    """
    if sys.platform == 'win32':
        return os.path.join(os.path.expandvars('%APPDATA%'), 'MComix')
    else:
        base_path = _xdg_base('XDG_CONFIG_HOME', '.config')
        return os.path.join(base_path, 'mcomix')


def get_data_directory() -> str:
    """Return the path to the MComix data directory. On UNIX, this will
    be $XDG_DATA_HOME/mcomix, on Windows it will be the same directory as
    get_config_directory().

    See http://standards.freedesktop.org/basedir-spec/latest/ for more
    information on the $XDG_DATA_HOME environmental variable.
    """
    if sys.platform == 'win32':
        return os.path.join(os.path.expandvars('%APPDATA%'), 'MComix')
    else:
        base_path = _xdg_base('XDG_DATA_HOME', '.local/share')
        return os.path.join(base_path, 'mcomix')


def get_thumbnail_directory() -> str:
    """Return the path to the MComix thumbnail directory. On UNIX, this will
    be in $XDG_CACHE_HOME. On Windows, DATA_DIR will be used. Refer to
    https://specifications.freedesktop.org/thumbnail/latest/directory.html
    for more information.
    """
    if sys.platform == 'win32':
        cache_dir = os.path.join(get_data_directory(), '.thumbnails')
    else:
        cache_dir = os.path.join(_xdg_base('XDG_CACHE_HOME', '.cache'),
                                 'thumbnails')

    return os.path.join(cache_dir, 'normal')


def number_of_digits(n: int) -> int:
    if n == 0:
        return 1
    return int(math.log10(abs(n))) + 1


def move_to_trash(path: str) -> None:
    """Move the file at <path> to the trash, from where it can be put back.

    What MComix deletes - a book, a page's file - goes there rather than
    being unlinked: a confirmation clicked through by mistake cost the
    file for good (upstream feature request 107).  Where the file cannot
    go to a trash - a file system that has none, a folder that cannot
    be written - GLib.Error is raised and the file stays where it is;
    it is not deleted for good instead, which is not what was asked.
    """
    Gio.File.new_for_path(path).trash(None)


def trash_refuses(path: str) -> bool:
    """Whether move_to_trash() is certain to refuse <path>, found out
    without trying.

    GLib moves a file on the home folder's device to the home trash, and
    any other to a trash at the top of its own mount, unless it counts
    that mount as internal to the system: a tmpfs, the root file system,
    and every mount whose root is not "/", which takes in a folder
    bind-mounted from another partition.  That is GLib's own rule
    (g_local_file_trash()), read here through the same calls.  A refusal
    it does not foresee, such as a mount whose trash folder cannot be
    made, still raises from move_to_trash(); where the rule cannot be
    read - on Windows, or a GLib older than 2.80 - nothing is foreseen.
    """
    gio_unix = _gio_unix()
    if gio_unix is None:
        return False
    try:
        device = os.lstat(path).st_dev
        if device == os.stat(GLib.get_home_dir()).st_dev:
            return False
        # The top of the mount: the last folder up on the same device.
        top = os.path.dirname(os.path.abspath(path))
        while (parent := os.path.dirname(top)) != top \
                and os.lstat(parent).st_dev == device:
            top = parent
    except OSError:
        return False
    return _mount_has_no_trash(gio_unix, top)


def _gio_unix() -> "types.ModuleType | None":
    """GLib's GioUnix, where there is one: GLib 2.80 on, not Windows."""
    if sys.platform == 'win32':
        return None
    try:
        import gi
        gi.require_version('GioUnix', '2.0')
        from gi.repository import GioUnix
    except (ImportError, ValueError):
        return None
    return GioUnix


def _mount_has_no_trash(gio_unix: types.ModuleType, top: str) -> bool:
    """Whether GLib keeps no trash on the mount at <top>.

    GLib 2.84 renamed the calls that say so, g_unix_mount_at() to
    g_unix_mount_entry_at() and so on, and the old names warn as
    deprecated from then on; 2.80 to 2.83, Ubuntu 24.04's among them,
    have only the old ones.  A mount GLib does not know of has no trash
    either.
    """
    if hasattr(gio_unix, 'mount_entry_at'):
        entry, _changed = gio_unix.mount_entry_at(top)
        return entry is None or bool(entry.is_system_internal())
    entry, _changed = gio_unix.mount_at(top)
    return entry is None or bool(gio_unix.mount_is_system_internal(entry))


def format_byte_size(n: int) -> str:
    """<n> bytes, written as GTK writes a size: in powers of 1000, kB
    and MB, in GLib's words for them.

    The file chooser lists its files with sizes GTK wrote, and the
    preview beside that list says the size of the same file, so the
    two have to agree.
    """
    return GLib.format_size(n)


def physical_memory() -> int | None:
    """The bytes of physical memory, or None where it cannot be told."""
    if sys.platform == 'win32':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong),
                        ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong),
                        ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong),
                        ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong),
                        ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(status)):
            return None
        return int(status.ullTotalPhys) or None
    try:
        pages = os.sysconf('SC_PHYS_PAGES')
        page_size = os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, ValueError, OSError):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return pages * page_size


#: The share of the physical memory the automatic thread count lets
#: the threads of one pool take, where each costs memory of its own.
THREAD_MEMORY_SHARE = 16


def thread_count(chosen: int, memory_each: int = 0) -> int:
    """How many worker threads a preference of <chosen> threads means.

    A positive number is taken as it is.  0, the default, is the
    automatic setting: one thread for each processor this process may
    run on, and where each thread costs <memory_each> bytes besides,
    no more than fit in a sixteenth of the physical memory.

    A thread itself costs next to nothing, and there is no ceiling on
    the processors on purpose: the pools start a thread only when there
    is an order for it, the thumbnails are made only for the rows on
    screen and a book has only so many pages.  Measured with 4, 8, 16
    and 24 of one machine's processors (at 44451e29), thumbnails of PNG
    pages and unpacking a ZIP or a 7z were fastest, or within 0.02 s of
    it, with one thread per processor.  Thumbnails of small JPEG pages,
    where the GIL is what the threads wait for, were fastest with 4 to 6
    threads however many processors there were, but lost under half a
    millisecond a thumbnail with more.

    What does cost memory is a thread that drives a process of its
    own, as each of the PDF reader's does: its own Python and PyMuPDF,
    about 130 MB, so that one per processor took 3 GB on 24 processors
    for one book.  How many of those are worth having depends on the
    book - a PDF whose pages are drawn kept gaining up to one per
    processor, one whose pages are pictures to copy out was fastest
    with 2 to 8 - so the bound is the memory they take, which is the
    same on every machine.
    """
    if chosen > 0:
        return chosen
    available: int | None
    if sys.version_info >= (3, 13):
        available = os.process_cpu_count()
    elif hasattr(os, 'sched_getaffinity'):
        available = len(os.sched_getaffinity(0))
    else:
        available = os.cpu_count()
    count = max(1, available or 1)
    if memory_each > 0:
        memory = physical_memory()
        if memory is not None:
            count = min(count, max(
                1, memory // THREAD_MEMORY_SHARE // memory_each))
    return count


def garbage_collect() -> None:
    """ Runs the garbage collector. """
    gc.collect(0)


def div(a: Numeric, b: Numeric) -> float:
    return float(a) / float(b)


def volume(t: Sequence[float]) -> float:
    return reduce(operator.mul, t, 1)


def relerr(approx: Numeric, ideal: Numeric) -> float:
    return abs(div(approx - ideal, ideal))


def smaller(a: Sequence[Numeric], b: Sequence[Numeric]) -> list[bool]:
    """ Returns a list with the i-th element set to True if and only if the i-th
    element in a is less than the i-th element in b. """
    return list(map(operator.lt, a, b))


def smaller_or_equal(a: Sequence[Numeric], b: Sequence[Numeric]) -> list[bool]:
    """ Returns a list with the i-th element set to True if and only if the i-th
    element in a is less than or equal to the i-th element in b. """
    return list(map(operator.le, a, b))


def scale(t: Sequence[Numeric], factor: Numeric) -> list[Numeric]:
    return [x * factor for x in t]


def vector_sub(a: Sequence[Numeric], b: Sequence[Numeric]) -> list[Numeric]:
    """ Subtracts vector b from vector a. """
    return list(map(operator.sub, a, b))


def vector_add(a: Sequence[Numeric], b: Sequence[Numeric]) -> list[Numeric]:
    """ Adds vector a to vector b. """
    return list(map(operator.add, a, b))


def vector_opposite(a: Sequence[Numeric]) -> list[Numeric]:
    """ Returns the opposite vector -a. """
    return list(map(operator.neg, a))


def remap_axes(vector: Sequence[T], order: Sequence[int]) -> list[T]:
    return [vector[i] for i in order]


def inverse_axis_map(order: Sequence[int]) -> list[int]:
    """Return the axis order that undoes remap_axes(..., <order>).

    remap_axes() reads dimension order[i] into position i, so undoing it
    means reading position i back into dimension order[i].
    """
    inverse = [0] * len(order)
    for position, axis in enumerate(order):
        inverse[axis] = position
    return inverse


def compile_rotations(*rotations: int) -> int:
    """ Returns the single rotation, in degrees, that <rotations> amount to.

    Each rotation was brought into range on its way in but the running
    total never was, so any pair adding up to more than a full turn came
    out as an angle nothing else here accepts: 270 and 180 gave 450
    rather than 90, which rotation_swaps_axes() reads as no swap and
    image_tools.angle_to_gdkpixbuf_rotation() refuses outright. """
    return sum(rotation % 360 for rotation in rotations) % 360


def rotation_swaps_axes(rotation: int) -> bool:
    return rotation in (90, 270)


def fixed_strings_regex(strings: Iterable[str]) -> str:
    # introduces a matching group
    unique_strings = set(strings)
    return r'(%s)' % '|'.join(sorted(re.escape(s) for s in unique_strings))


def formats_to_regex(
        formats: "Mapping[str, tuple[Collection[str], Collection[str]]]"
        ) -> "re.Pattern[str]":
    """Return a pattern matching the file extensions <formats> names.

    <formats> maps a format name to its MIME types and its extensions,
    the shape get_supported_formats() answers in; only the extensions
    are read.  The pattern matches one of them, case-insensitively, at
    the end of a name, and puts it in a group.
    """
    return re.compile(r'\.' + fixed_strings_regex(
        itertools.chain.from_iterable([e[1] for e in formats.values()])) + r'$', re.I)


def folder_prefix(folder: str) -> str:
    """<folder> as what the path of everything in it starts with: with
    the separator after it, which keeps "/comics" from taking in
    "/comics-old"."""
    folder = os.path.abspath(folder)
    return folder if folder.endswith(os.sep) else folder + os.sep


def relocated(path: str, old_folder: str, new_folder: str) -> "str | None":
    """Where <path> is now that <old_folder> is <new_folder>, or None
    where it was not in <old_folder>."""
    old = folder_prefix(old_folder)
    if not path.startswith(old):
        return None
    return folder_prefix(new_folder) + path[len(old):]


def replaced_path(path: str) -> str:
    """The file to rename a new version over, to replace <path>.

    <path> itself, unless it is a symbolic link: then the file it points
    at, so that the link stays and what it points at is what changes.
    Renamed over the link, the new file took its place - settings a
    dotfile manager had linked into place stopped reaching the file it
    keeps, and a book read through a link was saved beside the book it
    stood for.  A link whose target's directory is gone is replaced
    itself, as before.
    """
    real_path = os.path.realpath(path)
    if os.path.isdir(os.path.dirname(real_path)):
        return real_path
    return path


@contextlib.contextmanager
def atomic_write(path: str, binary: bool = False) -> "Iterator[IO[Any]]":  # type: ignore[explicit-any]  # the mode decides whether it is text or bytes
    """ Context manager that yields a file object for writing to <path>.

    The data is written to a temporary file in the same directory, which is
    only renamed over <path> after writing finished without error.  Since
    that rename is atomic, concurrently running instances can neither read a
    half-written file nor leave a truncated one behind by writing at the
    same time.  A <path> that is a symbolic link is written through, see
    replaced_path(). """
    path = replaced_path(path)
    directory = os.path.dirname(path) or os.curdir
    fd, temp_path = tempfile.mkstemp(dir=directory,
                                     prefix=os.path.basename(path) + '.',
                                     suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb' if binary else 'w') as file:
            yield file
            file.flush()
            os.fsync(file.fileno())

        try:
            # Keep the permissions of an already existing file instead of
            # silently replacing them by the restrictive ones of mkstemp.
            os.chmod(temp_path, os.stat(path).st_mode & 0o7777)
        except OSError:
            pass

        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def append_number_to_filename(filename: str, number: int) -> str:
    """ Generate a new string from filename with an appended number right
    before the extension. """
    file_no_ext = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1]
    return file_no_ext + (" (%s)" % (number)) + ext

# vim: expandtab:sw=4:ts=4
