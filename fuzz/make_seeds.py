"""Write the seed corpora of the fuzz targets, fuzz/corpus/<target>/,
from the builders the test suite makes its books with.

The fuzzer finds its way into a format from these: nothing gets past
Ion's version marker, a container's header or an XML document's root
by mutating bytes at random.  Run from the checkout, where the test
package is, under a display as the suite is:

    xvfb-run -a python3 fuzz/make_seeds.py

The seeds are kept in Git, so the targets run without it.
"""

import decimal
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from test import test_epub, test_ion, test_kfx  # noqa: E402
from test.test_ion import Annotated, dumps  # noqa: E402
from test.test_kfx import Book, picture  # noqa: E402

from mcomix.archive.ion import Symbol  # noqa: E402

CORPUS = os.path.join(ROOT, 'fuzz', 'corpus')


def write(target, name, data):
    folder = os.path.join(CORPUS, target)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), 'wb') as fp:
        fp.write(data if isinstance(data, bytes) else data.encode('utf-8'))


def ion_seeds():
    values = {
        'int': 300, 'negative': -5, 'big': 2 ** 70, 'float': 1.5,
        'decimal': decimal.Decimal('-12.34'), 'string': 'text',
        'symbol': Symbol(9), 'blob': b'\x00\x01blob', 'bool': True,
        'null': None, 'list': [1, 'a', [None, False]],
        'sexp': (Symbol(1), 2, 'x'),
        'struct': {4: 'YJ_symbols', 5: 10, 8: [1, 2, 3]},
        'annotated': Annotated([3], {6: [], 7: ['own'], 8: 860}),
    }
    for name, value in values.items():
        write('ion', name, dumps(value))
    # What dumps() does not write: a timestamp (2021-03-04, local
    # offset unknown), a clob, a NOP pad before a value, and a second
    # version marker.
    marker = test_ion.ion.VERSION_MARKER
    write('ion', 'timestamp', marker + bytes.fromhex('65c08f e5 83 84'.replace(' ', '')))
    write('ion', 'clob', marker + b'\x93abc')
    write('ion', 'pad', marker + b'\x01\x00' + dumps(7)[len(marker):])
    write('ion', 'markers', marker + marker + dumps('x')[len(marker):])


def kfx_seeds():
    jpeg = picture()
    write('kfx', 'comic', Book().comic(jpeg, picture(colour=(1, 2, 3))).container())
    book = Book().comic(jpeg, document={192: test_kfx.RIGHT_TO_LEFT})
    book.add(test_kfx.BOOK_METADATA, None, {491: [
        {495: 'kindle_title_metadata', 258: [
            {492: key, 307: value} for key, value in (
                ('title', 'Night Watch'), ('author', 'Ann Author'),
                ('publisher', 'Press'), ('issue_date', '2021-03-04'))]}]})
    write('kfx', 'metadata', book.container())
    # A spread: two pictures in one section's storyline.
    book = Book()
    book.picture_page(0, picture((1, 1)))
    book.add(test_kfx.SECTION, 'spread', {174: book.symbol('spread'), 141: [
        {155: 10, 159: test_kfx.CONTAINER, 156: test_kfx.PAGE_SPREAD,
         176: book.symbol('story')}]})
    book.add(test_kfx.STORYLINE, 'story', {176: book.symbol('story'), 146: [
        {155: 11 + side, 159: test_kfx.CONTAINER, 156: test_kfx.SCALE_FIT, 146: [
            {155: 13 + side, 159: test_kfx.IMAGE,
             175: book.symbol('half%d' % side)}]} for side in (0, 1)]})
    for side in (0, 1):
        book.resource('half%d' % side, 'h%d' % side)
        book.add(test_kfx.RAW_MEDIA, 'h%d' % side, picture((2 + side, 1)))
    book.reading_order('c0', 'spread')
    write('kfx', 'spread', book.container())
    # A picture in tiles, the larger of two resolutions.
    image = test_kfx.gradient(23, 17)
    book = Book()
    rows = []
    for top in range(0, 17, 6):
        row = []
        for left in range(0, 23, 10):
            name = 'tile-%d-%d' % (top, left)
            book.add(test_kfx.RAW_MEDIA, name, picture(
                image=image.crop((left, top, min(left + 10, 23), min(top + 6, 17))),
                format='PNG'))
            row.append(name)
        rows.append(row)
    book.page('c0', 'e0')
    book.resource('e0', 'small', format=test_kfx.PNG,
                  fields={635: [book.symbol('big')]})
    book.add(test_kfx.RAW_MEDIA, 'small', picture(format='PNG'))
    book.resource('big', None, size=(23, 17), format=test_kfx.PNG,
                  fields={636: rows, 637: 10, 638: 6, 797: 0})
    book.reading_order('c0')
    write('kfx', 'tiles', book.container())
    # A book in three parts, and the same as a KFX-ZIP.
    parts = test_kfx.split_book([jpeg])
    for name, part in zip(('main', 'metadata-part', 'resources'), parts):
        write('kfx', 'split-' + name, part)
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, part in zip(('CR!MAIN.kfx', 'CR!META.kfx', 'CR!RES.kfx'), parts):
            archive.writestr(name, part)
    write('kfx', 'kfx-zip', data.getvalue())


def epub_seeds():
    from mcomix.archive import epub
    separator = b'\n--8<--\n'
    container = (
        '<?xml version="1.0"?>\n<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>')
    package = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>A comic</dc:title><dc:creator>Ann Author</dc:creator>'
        '<dc:publisher>Press</dc:publisher><dc:date>2021-05-04</dc:date>'
        '<dc:identifier id="id">urn:uuid:1</dc:identifier></metadata><manifest>'
        '<item id="p1" href="p1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="p2" href="p2.svg" media-type="image/svg+xml"/>'
        '<item id="a" href="images/a.png" media-type="image/png"/>'
        '<item id="b" href="images/b.jpg" media-type="image/jpeg"/>'
        '</manifest><spine page-progression-direction="rtl">'
        '<itemref idref="p1"/><itemref idref="p2"/><itemref idref="b" linear="no"/>'
        '</spine></package>')
    page = test_epub.xhtml('<div><img src="images/a.png#x"/></div>'
                           '<p><img src="images/b.jpg"/></p>')
    svg = test_epub.svg_page('images/b.jpg')
    encryption = (
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
        '<enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>'
        '<enc:CipherData><enc:CipherReference URI="OEBPS/fonts/f.otf"/>'
        '</enc:CipherData></enc:EncryptedData></encryption>')
    comic_info = '<?xml version="1.0"?><ComicInfo><Series>S</Series></ComicInfo>'
    parts = [container.encode(), package.encode(), page, svg]
    write('epub', 'book', separator.join(parts))
    write('epub', 'fonts-obfuscated', separator.join(parts + [encryption.encode()]))
    write('epub', 'comicinfo', separator.join(parts + [encryption.encode(),
                                                       comic_info.encode()]))
    write('epub', 'drm', separator.join(parts + [encryption.replace(
        'http://www.idpf.org/2008/embedding',
        'http://www.w3.org/2001/04/xmlenc#aes128-cbc').encode()]))
    write('epub', 'no-package', container.encode())
    assert epub.MIMETYPE


def comicinfo_seeds():
    write('comicinfo', 'full', (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<Series>Series</Series><Volume>2</Volume><Number>7</Number>'
        '<Title>Title</Title><Year>2021</Year><Writer>Writer</Writer>'
        '<Penciller>Artist</Penciller><Publisher>Press</Publisher>'
        '<Manga>YesAndRightToLeft</Manga><PageCount>3</PageCount><Pages>'
        '<Page Image="0" Type="FrontCover" ImageWidth="800" ImageHeight="1200"/>'
        '<Page Image="1" DoublePage="true"/><Page Image="2" Bookmark="b"/>'
        '</Pages></ComicInfo>'))
    write('comicinfo', 'counted-one', '<ComicInfo><PageCount>1</PageCount>'
                                      '<Pages><Page Image="0"/></Pages></ComicInfo>')
    write('comicinfo', 'pages-first', '<ComicInfo><Pages><Page Image="0"/></Pages>'
                                      '<Manga>Yes</Manga></ComicInfo>')
    write('comicinfo', 'other-root', '<?xml version="1.0"?><Book><Title>x</Title></Book>')


if __name__ == '__main__':
    ion_seeds()
    kfx_seeds()
    epub_seeds()
    comicinfo_seeds()
    for target in sorted(os.listdir(CORPUS)):
        folder = os.path.join(CORPUS, target)
        print(target, len(os.listdir(folder)), 'seeds,',
              sum(os.path.getsize(os.path.join(folder, name))
                  for name in os.listdir(folder)), 'bytes')
