# -*- coding: utf-8 -*-

""" LHA archive extractor. """

import functools
import re

from mcomix import process
from mcomix.archive import archive_base

class LhaArchive(archive_base.ExternalExecutableArchive):
    """ LHA file extractor using the lha executable. """

    def _get_executable(self) -> str | None:
        return LhaArchive._find_lha_executable()

    #: A listing line looks like
    #: "-rw-------  1000/1000  332 100.0% Apr 12  2015 arg.jpeg":
    #: permissions, owner, size, ratio, a three part timestamp, then the name,
    #: which may itself contain spaces.
    _LIST_LINE_RE = re.compile(
        r'^\S+\s+\S+\s+\d+\s+[\d.]+%\s+\S+\s+\d+\s+\S+\s+(.+)$')

    def _get_list_arguments(self) -> list[str]:
        # The command letter and its options have to be a single argument,
        # and quiet level 2 drops the header and footer lines.
        return ['lq2']

    def _get_extract_arguments(self) -> list[str]:
        return ['pq2']

    def _parse_list_output_line(self, line: str) -> str | None:
        match = self._LIST_LINE_RE.match(line)
        if match:
            return match.group(1)
        else:
            return None

    @staticmethod
    @functools.cache
    def _find_lha_executable() -> str | None:
        """ Tries to start lha, and returns either 'lha' if
        it was started successfully or None otherwise. """
        return process.find_executable(('lha',))

    @staticmethod
    def is_available() -> bool:
        return bool(LhaArchive._find_lha_executable())


# vim: expandtab:sw=4:ts=4
