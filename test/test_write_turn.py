"""A page's turn written into its JPEG picture without loss.

jpeg_turn turns the picture, either its compressed blocks with
jpegtran or its Exif orientation tag; FileActions.write_turn() writes
that into a folder's picture at once, or into a copy that takes the
page's place in an archive until it is saved.
"""

import io
import itertools
import os
import shutil
import struct
import unittest
import zipfile
from unittest import mock

from PIL import Image, ImageOps

from . import MComixTest, get_testfile_path, prompts_over, pump, wait_for

from mcomix import jpeg_turn
from mcomix import page_rotations
from mcomix.preferences import prefs
from mcomix.transform import Transform


def _picture(width, height, orientation=None, make=None):
    """A JPEG picture with a different colour at every pixel, and the
    Exif <orientation> and camera <make> where they are given."""
    image = Image.new('RGB', (width, height))
    image.putdata([(x * 7 % 256, y * 5 % 256, x * y % 256)
                   for y in range(height) for x in range(width)])
    exif = Image.Exif()
    if orientation is not None:
        exif[jpeg_turn.ORIENTATION] = orientation
    if make is not None:
        exif[0x010f] = make
    written = io.BytesIO()
    image.save(written, 'JPEG', quality=90, exif=exif.tobytes())
    return written.getvalue()


def _shown(data, follow_exif=True):
    """The picture <data> as a viewer shows it."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        shown = ImageOps.exif_transpose(image) if follow_exif else image
        return shown.convert('RGB')


def _scan(data):
    """The compressed pixels of the JPEG picture <data>."""
    return data[data.index(b'\xff\xda'):]


def _tiff(order, entries, next_directory=True):
    """A TIFF header in the byte <order> of struct ('<' or '>') and one
    directory of <entries>, each a tag, a type, a count and a value of
    two bytes, followed by the offset of no next directory where
    <next_directory>."""
    tiff = (b'II' if order == '<' else b'MM') + struct.pack(
        order + 'HIH', 42, 8, len(entries))
    for tag, kind, count, value in entries:
        tiff += struct.pack(order + 'HHIHH', tag, kind, count, value, 0)
    return tiff + (struct.pack(order + 'I', 0) if next_directory else b'')


def _with_tiff(tiff):
    """A JPEG picture whose one Exif block holds <tiff>."""
    written = io.BytesIO()
    Image.new('RGB', (8, 8), 'red').save(written, 'JPEG')
    data = written.getvalue()
    payload = b'Exif\0\0' + tiff
    return (data[:2] + b'\xff\xe1' + struct.pack('>H', len(payload) + 2)
            + payload + data[2:])


def _without_jpegtran():
    return mock.patch.object(jpeg_turn, '_jpegtran', lambda: None)


class JpegTurnTest(MComixTest):

    def test_an_orientation_turned_shows_its_picture_turned(self):
        data = _picture(6, 4)
        for orientation, degrees in itertools.product(range(1, 9),
                                                      (90, 180, 270)):
            with self.subTest(orientation=orientation, degrees=degrees):
                tagged = jpeg_turn.with_orientation(data, orientation)
                turned = jpeg_turn.with_orientation(
                    data, jpeg_turn.turned(orientation, degrees))
                self.assertEqual(
                    _shown(tagged).rotate(-degrees, expand=True).tobytes(),
                    _shown(turned).tobytes())

    def test_without_jpegtran_only_the_tag_changes(self):
        data = _picture(61, 37, orientation=6, make='Probe')
        with _without_jpegtran():
            turned = jpeg_turn.turn(data, 90, follow_exif=True)
        self.assertEqual(_scan(data), _scan(turned))
        self.assertEqual(3, jpeg_turn.orientation_of(turned))
        self.assertEqual(_shown(data).rotate(-90, expand=True).tobytes(),
                         _shown(turned).tobytes())
        with Image.open(io.BytesIO(turned)) as image:
            self.assertEqual('Probe', image.getexif()[0x010f])

    def test_a_picture_with_no_exif_has_it_put_after_its_jfif_block(self):
        image = Image.new('L', (8, 8))
        written = io.BytesIO()
        image.save(written, 'JPEG')
        data = written.getvalue()
        with _without_jpegtran():
            turned = jpeg_turn.turn(data, 270, follow_exif=True)
        markers = [marker for marker, _, _ in jpeg_turn._segments(turned)]
        self.assertEqual([0xe0, 0xe1], markers[:2])
        self.assertEqual(8, jpeg_turn.orientation_of(turned))

    def test_a_reader_who_does_not_follow_exif_is_not_given_a_tag(self):
        data = _picture(61, 37, orientation=6)
        with _without_jpegtran(), self.assertRaises(jpeg_turn.NotLossless):
            jpeg_turn.turn(data, 90, follow_exif=False)

    def test_turned_back_to_upright_drops_the_turn(self):
        data = _picture(8, 8, orientation=8)
        with _without_jpegtran():
            self.assertEqual(1, jpeg_turn.orientation_of(
                jpeg_turn.turn(data, 90, follow_exif=True)))

    def test_jpegtran_turns_the_blocks_where_the_size_lets_it(self):
        if shutil.which('jpegtran') is None:
            self.skipTest('jpegtran is not installed')
        data = _picture(64, 48, orientation=3)
        for follow_exif in (True, False):
            with self.subTest(follow_exif=follow_exif):
                turned = jpeg_turn.turn(data, 90, follow_exif)
                self.assertNotEqual(_scan(data), _scan(turned))
                self.assertEqual(1, jpeg_turn.orientation_of(turned))
                wanted = _shown(data, follow_exif).rotate(-90, expand=True)
                shown = _shown(turned)
                self.assertEqual(wanted.size, shown.size)
                # Decoded from turned blocks, not from turned pixels:
                # the colour upsampling may differ by a step or two.
                self.assertLessEqual(max(
                    abs(a - b) for a, b in zip(wanted.tobytes(),
                                               shown.tobytes())), 3)

    def test_a_part_block_falls_back_to_the_tag(self):
        if shutil.which('jpegtran') is None:
            self.skipTest('jpegtran is not installed')
        data = _picture(64, 37)
        turned = jpeg_turn.turn(data, 90, follow_exif=True)
        self.assertEqual(_scan(data), _scan(turned))
        self.assertEqual(6, jpeg_turn.orientation_of(turned))

    def test_an_orientation_tag_is_changed_where_it_stands(self):
        """In either byte order, and with nothing else of the picture
        changed: the one byte of the value."""
        for order in ('<', '>'):
            with self.subTest(order):
                data = _with_tiff(_tiff(order, [
                    (0x0100, 3, 1, 8), (jpeg_turn.ORIENTATION, 3, 1, 1)]))
                turned = jpeg_turn.with_orientation(data, 6)
                self.assertEqual(6, jpeg_turn.orientation_of(turned))
                self.assertEqual(len(data), len(turned))
                self.assertEqual(1, sum(a != b for a, b in zip(data, turned)))

    def test_only_a_tag_of_one_short_is_changed_in_place(self):
        """Anything else under the tag is rewritten as a block of its
        own."""
        for kind, count in ((4, 1), (3, 2)):
            with self.subTest(kind=kind, count=count):
                tiff = _tiff('>', [(jpeg_turn.ORIENTATION, kind, count, 1)])
                self.assertIsNone(
                    jpeg_turn._set_in_place(tiff, 0, len(tiff), 6))

    def test_an_entry_is_changed_only_where_the_block_holds_all_of_it(self):
        tiff = _tiff('>', [(jpeg_turn.ORIENTATION, 3, 1, 1)],
                     next_directory=False)
        self.assertEqual(tiff[:-4] + b'\0\x06\0\0',
                         jpeg_turn._set_in_place(tiff, 0, len(tiff), 6))
        self.assertIsNone(jpeg_turn._set_in_place(tiff, 0, len(tiff) - 1, 6))
        # And only as many entries as the directory counts.
        two = _tiff('>', [(0x0100, 3, 1, 8), (jpeg_turn.ORIENTATION, 3, 1, 1)])
        uncounted = two[:8] + b'\0\x01' + two[10:]
        self.assertIsNone(
            jpeg_turn._set_in_place(uncounted, 0, len(uncounted), 6))

    def test_a_directory_beyond_the_block_is_damage(self):
        tiff = _tiff('>', [])[:10]
        self.assertIsNone(jpeg_turn._set_in_place(tiff, 0, 10, 6))
        with self.assertRaises(ValueError):
            jpeg_turn._set_in_place(tiff, 0, 9, 6)
        with self.assertRaises(ValueError):
            jpeg_turn._set_in_place(b'XX' + tiff[2:], 0, 10, 6)

    def test_what_is_no_jpeg_is_refused(self):
        with self.assertRaises(ValueError):
            jpeg_turn.with_orientation(b'\x89PNG\r\n\x1a\n', 6)

    def test_a_picture_past_pillows_pixel_limit_is_turned(self):
        """Pillow opens no picture of more pixels than its limit, and
        the turn read the orientation by opening it: one of 20000 by
        20000 pixels raised DecompressionBombError, which the window
        does not catch.  The turn needs none of its pixels."""
        data = bytearray(_picture(16, 16, orientation=6))
        frame = data.index(b'\xff\xc0')
        data[frame + 5:frame + 9] = (20000).to_bytes(2, 'big') * 2
        data = bytes(data)
        self.assertEqual(6, jpeg_turn.orientation_of(data))
        with _without_jpegtran():
            turned = jpeg_turn.turn(data, 90, follow_exif=True)
        self.assertEqual(3, jpeg_turn.orientation_of(turned))
        self.assertEqual(_scan(data), _scan(turned))

    def test_a_damaged_exif_block_is_refused(self):
        """Pillow, reading or writing the Exif block of a damaged
        picture, raised SyntaxError, struct.error or TypeError, none of
        which the window's "Save rotation to file" catches.  Each block
        is one found by mutating a picture's bytes at random; the
        orientation entry in each cannot be changed in place."""
        damaged = (
            # A TIFF header of 0x0f where 0x2a belongs (SyntaxError).
            '4d4d000f000000080003010f000200000006000000320110000200000006'
            '00000038011200030000ef0100030000000000004d616b6572004d6f6465'
            '6c00',
            # An entry of type 0xcd03 (struct.error, writing it back).
            '4d4d002a000000080003010f000200000006000000320150000200000006'
            '000000380112cd030000000100030000000000004d616b6572004d6f6465'
            '6c00',
            # An entry of type 0xf0 (TypeError, writing it back).
            '4d4d002a000000080003011f000200000006000000320110000200000006'
            '00000038011200f00000000100030000000000004d616b6572004d6f6465'
            '6c00')
        for block in damaged:
            payload = b'Exif\x00\x00' + bytes.fromhex(block)
            data = (b'\xff\xd8\xff\xe1' + (len(payload) + 2).to_bytes(2, 'big')
                    + payload + b'\xff\xda\x00\x02')
            for orientation in (1, 6):
                with self.subTest(block=block[:24], orientation=orientation), \
                        self.assertRaises(ValueError):
                    jpeg_turn.with_orientation(data, orientation)


class WriteTurnTest(MComixTest):

    """The book is either a folder or a ZIP of two pictures: a JPEG
    whose part blocks no turn can move, and a PNG."""

    JPEG = 'a-page.jpg'
    PNG = 'b-page.png'

    def setUp(self):
        super().setUp()
        self.prepare_main_window()
        self.enterContext(_without_jpegtran())
        self.folder = os.path.join(self.tmp_dir, 'folder-book')
        os.mkdir(self.folder)
        for source, name in (('portrait-no-exif.jpg', self.JPEG),
                             ('03-PNG-RGB.png', self.PNG)):
            shutil.copy(get_testfile_path('images', source),
                        os.path.join(self.folder, name))
        self.original = _shown(self._read(os.path.join(self.folder, self.JPEG)))

    def tearDown(self):
        self.close_main_window()
        super().tearDown()

    @staticmethod
    def _read(path):
        with open(path, 'rb') as file:
            return file.read()

    def _opened(self, path):
        self.open_main_window(open_path=path)
        images = self.window.imagehandler
        self.assertTrue(wait_for(
            lambda: images.get_number_of_pages() == 2
            and all(images.page_is_available(page) for page in (1, 2)),
            seconds=20))

    def _turned_by_hand(self, page, degrees=90):
        identity = self.window.filehandler.page_identity(page)
        page_rotations.remember(*identity, degrees)
        return identity

    def _shown_page(self, page):
        return _shown(self._read(
            self.window.imagehandler.get_path_to_page(page)))

    def _drawn(self):
        """What the page on screen was drawn with, once the redraw the
        window asked for has been made."""
        self.assertTrue(wait_for(lambda: not self.window._waiting_for_redraw))
        pump()
        paintable = self.window.images[0].get_paintable()
        return (self.window.transforms[0], paintable.get_intrinsic_width(),
                paintable.get_intrinsic_height())

    def test_a_folder_s_picture_is_written_at_once(self):
        """And shown as it was: turned by its picture now, which is read
        again, rather than by the turn kept for it."""
        self._opened(self.folder)
        self.window.rotate_90()
        identity = self.window.filehandler.page_identity(1)
        turned = self._drawn()
        self.assertEqual(Transform.from_rotation(90), turned[0])
        self.assertEqual(90, self.window.file_actions.turn_to_write(1))
        self.assertTrue(self.window.file_actions.write_turn(1))
        self.assertEqual(turned, self._drawn())
        self.assertEqual(self.original.rotate(-90, expand=True).tobytes(),
                         _shown(self._read(os.path.join(
                             self.folder, self.JPEG))).tobytes())
        self.assertEqual(0, page_rotations.rotation(*identity))
        self.assertEqual(0, prefs['rotation'])

    def test_only_a_jpeg_page_turned_by_hand_offers_it(self):
        self._opened(self.folder)
        actions = self.window.file_actions
        self.assertEqual(0, actions.turn_to_write(1))
        self._turned_by_hand(2)
        self.assertEqual(0, actions.turn_to_write(2))
        self._turned_by_hand(1)
        prefs['keep transformation'] = True
        self.assertEqual(0, actions.turn_to_write(1))

    def test_a_turn_that_would_lose_detail_is_refused(self):
        self._opened(self.folder)
        identity = self._turned_by_hand(1)
        prefs['auto rotate from exif'] = False
        self.assertFalse(self.window.file_actions.write_turn(1))
        self.assertTrue(wait_for(lambda: prompts_over(self.window)))
        for prompt in prompts_over(self.window):
            prompt.close()
        self.assertEqual(self.original.tobytes(), _shown(self._read(
            os.path.join(self.folder, self.JPEG))).tobytes())
        self.assertEqual(90, page_rotations.rotation(*identity))

    def _zipped(self):
        book = os.path.join(self.tmp_dir, 'book.cbz')
        with zipfile.ZipFile(book, 'w') as archive:
            for name in (self.JPEG, self.PNG):
                archive.write(os.path.join(self.folder, name), name)
        self._opened(book)
        return book

    def test_an_archive_s_page_is_turned_in_a_copy_until_it_is_saved(self):
        book = self._zipped()
        actions = self.window.file_actions
        identity = self._turned_by_hand(1, 270)
        with mock.patch.object(actions, 'offer_to_save') as offer:
            self.assertTrue(actions.write_turn(1))
        offer.assert_called_once_with()
        self.assertTrue(actions.has_unsaved_changes())
        self.assertEqual(self.original.rotate(-270, expand=True).tobytes(),
                         self._shown_page(1).tobytes())
        self.assertEqual(self.JPEG, actions.page_name(1))
        self.assertEqual(identity, self.window.filehandler.page_identity(1))
        self.assertEqual(0, page_rotations.rotation(*identity))
        with zipfile.ZipFile(book) as archive:
            self.assertEqual(self.original.tobytes(),
                             _shown(archive.read(self.JPEG)).tobytes())
        self.assertTrue(actions.save_archive())
        with zipfile.ZipFile(book) as archive:
            first = sorted(archive.namelist())[0]
            self.assertEqual(
                self.original.rotate(-270, expand=True).tobytes(),
                _shown(archive.read(first)).tobytes())

    def test_an_undo_brings_the_page_back_with_its_turn(self):
        self._zipped()
        actions = self.window.file_actions
        identity = self._turned_by_hand(1)
        with mock.patch.object(actions, 'offer_to_save'):
            self.assertTrue(actions.write_turn(1))
        self.assertTrue(actions.undo())
        self.assertEqual(self.original.tobytes(), self._shown_page(1).tobytes())
        self.assertEqual(90, page_rotations.rotation(*identity))
        self.assertFalse(actions.has_unsaved_changes())
        self.assertTrue(actions.redo())
        self.assertEqual(0, page_rotations.rotation(*identity))
        self.assertEqual(self.original.rotate(-90, expand=True).tobytes(),
                         self._shown_page(1).tobytes())


if __name__ == '__main__':
    unittest.main()
