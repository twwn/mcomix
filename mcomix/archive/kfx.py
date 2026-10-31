"""Kindle KFX books: the pictures of one, in its reading order.

KFX, which Amazon also calls KF10 or YJ, is the format of the Kindle
books Amazon delivers now.  A book is one or more containers, each a
file that begins with "CONT": a header, an index of the entities the
container holds, and the entities.  Every entity but the bytes of a
picture or a font is one value in Amazon Ion's binary encoding
(ion.py), whose symbols are numbers the container's symbol table gives
the text of.  A comic's pages are the sections of its reading order;
each draws one picture, or two for a spread, and a picture may be
stored in several resolutions, and cut into tiles.

A book is in one container as Calibre keeps it; as Amazon delivers it,
in several files: a main container with the reading order, one of
metadata whose container entity map names the book's containers, and
containers that hold only pictures' bytes, beside each other or in a
folder named after the main one with .sdr.  A KFX-ZIP, which the KFX
Input plugin gathers a book's files into, holds them side by side.

Written for issue #50, under the GPL v2 or later, from a description of
the format in prose and from Amazon's public Ion specification, by a
reader of neither the KFX Input plugin nor any other KFX reader's code.
Amazon does not publish the format; the symbol IDs below are the numbers
its shared symbol table, YJ_symbols, gives the fields and values a page
reader needs.

A book with DRM is refused: its pages cannot be read.
"""

import functools
import io
import os
import struct
import tempfile
import threading
import zipfile
from collections.abc import Iterator
from typing import IO, NamedTuple

from PIL import Image

from mcomix import comicinfo
from mcomix import image_tools
from mcomix import log
from mcomix import process
from mcomix.archive import archive_base
from mcomix.archive import ion
from mcomix.archive.ion import Symbol
from mcomix.i18n import _

#: How a container begins.
CONTAINER_SIGNATURE = b'CONT'
#: How a container wrapped in Amazon's DRM begins.
DRM_SIGNATURE = b'\xeaDRMION\xee'
#: How each entity in a container begins.
_ENTITY_SIGNATURE = b'ENTY'

# The symbols of Ion's own system symbol table.
_NAME, _IMPORTS, _SYMBOLS, _MAX_ID = 4, 6, 7, 8

# The symbols of YJ_symbols this module reads, by their IDs.  The
# container's header and each entity's.
_CONTAINER_ID = 409
_COMPRESSION, _DRM_SCHEME = 410, 411
_INDEX_OFFSET, _INDEX_LENGTH = 413, 414
_SYMBOLS_OFFSET, _SYMBOLS_LENGTH = 415, 416
# The entity types, and the name of an entity of which a book has one.
_RAW_MEDIA = 417
_EXTERNAL_RESOURCE = 164
_DOCUMENT_DATA = 538
_METADATA = 258
_SECTION = 260
_STORYLINE = 259
_STYLE = 157
_STRUCTURE = 608
_PREVIEW_IMAGES = 387
_CONTAINER_ENTITY_MAP = 419
_CONTAINER_LIST, _ID = 252, 155
_BOOK_METADATA = 490
_NAMELESS = 348
# The reading order, and the elements of a page.
_READING_ORDERS = 169
_SECTIONS = 170
_PAGE_TEMPLATES = 141
_TYPE = 159
_CONTENT_LIST = 146
_STORY_NAME = 176
_RESOURCE_NAME = 175
_BACKGROUND_IMAGE = 479
_IGNORE = 69
_IMAGE = 271
_ZOOM_TARGET = 439
# A picture: its format, its size, and where its bytes are.
_FORMAT = 161
_LOCATION = 165
_RESOURCE_WIDTH, _RESOURCE_HEIGHT = 422, 423
_FIXED_WIDTH, _FIXED_HEIGHT = 66, 67
_THUMBNAILS = 214
_VARIANTS = 635
_TILES = 636
_TILE_WIDTH, _TILE_HEIGHT = 637, 638
_TILE_PADDING = 797
# Which way the book reads.
_DIRECTION, _RIGHT_TO_LEFT = 192, 375
_WRITING_MODE, _VERTICAL_RIGHT_TO_LEFT = 560, 559
# What the book says of itself: categories of key and value pairs, or
# in older books fields of the metadata.
_CATEGORISED_METADATA = 491
_CATEGORY, _ENTRIES = 495, 258
_KEY, _VALUE = 492, 307
_TITLE, _AUTHOR, _PUBLISHER = 153, 222, 232

#: The formats of picture shown as they are stored, and the extension
#: each is listed under.
_EXTENSIONS = {285: 'jpg', 284: 'png', 286: 'gif'}
#: JPEG XR, in which books keep their larger resolutions as often as
#: not.  Neither Pillow nor GTK reads it: jxrlib's JxrDecApp decodes it
#: to a TIFF, where it is installed.
_JPEG_XR = 548

#: The YJ_symbols ID the first symbol of a document's own table has
#: where the table does not say, which no book seen does: the one after
#: Ion's system symbols.
_FIRST_LOCAL_SYMBOL = 10


class UnpackException(Exception):
    """The file is not a KFX book this handler can read; the message
    says why, for the reader."""


class _Protected(Exception):
    """The container's pages are encrypted."""


class _Unreadable(Exception):
    """The container is damaged, or not one this module reads."""


@functools.cache
def _jxr_decoder() -> str | None:
    """JxrDecApp, or None where it is not installed."""
    decoder = process.find_executable(('JxrDecApp',))
    if decoder is None:
        log.debug('JxrDecApp executable not found')
    return decoder


def _extension(stored_as: object) -> str | None:
    """The extension a picture stored as format <stored_as> is listed
    under, where it can be shown: a JPEG XR one as the TIFF it is
    decoded to."""
    if stored_as == _JPEG_XR:
        return 'tif' if _jxr_decoder() is not None else None
    return _EXTENSIONS.get(stored_as) if isinstance(stored_as, int) else None


def _decode_jpeg_xr(data: bytes, destination: str) -> None:
    """Write the JPEG XR picture <data> to <destination> as a TIFF.

    JxrDecApp reads only a file whose name ends in .jxr, so <data> is
    written to one beside <destination> first; the TIFF has the pixel
    format of the picture, 8-bit grey or colour in a comic.
    """
    decoder = _jxr_decoder()
    if decoder is None:
        raise _Unreadable('JxrDecApp is not installed')
    folder = os.path.dirname(os.path.abspath(destination))
    handle, source = tempfile.mkstemp(suffix='.jxr', dir=folder)
    try:
        with os.fdopen(handle, 'wb') as written:
            written.write(data)
        # Absolute paths: one that began with "-" would be an option.
        if not process.call([decoder, '-i', source,
                             '-o', os.path.abspath(destination)]):
            raise _Unreadable('JxrDecApp could not decode it')
    finally:
        os.unlink(source)


def _open_picture(data: bytes, stored_as: int, folder: str) -> Image.Image:
    """The picture <data>, stored as format <stored_as>, read whole;
    a JPEG XR one is decoded in <folder>."""
    if stored_as != _JPEG_XR:
        return Image.open(io.BytesIO(data))
    handle, decoded = tempfile.mkstemp(suffix='.tif', dir=folder)
    os.close(handle)
    try:
        _decode_jpeg_xr(data, decoded)
        with open(decoded, 'rb') as fp:
            return Image.open(io.BytesIO(fp.read()))
    finally:
        os.unlink(decoded)


def _integer(value: object) -> int | None:
    """<value>, where it is an Ion int."""
    if isinstance(value, int) and not isinstance(value, (bool, Symbol)):
        return value
    return None


def _names(value: object) -> list[str]:
    """The names <value> gives: a name, or a list of them."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [name for name in value if isinstance(name, str)]
    return []


def _strings(value: object) -> Iterator[str]:
    """Every string anywhere in <value>."""
    stack = [value]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            yield value
        elif isinstance(value, (list, tuple)):
            stack.extend(value)
        elif isinstance(value, dict):
            stack.extend(value.values())


class _SymbolTable:

    """A document symbol table: the text of the symbols a book names its
    own entities by, as its sections, its storylines and its pictures.

    In KFX the table imports YJ_symbols, whose max_id there is the
    highest ID of the import counting Ion's nine system symbols, not the
    number of symbols imported: the table's own symbols follow it.
    """

    def __init__(self, table: object) -> None:
        if not isinstance(table, dict):
            raise _Unreadable('symbol table')
        symbols = table.get(_SYMBOLS)
        self.texts = [text if isinstance(text, str) else None
                      for text in (symbols if isinstance(symbols, list) else ())]
        self.first: int | None = None
        imports = table.get(_IMPORTS)
        for imported in imports if isinstance(imports, list) else ():
            if isinstance(imported, dict) and imported.get(_NAME) == 'YJ_symbols':
                max_id = _integer(imported.get(_MAX_ID))
                if max_id is not None:
                    self.first = max_id + 1
        max_id = _integer(table.get(_MAX_ID))
        if self.first is None and max_id is not None:
            self.first = max_id - len(self.texts) + 1
        if self.first is None:
            self.first = _FIRST_LOCAL_SYMBOL

    def text(self, symbol: int) -> str | None:
        """The text of <symbol>, where it is one of the table's own."""
        assert self.first is not None
        index = symbol - self.first
        return self.texts[index] if 0 <= index < len(self.texts) else None

    def resolve(self, value: object) -> object:
        """<value>, with each of the table's own symbols in it replaced
        by its text.  A book refers to its entities by name, as a symbol
        and at times as a string; with both as text they compare."""
        if isinstance(value, Symbol):
            text = self.text(value)
            return value if text is None else text
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if isinstance(value, dict):
            return {name: self.resolve(item) for name, item in value.items()}
        return value


class _Entity(NamedTuple):
    """Where one entity of a container is: its type, the symbol it is
    named by, and its bytes, header and all."""
    type: int
    name: int
    start: int
    length: int


class _Container:

    """One KFX container: its header read, its entities listed, and the
    file kept open for them to be read from: the file at <path>, or
    <file>, a member of a KFX-ZIP, which <path> then names."""

    def __init__(self, path: str, file: IO[bytes] | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._file: IO[bytes] | None = file if file is not None else open(path, 'rb')
        try:
            self._read_header()
        except BaseException:
            self.close()
            raise

    def read(self, start: int, length: int) -> bytes:
        """The <length> bytes from <start> on, or fewer where the file
        ends first."""
        with self._lock:
            if self._file is None:
                raise _Unreadable('closed')
            self._file.seek(start)
            return self._file.read(length)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def _ion(self, start: int, length: int) -> object:
        """The Ion value of the <length> bytes from <start> on."""
        data = self.read(start, length)
        if len(data) != length:
            raise _Unreadable('truncated')
        return ion.loads(data)

    def _read_header(self) -> None:
        """Read the header, the index and the symbol table.

        The header is the signature, the version, where the entities
        begin, and where the container info is: an Ion struct that says
        whether the entities are compressed or encrypted, where the
        index and the symbol table are, and what the container's ID is.
        Each record of the index is an entity's name and type, and where
        it is, from where the entities begin.
        """
        assert self._file is not None
        size = self._file.seek(0, os.SEEK_END)
        header = self.read(0, 18)
        if header.startswith(DRM_SIGNATURE):
            raise _Protected()
        if len(header) < 18 or not header.startswith(CONTAINER_SIGNATURE):
            raise _Unreadable('not a container')
        _version, entities_start, info_start, info_length = struct.unpack_from(
            '<HIII', header, 4)
        if not 18 <= entities_start <= size:
            raise _Unreadable('header')
        info = self._ion(info_start, info_length)
        if not isinstance(info, dict):
            raise _Unreadable('container info')
        if info.get(_DRM_SCHEME) not in (0, None):
            raise _Protected()
        if info.get(_COMPRESSION) not in (0, None):
            raise _Unreadable('compressed')
        container_id = info.get(_CONTAINER_ID)
        self.id = container_id if isinstance(container_id, str) else None

        self.entities: list[_Entity] = []
        index_start = _integer(info.get(_INDEX_OFFSET))
        index_length = _integer(info.get(_INDEX_LENGTH)) or 0
        if index_start is not None and index_length > 0:
            index = self.read(index_start, index_length)
            if len(index) != index_length or index_length % 24:
                raise _Unreadable('index')
            for name, kind, offset, length in struct.iter_unpack('<IIQQ', index):
                start = entities_start + offset
                # One past the end of the file is left out, as a
                # download cut short would have it, rather than the
                # book refused.
                if length >= 10 and start + length <= size:
                    self.entities.append(_Entity(kind, name, start, length))

        self.symbols: _SymbolTable | None = None
        symbols_start = _integer(info.get(_SYMBOLS_OFFSET))
        symbols_length = _integer(info.get(_SYMBOLS_LENGTH)) or 0
        if symbols_start is not None and symbols_length > 0:
            self.symbols = _SymbolTable(self._ion(symbols_start, symbols_length))

    def holds(self, *types: int) -> bool:
        """Whether the container holds an entity of each of <types>."""
        held = {entity.type for entity in self.entities}
        return all(kind in held for kind in types)

    def book_ids(self) -> set[str] | None:
        """The IDs of the containers of the book, as the container
        entity map this one holds lists them, which need not include
        this one; None where it holds no map."""
        for entity in self.entities:
            if entity.type == _CONTAINER_ENTITY_MAP:
                try:
                    entity_map = ion.loads(self.payload(entity))
                except (_Protected, _Unreadable, ion.IonError):
                    return None
                listed = entity_map.get(_CONTAINER_LIST) \
                    if isinstance(entity_map, dict) else None
                return {container[_ID] for container in
                        (listed if isinstance(listed, list) else ())
                        if isinstance(container, dict)
                        and isinstance(container.get(_ID), str)}
        return None

    def payload(self, entity: _Entity) -> bytes:
        """What <entity> holds, without its header: "ENTY", a version,
        the header's length, and an Ion struct saying whether what
        follows is compressed or encrypted."""
        data = self.read(entity.start, entity.length)
        if len(data) != entity.length or not data.startswith(_ENTITY_SIGNATURE):
            raise _Unreadable('entity')
        header_length, = struct.unpack_from('<I', data, 6)
        if not 10 <= header_length <= len(data):
            raise _Unreadable('entity header')
        if header_length > 10:
            info = ion.loads(data[10:header_length])
            if not isinstance(info, dict):
                raise _Unreadable('entity info')
            if info.get(_DRM_SCHEME) not in (0, None):
                raise _Protected()
            if info.get(_COMPRESSION) not in (0, None):
                raise _Unreadable('compressed')
        return data[header_length:]


#: The extensions of the files a book is kept in, split or not.
_PART_EXTENSIONS = ('.kfx', '.azw', '.azw8', '.azw9', '.md', '.res', '.yj')


def _is_part(name: str) -> bool:
    """Whether the file <name> may be part of a book: not the index of
    the iOS app's books, an SQLite database, and not what macOS leaves
    beside a file on a foreign disk."""
    return name.lower().endswith(_PART_EXTENSIONS) \
        and not name.startswith('._') and name.lower() != 'bookmanifest.kfx'


def _is_voucher(name: str) -> bool:
    """Whether the file <name> is a voucher: the licence of a book
    delivered with DRM."""
    return name.lower() == 'voucher' or name.lower().endswith('.voucher')


def _beside(path: str) -> list[str]:
    """The files the other parts of the book whose part <path> is may
    be, and its voucher.

    A Kindle keeps the main container in documents, and the others
    in the folder named after it with .sdr, under assets; the apps keep
    them all in one folder.  Opened from within the .sdr folder, the
    book is that folder and the main container beside it.
    """
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    sdr = os.path.join(folder, stem + '.sdr')
    ancestor = folder
    while not ancestor.lower().endswith('.sdr') \
            and os.path.dirname(ancestor) != ancestor:
        ancestor = os.path.dirname(ancestor)
    found: list[str] = []
    if os.path.isdir(sdr) or ancestor.lower().endswith('.sdr'):
        if not os.path.isdir(sdr):
            sdr = ancestor
            main = os.path.basename(sdr)[:-len('.sdr')]
            with os.scandir(os.path.dirname(sdr)) as entries:
                found.extend(entry.path for entry in entries if entry.is_file()
                             and os.path.splitext(entry.name)[0] == main)
        for root, _folders, files in os.walk(sdr):
            found.extend(os.path.join(root, name) for name in files)
    else:
        for subfolder in ('', 'assets', 'attachables',
                          os.path.join('assets', 'attachables')):
            try:
                with os.scandir(os.path.join(folder, subfolder)) as entries:
                    found.extend(entry.path for entry in entries if entry.is_file())
            except OSError:
                continue
    return sorted(name for name in found
                  if os.path.normcase(name) != os.path.normcase(path))


def is_kfx_zip(path: str) -> bool:
    """Whether the ZIP archive at <path> is a KFX-ZIP: no page in it,
    and a file that is a container, or one wrapped in DRM.

    The KFX Input plugin gathers the files of a book into one, flattened
    to their names, with no list of them: each is told by its name and
    its first bytes.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist()
                     if not name.endswith('/')]
            if any(image_tools.is_image_file(name) for name in names):
                return False
            for name in names:
                if _is_part(os.path.basename(name)):
                    with archive.open(name) as member:
                        if member.read(len(DRM_SIGNATURE)).startswith(
                                (CONTAINER_SIGNATURE, DRM_SIGNATURE)):
                            return True
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        pass
    return False


def _zipped_containers(archive: zipfile.ZipFile, path: str) -> list[_Container]:
    """The containers of the KFX-ZIP <archive>, at <path>: those of one
    book, the one with the container entity map first.

    The plugin leaves a book in a KFX-ZIP where it cannot join its
    parts into one container, a part wrapped in DRM above all: such a
    part refuses the book.
    """
    containers: list[_Container] = []
    try:
        for name in sorted(archive.namelist()):
            if not _is_part(os.path.basename(name)):
                continue
            try:
                containers.append(_Container('%s/%s' % (path, name), archive.open(name)))
            except (_Unreadable, ion.IonError, struct.error, zipfile.BadZipFile,
                    RuntimeError, NotImplementedError) as error:
                log.debug('KFX %s/%s: %s', path, name, error)
        if not containers:
            raise _Unreadable('no container')
    except BaseException:
        for container in containers:
            container.close()
        raise
    containers.sort(key=lambda container: container.book_ids() is None)
    return containers


def _containers(path: str) -> list[_Container]:
    """The containers of the book whose part <path> is, the one with
    the container entity map first: its symbol table names what the
    containers without one hold.

    A container that holds the reading order, the pictures' descriptions
    and their bytes is a book of its own.  Another is joined by the
    files beside it that the map names, the map found in the container
    itself or in one that names it: a folder of other books gives none
    of theirs.  A book whose map names a container that is not there,
    where one beside it is wrapped in DRM or a voucher is, is refused.
    """
    opened = _Container(path)
    if opened.holds(_SECTION, _EXTERNAL_RESOURCE, _RAW_MEDIA):
        return [opened]
    others: list[_Container] = []
    try:
        protected = voucher = False
        for candidate in _beside(path):
            name = os.path.basename(candidate)
            if _is_voucher(name):
                voucher = True
            elif _is_part(name):
                try:
                    others.append(_Container(candidate))
                except _Protected:
                    protected = True
                except (_Unreadable, ion.IonError, struct.error, OSError) as error:
                    log.debug('KFX %s: %s', candidate, error)
        for holder in [opened] + others:
            ids = holder.book_ids()
            if ids is not None and (holder is opened or opened.id in ids):
                break
        else:
            return [opened]
        book = [holder] + [container for container in [opened] + others
                           if container is not holder and container.id in ids]
        missing = ids - {container.id for container in book}
        if missing and (protected or voucher):
            raise _Protected()
        if missing:
            log.warning('KFX %s: no container %s', path, ', '.join(sorted(missing)))
    except BaseException:
        for container in [opened] + others:
            container.close()
        raise
    for container in others:
        if container not in book:
            container.close()
    return book


class _Picture(NamedTuple):
    """One resolution of a page's picture, which can be shown: stored
    as format <stored_as>, whole under <location>, or cut into the
    <tiles> named, rows of them from the top, each <tile_size> large but
    for the last in a row or column, and overlapping the next by
    <padding> pixels."""
    extension: str
    stored_as: int
    width: int
    height: int
    location: str | None
    tiles: list[list[str]] | None = None
    tile_size: tuple[int, int] = (0, 0)
    padding: int = 0


class _Book:

    """The entities of a book's containers, by type and name."""

    def __init__(self, containers: list[_Container]) -> None:
        self.containers = containers
        # A container with no symbol table of its own, as one that holds
        # only pictures' bytes, names its entities by the book's.
        self._fallback = next((container.symbols for container in containers
                               if container.symbols is not None), None)
        self._entities: dict[tuple[int, str | None], tuple[_Container, _Entity]] = {}
        self._values: dict[tuple[int, str | None], object] = {}
        for container in containers:
            symbols = container.symbols or self._fallback
            for entity in container.entities:
                if entity.name == _NAMELESS:
                    name = None
                else:
                    name = symbols.text(entity.name) if symbols else None
                    if name is None:
                        name = '$%d' % entity.name
                self._entities.setdefault((entity.type, name), (container, entity))

    def has(self, type: int, name: str | None) -> bool:
        return (type, name) in self._entities

    def names(self, type: int) -> list[str]:
        """The names of the entities of <type>, in the order the
        containers list them."""
        return [name for kind, name in self._entities
                if kind == type and name is not None]

    def payload(self, type: int, name: str | None) -> bytes | None:
        """What the entity of <type> named <name> holds, as it stands."""
        found = self._entities.get((type, name))
        if found is None:
            return None
        container, entity = found
        return container.payload(entity)

    def value(self, type: int, name: str | None) -> dict[int, object]:
        """The struct the entity of <type> named <name> holds, with the
        book's symbols read as their text; empty where there is no such
        entity, or it cannot be read."""
        key = (type, name)
        if key not in self._values:
            value: object = None
            found = self._entities.get(key)
            if found is not None:
                container, entity = found
                symbols = container.symbols or self._fallback
                try:
                    value = ion.loads(container.payload(entity))
                except (_Protected, _Unreadable, ion.IonError) as error:
                    log.warning('KFX entity $%d %s of %s: %s', type, name,
                                container.path, error)
                if symbols is not None:
                    value = symbols.resolve(value)
            self._values[key] = value
        value = self._values[key]
        return value if isinstance(value, dict) else {}

    def pictures(self) -> list[_Picture]:
        """The pictures of the book's pages, in reading order."""
        names = self._reading_order()
        if names is None:
            names = self._unordered()
        pictures = []
        for name in names:
            picture = self._picture(name)
            if picture is None:
                log.warning('KFX: no picture of %s can be shown', name)
            else:
                pictures.append(picture)
        return pictures

    def _reading_order(self) -> list[str] | None:
        """The names of the pictures the reading order shows, in order;
        None where the book has no reading order.

        The reading order is a list of sections, each a page or a
        spread, in the document data or, in older books, the metadata.
        A book with more than one has their sections one after the
        other, each once.
        """
        for source in (_DOCUMENT_DATA, _METADATA):
            orders = self.value(source, None).get(_READING_ORDERS)
            sections: list[str] = []
            for order in orders if isinstance(orders, list) else ():
                if isinstance(order, dict):
                    for section in _names(order.get(_SECTIONS)):
                        if section not in sections:
                            sections.append(section)
            if sections:
                return [picture for section in sections
                        for picture in self._section(section)]
        return None

    def _section(self, name: str) -> Iterator[str]:
        """The names of the pictures section <name> shows, in document
        order: an element before its children, its children in order.

        A section's page template is the page: in a comic a container
        with the page's picture in it, or a spread holding two of them,
        the first page to be read first.  Children are listed in the
        element, or in the storyline it names.  Nothing that is not
        shown counts, nor a zoom target, which repeats a panel.
        """
        templates = self.value(_SECTION, name).get(_PAGE_TEMPLATES)
        if not isinstance(templates, list) or not templates:
            return
        template = templates[0]
        if isinstance(template, str):
            template = self.value(_STRUCTURE, template)
        stories: set[str] = set()
        stack = [template]
        while stack:
            element = stack.pop()
            if not isinstance(element, dict) or element.get(_IGNORE) is True \
                    or element.get(_TYPE) == _ZOOM_TARGET:
                continue
            background = element.get(_BACKGROUND_IMAGE)
            style = element.get(_STYLE)
            if background is None and isinstance(style, str):
                background = self.value(_STYLE, style).get(_BACKGROUND_IMAGE)
            if isinstance(background, str):
                yield background
            resource = element.get(_RESOURCE_NAME)
            if element.get(_TYPE) == _IMAGE and isinstance(resource, str):
                yield resource
            children = element.get(_CONTENT_LIST)
            story = element.get(_STORY_NAME)
            if not isinstance(children, list) and isinstance(story, str) \
                    and story not in stories:
                stories.add(story)
                children = self.value(_STORYLINE, story).get(_CONTENT_LIST)
            if isinstance(children, list):
                stack.extend(reversed(children))

    def _unordered(self) -> list[str]:
        """The pictures of a book without a reading order, in the order
        the containers list them: what that order is worth is not
        known.  A thumbnail, another resolution of a picture, and the
        pictures the Kindle's own interface shows are no pages."""
        resources = self.names(_EXTERNAL_RESOURCE)
        excluded = set(_strings(self.value(_PREVIEW_IMAGES, None)))
        for name in resources:
            resource = self.value(_EXTERNAL_RESOURCE, name)
            excluded.update(_names(resource.get(_THUMBNAILS)))
            excluded.update(_names(resource.get(_VARIANTS)))
        return [name for name in resources if name not in excluded]

    def _picture(self, name: str) -> _Picture | None:
        """The resolution of picture <name> to show: the largest of it
        and the variants it lists that can be shown, where one is larger
        than the rest in both width and height."""
        primary = self.value(_EXTERNAL_RESOURCE, name)
        best = self._resolution(primary, True)
        for variant in _names(primary.get(_VARIANTS)):
            picture = self._resolution(self.value(_EXTERNAL_RESOURCE, variant), False)
            if picture is not None and (
                    best is None
                    or picture.width > best.width and picture.height > best.height):
                best = picture
        return best

    def _resolution(self, resource: dict[int, object], primary: bool) -> _Picture | None:
        """The picture external resource <resource> describes, where it
        can be shown.  The tiles of a variant have to be there, every
        one; a tile missing from the picture a page names leaves a gap."""
        stored_as = resource.get(_FORMAT)
        extension = _extension(stored_as)
        if extension is None or not isinstance(stored_as, int):
            return None
        width = _integer(resource.get(_RESOURCE_WIDTH, resource.get(_FIXED_WIDTH))) or 0
        height = _integer(resource.get(_RESOURCE_HEIGHT, resource.get(_FIXED_HEIGHT))) or 0
        location = resource.get(_LOCATION)
        if isinstance(location, str):
            if not self.has(_RAW_MEDIA, location):
                return None
            return _Picture(extension, stored_as, width, height, location)
        tiles = resource.get(_TILES)
        tile_width = _integer(resource.get(_TILE_WIDTH)) or 0
        tile_height = _integer(resource.get(_TILE_HEIGHT)) or 0
        padding = _integer(resource.get(_TILE_PADDING)) or 0
        if not isinstance(tiles, list) or tile_width <= 0 or tile_height <= 0 \
                or width <= 0 or height <= 0 or padding < 0:
            return None
        # Pillow's own limit on a picture it opens, for the one put
        # together here from what the book says its size is.
        if Image.MAX_IMAGE_PIXELS is not None \
                and width * height > Image.MAX_IMAGE_PIXELS:
            return None
        rows = [_names(row) for row in tiles]
        present = [self.has(_RAW_MEDIA, tile) for row in rows for tile in row]
        if not any(present) or not primary and not all(present):
            return None
        return _Picture('png', stored_as, width, height, None, rows,
                        (tile_width, tile_height), padding)

    def comic_info(self) -> bytes | None:
        """What the book says of itself, as a ComicInfo.xml: its title,
        authors, publisher and year, and whether it reads right to left;
        None where it says none of it.

        MComix reads a ComicInfo.xml for the book's properties, and opens
        a book whose file says it reads right to left in manga mode.  A
        book reads right to left where its document data says so, or
        its writing runs in vertical lines from the right.
        """
        entries: dict[str, list[object]] = {}
        categories = self.value(_BOOK_METADATA, None).get(_CATEGORISED_METADATA)
        for category in categories if isinstance(categories, list) else ():
            if not isinstance(category, dict) \
                    or category.get(_CATEGORY) != 'kindle_title_metadata':
                continue
            pairs = category.get(_ENTRIES)
            for pair in pairs if isinstance(pairs, list) else ():
                if isinstance(pair, dict) and isinstance(pair.get(_KEY), str):
                    entries.setdefault(str(pair[_KEY]), []).append(pair.get(_VALUE))
        # Older books keep it in fields of their metadata, the authors
        # in one, joined by "&".
        older = self.value(_METADATA, None)
        for key, field in (('title', _TITLE), ('author', _AUTHOR),
                           ('publisher', _PUBLISHER)):
            if key not in entries and isinstance(older.get(field), str):
                value = str(older[field])
                entries[key] = list(value.split('&')) if key == 'author' \
                    else [value]

        def text(key: str) -> list[str]:
            return [value.strip() for value in entries.get(key, ())
                    if isinstance(value, str) and value.strip()]

        document = self.value(_DOCUMENT_DATA, None)
        return comicinfo.of_book(
            next(iter(text('title')), None),
            next((date[:4] for date in text('issue_date')[:1]), None),
            text('author'),
            next(iter(text('publisher')), None),
            document.get(_DIRECTION) == _RIGHT_TO_LEFT
            or document.get(_WRITING_MODE) == _VERTICAL_RIGHT_TO_LEFT)

    def tiled(self, picture: _Picture, folder: str) -> Image.Image:
        """The picture whose tiles <picture> names, put together; tiles
        in JPEG XR are decoded in <folder>.

        A tile is its cell of the grid with up to <padding> pixels of
        the cells around it on each side, where there are cells: the
        padding left of it and above it is cut off, and what follows
        the cell is drawn over by the next one, or is past the edge.
        """
        assert picture.tiles is not None
        tile_width, tile_height = picture.tile_size
        canvas: Image.Image | None = None
        for row, locations in enumerate(picture.tiles):
            for column, location in enumerate(locations):
                data = self.payload(_RAW_MEDIA, location)
                if data is None:
                    continue
                try:
                    tile = _open_picture(data, picture.stored_as, folder)
                    tile.load()
                except (OSError, ValueError, Image.DecompressionBombError) as error:
                    # Bytes no decoder reads leave a gap, as a tile not
                    # there does (UnidentifiedImageError is an OSError).
                    log.debug('KFX tile %s: %s', location, error)
                    continue
                if canvas is None:
                    mode = 'L' if tile.mode == 'L' else 'RGB'
                    canvas = Image.new(mode, (picture.width, picture.height), 'white')
                left = picture.padding if column else 0
                top = picture.padding if row else 0
                width = min(tile_width, picture.width - column * tile_width)
                height = min(tile_height, picture.height - row * tile_height)
                if width <= 0 or height <= 0:
                    continue
                cell = tile.convert(canvas.mode).crop((left, top, left + width, top + height))
                canvas.paste(cell, (column * tile_width, row * tile_height))
        if canvas is None:
            raise _Unreadable('no tiles')
        return canvas


class KfxArchive(archive_base.BaseArchive):

    """The pictures of a KFX book's pages, as though they were an
    archive's: page00001.jpg on, in reading order, then a ComicInfo.xml
    of what the book says of itself, where it says anything.

    The book stays open for as long as the handler does, and a page is
    read out of it as it is asked for.  A page whose picture is cut into
    tiles is put together and listed as a PNG; one in JPEG XR is
    decoded and listed as a TIFF.
    """

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        name = os.path.basename(archive)
        self._zip: zipfile.ZipFile | None = None
        try:
            with open(archive, 'rb') as fp:
                head = fp.read(len(DRM_SIGNATURE))
            if head.startswith((CONTAINER_SIGNATURE, DRM_SIGNATURE)):
                containers = _containers(archive)
            else:
                self._zip = zipfile.ZipFile(archive)
                containers = _zipped_containers(self._zip, archive)
        except BaseException as error:
            if self._zip is not None:
                self._zip.close()
            if isinstance(error, _Protected):
                raise UnpackException(
                    _('Could not open %s: it is protected by DRM.') % name) from None
            # NotImplementedError and RuntimeError: a KFX-ZIP of a ZIP
            # version or a feature zipfile does not read, or encrypted.
            if isinstance(error, (_Unreadable, ion.IonError, struct.error,
                                  zipfile.BadZipFile, NotImplementedError,
                                  RuntimeError)):
                log.debug('KFX %s: %s', archive, error)
                raise UnpackException(
                    _('Could not open %s: it is not a Kindle book MComix can read.')
                    % name) from None
            raise
        self._book = _Book(containers)
        self._pages: dict[str, _Picture] | None = None
        self._comic_info: bytes | None = None

    def _listed(self) -> dict[str, _Picture]:
        if self._pages is None:
            pictures = self._book.pictures()
            self._comic_info = self._book.comic_info()
            self._pages = {'page%05d.%s' % (number, picture.extension): picture
                           for number, picture in enumerate(pictures, 1)}
        return self._pages

    def iter_contents(self) -> Iterator[str]:
        yield from self._listed()
        if self._comic_info is not None:
            yield comicinfo.NAME

    def extract(self, filename: str, destination_dir: str) -> None:
        """Extract <filename> from the archive to <destination_dir>."""
        picture = self._listed().get(filename)
        destination_path = os.path.join(destination_dir, filename)
        if filename == comicinfo.NAME and self._comic_info is not None:
            with self._create_file(destination_path) as new:
                new.write(self._comic_info)
            return
        if picture is None:
            return
        self._create_directory(destination_dir)
        if picture.location is not None:
            data = self._book.payload(_RAW_MEDIA, picture.location)
            if data is None:
                return
            if picture.stored_as == _JPEG_XR:
                _decode_jpeg_xr(data, destination_path)
                return
            with self._create_file(destination_path) as new:
                new.write(data)
        else:
            image = self._book.tiled(picture, destination_dir)
            with self._create_file(destination_path) as new:
                image.save(new, 'PNG', compress_level=1)

    def close(self) -> None:
        for container in self._book.containers:
            container.close()
        if self._zip is not None:
            self._zip.close()
