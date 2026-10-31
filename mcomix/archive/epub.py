"""EPUB books: the pictures of their pages, in reading order.

An EPUB is a ZIP archive whose first member, "mimetype", says
application/epub+zip.  META-INF/container.xml names the package
document (the OPF); its manifest lists every file of the book, and its
spine the order in which the reader goes through them.  A comic or a
manga made into an EPUB - fixed-layout ones from a store, or a CBZ
converted by Calibre or KCC - has one picture per spine document: an
XHTML or SVG page holding it, or the picture itself.

Opened as a plain ZIP, such a book listed its pictures in the order of
their names, which is the reading order only by chance, and listed
none where the pictures are named after hashes; and a folder of them
listed none at all, since .epub was not among the extensions MComix
takes for books.

Built from the EPUB 3.3 specification (https://www.w3.org/TR/epub-33/)
and the OCF container format it defines.
"""

import os
import posixpath
import threading
import urllib.parse
import zipfile
from collections.abc import Iterator
from xml.etree import ElementTree

from mcomix import comicinfo
from mcomix import image_tools
from mcomix import log
from mcomix.archive import archive_base
from mcomix.i18n import _

#: What the "mimetype" member of an EPUB says.
MIMETYPE = b'application/epub+zip'

_CONTAINER = 'META-INF/container.xml'
_ENCRYPTION = 'META-INF/encryption.xml'

_OCF = '{urn:oasis:names:tc:opendocument:xmlns:container}'
_OPF = '{http://www.idpf.org/2007/opf}'
_DC = '{http://purl.org/dc/elements/1.1/}'
_XHTML = '{http://www.w3.org/1999/xhtml}'
_SVG = '{http://www.w3.org/2000/svg}'
_XLINK = '{http://www.w3.org/1999/xlink}'
_ENC = '{http://www.w3.org/2001/04/xmlenc#}'

#: The spine documents a page's picture is looked for in.
_DOCUMENTS = ('application/xhtml+xml', 'text/html', 'image/svg+xml')

#: What encryption.xml may say of fonts alone: the font obfuscations of
#: the IDPF and of Adobe, which leave every other file as it is.  Any
#: other algorithm is DRM.
_FONT_OBFUSCATION = ('http://www.idpf.org/2008/embedding',
                     'http://ns.adobe.com/pdf/enc#RC')

#: The most read of a spine document or of the package document: a page
#: of a comic is a few hundred bytes, and a chapter of a novel some
#: tens of kilobytes.
_LARGEST_DOCUMENT = 4 * 1024 * 1024


class UnpackException(Exception):
    """The book cannot be read; the message says why, for the reader."""


def is_epub(path: str) -> bool:
    """Whether the ZIP archive at <path> is an EPUB: its "mimetype"
    member says application/epub+zip.  The specification has it first
    and stored, but books written carelessly have it anywhere, and some
    end it with a line break."""
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                info = archive.getinfo('mimetype')
            except KeyError:
                return False
            if info.file_size > 64:
                return False
            return archive.read(info).strip() == MIMETYPE
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        return False


def _parse(archive: zipfile.ZipFile, name: str) -> ElementTree.Element | None:
    """The XML document <name> in <archive>, or None where it is not
    there, too large, or not XML."""
    try:
        info = archive.getinfo(name)
        if info.file_size > _LARGEST_DOCUMENT:
            log.debug('EPUB member %s: %d bytes, not read', name, info.file_size)
            return None
        return ElementTree.fromstring(archive.read(info))
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile,
            RuntimeError, NotImplementedError, OSError, ValueError) as error:
        log.debug('EPUB member %s: %s', name, error)
        return None


def _resolve(base: str, reference: str) -> str:
    """The member name <reference>, a URL relative to the member <base>,
    points at: its fragment and query left out, its escapes undone."""
    path = urllib.parse.urlsplit(reference).path
    if not path:
        return ''
    path = urllib.parse.unquote(path)
    if path.startswith('/'):
        return posixpath.normpath(path.lstrip('/'))
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), path))


def _pictures_in(document: ElementTree.Element) -> Iterator[str]:
    """The references of the pictures a page document shows, in the
    order it shows them: XHTML's img, and SVG's image."""
    for element in document.iter():
        if element.tag in (_XHTML + 'img', 'img'):
            reference = element.get('src')
        elif element.tag == _SVG + 'image':
            reference = element.get(_XLINK + 'href') or element.get('href')
        else:
            continue
        if reference:
            yield reference


class _Book:

    """What the package document says: the pictures in reading order,
    and what the book says of itself."""

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.pictures: list[str] = []
        self.comic_info: bytes | None = None
        container = _parse(archive, _CONTAINER)
        package_path = ''
        if container is not None:
            for rootfile in container.iter(_OCF + 'rootfile'):
                if rootfile.get('media-type', 'application/oebps-package+xml') \
                        == 'application/oebps-package+xml':
                    package_path = rootfile.get('full-path', '')
                    if package_path:
                        break
        package = _parse(archive, package_path) if package_path else None
        if package is None:
            return
        manifest: dict[str, tuple[str, str]] = {}
        for item in package.iter(_OPF + 'item'):
            identifier, href = item.get('id'), item.get('href')
            if identifier and href:
                manifest[identifier] = (_resolve(package_path, href),
                                        item.get('media-type', ''))
        members = set(archive.namelist())
        seen = set()
        spine = package.find(_OPF + 'spine')
        for itemref in spine.iter(_OPF + 'itemref') if spine is not None else ():
            if itemref.get('linear', 'yes') == 'no':
                continue
            path, media_type = manifest.get(itemref.get('idref', ''), ('', ''))
            if path not in members:
                continue
            if media_type in _DOCUMENTS:
                document = _parse(archive, path)
                references = [_resolve(path, reference) for reference in
                              _pictures_in(document)] if document is not None else []
            else:
                references = [path]
            for picture in references:
                if picture in members and picture not in seen \
                        and image_tools.is_image_file(picture):
                    seen.add(picture)
                    self.pictures.append(picture)
        right_to_left = spine is not None \
            and spine.get('page-progression-direction') == 'rtl'
        metadata = package.find(_OPF + 'metadata')

        def texts(tag: str) -> list[str]:
            if metadata is None:
                return []
            return [element.text.strip() for element in metadata.iter(_DC + tag)
                    if element.text and element.text.strip()]

        self.comic_info = comicinfo.of_book(
            next(iter(texts('title')), None),
            next((date[:4] for date in texts('date')[:1]), None),
            texts('creator'),
            next(iter(texts('publisher')), None),
            right_to_left)


def _encrypted(archive: zipfile.ZipFile) -> bool:
    """Whether encryption.xml says that a file other than a font is
    encrypted: DRM, from Adobe, Apple, Kobo or Barnes & Noble alike."""
    try:
        archive.getinfo(_ENCRYPTION)
    except KeyError:
        return False
    document = _parse(archive, _ENCRYPTION)
    if document is None:
        return True
    for data in document.iter(_ENC + 'EncryptedData'):
        method = data.find(_ENC + 'EncryptionMethod')
        algorithm = method.get('Algorithm', '') if method is not None else ''
        if algorithm not in _FONT_OBFUSCATION:
            return True
    return False


class EpubArchive(archive_base.BaseArchive):

    """The pictures of an EPUB's pages, as though they were an
    archive's: page00001.jpg on, in the order of the spine, then a
    ComicInfo.xml of what the book says of itself, where it says
    anything and carries none of its own.  A book whose package
    document cannot be read lists its pictures by their own names, as
    a ZIP archive would.

    The book stays open for as long as the handler does, and a page is
    read out of it as it is asked for.
    """

    support_concurrent_extractions = True

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        name = os.path.basename(archive)
        self._zip = zipfile.ZipFile(archive)
        try:
            if _encrypted(self._zip):
                raise UnpackException(
                    _('Could not open %s: it is protected by DRM.') % name)
        except BaseException:
            self._zip.close()
            raise
        # Extraction threads may ask for the pages before the listing
        # has; the package document is read once.
        self._listing = threading.Lock()
        self._pages: dict[str, str] | None = None
        self._comic_info: bytes | None = None

    def _listed(self) -> dict[str, str]:
        """The names pages are listed under, in reading order, against
        the members they are read from.  A member's own name is made
        safe to write first, as every handler's is: no "../", nothing
        the file system refuses."""
        with self._listing:
            if self._pages is None:
                book = _Book(self._zip)
                members = self._zip.namelist()
                if book.pictures:
                    pages = {'page%05d%s' % (number, os.path.splitext(picture)[1].lower()):
                             picture for number, picture in enumerate(book.pictures, 1)}
                else:
                    pages = {self._replace_invalid_filesystem_chars(member): member
                             for member in members if image_tools.is_image_file(member)}
                carried = [member for member in members
                           if posixpath.basename(member) == comicinfo.NAME]
                if carried:
                    # A ComicInfo.xml the book carries itself.
                    pages[comicinfo.NAME] = carried[0]
                else:
                    self._comic_info = book.comic_info
                self._pages = pages
            return self._pages

    def iter_contents(self) -> Iterator[str]:
        yield from self._listed()
        if self._comic_info is not None:
            yield comicinfo.NAME

    def extract(self, filename: str, destination_dir: str) -> None:
        """Extract <filename> from the archive to <destination_dir>."""
        destination_path = os.path.join(destination_dir, filename)
        member = self._listed().get(filename)
        if filename == comicinfo.NAME and self._comic_info is not None:
            with self._create_file(destination_path) as new:
                new.write(self._comic_info)
            return
        if member is None:
            return
        data = self._zip.read(member)
        with self._create_file(destination_path) as new:
            new.write(data)

    def close(self) -> None:
        self._zip.close()

# vim: expandtab:sw=4:ts=4
