"""EPUB books: the pictures of their pages, in the order of the spine.

The books are written here, after the EPUB 3.3 specification: an OCF
ZIP container with its mimetype, META-INF/container.xml naming the
package document, and the package's manifest and spine.
"""

import io
import os
import zipfile

from PIL import Image

from . import MComixTest, wait_for
from .test_file_handler import _WindowTest

from mcomix import archive_tools
from mcomix import comicinfo
from mcomix import constants
from mcomix.archive import epub
from mcomix.preferences import prefs


def picture(colour=(200, 40, 40), size=(40, 60), kind='PNG'):
    data = io.BytesIO()
    Image.new('RGB', size, colour).save(data, kind)
    return data.getvalue()


def xhtml(body):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>p</title>'
            '</head><body>%s</body></html>' % body).encode('utf-8')


def svg_page(href):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 40 60">'
            '<image width="40" height="60" xlink:href="%s"/></svg>' % href).encode('utf-8')


class Book:

    """An EPUB to write: files under OEBPS/, a manifest item for each
    file, and the spine, the ids of items in reading order."""

    def __init__(self, package='OEBPS/content.opf'):
        self.package = package
        self.files = {}
        self.items = []
        self.spine = []
        self.metadata = ('<dc:title>A comic</dc:title>'
                         '<dc:identifier id="id">urn:uuid:1</dc:identifier>'
                         '<dc:language>en</dc:language>')
        self.direction = None
        self.extra = {}
        #: Whether the package document is written where the container
        #: says it is.
        self.package_written = True

    def add(self, name, data, media_type, spine=False, linear=True):
        """Put <data> at OEBPS/<name>, in the manifest, and in the spine
        if <spine>."""
        identifier = 'item%d' % len(self.items)
        self.files['OEBPS/' + name] = data
        self.items.append((identifier, name, media_type))
        if spine:
            self.spine.append((identifier, linear))
        return self

    def page(self, name, image, kind='PNG'):
        """A page of its own: OEBPS/<name>.xhtml showing OEBPS/images/<image>."""
        self.add('images/' + image, picture(kind=kind),
                 'image/png' if kind == 'PNG' else 'image/jpeg')
        self.add(name + '.xhtml', xhtml('<img src="images/%s" alt=""/>' % image),
                 'application/xhtml+xml', spine=True)
        return self

    def write(self, path, mimetype=epub.MIMETYPE):
        manifest = ''.join('<item id="%s" href="%s" media-type="%s"/>' % item
                           for item in self.items)
        spine = ''.join('<itemref idref="%s"%s/>' % (identifier, '' if linear
                                                     else ' linear="no"')
                        for identifier, linear in self.spine)
        direction = (' page-progression-direction="%s"' % self.direction
                     if self.direction else '')
        package = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">%s</metadata>'
            '<manifest>%s</manifest><spine%s>%s</spine></package>'
            % (self.metadata, manifest, direction, spine))
        container = (
            '<?xml version="1.0"?>\n<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="%s" media-type="application/oebps-package+xml"/>'
            '</rootfiles></container>' % self.package)
        with zipfile.ZipFile(path, 'w') as book:
            if mimetype is not None:
                book.writestr('mimetype', mimetype, zipfile.ZIP_STORED)
            book.writestr('META-INF/container.xml', container, zipfile.ZIP_DEFLATED)
            if self.package_written:
                book.writestr(self.package, package, zipfile.ZIP_DEFLATED)
            for name, data in {**self.files, **self.extra}.items():
                book.writestr(name, data, zipfile.ZIP_DEFLATED)
        return path


class EpubTest(MComixTest):

    def write(self, book, name='book.epub', **kwargs):
        return book.write(os.path.join(self.tmp_dir, name), **kwargs)

    def open(self, book, **kwargs):
        archive = epub.EpubArchive(self.write(book, **kwargs))
        self.addCleanup(archive.close)
        return archive

    def extracted(self, archive, name):
        destination = os.path.join(self.tmp_dir, 'out')
        archive.extract(name, destination)
        with open(os.path.join(destination, name), 'rb') as fp:
            return fp.read()

    def test_an_epub_is_told_by_its_mimetype(self):
        book = Book().page('p1', 'a.png')
        self.assertEqual(constants.EPUB, archive_tools.archive_mime_type(
            self.write(book)))
        # Whatever it is called, and with a line break after the type.
        self.assertEqual(constants.EPUB, archive_tools.archive_mime_type(
            self.write(book, 'book.zip', mimetype=epub.MIMETYPE + b'\n')))
        self.assertEqual(constants.ZIP, archive_tools.archive_mime_type(
            self.write(book, 'none.cbz', mimetype=None)))
        self.assertEqual(constants.ZIP, archive_tools.archive_mime_type(
            self.write(book, 'other.zip', mimetype=b'application/zip')))
        self.assertTrue(archive_tools.is_archive_file('A Book.epub'))

    def test_pages_come_in_the_order_of_the_spine(self):
        """Not in the order of the pictures' names: a converter names
        them after hashes, or as it pleases."""
        book = Book().page('p1', 'zz.png').page('p2', 'aa.jpg', 'JPEG') \
            .page('p3', 'mm.png')
        archive = self.open(book)
        self.assertEqual(['page00001.png', 'page00002.jpg', 'page00003.png',
                          comicinfo.NAME], archive.list_contents())
        self.assertEqual(book.files['OEBPS/images/aa.jpg'],
                         self.extracted(archive, 'page00002.jpg'))

    def test_what_a_spine_document_shows(self):
        """A picture in the spine itself, an SVG page with its image, an
        XHTML page with two pictures; a chapter of text alone, an item
        out of the linear reading order, and a picture shown again are
        no pages."""
        book = Book()
        book.add('images/cover.png', picture((1, 1, 1)), 'image/png', spine=True)
        book.add('images/svg.png', picture((2, 2, 2)), 'image/png')
        book.add('svg.svg', svg_page('images/svg.png'), 'image/svg+xml', spine=True)
        book.add('text.xhtml', xhtml('<p>Chapter one</p>'),
                 'application/xhtml+xml', spine=True)
        book.add('images/a.png', picture((3, 3, 3)), 'image/png')
        book.add('images/b.png', picture((4, 4, 4)), 'image/png')
        book.add('two.xhtml', xhtml('<div><img src="images/a.png"/></div>'
                                    '<p><img src="images/b.png"/></p>'),
                 'application/xhtml+xml', spine=True)
        book.add('notes.xhtml', xhtml('<img src="images/a.png"/>'),
                 'application/xhtml+xml', spine=True, linear=False)
        book.add('again.xhtml', xhtml('<img src="images/cover.png"/>'),
                 'application/xhtml+xml', spine=True)
        archive = self.open(book)
        pages = [name for name in archive.list_contents() if name != comicinfo.NAME]
        self.assertEqual(4, len(pages))
        for name, source in zip(pages, ('cover', 'svg', 'a', 'b')):
            self.assertEqual(book.files['OEBPS/images/%s.png' % source],
                             self.extracted(archive, name))

    def test_references_relative_escaped_and_with_fragments(self):
        book = Book(package='content/package.opf')
        book.files['images/My Page.png'] = picture()
        book.items.append(('i', '../images/My Page.png', 'image/png'))
        book.add('../text/p.xhtml', xhtml('<img src="../images/My%20Page.png#x"/>'),
                 'application/xhtml+xml', spine=True)
        # add() put it under OEBPS/; the package is elsewhere here.
        book.files['text/p.xhtml'] = book.files.pop('OEBPS/../text/p.xhtml')
        archive = self.open(book)
        self.assertEqual(['page00001.png'], archive.list_contents()[:1])
        self.assertEqual(book.files['images/My Page.png'],
                         self.extracted(archive, 'page00001.png'))

    def test_what_the_book_says_of_itself(self):
        """Its title, authors, publisher and year in a ComicInfo.xml, and
        a book that turns its pages from right to left read so."""
        book = Book().page('p1', 'a.png').page('p2', 'b.png')
        book.metadata += ('<dc:creator>Mangaka One</dc:creator>'
                          '<dc:creator>Two</dc:creator>'
                          '<dc:publisher>Press</dc:publisher>'
                          '<dc:date>2021-05-04</dc:date>')
        book.direction = 'rtl'
        path = os.path.join(self.tmp_dir, 'out', comicinfo.NAME)
        self.extracted(self.open(book), comicinfo.NAME)
        self.assertTrue(comicinfo.reads_right_to_left(path))
        self.assertEqual([('Title', 'A comic'), ('Year', '2021'),
                          ('Writer', 'Mangaka One, Two'), ('Publisher', 'Press')],
                         _fields(path))
        book.direction = 'ltr'
        self.extracted(self.open(book, name='ltr.epub'), comicinfo.NAME)
        self.assertFalse(comicinfo.reads_right_to_left(path))

    def test_a_comicinfo_the_book_carries_is_listed_as_it_is(self):
        book = Book().page('p1', 'a.png')
        carried = b'<?xml version="1.0"?><ComicInfo><Series>S</Series></ComicInfo>'
        book.extra['ComicInfo.xml'] = carried
        archive = self.open(book)
        self.assertEqual(['page00001.png', comicinfo.NAME], archive.list_contents())
        self.assertEqual(carried, self.extracted(archive, comicinfo.NAME))

    def test_drm(self):
        """encryption.xml naming a picture encrypted is DRM; one naming
        fonts obfuscated, as books without DRM carry, is not."""
        encrypted = (
            '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
            'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
            '<enc:EncryptionMethod Algorithm="%s"/><enc:CipherData>'
            '<enc:CipherReference URI="OEBPS/%s"/></enc:CipherData>'
            '</enc:EncryptedData></encryption>')
        book = Book().page('p1', 'a.png')
        book.extra['META-INF/encryption.xml'] = encrypted % (
            'http://www.w3.org/2001/04/xmlenc#aes128-cbc', 'images/a.png')
        with self.assertRaises(epub.UnpackException) as raised:
            epub.EpubArchive(self.write(book))
        self.assertEqual('Could not open book.epub: it is protected by DRM.',
                         str(raised.exception))
        book.extra['META-INF/encryption.xml'] = encrypted % (
            'http://www.idpf.org/2008/embedding', 'fonts/f.otf')
        self.assertEqual(['page00001.png'], self.open(book).list_contents()[:1])

    def test_without_a_package_the_pictures_by_their_names(self):
        """A container naming no package, or one that does not parse,
        leaves the pictures as a ZIP archive would list them, made safe
        to write as every handler's names are."""
        book = Book().page('p1', 'b.png').page('p2', 'a.png')
        book.package_written = False
        book.extra['../outside.png'] = picture()
        archive = self.open(book)
        names = archive.list_contents()
        self.assertEqual({'OEBPS/images/a.png', 'OEBPS/images/b.png',
                          'outside.png'},
                         {name.replace(os.sep, '/') for name in names})
        self.extracted(archive, 'outside.png')
        self.assertFalse(os.path.exists(os.path.join(self.tmp_dir, 'outside.png')))

    def test_a_book_of_text_alone_has_no_pages(self):
        book = Book().add('t.xhtml', xhtml('<p>Words</p>'),
                          'application/xhtml+xml', spine=True)
        self.assertEqual([comicinfo.NAME], self.open(book).list_contents())


def _fields(path):
    return [(field, text) for field, text in comicinfo.describe(path)
            if field in ('Title', 'Year', 'Writer', 'Publisher')]


class EpubBookTest(_WindowTest):

    def test_it_opens_as_a_book_of_its_pages(self):
        path = Book().page('p1', 'a.png').page('p2', 'b.png').write(
            os.path.join(self.tmp_dir, 'book.epub'))
        self.assertTrue(self.handler.open_file(path))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 2,
            seconds=20))
        self.assertEqual(constants.EPUB, self.handler.archive_type)

    def test_a_book_read_right_to_left_opens_in_manga_mode(self):
        prefs['default manga mode'] = False
        book = Book().page('p1', 'a.png').page('p2', 'b.png')
        book.direction = 'rtl'
        self.assertTrue(self.handler.open_file(
            book.write(os.path.join(self.tmp_dir, 'book.epub'))))
        self.assertTrue(wait_for(lambda: self.window.is_manga_mode, seconds=20),
                        'the book was not read right to left')

# vim: expandtab:sw=4:ts=4
