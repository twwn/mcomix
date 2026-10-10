"""archive_tools.py - Archive tool functions."""

import functools
import os
import re
import shutil
import zipfile
import tarfile
import tempfile
from collections.abc import Callable

from mcomix import image_tools
from mcomix import constants
from mcomix import log
from mcomix.archive import (
    archive_base,
    lha_external,
    mobi,
    pdf_multi,
    pdf_external,
    djvu_external,
    rar,
    rar_external,
    sevenzip_external,
    tar,
    zip,
    zip_external,
)
from mcomix import tools
from mcomix.i18n import _

# Handlers for each archive type, best first.
_HANDLERS: dict[int, tuple[type[archive_base.BaseArchive], ...]] = {
    constants.ZIP: (
        zip.ZipArchive,
    ),
    # Prefer 7z over zip executable for encryption and Unicode support.
    constants.ZIP_EXTERNAL: (
        sevenzip_external.SevenZipArchive,
        zip_external.ZipArchive
    ),
    constants.TAR: (
        tar.TarArchive,
    ),
    constants.GZIP: (
        tar.TarArchive,
    ),
    constants.BZIP2: (
        tar.TarArchive,
    ),
    # Only reached for xz/lzma compressed tarballs that the tarfile module
    # does not recognize; it reads the usual ones itself, and those are
    # reported as constants.TAR by archive_mime_type().
    constants.XZ: (
        sevenzip_external.TarArchive,
    ),
    constants.RAR: (
        rar.RarArchive,
        rar_external.RarArchive,
        # Last resort: some versions of 7z support RAR.
        sevenzip_external.SevenZipArchive,
    ),
    # Prefer 7z over lha executable for Unicode support.
    constants.LHA: (
        sevenzip_external.SevenZipArchive,
        lha_external.LhaArchive,
    ),
    constants.SEVENZIP: (
        sevenzip_external.SevenZipArchive,
    ),
    constants.PDF: (
        pdf_multi.PdfMultiArchive,
        pdf_external.PdfArchive,
    ),
    constants.MOBI: (
        mobi.MobiArchive,
    ),
    constants.DJVU: (
        djvu_external.DjvuArchive,
    ),
}


def _get_handler(archive_type: int) -> type[archive_base.BaseArchive] | None:
    """ Return best archive class for format <archive_type> """

    for handler in _HANDLERS[archive_type]:
        if handler.is_available():
            return handler
        log.debug("Ignoring unavailable handler %s", handler.__name__)
    return None


def helpers(archive_type: int) -> list[str]:
    """The programs or Python modules that would open an archive of
    <archive_type>, best first, each named once; empty for a format
    Python reads itself."""
    return list(dict.fromkeys(
        handler.helper for handler in _HANDLERS[archive_type]
        if handler.helper is not None))


def cannot_open(path: str, archive_type: int | None = None) -> str:
    """Why the archive <path>, which no installed handler opens, cannot
    be opened, for the reader: the program or module it needs.

    <archive_type> is worked out from the file where it is not given.
    """
    if archive_type is None:
        archive_type = archive_mime_type(path)
    names = helpers(archive_type) if archive_type is not None else []
    name = os.path.basename(path)
    if len(names) == 1:
        return _('Could not open %(file)s: it needs %(program)s.') % {
            'file': name, 'program': names[0]}
    if names:
        # No format has more than two, and the second is the fallback.
        return _('Could not open %(file)s: it needs %(first)s or '
                 '%(second)s.') % {
            'file': name, 'first': names[0], 'second': names[1]}
    return _('Non-supported archive format: %s') % name


def _is_available(archive_type: int) -> bool:
    """ Return True if a handler supporting the <archive_type> format is available """
    return _get_handler(archive_type) is not None


def szip_available() -> bool:
    return _is_available(constants.SEVENZIP)


def rar_available() -> bool:
    return _is_available(constants.RAR)


def lha_available() -> bool:
    return _is_available(constants.LHA)


def pdf_available() -> bool:
    return _is_available(constants.PDF)


def mobi_available() -> bool:
    return _is_available(constants.MOBI)


def djvu_available() -> bool:
    return _is_available(constants.DJVU)


@functools.cache
def get_supported_formats() -> dict[str, tuple[set[str], set[str]]]:
    """ Return the archive formats a handler is installed for, as a mapping
    of a name to its mime types and its extensions. """
    supported_formats = {}
    for name, formats, is_available in (
        ('ZIP', constants.ZIP_FORMATS, True),
        ('Tar', constants.TAR_FORMATS, True),
        ('RAR', constants.RAR_FORMATS, rar_available()),
        ('7z', constants.SZIP_FORMATS, szip_available()),
        ('LHA', constants.LHA_FORMATS, lha_available()),
        ('PDF', constants.PDF_FORMATS, pdf_available()),
        ('MobiPocket', constants.MOBI_FORMATS, mobi_available()),
        ('DjVu', constants.DJVU_FORMATS, djvu_available()),
    ):
        if is_available:
            supported_formats[name] = (set(formats[0]), set(formats[1]))
    return supported_formats


# Set supported archive extensions regexp from list of supported formats.
# Only used internally.
_SUPPORTED_ARCHIVE_REGEX = tools.formats_to_regex(get_supported_formats())
log.debug("_SUPPORTED_ARCHIVE_REGEX='%s'", _SUPPORTED_ARCHIVE_REGEX.pattern)


def is_archive_file(path: str) -> bool:
    """Return True if the file at <path> is a supported archive file.
    """
    return _SUPPORTED_ARCHIVE_REGEX.search(path) is not None


def archive_mime_type(path: str) -> int | None:
    """Return the archive type of <path> or None for non-archives."""
    try:

        if os.path.isfile(path):

            if not os.access(path, os.R_OK):
                return None

            if zipfile.is_zipfile(path):
                if zip.is_py_supported_zipfile(path):
                    return constants.ZIP
                else:
                    return constants.ZIP_EXTERNAL

            with open(path, 'rb') as fd:
                magic = fd.read(16)
                fd.seek(60)
                magic2 = fd.read(8)

            mode = tar.open_mode(magic)
            if _is_tarfile(path, mode):
                return _TAR_MODE_TYPES[mode]

            if magic[0:4] == b'Rar!':
                return constants.RAR

            if magic[0:4] == b'7z\xBC\xAF':
                return constants.SEVENZIP

            # Headers for TAR-XZ and TAR-LZMA that aren't supported by tarfile
            if magic[0:5] == b'\xFD7zXZ' or magic[0:5] == b']\x00\x00\x80\x00':
                return constants.XZ

            if magic[2:4] == b'-l':
                return constants.LHA

            if magic[0:4] == b'%PDF':
                return constants.PDF

            if magic2 == b'BOOKMOBI':
                return constants.MOBI

            # One page, or several bundled; an indirect document's index
            # names its pages' files and holds no page itself.
            if magic[0:8] == b'AT&TFORM' and magic[12:16] in (b'DJVU',
                                                              b'DJVM'):
                return constants.DJVU

    except Exception:
        log.warning(_('! Could not read %s'), path)

    return None


#: The signatures a RAR archive starts with, in the two formats.
_RAR4_SIGNATURE = b'Rar!\x1a\x07\x00'
_RAR5_SIGNATURE = b'Rar!\x1a\x07\x01\x00'


def _read_vint(data: bytes, offset: int) -> tuple[int, int]:
    """The variable-length integer of RAR 5 at <offset> in <data>, and
    the offset after it: seven bits a byte, lowest first, the high bit
    saying another byte follows.  IndexError if <data> ends first."""
    value = shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, offset


def _is_later_rar_volume(head: bytes) -> bool:
    """Whether <head>, the start of a file, is the start of a RAR volume
    other than the first of its set.

    RAR 5 says so in the main archive header: the "volume" flag with the
    "volume number" field, which every volume but the first carries.
    RAR 3 and 4 set "first volume" on the first volume of a set, and
    also a flag for the name.partN.rar naming; a volume of that naming
    without "first volume" is a later one.  A set from before RAR 3
    sets neither, and is never taken for a later volume: its other
    volumes are name.r00, name.r01 and so on, which are not listed as
    archives in the first place.
    """
    try:
        if head.startswith(_RAR5_SIGNATURE):
            offset = len(_RAR5_SIGNATURE) + 4  # after the header's CRC32
            _size, offset = _read_vint(head, offset)
            header_type, offset = _read_vint(head, offset)
            if header_type != 1:  # not the main archive header
                return False
            header_flags, offset = _read_vint(head, offset)
            if header_flags & 0x0001:  # an extra area
                _extra_size, offset = _read_vint(head, offset)
            if header_flags & 0x0002:  # a data area
                _data_size, offset = _read_vint(head, offset)
            archive_flags, offset = _read_vint(head, offset)
            return archive_flags & 0x0003 == 0x0003
        if head.startswith(_RAR4_SIGNATURE):
            offset = len(_RAR4_SIGNATURE) + 2  # after the header's CRC16
            if head[offset] != 0x73:  # not the main archive header
                return False
            flags = int.from_bytes(head[offset + 1:offset + 3], 'little')
            volume, new_numbering, first_volume = 0x0001, 0x0010, 0x0100
            return (flags & (volume | new_numbering | first_volume)
                    == volume | new_numbering)
    except IndexError:
        pass
    return False


def is_later_volume(path: str) -> bool:
    """Whether the file at <path> is a volume of an archive packed in
    several, other than the first.

    Such a file is not a book: opened on its own it lists what is left
    from the volume before, and the set is read from its first volume,
    which the archive handlers follow through the rest.  Only RAR sets
    are recognised; a file that cannot be read is not a later volume.
    """
    if not is_archive_file(path):
        return False
    try:
        with open(path, 'rb') as archive:
            head = archive.read(32)
    except OSError:
        return False
    return _is_later_rar_volume(head)


#: A volume of a set named the way RAR 3 and later name them:
#: name.part1.rar, name.part2.rar, or name.part01.rar and on for a set
#: of ten or more.
_VOLUME_NAME = re.compile(r'^(?P<stem>.*\.part)(?P<number>\d+)(?P<ext>\.[^.]+)$',
                          re.IGNORECASE)


def first_volume(path: str) -> str | None:
    """The first volume of the set <path> is a later volume of, where it
    is beside it; None where <path> is no later volume, or the first
    one is not there.

    A later volume opened by itself is the rest of the set from the
    middle of a page on, and the reader who opens one wants the book:
    the set is read from its first volume, which the archive handlers
    follow through the rest.
    """
    if not is_later_volume(path):
        return None
    named = _VOLUME_NAME.match(path)
    if named is None:
        return None
    number = named.group('number')
    first = (named.group('stem') + '1'.zfill(len(number))
             + named.group('ext'))
    if first == path or not os.path.isfile(first) or is_later_volume(first):
        return None
    return first


def describe(path: str, archive_type: int) -> str:
    """How the archive at <path>, of <archive_type>, is described to the
    reader.

    An xz compressed tarball is of type constants.TAR, since tarfile
    reads it as it reads a plain one, but it is described by what it is,
    as a gzip or bzip2 compressed one is.
    """
    # Imported here: strings translates at import time, which has to
    # wait for gettext, and this module is imported before that.
    from mcomix import strings
    if archive_type == constants.TAR:
        try:
            if tar.open_mode(tar.read_magic(path)) == 'r:xz':
                archive_type = constants.XZ
        except OSError:
            pass
    return strings.ARCHIVE_DESCRIPTIONS.get(archive_type, '')


#: What a tar opened in each of tar.open_mode()'s modes is reported as.
#: An xz or lzma compressed tarball is read by tarfile like any other tar,
#: so constants.XZ is left for the ones it cannot read.
_TAR_MODE_TYPES: dict[tar.ReadMode, int] = {
    'r:bz2': constants.BZIP2,
    'r:gz': constants.GZIP,
    'r:xz': constants.TAR,
    'r:': constants.TAR,
}


def _is_tarfile(path: str, mode: tar.ReadMode) -> bool:
    """Return True if <path> is a tar archive that opens in <mode>."""
    try:
        with tarfile.open(path, mode) as archive:
            if archive.next() is not None:
                return True
            # An archive naming no entry at all is a run of zero bytes, which
            # is what a file that is merely broken is full of as well.  Tar
            # writes an empty archive as a single record and stops, so a file
            # longer than that which decodes to nothing is not one.
            return os.path.getsize(path) <= tarfile.RECORDSIZE
    except (tarfile.TarError, EOFError, IOError):
        # Tarfile raises an error when accessing certain network shares.
        return False


def get_archive_info(path: str) -> tuple[int, int, int] | None:
    """Return a tuple (mime, num_pages, size) with info about the archive
    at <path>, or None if <path> doesn't point to a supported archive.

    <mime> is the archive type, one of the constants archive_mime_type()
    answers with, and <num_pages> counts the images in the archive and
    in the archives within it.
    """
    cleanup: list[Callable[[], object]] = []
    try:
        tmpdir = tempfile.mkdtemp(prefix='mcomix_archive_info.')
        cleanup.append(lambda: shutil.rmtree(tmpdir, True))

        mime = archive_mime_type(path)
        if mime is None:
            return None
        archive = get_recursive_archive_handler(path, tmpdir, type=mime)
        if archive is None:
            return None
        cleanup.append(archive.close)

        files = archive.list_contents()
        num_pages = len(list(filter(image_tools.is_image_file, files)))
        size = os.stat(path).st_size

        return (mime, num_pages, size)
    finally:
        for fn in reversed(cleanup):
            fn()


def get_archive_handler(path: str, mimetype: int | None = None) -> archive_base.BaseArchive | None:
    """ Returns a fitting extractor handler for the archive passed
    in <path> (with optional mime type <mimetype>. Returns None if no matching
    extractor was found.
    """
    if mimetype is None:
        mimetype = archive_mime_type(path)
        if mimetype is None:
            return None

    handler = _get_handler(mimetype)
    if handler is None:
        return None

    log.debug('Archive handler %(handler)s for archive "%(archivename)s" was selected.',
              {'handler': handler.__name__, 'archivename': os.path.split(path)[1]})
    return handler(path)


def get_recursive_archive_handler(path: str, destination_dir: str,
                                  type: int | None = None) -> archive_base.BaseArchive | None:
    """ Same as <get_archive_handler> but the handler will transparently handle
    archives within archives.
    """
    archive = get_archive_handler(path, mimetype=type)
    if archive is None:
        return None
    # Deferred: archive_recursive imports this module, so it cannot
    # be imported at the top of it.
    from mcomix.archive import archive_recursive
    return archive_recursive.RecursiveArchive(archive, destination_dir)

# vim: expandtab:sw=4:ts=4
