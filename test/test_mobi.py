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


def _book(resources, ident=b'BOOKMOBI', crypto_type=0, first_image=2,
          text=b'<html><body>Page one</body></html>', header_size=0xE8):
    """A MobiPocket book: a header record of <header_size> bytes, one of
    <text>, then <resources>, the first of them record <first_image>."""
    header = bytearray(header_size)
    header[0x10:0x14] = b'MOBI'
    struct.pack_into('>H', header, 0xC, crypto_type)
    struct.pack_into('>L', header, 0x6C, first_image)
    records = [bytes(header), text]
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

    def test_a_book_of_text_alone_has_no_pages(self):
        """A book without pictures names no first one, 0xFFFFFFFF, and
        the text before the pictures is no page, however it begins."""
        archive = self._open(_book(self.resources, first_image=0xFFFFFFFF))
        self.assertEqual([], archive.list_contents())
        archive = self._open(_book([self.png], text=b'BMW, the book of it'))
        self.assertEqual(['image00001.png'], archive.list_contents())

    def test_a_record_too_short_for_a_signature_is_no_picture(self):
        """What follows a record is not read as the rest of it."""
        archive = self._open(_book([b'\xff\xd8', self.jpeg]))
        self.assertEqual(['image00002.jpg'], archive.list_contents())

    def test_a_header_as_short_as_the_first_picture_s_place_allows(self):
        archive = self._open(_book([self.png], header_size=0x70))
        self.assertEqual(['image00001.png'], archive.list_contents())

    def test_the_book_is_let_go_of_once_and_for_all(self):
        archive = self._open(_book(self.resources))
        book = archive.file
        archive.close()
        self.assertTrue(book.closed)
        self.assertIsNone(archive.file)
        archive.close()

    def test_refuses_a_palm_database_that_is_not_a_book(self):
        with self.assertRaisesRegex(mobi.UnpackException, 'invalid file format'):
            self._open(_book(self.resources, ident=b'TEXtREAd'))

    def test_a_damaged_book_is_refused_or_read_as_far_as_it_goes(self):
        """A file cut short in its Palm header, its record index or its
        MOBI header raised struct.error rather than UnpackException; an
        index whose offsets go backwards read a negative length, which
        is the rest of the file.  The fuzzer found the first with an
        empty file (fuzz/fuzz_mobi.py)."""
        book = _book([self.jpeg])
        for broken, why in ((b'', 'not a Palm database'),
                            (book[:50], 'not a Palm database'),
                            (book[:80], 'record index cut short'),
                            (book[:96], 'record index cut short'),
                            (book[:120], 'MOBI header cut short')):
            with self.subTest(len(broken)), \
                    self.assertRaisesRegex(mobi.UnpackException, why):
                self._open(broken)
        # The PNG record's offset made 0: the JPEG record before it ends
        # before it starts, and was read to the end of the file as a
        # picture of the JPEG and the PNG together.
        damaged = bytearray(_book([self.jpeg, self.png]))
        struct.pack_into('>L', damaged, 78 + 8 * 3, 0)
        archive = self._open(bytes(damaged))
        self.assertEqual([], archive.list_contents())

    def test_refuses_an_encrypted_book(self):
        with self.assertRaisesRegex(mobi.UnpackException, 'file is encrypted'):
            self._open(_book(self.resources, crypto_type=2))
