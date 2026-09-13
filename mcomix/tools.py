"""tools.py - Contains various helper functions."""

import bisect
import contextlib
import gc
import itertools
import math
import operator
import os
import re
import sys
import tempfile
from functools import reduce
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from typing import Any, IO, Protocol, TypeVar

Numeric = TypeVar('Numeric', int, float)
#: Whatever a vector happens to hold, where nothing is done to it.
T = TypeVar('T')


class SupportsLessThan(Protocol):
    """Anything that can be put in order, which needs only __lt__:
    Python answers a > b with b.__lt__(a) when a has no __gt__."""

    def __lt__(self, other: Any, /) -> bool: ...  # type: ignore[explicit-any]  # a protocol asking for object matches no real __lt__


Comparable = TypeVar('Comparable', bound=SupportsLessThan)

NUMERIC_REGEXP = re.compile(r"\d+|\D+")  # Split into numerics and characters
PREFIXED_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB", "RiB", "QiB")


def cmp(a: Comparable, b: Comparable) -> int:
    """ Forward port of Python2's cmp function """
    return (b < a) - (a < b)


class AlphanumericSortKey:
    """ Compares two strings by their natural order (i.e. 1 before 10) """
    def __init__(self, filename: str) -> None:
        self.filename_parts: list[int | str] = [
            int(part) if part.isdigit() else part
            for part in NUMERIC_REGEXP.findall(filename.lower())
        ]

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

        return False


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
    """The directory MComix treats as the user's own.

    The home directory itself on UNIX-like systems, e.g. /home/username.
    On Windows it is an MComix directory inside the user's profile,
    since Windows has no convention of dotfiles in the profile root.
    """
    if sys.platform == 'win32':
        return os.path.join(os.path.expanduser('~'), 'MComix')
    else:
        return os.path.expanduser('~')


def get_config_directory() -> str:
    """Return the path to the MComix config directory. On UNIX, this will
    be $XDG_CONFIG_HOME/mcomix, on Windows it will be in %APPDATA%/MComix.

    See http://standards.freedesktop.org/basedir-spec/latest/ for more
    information on the $XDG_CONFIG_HOME environmental variable.
    """
    if sys.platform == 'win32':
        return os.path.join(os.path.expandvars('%APPDATA%'), 'MComix')
    else:
        base_path = os.getenv('XDG_CONFIG_HOME',
                              os.path.join(get_home_directory(), '.config'))
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
        base_path = os.getenv('XDG_DATA_HOME',
                              os.path.join(get_home_directory(), '.local/share'))
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
        cache_dir = os.getenv('XDG_CACHE_HOME',
                              os.path.join(get_home_directory(), '.cache'))
        cache_dir = os.path.join(cache_dir, 'thumbnails')

    return os.path.join(cache_dir, 'normal')


def number_of_digits(n: int) -> int:
    if n == 0:
        return 1
    return int(math.log10(abs(n))) + 1


def decompose_byte_size_exponent(n: float) -> tuple[float, int]:
    e = 0
    while n > 1024.0:
        n /= 1024.0
        e += 1
    return (n, e)


def byte_size_exponent_to_prefix(e: int) -> str:
    return PREFIXED_BYTE_UNITS[min(e, len(PREFIXED_BYTE_UNITS) - 1)]


def format_byte_size(n: float) -> str:
    nn, e = decompose_byte_size_exponent(n)
    return ('%d %s' if nn == int(nn) else '%.1f %s') % \
        (nn, byte_size_exponent_to_prefix(e))


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
    means reading position i back into dimension order[i].  What used to
    stand here was list(range(len(order))) indexed by order and then by
    itself, which is order copied out again: an inverse only for a
    permutation that is its own, which the two MComix passes -
    NORMAL_AXES and SWAPPED_AXES, the only permutations of two - both
    are.
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


@contextlib.contextmanager
def atomic_write(path: str, binary: bool = False) -> "Iterator[IO[Any]]":  # type: ignore[explicit-any]  # the mode decides whether it is text or bytes
    """ Context manager that yields a file object for writing to <path>.

    The data is written to a temporary file in the same directory, which is
    only renamed over <path> after writing finished without error.  Since
    that rename is atomic, concurrently running instances can neither read a
    half-written file nor leave a truncated one behind by writing at the
    same time. """
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
