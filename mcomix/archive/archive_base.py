""" Base class for unified handling of various archive formats. Used for simplifying
extraction and adding new archive formats. """

import calendar
import datetime
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
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
    #: The memory, in bytes, that each extraction thread costs besides
    #: the thread: 0, unless each thread drives a process of its own.
    extraction_thread_memory = 0
    #: The program or Python module this handler needs, by the name the
    #: reader would install it under; None for a format Python reads
    #: itself.  Named to a reader whose MComix has no handler for an
    #: archive.
    helper: str | None = None

    def __init__(self, archive: str) -> None:
        assert isinstance(archive, str), "File should be an Unicode string."

        self.archive = archive
        self._password: str | None = None
        self._event = threading.Event()
        #: When each member was last modified, as the archive records
        #: it, in seconds since the epoch: filled in while listing, by
        #: the name the format itself gives the member, by the handlers
        #: whose format keeps a date.
        self._dates: dict[str, float] = {}
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

    def member_date(self, name: str) -> float | None:
        """When member <name>, as the listing gave it, was last
        modified, in seconds since the epoch: None where the format
        keeps no date, or the listing has not reached the member."""
        return self._dates.get(name)

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
        """ Recursively create a directory if it doesn't exist yet.

        Extraction threads may make the same one at the same time. """
        os.makedirs(directory, exist_ok=True)

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
            if self._password:
                archive_password.remember(self.archive, self._password)
            self._event.set()

        archive_password.ask_for_password(self.archive, got_password)

    def forget_password(self) -> None:
        """Forget the password kept for this archive, if it used one:
        something would not unpack, and a wrong password kept for the
        session would leave the book unreadable until MComix closed."""
        if self._password:
            archive_password.forget(self.archive)

    def _get_password(self) -> str:
        """ Returns the password for this archive, asking for it once if it
        has not been asked for yet.  Blocks until the dialog is answered.

        Inside archive_password.never_asked() nothing is asked and the
        answer is no password, which is not remembered: a prompt the
        reader does ask for, by opening the book, still comes. """
        if self._password is None and archive_password.withheld_here():
            # A password typed earlier is not used either: what works
            # through archives unasked - thumbnails, the library - would
            # write the pages of an encrypted book to a shared cache.
            return ''
        if self._password is None:
            remembered = archive_password.remembered(self.archive)
            if remembered is not None:
                self._password = remembered
                return remembered
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
        if threading.current_thread() is threading.main_thread():
            # The prompt is answered by the main loop, and this is the
            # thread that runs it: the library lists an archive it adds
            # here, between turns of the loop.  Waiting on the event
            # stopped the only loop that could set it, and MComix froze
            # with the prompt on screen, so turn the loop until then.
            from gi.repository import GLib
            context = GLib.MainContext.default()
            while not self._event.is_set():
                context.iteration(True)
        self._event.wait()
        # got_password() sets the event only after assigning the password,
        # so by here it is a string, empty if the user gave none.
        assert self._password is not None
        return self._password


def name_encoding(raw_names: Sequence[bytes], fallback: str) -> str:
    """The encoding the member names <raw_names> were written in.

    An archive format that does not say - a zip name without its UTF-8
    flag, any tar name - holds whatever the program that wrote it used:
    UTF-8 from most tools of the last twenty years, the code page of its
    language from Windows, and a DOS code page from DOS and from
    Windows' zip folders.  UTF-8 is taken if every name is UTF-8.
    Otherwise the choice is between chardet's guess at all the names at
    once, where it is installed (one name is too short to tell a code
    page by: it read a Shift-JIS "表紙.jpg" as Windows-1252), the DOS
    code pages and <fallback>, which has to decode any byte, by what
    reads them best (i18n.best_decoding()), chardet's guess first.
    """
    if i18n.best_decoding(raw_names, ['utf-8']) is not None:
        return 'utf-8'
    candidates = []
    guessed = i18n.guess_encoding(b'\n'.join(raw_names), sure=True)
    if guessed is not None:
        candidates.append(guessed)
    candidates.extend(i18n.DOS_CODE_PAGES)
    candidates.append(fallback)
    return i18n.best_decoding(raw_names, candidates) or fallback


def surrogate_name_decoder(names: Sequence[str]) -> Callable[[str], str]:
    """How to read back those of <names> that are not UTF-8.

    tarfile, and the 7z handler, read a name as UTF-8 and keep the bytes
    they cannot as lone surrogates, which GTK refuses in a label or a
    title and the log refuses to write.  Those names are turned back into their bytes and
    read in the encoding name_encoding() finds for all of
    them, Latin-1 where it finds none: that reads any byte, so what is
    listed is always text that can be shown.
    """
    raw = [name.encode('utf-8', 'surrogateescape') for name in names
           if _has_surrogates(name)]
    if not raw:
        return lambda name: name
    chosen = name_encoding(raw, 'latin-1')

    def decode(name: str) -> str:
        if not _has_surrogates(name):
            return name
        return name.encode('utf-8', 'surrogateescape').decode(chosen)
    return decode


def _has_surrogates(name: str) -> bool:
    """Whether <name> holds bytes tarfile could not read as UTF-8."""
    try:
        name.encode('utf-8')
    except UnicodeEncodeError:
        return True
    return False


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

    def member_date(self, name: str) -> float | None:
        """As BaseArchive.member_date(), whose dates are kept by the
        name inside the archive rather than the one listed."""
        return self._dates.get(self._original_filename(name))


def local_timestamp(text: str) -> float | None:
    """The time "YYYY-MM-DD HH:MM:SS" in <text>, local time as archivers
    print it, in seconds since the epoch; anything after the seconds
    (a fraction) is left out.  None for text that is not such a time."""
    try:
        return datetime.datetime.strptime(
            text.strip()[:19], '%Y-%m-%d %H:%M:%S').timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def today_shifted_timestamp(text: str) -> float | None:
    """The time "YYYY-MM-DD HH:MM:SS" in <text>, as 7z prints a time
    the archive keeps in UTC: moved into local time by the offset from
    UTC in force now, rather than the one in force on that date, so a
    date in winter came out an hour late in summer.  In seconds since
    the epoch; None for text that is not such a time."""
    try:
        shown = datetime.datetime.strptime(text.strip()[:19],
                                           '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None
    offset = time.localtime().tm_gmtoff
    return calendar.timegm(shown.timetuple()) - offset


def dos_timestamp(packed: int) -> float | None:
    """The time a DOS date and time packed into 32 bits stand for, the
    date in the high half, local time, in seconds since the epoch.  None
    where the fields are not a time."""
    date, clock = packed >> 16, packed & 0xFFFF
    try:
        return datetime.datetime(
            (date >> 9) + 1980, (date >> 5) & 15, date & 31,
            clock >> 11, (clock >> 5) & 63, (clock & 31) * 2).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def utf8_environment() -> dict[str, str] | None:
    """The environment an external archiver runs in: MComix' own, in a
    UTF-8 locale.

    unrar and unzip write the names they list in the character set of
    their locale, and read the names they are given the same way, while
    MComix reads their listings as UTF-8.  Under C, unrar wrote every
    letter outside ASCII as '?' and unzip as '#U' and its code, and
    under a Latin-1 locale neither listing was UTF-8 at all.  C.UTF-8 is
    there on any glibc from 2.35 and on musl; where it is not, the C
    library falls back to C, which is no worse than before.  Windows has
    no such locale, and its archivers speak the console's code page.
    """
    if sys.platform == 'win32':
        return None
    return dict(os.environ, LC_ALL='C.UTF-8')


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
                             [self.archive], env=utf8_environment())
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
                         stdout=output, env=utf8_environment())
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
