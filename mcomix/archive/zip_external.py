""" ZIP archive extractor via executable."""

import functools
import re
from collections.abc import Callable, Iterator

from mcomix import i18n
from mcomix import process
from mcomix.archive import archive_base


class ZipArchive(archive_base.ExternalExecutableArchive):
    """ ZIP file extractor using unzip executable. """

    helper = 'unzip'

    #: A line of "unzip -ZT", which puts a member's date in one piece:
    #: "-rw-r--r--  3.0 unx  1 tx stor 20261005.134510 a b.jpg".
    _DATED_LINE_RE = re.compile(
        r'^\S+\s+\S+\s+\S+\s+\d+\s+\S+\s+\S+\s+'
        r'(\d{4})(\d\d)(\d\d)\.(\d\d)(\d\d)(\d\d)\s(.*)$')

    def _get_executable(self) -> str | None:
        return ZipArchive._find_unzip_executable()

    def _get_list_arguments(self) -> list[str]:
        """The switches that list the archive.

        "-Z1" puts unzip in its zipinfo mode and asks for names alone,
        one to a line, rather than a table with a header and a summary.
        """
        return ['-Z1']

    def iter_contents(self) -> Iterator[str]:
        """The names, as unzip lists them one to a line, then the dates
        from a second listing.

        Kept apart because the names are what the book is: a line of
        the dated listing that did not read as expected costs a date
        that has something to fall back on, and not a page.
        """
        yield from super().iter_contents()
        if self._get_executable():
            self._read_dates()

    def _read_dates(self) -> None:
        """Note when each member was last modified, local time as a zip
        keeps it, by the name it is asked for by."""
        proc = process.popen([self._executable, '-ZT', self.archive],
                             env=archive_base.utf8_environment())
        assert proc.stdout is not None
        try:
            for raw_line in proc.stdout:
                match = self._DATED_LINE_RE.match(
                    i18n.to_unicode(raw_line).rstrip('\r\n'))
                if match is None:
                    continue
                year, month, day, hour, minute, second, name = match.groups()
                date = archive_base.local_timestamp(
                    f'{year}-{month}-{day} {hour}:{minute}:{second}')
                if date is not None:
                    self._dates[self._as_pattern(name)] = date
        finally:
            proc.stdout.close()
            proc.wait()

    def _get_extract_arguments(self) -> list[str]:
        """The switches that write a member to standard output.

        "-p" is what sends it there; "-P ''" hands over an empty
        password, which keeps unzip from stopping to read one from a
        terminal that is not there when it meets an encrypted member.
        """
        return ['-p', '-P', '']

    @staticmethod
    @functools.cache
    def _find_unzip_executable() -> str | None:
        """ Tries to run unzip, and returns 'unzip' on success.
        Returns None on failure. """
        return process.find_executable(('unzip',))

    @staticmethod
    def is_available() -> bool:
        return bool(ZipArchive._find_unzip_executable())

    def _unicode_filename(self, filename: str,
                          conversion_func: Callable[[str], str] = i18n.to_unicode) -> str:
        """Map <filename> to a name that is safe to write and to ask for.

        Two escapes on top of what the base class does, because the name
        goes back to unzip on a command line: unzip reads a member name
        as a shell-style pattern, so the characters that make one are
        wrapped in brackets to stand for themselves, and a backslash is
        doubled.
        """
        unicode_name = conversion_func(filename)
        safe_name = self._replace_invalid_filesystem_chars(unicode_name)
        self.unicode_mapping[safe_name] = self._as_pattern(filename)
        return safe_name

    @staticmethod
    def _as_pattern(filename: str) -> str:
        """<filename> as unzip has to be asked for it."""
        # As it turns out, unzip will try to interpret filenames as glob...
        for c in '[*?':
            filename = filename.replace(c, '[' + c + ']')
        # Won't work on Windows...
        return filename.replace('\\', '\\\\')

# vim: expandtab:sw=4:ts=4
