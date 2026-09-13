# -*- coding: utf-8 -*-

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
        return ['-Z1']

    def _get_extract_arguments(self) -> list[str]:
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
