""" Base class for unified handling of various archive formats. Used for simplifying
extraction and adding new archive formats. """

import os
import errno
import threading
from collections.abc import Callable, Iterable, Iterator
from typing import IO

from mcomix import portability
from mcomix import i18n
from mcomix import process
from mcomix import callback
from mcomix.archive import password as archive_password


class BaseArchive:
    """ Base archive interface. All filenames passed from and into archives
    are expected to be Unicode objects. Archive files are converted to
    Unicode with some guess-work. """

    # True if concurrent calls to extract is supported.
    support_concurrent_extractions = False

    def __init__(self, archive: str) -> None:
        assert isinstance(archive, str), "File should be an Unicode string."

        self.archive = archive
        self._password: str | None = None
        self._event = threading.Event()
        if self.support_concurrent_extractions:
            # When multiple concurrent extractions are supported,
            # we need a lock to handle concurent calls to _get_password.
            self._lock = threading.Lock()
            self._waiting_for_password = False

    def iter_contents(self) -> Iterator[str]:
        """ Lists the archive contents.  A base archive holds nothing;
        every handler overrides this with a generator of its own.
        """
        return iter(())

    def list_contents(self) -> list[str]:
        """ Returns a list of unicode filenames relative to the archive root.
        These names do not necessarily exist in the actual archive since they
        need to saveable on the local filesystems, so some characters might
        need to be replaced. """

        return list(self.iter_contents())

    def extract(self, filename: str, destination_dir: str) -> None:
        """ Extracts the file specified by <filename>. This filename must
        be obtained by calling list_contents(). The file is saved to
        <destination_dir>. """

        assert isinstance(filename, str) and \
            isinstance(destination_dir, str)

    def iter_extract(self, entries: Iterable[str], destination_dir: str) -> Iterator[str]:
        """ Generator to extract <entries> from archive to <destination_dir>. """
        wanted = set(entries)
        for filename in self.iter_contents():
            if filename not in wanted:
                continue
            self.extract(filename, destination_dir)
            yield filename
            wanted.remove(filename)
            if not wanted:
                break

    def close(self) -> None:
        """ Closes the archive and releases held resources. """

        pass

    @staticmethod
    def is_available() -> bool:
        """ Whether this archiver can be used.  Handlers that need an
        external program or an optional module override this. """
        return True

    def is_solid(self) -> bool:
        """ Returns True if the archive is solid and extraction should be done
        in one pass. """
        return False

    def _replace_invalid_filesystem_chars(self, filename: str) -> str:
        """ Replaces characters in <filename> that cannot be saved to the disk
        with underscore and returns the cleaned-up name. """

        unsafe_chars = portability.invalid_filesystem_chars()
        translation_table = {}
        replacement_char = '_'
        for char in unsafe_chars:
            translation_table[ord(char)] = replacement_char

        new_name = filename.translate(translation_table)

        # Make sure the filename does not contain portions that might
        # traverse directories, i.e. do not allow absolute paths
        # and paths containing ../
        # Note that str.lstrip() cannot be used to drop the leading "../"
        # and separators here, as it strips a set of characters rather than
        # a prefix, and would eat the leading dot of names like ".foo.jpg".
        normalized = os.path.splitdrive(os.path.normpath(new_name))[1]
        return os.sep.join(part for part in normalized.split(os.sep)
                           if part not in ('', os.curdir, os.pardir))

    def _create_directory(self, directory: str) -> None:
        """ Recursively create a directory if it doesn't exist yet. """
        if os.path.exists(directory):
            return
        try:
            os.makedirs(directory)
        except OSError as e:
            # Can happen with concurrent calls.
            if e.errno != errno.EEXIST:
                raise e

    def _create_file(self, dst_path: str) -> IO[bytes]:
        """ Open <dst_path> for writing, making sure base directory exists. """
        dst_dir = os.path.dirname(dst_path)
        # Create directory if it doesn't exist
        self._create_directory(dst_dir)
        return open(dst_path, 'wb')

    @callback.Callback
    def _password_required(self) -> None:
        """ Asks the user for a password and sets <self._password>.
        If <self._password> is None, no password has been requested yet.
        If an empty string is set, assume that the user did not provide
        a password.

        The dialog is not waited for here.  This runs on the main thread,
        by way of the Callback decorator, while the thread that wanted the
        password waits on <self._event> in _get_password(). """

        def got_password(password: str | None) -> None:
            self._password = password if password is not None else ""
            self._event.set()

        archive_password.ask_for_password(self.archive, got_password)

    def _get_password(self) -> str:
        """ Returns the password for this archive, asking for it once if it
        has not been asked for yet.  Blocks until the dialog is answered. """
        ask_for_password = self._password is None
        # Don't trigger concurrent password dialogs.
        if ask_for_password and self.support_concurrent_extractions:
            with self._lock:
                if self._waiting_for_password:
                    ask_for_password = False
                else:
                    self._waiting_for_password = True
        if ask_for_password:
            self._password_required()
        self._event.wait()
        # got_password() sets the event only after assigning the password,
        # so by here it is a string, empty if the user gave none.
        assert self._password is not None
        return self._password


class NonUnicodeArchive(BaseArchive):
    """ Base class for archives that manage a conversion of byte member names ->
    Unicode member names internally. Required for formats that do not provide
    wide character member names. """

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        # Maps Unicode names to regular names as expected by the original archive format
        self.unicode_mapping: dict[str, str] = {}

    def _unicode_filename(self, filename: str,
                          conversion_func: Callable[[str], str] = i18n.to_unicode) -> str:
        """ Instead of returning archive members directly, map each filename through
        this function first to convert them to Unicode. """

        unicode_name = conversion_func(filename)
        safe_name = self._replace_invalid_filesystem_chars(unicode_name)
        self.unicode_mapping[safe_name] = filename
        return safe_name

    def _original_filename(self, filename: str) -> str:
        """ Map Unicode filename back to original archive name.  Names that
        were never listed have no mapping, and stand for themselves. """
        return self.unicode_mapping.get(filename, filename)


class ExternalExecutableArchive(NonUnicodeArchive):
    """ For archives that are extracted by spawning an external
    application. """

    # Since we're using an external program for extraction,
    # concurrent calls are supported.
    support_concurrent_extractions = True

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        # Flag to determine if list_contents() has been called
        # This builds the Unicode mapping and is likely required
        # for extracting filenames that have been internally mapped.
        self.filenames_initialized = False

    @property
    def _executable(self) -> str:
        """ The executable, for the code paths that have already found
        _get_executable() answers.  Raising here names the invariant
        rather than letting None into an argument vector. """
        executable = self._get_executable()
        if not executable:
            raise ValueError('%s has no executable to run.' % type(self).__name__)
        return executable

    def _get_executable(self) -> str | None:
        """ Returns the executable's name or path. Return None if no executable
        was found on the system. """
        raise NotImplementedError("Subclasses must override _get_executable.")

    def _get_list_arguments(self) -> list[str]:
        """ Returns an array of arguments required for the executable
        to produce a list of archive members. """
        raise NotImplementedError("Subclasses must override _get_list_arguments.")

    def _get_extract_arguments(self) -> list[str]:
        """ Returns an array of arguments required for the executable
        to extract a file to STDOUT. """
        raise NotImplementedError("Subclasses must override _get_extract_arguments.")

    def _parse_list_output_line(self, line: str) -> str | None:
        """ Parses the output of the external executable's list command
        and return either a file path relative to the archive's root,
        or None if the current line doesn't contain any file references. """

        return line

    def _flush_pending_entry(self) -> str | None:
        """The entry the parser is still holding back, if it was a file.

        A listing that names an entry on one line and says what it *is*
        on a later one - which both 7z and rar do, and which is the only
        way to tell a directory from a file - cannot be parsed by
        returning each name as it is read.  Such a parser holds the name
        back until the next entry begins, and this hands over whichever
        one it was still holding when the listing ended.  A parser that
        decides on the spot holds nothing back.
        """
        return None

    def iter_contents(self) -> Iterator[str]:
        if not self._get_executable():
            return

        proc = process.popen([self._executable] +
                             self._get_list_arguments() +
                             [self.archive])
        assert proc.stdout is not None
        try:
            for raw_line in proc.stdout:
                # The listing is read as bytes, as the encoding the external
                # tool uses for member names is not known in advance.
                line = i18n.to_unicode(raw_line).rstrip('\r\n')
                filename = self._parse_list_output_line(line)
                if filename is not None:
                    yield self._unicode_filename(filename)
            pending = self._flush_pending_entry()
            if pending is not None:
                yield self._unicode_filename(pending)
        finally:
            proc.stdout.close()
            proc.wait()

        self.filenames_initialized = True

    def extract(self, filename: str, destination_dir: str) -> None:
        """ Extract <filename> from the archive to <destination_dir>. """
        assert isinstance(filename, str) \
            and isinstance(destination_dir, str)

        if not self._get_executable():
            return

        if not self.filenames_initialized:
            self.list_contents()

        output = self._create_file(os.path.join(destination_dir, filename))
        try:
            process.call([self._executable] +
                         self._get_extract_arguments() +
                         [self.archive, self._original_filename(filename)],
                         stdout=output)
        finally:
            output.close()


class DisabledArchive(BaseArchive):
    """Returned to indicate that a requested archiver is unavailable."""

    def __init__(self, archive: str) -> None:
        super().__init__(archive)

    @staticmethod
    def is_available() -> bool:
        """Status of this archiver (always false)."""
        return False

# vim: expandtab:sw=4:ts=4
