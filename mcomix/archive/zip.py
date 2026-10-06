""" Unicode-aware wrapper for zipfile.ZipFile. """

import datetime
import os
import struct
import zipfile
import zlib
from collections.abc import Callable, Iterator, Sequence

from mcomix import log
from mcomix import i18n
from mcomix.archive import archive_base
from mcomix.i18n import _


def is_py_supported_zipfile(path: str) -> bool:
    """Check if a given zipfile has all internal files stored with Python supported compression
    """
    with zipfile.ZipFile(path, 'r') as zip_file:
        for file_info in zip_file.infolist():
            if file_info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                return False
    return True


#: The general purpose flag that says a member's name is UTF-8.
_UTF8_FLAG = 0x800

#: Info-ZIP's "Unicode Path" extra field: the name again, in UTF-8.
_UNICODE_PATH = 0x7075


def _named_in_utf8(info: zipfile.ZipInfo) -> bool:
    """Whether zipfile read the name of <info> as UTF-8.

    It does for a name with the UTF-8 flag, and for one stored in a code
    page with a Unicode Path field beside it, which zipfile reads instead
    of the name - where the field's checksum is that of the name, as it
    is unless something renamed the member without updating the field.
    """
    if info.flag_bits & _UTF8_FLAG:
        return True
    extra = info.extra
    stored_crc = None
    while len(extra) >= 4:
        kind, length = struct.unpack('<HH', extra[:4])
        data = extra[4:4 + length]
        if kind == _UNICODE_PATH and len(data) > 5 and data[0] == 1:
            stored_crc = struct.unpack('<L', data[1:5])[0]
        extra = extra[4 + length:]
    # The name as stored comes back through code page 437 intact.
    return (stored_crc is not None
            and stored_crc == zlib.crc32(info.orig_filename.encode('cp437')))


def _legacy_name_decoder(infos: Sequence[zipfile.ZipInfo]) \
        -> Callable[[str], str]:
    """How to read back the names <infos> stored without the UTF-8 flag.

    zipfile reads such a name as code page 437, which is what the format
    once said, but the tools that wrote most of them did not.  The bytes
    come back intact through code page 437, and are read in the encoding
    archive_base.name_encoding() finds for all of them; where it finds
    none, they stay as zipfile read them.
    """
    raw = [info.filename.encode('cp437') for info in infos
           if not _named_in_utf8(info) and not info.filename.isascii()]
    if not raw:
        return lambda name: name
    chosen = archive_base.name_encoding(raw, 'cp437')

    def decode(name: str) -> str:
        if name.isascii():
            return name
        return name.encode('cp437').decode(chosen)
    return decode


class ZipArchive(archive_base.NonUnicodeArchive):

    """A ZIP file read through the standard library."""

    # zipfile reads one member at a time under a lock of its own, and
    # each member it opens keeps its own place in the file, so several
    # threads can read from the one ZipFile.  The work that is worth
    # sharing out, inflating, runs outside the GIL.
    support_concurrent_extractions = True

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        self.zip = zipfile.ZipFile(archive, 'r')

    def iter_contents(self) -> Iterator[str]:
        """Yield the name of every member.

        The password is asked for here rather than at the first read, so
        that a reader who declines is not asked again per page.
        """
        if self._has_encryption():
            self.zip.setpassword(i18n.to_utf8(self._get_password()))

        infos = self.zip.infolist()
        legacy = _legacy_name_decoder(infos)
        for info in infos:
            if info.is_dir():
                # A zip records the directories its files are in as
                # entries of their own.  They are not members anything
                # can extract - opening one for writing raises - so the
                # listing does not offer them.
                continue
            # Local time, as a zip keeps it: no zone is recorded.
            year, month, day, hour, minute, second = info.date_time
            try:
                self._dates[info.filename] = datetime.datetime(
                    year, month, day, hour, minute, second).timestamp()
            except (ValueError, OverflowError, OSError):
                pass
            if _named_in_utf8(info):
                yield self._unicode_filename(info.filename)
            else:
                # Listed under the name it was written in, and extracted
                # under the one zipfile knows it by.
                yield self._unicode_filename(info.filename, legacy)

    def extract(self, filename: str, destination_dir: str) -> None:
        """Write member <filename> into <destination_dir>."""
        original_filename = self._original_filename(filename)
        # Read before creating the destination, so a member that cannot be
        # read does not leave an empty file behind.
        content = self.zip.read(original_filename)
        with self._create_file(os.path.join(destination_dir, filename)) as new:
            new.write(content)

        zipinfo = self.zip.getinfo(original_filename)
        if len(content) != zipinfo.file_size:
            log.warning(_('%(filename)s\'s extracted size is %(actual_size)d bytes,'
                          ' but should be %(expected_size)d bytes.'
                          ' The archive might be corrupt or in an unsupported format.'),
                        {'filename': filename, 'actual_size': len(content),
                         'expected_size': zipinfo.file_size})

    def close(self) -> None:
        """Close the ZIP file."""
        self.zip.close()

    def _has_encryption(self) -> bool:
        """ Checks all files in the archive for encryption.
        Returns True if at least one encrypted file was found. """
        for zipinfo in self.zip.infolist():
            if zipinfo.flag_bits & 0x1:  # File is encrypted
                return True

        return False

# vim: expandtab:sw=4:ts=4
