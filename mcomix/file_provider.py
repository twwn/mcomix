""" file_provider.py - Handles listing files for the current directory and
    switching to the next/previous directory. """

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
    """ Initialize a FileProvider with the files in <filelist>.
    If len(filelist) is 1, a OrderedFileProvider will be constructed, which
    will simply open all files in the passed directory.
    If len(filelist) is greater 1, a PreDefinedFileProvider will be created,
    which will only ever list the files that were passed into it.
    If len(filelist) is zero, FileProvider will look at the last file opened,
    if "Auto Open last file" is set. Otherwise, no provider is constructed. """

    provider: FileProvider | None
    if len(filelist) > 0:
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
    """ Base class for various file listing strategies. """

    # Constants for determining which files to list.
    IMAGES, ARCHIVES = 1, 2

    def set_directory(self, file_or_directory: str) -> None:
        pass

    def get_directory(self) -> str:
        return os.path.abspath(os.getcwd())

    def list_files(self, mode: int = IMAGES) -> list[str]:
        return []

    def next_directory(self) -> bool:
        return False

    def previous_directory(self) -> bool:
        return False

    @staticmethod
    def sort_files(files: list[str]) -> None:
        """ Sorts a list of C{files} depending on the current preferences.
        The list is sorted in-place. """
        if preferences.prefs['sort by'] == constants.SORT_NAME:
            tools.alphanumeric_sort(files)
        elif preferences.prefs['sort by'] == constants.SORT_NAME_GLIB:
            files.sort(key=lambda filename: GLib.utf8_collate_key_for_filename(os.path.basename(filename), -1))
        elif preferences.prefs['sort by'] == constants.SORT_LAST_MODIFIED:
            # Most recently modified file first
            files.sort(key=lambda filename: -_modification_time(filename))
        elif preferences.prefs['sort by'] == constants.SORT_SIZE:
            # Smallest file first
            files.sort(key=_file_size)
        # else: don't sort at all: use OS ordering.

        # Default is ascending.
        if preferences.prefs['sort order'] == constants.SORT_DESCENDING:
            files.reverse()


class OrderedFileProvider(FileProvider):
    """ This provider will list all files in the same directory as the
        one passed to the constructor. """

    def __init__(self, file_or_directory: str) -> None:
        """ Initializes the file listing. If <file_or_directory> is a file,
            directory will be used as base path. If it is a directory, that
            will be used as base file. """

        self.set_directory(file_or_directory)

    def set_directory(self, file_or_directory: str) -> None:
        """ Sets the base directory. """

        if os.path.isdir(file_or_directory):
            dir = file_or_directory
        elif os.path.isfile(file_or_directory):
            dir = os.path.dirname(file_or_directory)
        else:
            # Passed file doesn't exist
            raise ValueError(_("Invalid path: '%s'") % file_or_directory)

        self.base_dir = os.path.abspath(dir)

    def get_directory(self) -> str:
        return self.base_dir

    def list_files(self, mode: int = FileProvider.IMAGES) -> list[str]:
        """ Lists all files in the current directory.
            Returns a list of absolute paths, already sorted. """

        should_accept: Callable[[str], bool]
        if mode == FileProvider.IMAGES:
            should_accept = image_tools.is_image_file
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

    def next_directory(self) -> bool:
        """ Switches to the next sibling directory. Next call to
            list_file() returns files in the new directory.
            Returns True if the directory was changed, otherwise False. """

        return self.__switch_directory(1)

    def previous_directory(self) -> bool:
        """ Switches to the previous sibling directory. Next call to
            list_file() returns files in the new directory.
            Returns True if the directory was changed, otherwise False. """

        return self.__switch_directory(-1)

    def __switch_directory(self, offset: int) -> bool:
        """ Switches to the sibling directory <offset> places away, and
            returns True if there was one. """

        directories = self.__get_sibling_directories(self.base_dir)
        try:
            index = directories.index(self.base_dir) + offset
        except ValueError:
            # The directory is not among its own siblings: it is the root of
            # the file system, or it was removed while it was open.
            return False
        if 0 <= index < len(directories):
            self.base_dir = directories[index]
            return True
        return False

    def __get_sibling_directories(self, dir: str) -> list[str]:
        """ Returns a list of all sibling directories of <dir>,
            already sorted. Empty if the parent cannot be read, which
            leaves the caller where it was. """

        parent_dir = os.path.dirname(dir)
        try:
            entries = os.listdir(parent_dir)
        except OSError:
            log.warning('! ' + _('Could not open %s: Permission denied.'), parent_dir)
            return []

        directories = [path for path in
                       (os.path.join(parent_dir, entry) for entry in entries)
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
            elif image_tools.is_image_file(file):
                self.__files[FileProvider.IMAGES].append(os.path.abspath(file))
            elif archive_tools.is_archive_file(file):
                self.__files[FileProvider.ARCHIVES].append(os.path.abspath(file))

    def list_files(self, mode: int = FileProvider.IMAGES) -> list[str]:
        """The files of the kind <mode> asks for.

        A mode that is neither of the two lists everything, which is
        what the ordered provider does with one.
        """
        if mode in self.__files:
            return self.__files[mode]
        return [path for listed in self.__files.values() for path in listed]


# vim: expandtab:sw=4:ts=4
