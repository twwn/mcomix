""" ZIP archive extractor via executable."""

import functools
from collections.abc import Callable

from mcomix import i18n
from mcomix import process
from mcomix.archive import archive_base


class ZipArchive(archive_base.ExternalExecutableArchive):
    """ ZIP file extractor using unzip executable. """

    def _get_executable(self) -> str | None:
        return ZipArchive._find_unzip_executable()

    def _get_list_arguments(self) -> list[str]:
        """The switches that list the archive.

        "-Z1" puts unzip in its zipinfo mode and asks for names alone,
        one to a line, rather than a table with a header and a summary.
        """
        return ['-Z1']

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
        # As it turns out, unzip will try to interpret filenames as glob...
        for c in '[*?':
            filename = filename.replace(c, '[' + c + ']')
        # Won't work on Windows...
        filename = filename.replace('\\', '\\\\')
        self.unicode_mapping[safe_name] = filename
        return safe_name

# vim: expandtab:sw=4:ts=4
