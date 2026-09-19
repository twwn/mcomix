"""The MobiPocket handler, over books put together here.

A MobiPocket book is a Palm database whose records are the book's text
and, from the one its header names on, its resources - the images among
them.  test/files has no such book, and the handler reads little enough
of the format that one is quicker to build than to ship.
"""

import io
import os
import struct
import unittest.mock

from PIL import Image

from . import MComixTest

from mcomix import archive_tools
from mcomix import constants
from mcomix.archive import mobi


def _image(format):
    """A small picture, encoded as <format>."""
    data = io.BytesIO()
    Image.new('RGB', (4, 6), (200, 30, 90)).save(data, format)
    return data.getvalue()


def _book(resources, ident=b'BOOKMOBI', crypto_type=0):
    """A MobiPocket book: a header record, one of text, then <resources>."""
    header = bytearray(0xE8)
    header[0x10:0x14] = b'MOBI'
    struct.pack_into('>H', header, 0xC, crypto_type)
    # The first resource: the one after the header and the text.
    struct.pack_into('>L', header, 0x6C, 2)
    records = [bytes(header), b'<html><body>Page one</body></html>']
    records.extend(resources)

    database = bytearray(78)
    database[0:4] = b'Book'
    database[0x3C:0x44] = ident
    struct.pack_into('>H', database, 76, len(records))
    offset = len(database) + 8 * len(records) + 2
    for uid, record in enumerate(records):
        database += struct.pack('>LL', offset, 2 * uid)
        offset += len(record)
    database += b'\0\0'
    for record in records:
        database += record
    return bytes(database)


class MobiArchiveTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.jpeg = _image('JPEG')
        self.png = _image('PNG')
        self.gif = _image('GIF')
        self.bmp = _image('BMP')
        # What follows the images in a real book: records that are not
        # pictures, and the end-of-file marker.
        self.resources = [self.jpeg, self.png, self.gif, self.bmp,
                          b'FLIS\0\0\0\x08\0\x41', b'\xe9\x8e\r\n']

    def _open(self, data):
        path = os.path.join(self.tmp_dir, 'book.mobi')
        with open(path, 'wb') as book:
            book.write(data)
        archive = mobi.MobiArchive(path)
        self.addCleanup(archive.close)
        return archive

    def test_lists_the_images_and_only_the_images(self):
        archive = self._open(_book(self.resources))
        self.assertEqual(list(archive.iter_contents()),
                         ['image00001.jpg', 'image00002.png',
                          'image00003.gif', 'image00004.bmp'])

    def test_lists_the_images_where_gio_cannot_tell_them_from_data(self):
        """On Windows Gio.content_type_guess() guesses from a file name
        alone, and answers "*" for data with none - so the handler,
        which asked it, found no image in any book."""
        archive = self._open(_book(self.resources))
        with unittest.mock.patch('gi.repository.Gio.content_type_guess',
                                 return_value=('*', False)):
            self.assertEqual(len(list(archive.iter_contents())), 4)

    def test_a_book_is_recognised_and_its_pages_counted(self):
        """What the library asks of a book it is given: the pages are
        images by their names, so the extensions have to be ones an
        image is recognised by."""
        data = _book(self.resources)
        path = os.path.join(self.tmp_dir, 'book.mobi')
        with open(path, 'wb') as book:
            book.write(data)
        self.assertEqual(archive_tools.get_archive_info(path),
                         (constants.MOBI, 4, len(data)))

    def test_extracts_an_image_as_it_is_stored(self):
        archive = self._open(_book(self.resources))
        names = list(archive.iter_contents())
        archive.extract(names[1], self.tmp_dir)
        with open(os.path.join(self.tmp_dir, names[1]), 'rb') as page:
            self.assertEqual(page.read(), self.png)

    def test_the_last_record_reaches_the_end_of_the_file(self):
        archive = self._open(_book([self.jpeg, self.png]))
        names = list(archive.iter_contents())
        archive.extract(names[-1], self.tmp_dir)
        with open(os.path.join(self.tmp_dir, names[-1]), 'rb') as page:
            self.assertEqual(page.read(), self.png)

    def test_refuses_a_palm_database_that_is_not_a_book(self):
        with self.assertRaises(mobi.UnpackException):
            self._open(_book(self.resources, ident=b'TEXtREAd'))

    def test_refuses_an_encrypted_book(self):
        with self.assertRaises(mobi.UnpackException):
            self._open(_book(self.resources, crypto_type=2))
