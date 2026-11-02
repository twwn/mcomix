""" LHA archive extractor. """

import datetime
import functools
import re

from mcomix import process
from mcomix.archive import archive_base


class LhaArchive(archive_base.ExternalExecutableArchive):
    """ LHA file extractor using the lha executable. """

    helper = 'lha'

    def _get_executable(self) -> str | None:
        return LhaArchive._find_lha_executable()

    #: A listing line looks like
    #: "-rw-------  1000/1000  332 100.0% Apr 12  2015 arg.jpeg":
    #: permissions, owner, size, ratio, a three part timestamp, then the name,
    #: which may itself contain spaces.
    _LIST_LINE_RE = re.compile(
        r'^\S+\s+\S+\s+\d+\s+[\d.]+%\s+(\S+)\s+(\d+)\s+(\S+)\s+(.+)$')

    #: The months of a listing, in English whatever the locale.
    _MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')

    def _get_list_arguments(self) -> list[str]:
        # The command letter and its options have to be a single argument,
        # and quiet level 2 drops the header and footer lines.
        return ['lq2']

    def _get_extract_arguments(self) -> list[str]:
        """The command letter that writes a member to standard output."""
        return ['pq2']

    def _parse_list_output_line(self, line: str) -> str | None:
        """The name in one listing line, or None if it named nothing.

        A line whose permissions begin with "d" describes a directory,
        which is not a member anything can extract, so it names nothing
        as far as the listing is concerned.
        """
        match = self._LIST_LINE_RE.match(line)
        if match is None or line.startswith('d'):
            return None
        month, day, year_or_time, name = match.groups()
        date = self._listed_date(month, int(day), year_or_time)
        if date is not None:
            self._dates[name] = date
        return name

    @classmethod
    def _listed_date(cls, month: str, day: int,
                     year_or_time: str) -> float | None:
        """The time a listing's "Apr 12  2015" or "Nov  2 21:20" stands
        for, local time, in seconds since the epoch; None for anything
        else.  The second form, for a recent file, names no year: it is
        the last such date that is not in the future, a day allowed for
        a clock or a time zone apart."""
        if month not in cls._MONTHS:
            return None
        number = cls._MONTHS.index(month) + 1
        try:
            if ':' not in year_or_time:
                return datetime.datetime(int(year_or_time), number,
                                         day).timestamp()
            hour, minute = year_or_time.split(':')
            now = datetime.datetime.now()
            date = datetime.datetime(now.year, number, day,
                                     int(hour), int(minute))
            if date > now + datetime.timedelta(days=1):
                date = date.replace(year=now.year - 1)
            return date.timestamp()
        except (ValueError, OverflowError, OSError):
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
