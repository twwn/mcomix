"""file_provider.py - Which files make up the book that is open.

The file handler asks a provider for the files to read and gets back a
sorted list of absolute paths, of one kind at a time: the pictures or
the archives.  Which provider it holds depends on what MComix was asked
to open - a directory to walk through, or a set of files chosen on
purpose - and get_file_provider() picks one.
"""

import os
from gi.repository import GLib

from mcomix import image_tools
from mcomix import archive_tools
from mcomix import tools
from mcomix import constants
from mcomix import preferences
from mcomix import log
from mcomix.i18n import _

from collections.abc import Callable, Sequence

# Listing a directory and sorting what it held are two steps, and sorting
# by size or by date has to stat every name to do it, so a file can be
# deleted in between.  One that has gone sorts as if it were empty and
# ancient, losing its place, rather than taking the whole listing with it.


def _modification_time(filename: str) -> float:
    """ Returns the time <filename> was last modified, or 0 if it
    cannot be read. """

    try:
        return os.path.getmtime(filename)
    except OSError:
        return 0.0


def _file_size(filename: str) -> int:
    """ Returns the size of <filename> in bytes, or 0 if it cannot be
    read. """

    try:
        return os.path.getsize(filename)
    except OSError:
        return 0


def _every_file(path: str) -> bool:
    """Accept whatever the directory holds, which is what a mode that
    asks for neither images nor archives means."""
    return True


def get_file_provider(filelist: Sequence[str]) -> 'FileProvider | None':
    """The provider that lists what <filelist> asks to have opened.

    One name is a book opened out of its directory, so the directory is
    listed and the neighbouring ones can be walked to: an
    OrderedFileProvider.  Several names are a set chosen on purpose, and
    a PreDefinedFileProvider lists those and nothing else.  No names at
    all is a start with no arguments, which reopens the last file where
    the "auto load last file" preference asks for it and that file is
    still there.

    None where there is nothing to list: a single name that is not
    there, or an empty list with nothing to reopen.
    """

    provider: FileProvider | None
    if filelist:
        if len(filelist) == 1:
            if os.path.exists(filelist[0]):
                provider = OrderedFileProvider(filelist[0])
            else:
                provider = None
        else:
            provider = PreDefinedFileProvider(filelist)

    elif (preferences.prefs['auto load last file']
          and os.path.isfile(preferences.prefs['path to last file'])):
        provider = OrderedFileProvider(preferences.prefs['path to last file'])

    else:
        provider = None

    return provider


class FileProvider:
    """Where the file handler gets the list of files to open from.

    Two of them: one lists a directory and can walk to the one beside
    it, the other only ever hands back the files it was given.  The
    methods here are what the file handler calls on either, and they are
    written as a provider that has nothing to offer rather than as
    abstract methods, so that a subclass only has to answer the
    questions it has an answer to - a list of files that were named on
    the command line has no directory to step out of, and says so by
    leaving next_directory() and previous_directory() alone.
    """

    #: The kinds of file a caller can ask to have listed.  The file
    #: handler opens an archive and a loose picture in quite different
    #: ways, so it asks for one kind at a time; a mode that is neither
    #: means everything, whatever it holds.
    IMAGES, ARCHIVES = 1, 2

    def set_directory(self, file_or_directory: str) -> None:
        """Point the provider at <file_or_directory>.

        A file names the directory it is in.  Nothing to do for a
        provider that lists a fixed set of files.
        """
        pass

    def get_directory(self) -> str:
        """The directory the files being listed come from.

        The working directory for a provider that is not reading one,
        which is what the file handler shows and what a file chooser
        opens on.
        """
        return os.path.abspath(os.getcwd())

    def list_files(self, mode: int = IMAGES) -> list[str]:
        """The absolute paths of the files of the kind <mode> asks for.

        Sorted the way sort_files() sorts them, which is the order the
        book is read in.
        """
        return []

    def next_directory(self, accept: "Callable[[], bool] | None" = None
                       ) -> bool:
        """Move to the directory after this one, and say whether there
        was one.  The next list_files() lists the new directory.

        With <accept>, the directories it says no to, asked while each
        is the one listed, are passed over.
        """
        return False

    def previous_directory(self, accept: "Callable[[], bool] | None" = None
                           ) -> bool:
        """Move to the directory before this one, and say whether there
        was one, as next_directory() does."""
        return False

    @staticmethod
    def sort_files(files: list[str]) -> None:
        """Sort <files> in place, the way the sort preferences say.

        One of the choices is not to sort at all, which leaves whatever
        order the file system listed them in; a descending sort order
        still reverses that.
        """
        # Files the chosen key cannot tell apart - pages copied in one
        # go share their modification time - are put in natural order
        # by name, rather than left in the order the file system listed
        # them, which is not the same from one copy of a book to the
        # next.
        if preferences.prefs['sort by'] == constants.SORT_NAME:
            tools.alphanumeric_sort(files)
        elif preferences.prefs['sort by'] == constants.SORT_NAME_GLIB:
            files.sort(key=lambda filename: (
                GLib.utf8_collate_key_for_filename(os.path.basename(filename), -1),
                tools.AlphanumericSortKey(filename)))
        elif preferences.prefs['sort by'] == constants.SORT_LAST_MODIFIED:
            # Most recently modified file first
            files.sort(key=lambda filename: (
                -_modification_time(filename),
                tools.AlphanumericSortKey(filename)))
        elif preferences.prefs['sort by'] == constants.SORT_SIZE:
            # Smallest file first
            files.sort(key=lambda filename: (
                _file_size(filename), tools.AlphanumericSortKey(filename)))
        # else: don't sort at all: use OS ordering.

        # Default is ascending.
        if preferences.prefs['sort order'] == constants.SORT_DESCENDING:
            files.reverse()


#: How far below the shelf the walk from directory to directory goes:
#: the shelf's own directories, and the ones in those.
SHELF_DEPTH = 2


class OrderedFileProvider(FileProvider):
    """Every file in one directory, and the directories around it.

    This is what opening a book does: the rest of the directory is the
    rest of the series, so the reader can walk out of one volume and
    into the next without going back to a file chooser.

    The walk stays on a shelf: the directory above the one the book
    opened by hand is in.  It visits the shelf's directories and the
    ones in them, in natural order, each directory before the ones in
    it - SHELF_DEPTH levels and no further, so a book in Series/Volume
    leads on to Series/Volume 2 and from there to the next series.  It
    never climbs above the shelf, and does not go into a directory that
    is a symbolic link, which may lead anywhere, though such a directory
    is visited itself.
    """

    def __init__(self, file_or_directory: str) -> None:
        """List the directory <file_or_directory> is in, or is.

        A path that is neither raises ValueError, which is what opening
        a file that has been deleted since it was last read comes to.
        """

        self.set_directory(file_or_directory)
        self.shelf = os.path.dirname(self.base_dir)

    def set_directory(self, file_or_directory: str) -> None:
        """List <file_or_directory> from now on, or the directory it is in."""

        if os.path.isdir(file_or_directory):
            dir = file_or_directory
        elif os.path.isfile(file_or_directory):
            dir = os.path.dirname(file_or_directory)
        else:
            # Passed file doesn't exist
            raise ValueError(_("Invalid path: '%s'") % file_or_directory)

        self.base_dir = os.path.abspath(dir)

    def get_directory(self) -> str:
        """The directory being listed."""
        return self.base_dir

    def list_files(self, mode: int = FileProvider.IMAGES) -> list[str]:
        """The files of the kind <mode> asks for, as sorted absolute paths.

        Empty where the directory cannot be read, which is reported and
        then treated as a directory holding nothing: the reader is left
        where they were rather than with a book that half opened.
        """

        should_accept: Callable[[str], bool]
        if mode == FileProvider.IMAGES:
            should_accept = image_tools.is_picture_file
        elif mode == FileProvider.ARCHIVES:
            should_accept = archive_tools.is_archive_file
        else:
            should_accept = _every_file

        try:
            entries = os.listdir(self.base_dir)
        except OSError:
            log.warning('! ' + _('Could not open %s: Permission denied.'), self.base_dir)
            return []

        files = [path for path in
                 (os.path.join(self.base_dir, entry) for entry in entries)
                 if should_accept(path)]
        FileProvider.sort_files(files)

        return files

    def next_directory(self, accept: "Callable[[], bool] | None" = None
                       ) -> bool:
        """Move to the next directory on the shelf, if there is one."""

        return self.__switch_directory(1, accept)

    def previous_directory(self, accept: "Callable[[], bool] | None" = None
                           ) -> bool:
        """Move to the directory before this one on the shelf, if there
        is one."""

        return self.__switch_directory(-1, accept)

    def __switch_directory(self, step: int,
                           accept: "Callable[[], bool] | None") -> bool:
        """Move along the shelf in the direction <step> gives, to the
        first directory <accept> takes, and say whether there was one.

        Nothing moves and False comes back at either end of the shelf,
        or where this directory is not on it.
        """

        directories = self.__shelf_directories()
        try:
            index = directories.index(self.base_dir)
        except ValueError:
            # The directory is not on the shelf: it is the root of the
            # file system, which is its own shelf, or it was removed
            # while it was open.
            return False
        start = self.base_dir
        index += step
        while 0 <= index < len(directories):
            self.base_dir = directories[index]
            if accept is None or accept():
                return True
            index += step
        self.base_dir = start
        return False

    def __shelf_directories(self) -> list[str]:
        """Every directory on the shelf, in the order the walk visits
        them: depth first, in natural order, SHELF_DEPTH levels deep.

        Empty where the shelf cannot be read, which leaves the caller
        where it was.  A directory below it that cannot be read is
        visited, with nothing visited inside it.
        """

        if self.base_dir == self.shelf:
            return []
        walk: list[str] = []

        def visit(directory: str, depth: int) -> None:
            for child in self.__directories_in(directory):
                walk.append(child)
                if depth < SHELF_DEPTH and not os.path.islink(child):
                    visit(child, depth + 1)

        visit(self.shelf, 1)
        return walk

    @staticmethod
    def __directories_in(directory: str) -> list[str]:
        """The directories in <directory>, sorted; empty where it cannot
        be read, which is reported."""

        try:
            entries = os.listdir(directory)
        except OSError:
            log.warning('! ' + _('Could not open %s: Permission denied.'), directory)
            return []

        directories = [path for path in
                       (os.path.join(directory, entry) for entry in entries)
                       if os.path.isdir(path)]

        tools.alphanumeric_sort(directories)
        return directories


class PreDefinedFileProvider(FileProvider):

    """Only the files it was given, with the two kinds kept apart.

    A list can name files of both kinds, and a directory named in it can
    hold both by itself, so each kind is listed under its own mode
    rather than the whole list being reduced to whichever kind happened
    to come first.  The file handler asks for one kind at a time and
    would not know what to do with a listing that mixed them.
    """

    def __init__(self, files: Sequence[str]) -> None:
        """Take the files to show from <files>.

        A directory named there is listed for both kinds, since which of
        them is wanted is not known until list_files() asks.
        """
        self.__files: dict[int, list[str]] = {
            FileProvider.IMAGES: [],
            FileProvider.ARCHIVES: [],
        }

        for file in files:
            if os.path.isdir(file):
                provider = OrderedFileProvider(file)
                for mode, listed in self.__files.items():
                    listed.extend(provider.list_files(mode))
            elif image_tools.is_picture_file(file):
                self.__files[FileProvider.IMAGES].append(os.path.abspath(file))
            elif archive_tools.is_archive_file(file):
                self.__files[FileProvider.ARCHIVES].append(os.path.abspath(file))

    def get_directory(self) -> str:
        """The directory the first of the listed files sits in.

        A list can name files in several directories, so there is no one
        directory it came from; the first is the one an ordered provider
        over the same book would have answered with.  The base class
        falls back on the working directory, which for a book named on
        the command line has nothing to do with where the book is, and
        the file handler writes that answer into its base path.

        Where nothing was listed - a command line of paths that are
        neither pictures nor archives - the base class's answer stands,
        there being no file to take a directory from.
        """
        for listed in self.__files.values():
            if listed:
                return os.path.dirname(listed[0])
        return super().get_directory()

    def list_files(self, mode: int = FileProvider.IMAGES) -> list[str]:
        """The files of the kind <mode> asks for.

        A mode that is neither of the two lists everything, which is
        what the ordered provider does with one.
        """
        if mode in self.__files:
            return self.__files[mode]
        return [path for listed in self.__files.values() for path in listed]


# vim: expandtab:sw=4:ts=4
