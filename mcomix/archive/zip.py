""" Unicode-aware wrapper for zipfile.ZipFile. """

import os
import struct
import zipfile
import zlib
from collections.abc import Callable, Iterator, Sequence

from mcomix import log
from mcomix import i18n
from mcomix.archive import archive_base
from mcomix.i18n import _


def _methods_python_reads() -> frozenset[int]:
    """The compression methods this Python's zipfile reads: stored and
    deflated always, bzip2 and LZMA where Python was built with bz2 and
    lzma, as nearly every build is, and Zstandard from Python 3.14 on,
    where compression.zstd is there.  zipfile names each module it found,
    and None for one it did not."""
    methods = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
    if getattr(zipfile, 'bz2', None) is not None:
        methods.add(zipfile.ZIP_BZIP2)
    if getattr(zipfile, 'lzma', None) is not None:
        methods.add(zipfile.ZIP_LZMA)
    zstandard: int | None = getattr(zipfile, 'ZIP_ZSTANDARD', None)
    if zstandard is not None and getattr(zipfile, 'zstd', None) is not None:
        methods.add(zstandard)
    return frozenset(methods)


def is_py_supported_zipfile(path: str) -> bool:
    """Whether Python's zipfile reads every member of the ZIP file at
    <path>.  A member compressed otherwise - Deflate64, PPMd, AES
    encryption (method 99) - leaves the whole file to 7-Zip."""
    readable = _methods_python_reads()
    with zipfile.ZipFile(path, 'r') as zip_file:
        for file_info in zip_file.infolist():
            if file_info.compress_type not in readable:
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
        #: The member each listed name stands for.  A zip can hold two
        #: members of one name, which zipfile finds only the later of by
        #: name; the record of each is what reads the right one.
        self._members: dict[str, zipfile.ZipInfo] = {}

    def iter_contents(self) -> Iterator[str]:
        """Yield the name of every member.

        The password is asked for here rather than at the first read, so
        that a reader who declines is not asked again per page.

        Two members that would be listed under one name, as the same
        name twice or two that come out the same once made safe to
        write, are both pages, and a page is a file: the later ones are
        listed as name~2.jpg, which sorts after name.jpg.
        """
        if self._has_encryption():
            self.zip.setpassword(i18n.to_utf8(self._get_password()))

        infos = [info for info in self.zip.infolist()
                 # A zip records the directories its files are in as
                 # entries of their own.  They are not members anything
                 # can extract - opening one for writing raises - so the
                 # listing does not offer them.
                 if not info.is_dir()]
        legacy = _legacy_name_decoder(infos)
        listed = [self._unicode_filename(info.filename) if _named_in_utf8(info)
                  # Listed under the name it was written in, and extracted
                  # under the one zipfile knows it by.
                  else self._unicode_filename(info.filename, legacy)
                  for info in infos]
        taken = {archive_base.file_key(name) for name in listed}
        members: dict[str, zipfile.ZipInfo] = {}
        for info, name in zip(infos, listed):
            if name in members:
                name = self._next_free_name(name, taken)
                taken.add(archive_base.file_key(name))
            members[name] = info
            date = archive_base.zip_member_date(info)
            if date is not None:
                self._dates[name] = date
        self._members = members
        yield from members

    def member_date(self, name: str) -> float | None:
        """When the member listed as <name> was last modified."""
        return self._dates.get(name)

    def extract(self, filename: str, destination_dir: str) -> None:
        """Write member <filename> into <destination_dir>."""
        zipinfo: zipfile.ZipInfo | str = self._members.get(
            filename, self._original_filename(filename))
        # Read before creating the destination, so a member that cannot be
        # read does not leave an empty file behind.
        content = self.zip.read(zipinfo)
        with self._create_file(os.path.join(destination_dir, filename)) as new:
            new.write(content)

        if isinstance(zipinfo, str):
            zipinfo = self.zip.getinfo(zipinfo)
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
