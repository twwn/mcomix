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

Written for issue #50, under the GPL v2 or later, from a description of
the format in prose and from Amazon's public Ion specification, by a
reader of neither the KFX Input plugin nor any other KFX reader's code.
Amazon does not publish the format; the symbol IDs below are the numbers
its shared symbol table, YJ_symbols, gives the fields and values a page
reader needs.

A book with DRM is refused: its pages cannot be read.
"""

import io
import os
import struct
import threading
from collections.abc import Iterator
from typing import IO, NamedTuple

from PIL import Image

from mcomix import log
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

#: The formats of picture shown as they are stored, and the extension
#: each is listed under.
_EXTENSIONS = {285: 'jpg', 284: 'png', 286: 'gif'}

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
    file kept open for them to be read from."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._file: IO[bytes] | None = open(path, 'rb')
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
        size = os.fstat(self._file.fileno()).st_size
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


class _Picture(NamedTuple):
    """One resolution of a page's picture, which can be shown: stored
    whole under <location>, or cut into the <tiles> named, rows of them
    from the top, each <tile_size> large but for the last in a row or
    column, and overlapping the next by <padding> pixels."""
    extension: str
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
        extension = _EXTENSIONS.get(stored_as) if isinstance(stored_as, int) else None
        if extension is None:
            return None
        width = _integer(resource.get(_RESOURCE_WIDTH, resource.get(_FIXED_WIDTH))) or 0
        height = _integer(resource.get(_RESOURCE_HEIGHT, resource.get(_FIXED_HEIGHT))) or 0
        location = resource.get(_LOCATION)
        if isinstance(location, str):
            if not self.has(_RAW_MEDIA, location):
                return None
            return _Picture(extension, width, height, location)
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
        return _Picture('png', width, height, None, rows,
                        (tile_width, tile_height), padding)

    def tiled(self, picture: _Picture) -> Image.Image:
        """The picture whose tiles <picture> names, put together.

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
                tile = Image.open(io.BytesIO(data))
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
    archive's: page00001.jpg on, in reading order.

    The book stays open for as long as the handler does, and a page is
    read out of it as it is asked for.  A page whose picture is cut into
    tiles is put together and listed as a PNG.
    """

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        name = os.path.basename(archive)
        try:
            self._book = _Book([_Container(archive)])
        except _Protected:
            raise UnpackException(
                _('Could not open %s: it is protected by DRM.') % name) from None
        except (_Unreadable, ion.IonError, struct.error) as error:
            log.debug('KFX %s: %s', archive, error)
            raise UnpackException(
                _('Could not open %s: it is not a Kindle book MComix can read.')
                % name) from None
        self._pages: dict[str, _Picture] | None = None

    def _listed(self) -> dict[str, _Picture]:
        if self._pages is None:
            pictures = self._book.pictures()
            self._pages = {'page%05d.%s' % (number, picture.extension): picture
                           for number, picture in enumerate(pictures, 1)}
        return self._pages

    def iter_contents(self) -> Iterator[str]:
        yield from self._listed()

    def extract(self, filename: str, destination_dir: str) -> None:
        """Extract <filename> from the archive to <destination_dir>."""
        picture = self._listed().get(filename)
        if picture is None:
            return
        destination_path = os.path.join(destination_dir, filename)
        if picture.location is not None:
            data = self._book.payload(_RAW_MEDIA, picture.location)
            if data is None:
                return
            with self._create_file(destination_path) as new:
                new.write(data)
        else:
            image = self._book.tiled(picture)
            with self._create_file(destination_path) as new:
                image.save(new, 'PNG', compress_level=1)

    def close(self) -> None:
        for container in self._book.containers:
            container.close()
