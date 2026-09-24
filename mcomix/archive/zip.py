""" Unicode-aware wrapper for zipfile.ZipFile. """

import os
import zipfile
from collections.abc import Callable, Iterator, Sequence

from mcomix import log
from mcomix import i18n

try:
    import chardet
except ImportError:
    chardet = None  # type: ignore[assignment]
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


def _legacy_name_decoder(infos: Sequence[zipfile.ZipInfo]) \
        -> Callable[[str], str]:
    """How to read back the names <infos> stored without the UTF-8 flag.

    zipfile reads such a name as code page 437, which is what the format
    once said, but the tools that wrote most of them did not: an older
    Linux or Mac archiver wrote UTF-8 and left the flag off, and Windows
    wrote the code page of its language.  The bytes come back intact
    through code page 437, so every such name is tried as UTF-8 first,
    and then, where chardet is installed, in whatever it makes of all of
    them at once - one name is too short to tell a code page by.  Where
    neither reads every name, they stay as zipfile read them.
    """
    raw = [info.filename.encode('cp437') for info in infos
           if not info.flag_bits & _UTF8_FLAG and not info.filename.isascii()]
    if not raw:
        return lambda name: name
    candidates = ['utf-8']
    if chardet is not None:
        guessed = chardet.detect(b'\n'.join(raw))
        if guessed['encoding'] and guessed['confidence'] >= 0.5:
            candidates.append(guessed['encoding'])
    for encoding in candidates:
        try:
            for name in raw:
                name.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        chosen = encoding

        def decode(name: str) -> str:
            if name.isascii():
                return name
            return name.encode('cp437').decode(chosen)
        return decode
    return lambda name: name


class ZipArchive(archive_base.NonUnicodeArchive):

    """A ZIP file read through the standard library."""

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
            if info.flag_bits & _UTF8_FLAG:
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
