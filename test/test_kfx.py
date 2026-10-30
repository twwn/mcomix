"""The KFX handler, over books put together here.

No KFX comic free of DRM is to be had, so the books are built from the
description of the format: containers whose entities are Ion values
written by test_ion.dumps(), and pictures made by Pillow.
"""

import io
import os
import struct

from PIL import Image, ImageChops

from . import MComixTest, wait_for
from .test_file_handler import _WindowTest
from .test_ion import Annotated, dumps

from mcomix import archive_tools
from mcomix import comicinfo
from mcomix import constants
from mcomix.archive import kfx
from mcomix.archive.ion import Symbol
from mcomix.preferences import prefs

# The symbols of YJ_symbols the books below use.
NAMELESS = Symbol(348)
RAW_MEDIA, EXTERNAL_RESOURCE, DOCUMENT_DATA, METADATA = 417, 164, 538, 258
SECTION, STORYLINE, STYLE, BOOK_METADATA = 260, 259, 157, 490
CONTAINER, IMAGE, ZOOM_TARGET = Symbol(270), Symbol(271), Symbol(439)
SCALE_FIT, PAGE_SPREAD = Symbol(326), Symbol(437)
JPG, PNG, JXR = Symbol(285), Symbol(284), Symbol(548)
RIGHT_TO_LEFT, VERTICAL_RIGHT_TO_LEFT = Symbol(375), Symbol(559)

#: The max_id of the YJ_symbols import: the highest symbol ID it
#: reaches, the system symbols counted.  The book's own symbols follow.
SHARED_MAX_ID = 859


def picture(size=(8, 12), colour=(200, 30, 90), format='JPEG', image=None):
    """A picture of <size>, all <colour> or <image>, encoded as <format>."""
    data = io.BytesIO()
    (image or Image.new('RGB', size, colour)).save(data, format)
    return data.getvalue()


def gradient(width, height):
    """A picture no two of whose pixels are alike, as far as it goes."""
    image = Image.new('RGB', (width, height))
    image.putdata([(x * 7 % 256, y * 5 % 256, (x * y) % 256)
                   for y in range(height) for x in range(width)])
    return image


class Book:

    """A KFX book being put together: its own symbols, and its entities."""

    def __init__(self, shared_max_id=SHARED_MAX_ID):
        self.shared_max_id = shared_max_id
        self.symbols = []
        self.entities = []

    def symbol(self, text):
        """The book's own symbol for <text>, added if it is new."""
        if text not in self.symbols:
            self.symbols.append(text)
        return Symbol(self.shared_max_id + 1 + self.symbols.index(text))

    def add(self, type, name, value):
        """An entity of <type>, named <name> (None for none), holding
        <value>: bytes as they are, anything else as Ion."""
        name = NAMELESS if name is None else self.symbol(name)
        payload = value if isinstance(value, bytes) else dumps(value)
        self.entities.append((type, name, payload))

    def reading_order(self, *sections, source=DOCUMENT_DATA, fields=()):
        self.add(source, None, {169: [{178: Symbol(351), 170: [
            self.symbol(section) for section in sections]}], **dict(fields)})

    def resource(self, name, location, size=(8, 12), format=JPG, fields=()):
        """The external resource <name>, whose bytes are at <location>,
        with <fields> besides."""
        value = {175: self.symbol(name), 161: format, 162: 'image/jpg',
                 422: size[0], 423: size[1], **dict(fields)}
        if location is not None:
            value[165] = location
        self.add(EXTERNAL_RESOURCE, name, value)

    def page(self, section, resource):
        """Section <section>, a page drawing resource <resource>."""
        self.add(SECTION, section, {174: self.symbol(section), 141: [
            {155: 1, 159: CONTAINER, 156: SCALE_FIT, 66: 8, 67: 12,
             146: [{155: 2, 159: IMAGE, 175: self.symbol(resource)}]}]})

    def picture_page(self, number, data):
        """Section c<number>, a page showing the JPEG <data>."""
        self.page('c%d' % number, 'e%d' % number)
        self.resource('e%d' % number, 'rsrc%d' % number)
        self.add(RAW_MEDIA, 'rsrc%d' % number, data)

    def comic(self, *pages, document=()):
        """A comic of <pages>, pictures in reading order, each its own
        page, resource and bytes; the last picture's bytes the last
        entity.  <document> adds to the document data."""
        self.reading_order(*('c%d' % number for number in range(len(pages))),
                           fields=document)
        for number, data in enumerate(pages):
            self.picture_page(number, data)
        return self

    def container(self, container_id='CR!TEST', info=None, symbols=True,
                  entity_info=None):
        """The book as one container.  <info> and <entity_info> add to
        or replace what the container info and each entity's say."""
        index = b''
        data = b''
        for type, name, payload in self.entities:
            header = dumps({410: 0, 411: 0, **(entity_info or {})})
            entity = (b'ENTY' + struct.pack('<HI', 1, 10 + len(header))
                      + header + payload)
            index += struct.pack('<IIQQ', name, type, len(data), len(entity))
            data += entity
        table = dumps(Annotated([3], {
            6: [{4: 'YJ_symbols', 5: 10, 8: self.shared_max_id}],
            7: list(self.symbols),
            8: self.shared_max_id + len(self.symbols)})) if symbols else b''
        index_start = 18
        table_start = index_start + len(index)
        info_start = table_start + len(table)
        fields = {409: container_id, 410: 0, 411: 0, 412: 4096,
                  413: index_start, 414: len(index)}
        if table:
            fields.update({415: table_start, 416: len(table)})
        fields.update(info or {})
        container_info = dumps(fields)
        trailer = b'[]'
        start = info_start + len(container_info) + len(trailer)
        header = b'CONT' + struct.pack('<HIII', 2, start, info_start,
                                       len(container_info))
        return header + index + table + container_info + trailer + data


class KfxTest(MComixTest):

    def write(self, data, name='book.kfx'):
        path = os.path.join(self.tmp_dir, name)
        with open(path, 'wb') as fp:
            fp.write(data)
        return path

    def open(self, data):
        archive = kfx.KfxArchive(self.write(data))
        self.addCleanup(archive.close)
        return archive

    def extracted(self, archive, name):
        destination = os.path.join(self.tmp_dir, 'out')
        archive.extract(name, destination)
        with open(os.path.join(destination, name), 'rb') as fp:
            return fp.read()

    def test_a_comic(self):
        """A book of one container lists its pages in reading order, and
        each holds its picture's bytes as the book stores them; a file
        that begins as a container is a KFX book, whatever its name."""
        pages = [picture(colour=(n * 60, 0, 0)) for n in range(3)]
        archive = self.open(Book().comic(*pages).container())
        self.assertEqual(['page00001.jpg', 'page00002.jpg', 'page00003.jpg'],
                         archive.list_contents())
        for number, data in enumerate(pages, 1):
            self.assertEqual(data, self.extracted(archive, 'page%05d.jpg' % number))
        self.assertEqual(constants.KFX, archive_tools.archive_mime_type(
            self.write(Book().comic(pages[0]).container(), 'book')))
        self.assertEqual((constants.KFX, 3), archive_tools.get_archive_info(
            self.write(Book().comic(*pages).container()))[:2])

    def test_reading_order(self):
        """The pages come in the reading order's order, whatever order
        the container keeps their entities in."""
        book = Book()
        for number in (2, 0, 1):
            book.page('c%d' % number, 'e%d' % number)
            book.resource('e%d' % number, 'rsrc%d' % number, format=PNG)
            book.add(RAW_MEDIA, 'rsrc%d' % number,
                     picture(colour=(number, 0, 0), format='PNG'))
        book.reading_order('c0', 'c1', 'c2')
        archive = self.open(book.container())
        self.assertEqual([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [
            Image.open(io.BytesIO(self.extracted(archive, name))).getpixel((0, 0))
            for name in archive.list_contents()])

    def test_older_books_keep_the_order_in_their_metadata(self):
        book = Book()
        for number in (1, 0):
            book.page('c%d' % number, 'e%d' % number)
            book.resource('e%d' % number, 'rsrc%d' % number)
            book.add(RAW_MEDIA, 'rsrc%d' % number, picture((number + 1, 1)))
        book.reading_order('c0', 'c1', source=METADATA)
        archive = self.open(book.container())
        self.assertEqual(picture((1, 1)),
                         self.extracted(archive, 'page00001.jpg'))

    def test_a_spread(self):
        """A section that is a spread shows its two pages, in the order
        its storyline lists them."""
        book = Book()
        book.picture_page(0, picture((1, 1)))
        book.add(SECTION, 'spread', {174: book.symbol('spread'), 141: [
            {155: 10, 159: CONTAINER, 156: PAGE_SPREAD,
             176: book.symbol('story')}]})
        book.add(STORYLINE, 'story', {176: book.symbol('story'), 146: [
            {155: 11 + side, 159: CONTAINER, 156: SCALE_FIT, 146: [
                {155: 13 + side, 159: IMAGE, 175: book.symbol('half%d' % side)}]}
            for side in (0, 1)]})
        for side in (0, 1):
            book.resource('half%d' % side, 'h%d' % side)
            book.add(RAW_MEDIA, 'h%d' % side, picture((2 + side, 1)))
        book.reading_order('c0', 'spread')
        archive = self.open(book.container())
        self.assertEqual(3, len(archive.list_contents()))
        self.assertEqual(picture((2, 1)), self.extracted(archive, 'page00002.jpg'))
        self.assertEqual(picture((3, 1)), self.extracted(archive, 'page00003.jpg'))

    def test_what_is_not_shown(self):
        """An element marked to be ignored, and a zoom target, which
        repeats a panel, draw no page; a background, the element's own
        or its style's, does."""
        book = Book()
        book.add(SECTION, 's', {174: book.symbol('s'), 141: [
            {155: 1, 159: CONTAINER, 146: [
                {155: 2, 159: IMAGE, 175: book.symbol('hidden'), 69: True},
                {155: 3, 159: ZOOM_TARGET, 146: [
                    {155: 4, 159: IMAGE, 175: book.symbol('zoomed')}]},
                {155: 5, 159: CONTAINER, 157: book.symbol('style')},
                {155: 6, 159: CONTAINER, 479: book.symbol('own')},
            ]}]})
        book.add(STYLE, 'style', {479: book.symbol('styled')})
        for number, name in enumerate(('hidden', 'zoomed', 'styled', 'own')):
            book.resource(name, name)
            book.add(RAW_MEDIA, name, picture((number + 1, 1)))
        book.reading_order('s')
        archive = self.open(book.container())
        self.assertEqual(['page00001.jpg', 'page00002.jpg'], archive.list_contents())
        self.assertEqual(picture((3, 1)), self.extracted(archive, 'page00001.jpg'))
        self.assertEqual(picture((4, 1)), self.extracted(archive, 'page00002.jpg'))

    def test_without_a_reading_order(self):
        """A book without a reading order shows its pictures in the order
        its container lists them, but not a thumbnail, another
        resolution of a picture, or a picture of the Kindle's own."""
        book = Book()
        book.resource('e0', 'r0', fields={214: Annotated([164], book.symbol('thumb'))})
        book.resource('thumb', 'rt')
        book.resource('e1', 'r1', fields={635: [book.symbol('big')]})
        book.resource('big', 'rb', size=(16, 24))
        book.resource('toc', 'rc')
        book.add(387, None, {212: [book.symbol('toc')]})
        for location in ('r0', 'rt', 'r1', 'rb', 'rc'):
            book.add(RAW_MEDIA, location, picture())
        archive = self.open(book.container())
        self.assertEqual(['page00001.jpg', 'page00002.jpg'], archive.list_contents())

    def test_the_largest_resolution(self):
        """Of a picture's resolutions, the one larger than the rest in
        both width and height is shown; one larger in one only, one
        whose bytes are not there, and one in a format not shown (JPEG
        XR) are passed over."""
        book = Book()
        book.page('c0', 'e0')
        book.resource('e0', 'small', fields={635: [
            book.symbol(name) for name in ('large', 'wide', 'gone', 'jxr')]})
        book.resource('wide', 'wide', size=(100, 12))
        book.resource('gone', 'nowhere', size=(400, 600))
        book.resource('jxr', 'jxr', size=(300, 450), format=JXR)
        book.resource('large', 'large', size=(16, 24))
        for number, location in enumerate(('small', 'wide', 'jxr', 'large')):
            book.add(RAW_MEDIA, location, picture(colour=(number, 0, 0)))
        book.reading_order('c0')
        archive = self.open(book.container())
        self.assertEqual(picture(colour=(3, 0, 0)),
                         self.extracted(archive, 'page00001.jpg'))

    def tiled(self, padding, primary=False, missing=()):
        """A comic of one page whose picture, 23 by 17, is cut into tiles
        of 10 by 6 overlapping by <padding>, the resolution shown or
        the page's own; and the picture."""
        image = gradient(23, 17)
        width, height, size = 23, 17, (10, 6)
        book = Book()
        rows = []
        for top in range(0, height, size[1]):
            row = []
            for left in range(0, width, size[0]):
                name = 'tile-%d-%d' % (top, left)
                box = (max(left - padding, 0), max(top - padding, 0),
                       min(left + size[0] + padding, width),
                       min(top + size[1] + padding, height))
                if name not in missing:
                    book.add(RAW_MEDIA, name, picture(
                        image=image.crop(box), format='PNG'))
                row.append(name)
            rows.append(row)
        tiles = {636: rows, 637: size[0], 638: size[1], 797: padding}
        book.page('c0', 'e0')
        if primary:
            book.resource('e0', None, size=(width, height), format=PNG, fields=tiles)
        else:
            book.resource('e0', 'small', format=PNG, fields={635: [book.symbol('big')]})
            book.add(RAW_MEDIA, 'small', picture(format='PNG'))
            book.resource('big', None, size=(width, height), format=PNG, fields=tiles)
        book.reading_order('c0')
        return self.open(book.container()), image

    def test_tiles(self):
        """A picture cut into tiles is put together as it was, the tiles
        overlapping or not, and listed as a PNG."""
        for padding in (0, 2, 5):
            with self.subTest(padding=padding):
                archive, image = self.tiled(padding)
                self.assertEqual(['page00001.png'], archive.list_contents())
                shown = Image.open(io.BytesIO(
                    self.extracted(archive, 'page00001.png')))
                self.assertEqual(image.size, shown.size)
                self.assertIsNone(ImageChops.difference(
                    image, shown.convert('RGB')).getbbox())

    def test_missing_tiles(self):
        """A tile missing from another resolution of the picture passes
        that resolution over; from the page's own picture, it leaves a
        gap."""
        archive, _image = self.tiled(2, missing=('tile-6-10',))
        self.assertEqual(['page00001.png'], archive.list_contents())
        self.assertEqual((8, 12), Image.open(io.BytesIO(
            self.extracted(archive, 'page00001.png'))).size)
        archive, image = self.tiled(2, primary=True, missing=('tile-6-10',))
        shown = Image.open(io.BytesIO(self.extracted(archive, 'page00001.png')))
        self.assertEqual((10, 6, 20, 12), ImageChops.difference(
            image, shown.convert('RGB')).getbbox())

    def test_symbol_tables(self):
        """The book's own symbols follow the YJ_symbols import, wherever
        its max_id puts them, and where it has none, the table's own
        max_id says where they end."""
        for shared_max_id in (626, 700, 900):
            with self.subTest(shared_max_id=shared_max_id):
                book = Book(shared_max_id).comic(picture())
                self.assertEqual(['page00001.jpg'],
                                 self.open(book.container()).list_contents())
        book = Book(700).comic(picture())
        data = book.container()
        # The import's max_id, field 8, made null: dumps() writes 700 as
        # 22 02 bc, null.int is 2f, and a field $0 holding a pad of one
        # byte keeps the length.
        imported = bytes.fromhex('88 22 02 bc')
        self.assertEqual(1, data.count(imported))
        data = data.replace(imported, bytes.fromhex('88 2f 80 00'))
        self.assertEqual(['page00001.jpg'], self.open(data).list_contents())

    def comic_info(self, archive):
        """The ComicInfo.xml <archive> lists, written out."""
        self.assertEqual(comicinfo.NAME, archive.list_contents()[-1])
        destination = os.path.join(self.tmp_dir, 'out')
        archive.extract(comicinfo.NAME, destination)
        return os.path.join(destination, comicinfo.NAME)

    def test_what_the_book_says_of_itself(self):
        """The book's title, authors, publisher and year, and that it
        reads right to left, are listed as a ComicInfo.xml, which is
        what MComix reads them from."""
        book = Book().comic(picture(), document={192: RIGHT_TO_LEFT})
        book.add(BOOK_METADATA, None, {491: [
            {495: 'kindle_capability_metadata', 258: [
                {492: 'yj_fixed_layout', 307: 1}]},
            {495: 'kindle_title_metadata', 258: [
                {492: key, 307: value} for key, value in (
                    ('title', 'Night Watch'), ('author', 'Ann Author'),
                    ('author', 'Bo Artist'), ('publisher', 'Press'),
                    ('issue_date', '2021-03-04'), ('cover_image', 'e0'))]}]})
        path = self.comic_info(self.open(book.container()))
        self.assertEqual([('Title', 'Night Watch'), ('Year', '2021'),
                          ('Writer', 'Ann Author, Bo Artist'),
                          ('Publisher', 'Press')],
                         comicinfo.describe(path))
        with open(path, encoding='utf-8') as fp:
            self.assertIn('<Title>Night Watch</Title><Year>2021</Year>'
                          '<Writer>Ann Author, Bo Artist</Writer>'
                          '<Publisher>Press</Publisher>'
                          '<Manga>YesAndRightToLeft</Manga>', fp.read())
        self.assertTrue(comicinfo.reads_right_to_left(path))

    def test_older_books_and_vertical_writing(self):
        """An older book keeps its title and authors in its metadata, the
        authors joined by "&"; vertical lines from the right read right
        to left too."""
        book = Book().comic(picture(), document={560: VERTICAL_RIGHT_TO_LEFT})
        book.add(METADATA, None, {153: 'Old', 222: 'Ann & Bo'})
        path = self.comic_info(self.open(book.container()))
        self.assertEqual([('Title', 'Old'), ('Writer', 'Ann, Bo')],
                         comicinfo.describe(path))
        self.assertTrue(comicinfo.reads_right_to_left(path))
        book = Book().comic(picture(), document={192: Symbol(376)})
        book.add(METADATA, None, {153: 'Left to right'})
        path = self.comic_info(self.open(book.container()))
        self.assertFalse(comicinfo.reads_right_to_left(path))

    def test_drm(self):
        """A book wrapped in DRM, or whose container says it is
        encrypted, is refused, and the reader is told why; entities that
        say they are encrypted show nothing."""
        book = Book().comic(picture())
        for data in (kfx.DRM_SIGNATURE + bytes(100),
                     book.container(info={411: 1})):
            with self.subTest(data[:8]):
                path = self.write(data)
                self.assertEqual(constants.KFX,
                                 archive_tools.archive_mime_type(path))
                with self.assertRaisesRegex(kfx.UnpackException,
                                            'book.kfx.*protected by DRM'):
                    kfx.KfxArchive(path)
        archive = self.open(book.container(entity_info={411: 1}))
        self.assertEqual([], archive.list_contents())

    def test_damaged(self):
        """A container that is cut short or garbled is refused with a
        message, or its pages are left out, rather than failing."""
        data = Book().comic(picture(), picture()).container()
        for broken in (b'CONT', data[:30], data[:4] + bytes(len(data) - 4),
                       data[:6] + b'\xff' * 12 + data[18:]):
            with self.subTest(broken[:20]):
                with self.assertRaisesRegex(kfx.UnpackException, 'book.kfx'):
                    kfx.KfxArchive(self.write(broken))
        # The second picture's bytes, the last entity, cut off.
        archive = self.open(data[:-10])
        self.assertEqual(['page00001.jpg'], archive.list_contents())


class KfxBookTest(_WindowTest):

    def test_it_opens_as_a_book_of_its_pages(self):
        path = os.path.join(self.tmp_dir, 'book.kfx')
        with open(path, 'wb') as fp:
            fp.write(Book().comic(picture(), picture()).container())
        self.assertTrue(self.handler.open_file(path))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 2,
            seconds=20))
        self.assertEqual(constants.KFX, self.handler.archive_type)

    def test_a_book_read_right_to_left_opens_in_manga_mode(self):
        prefs['default manga mode'] = False
        path = os.path.join(self.tmp_dir, 'book.kfx')
        with open(path, 'wb') as fp:
            fp.write(Book().comic(picture(), picture(),
                                  document={192: RIGHT_TO_LEFT}).container())
        self.assertTrue(self.handler.open_file(path))
        self.assertTrue(wait_for(lambda: self.window.is_manga_mode, seconds=20),
                        'the book was not read right to left')

    def test_drm_is_named_to_the_reader(self):
        path = os.path.join(self.tmp_dir, 'book.kfx')
        with open(path, 'wb') as fp:
            fp.write(kfx.DRM_SIGNATURE + bytes(100))
        self.assertFalse(self.handler.open_file(path))
        self.assertEqual('Could not open book.kfx: it is protected by DRM.',
                         self.window.statusbar.message.get_text())
