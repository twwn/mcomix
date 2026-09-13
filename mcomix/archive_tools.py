"""archive_tools.py - Archive tool functions."""

import functools
import os
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
}

def _get_handler(archive_type: int) -> type[archive_base.BaseArchive] | None:
    """ Return best archive class for format <archive_type> """

    for handler in _HANDLERS[archive_type]:
        if handler.is_available():
            return handler
        log.debug("Ignoring unavailable handler %s", handler.__name__)
    return None

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

@functools.cache
def get_supported_formats() -> dict[str, tuple[set[str], set[str]]]:
    """ Return the archive formats a handler is installed for, as a mapping
    of a name to its mime types and its extensions. """
    supported_formats = {}
    for name, formats, is_available in (
        ('ZIP', constants.ZIP_FORMATS , True            ),
        ('Tar', constants.TAR_FORMATS , True            ),
        ('RAR', constants.RAR_FORMATS , rar_available() ),
        ('7z' , constants.SZIP_FORMATS, szip_available()),
        ('LHA', constants.LHA_FORMATS , lha_available() ),
        ('PDF', constants.PDF_FORMATS , pdf_available() ),
        ('MobiPocket', constants.MOBI_FORMATS , mobi_available() ),
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
                magic = fd.read(5)
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

    except Exception:
        log.warning(_('! Could not read %s'), path)

    return None

#: What a tar opened in each of tar.open_mode()'s modes is reported as.
#: An xz or lzma compressed tarball is read by tarfile like any other tar,
#: so constants.XZ is left for the ones it cannot read.
_TAR_MODE_TYPES: dict[tar.ReadMode, int] = {
    'r:bz2': constants.BZIP2,
    'r:gz' : constants.GZIP,
    'r:xz' : constants.TAR,
    'r:'   : constants.TAR,
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
    at <path>, or None if <path> doesn't point to a supported
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
    # XXX: Deferred import to avoid circular dependency
    from mcomix.archive import archive_recursive
    return archive_recursive.RecursiveArchive(archive, destination_dir)
 
# vim: expandtab:sw=4:ts=4
