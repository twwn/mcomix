"""A TIFF of several pages opens as a book of them."""

import os
import struct

from PIL import Image

from mcomix import (
    archive_tools,
    constants,
    file_chooser_base_dialog,
    file_provider,
    icons,
    main,
)
from mcomix.archive import tiff

from . import MComixTest, pump, wait_for


def _pages():
    """Three pictures no two of which have a size or a mode in common."""
    first = Image.new('RGB', (40, 60), 'red')
    first.putpixel((0, 0), (0, 0, 255))
    return [first, Image.new('1', (50, 30), 1),
            Image.new('L', (20, 80), 128)]


def _write(path, pictures, **parameters):
    pictures[0].save(path, format='TIFF', save_all=True,
                     append_images=pictures[1:], **parameters)
    return path


def _with_previews(path, pages):
    """A TIFF at <path> with a reduced copy behind each of <pages>, each
    marked as one, as a program that keeps previews writes it."""
    frames = []
    for page in pages:
        preview = page.copy()
        preview.thumbnail((8, 8))
        frames += [page, preview]
    # Every picture gets the tag that says what kind it is, and the
    # previews' are then set in the file: a Pillow before 11 gives
    # every picture of a file the same tags.
    _write(path, frames, tiffinfo={254: 0})
    with open(path, 'rb') as fp:
        data = bytearray(fp.read())
    order = '<' if data[:2] == b'II' else '>'
    directory, = struct.unpack_from(order + 'L', data, 4)
    index = 0
    while directory:
        entries, = struct.unpack_from(order + 'H', data, directory)
        for entry in range(directory + 2, directory + 2 + 12 * entries, 12):
            tag, = struct.unpack_from(order + 'H', data, entry)
            if tag == 254 and index % 2:
                struct.pack_into(order + 'L', data, entry + 8, 1)
        directory, = struct.unpack_from(order + 'L', data,
                                        directory + 2 + 12 * entries)
        index += 1
    with open(path, 'wb') as fp:
        fp.write(data)
    return path


class TypeTest(MComixTest):

    def _type(self, name, pictures, **parameters):
        path = _write(os.path.join(self.tmp_dir, name), pictures,
                      **parameters)
        return archive_tools.archive_mime_type(path)

    def test_several_pages_are_a_book(self):
        self.assertEqual(constants.TIFF, self._type('scan.tif', _pages()))
        self.assertEqual(constants.TIFF, self._type('SCAN.TIFF', _pages()))

    def test_a_bigtiff_is_read_too(self):
        path = os.path.join(self.tmp_dir, 'big.tif')
        _write(path, _pages(), big_tiff=True)
        with open(path, 'rb') as fp:
            if fp.read(4) not in (b'II+\x00', b'MM\x00+'):
                self.skipTest('this Pillow writes no BigTIFF')
        self.assertEqual(constants.TIFF, archive_tools.archive_mime_type(path))

    def test_one_page_stays_an_image(self):
        self.assertIsNone(self._type('one.tif', _pages()[:1]))

    def test_a_page_and_its_preview_stay_an_image(self):
        path = _with_previews(os.path.join(self.tmp_dir, 'one.tif'),
                              _pages()[:1])
        with Image.open(path) as image:
            self.assertEqual(2, image.n_frames)
        self.assertIsNone(archive_tools.archive_mime_type(path))

    def test_a_tiff_under_another_name_is_no_book(self):
        """A camera's raw file is a TIFF of several pictures too."""
        self.assertIsNone(self._type('photo.dng', _pages()))

    def test_a_tiff_that_cannot_be_read_is_no_book(self):
        path = os.path.join(self.tmp_dir, 'broken.tif')
        with open(path, 'wb') as fp:
            fp.write(b'II*\x00' + b'\xff' * 60)
        self.assertIsNone(archive_tools.archive_mime_type(path))

    def test_a_folder_lists_it_as_an_image(self):
        """The folder's files are told by name, and are not opened."""
        path = _write(os.path.join(self.tmp_dir, 'scan.tif'), _pages())
        provider = file_provider.OrderedFileProvider(self.tmp_dir)
        self.assertEqual(
            [path], provider.list_files(file_provider.FileProvider.IMAGES))
        self.assertEqual(
            [], provider.list_files(file_provider.FileProvider.ARCHIVES))

    def test_the_preview_counts_its_pages(self):
        path = _write(os.path.join(self.tmp_dir, 'scan.tif'), _pages())
        self.assertEqual('3 pages, TIFF document',
                         file_chooser_base_dialog.file_details(path))


class HandlerTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp_dir, 'out')

    def _open(self, path):
        archive = archive_tools.get_archive_handler(path)
        self.assertIsInstance(archive, tiff.TiffArchive)
        self.addCleanup(archive.close)
        return archive

    def _extracted(self, archive, name):
        archive.extract(name, self.out)
        with Image.open(os.path.join(self.out, name)) as image:
            image.load()
            self.assertEqual(1, getattr(image, 'n_frames', 1))
            return image.copy()

    def test_each_page_is_listed_and_written_as_it_is(self):
        pages = _pages()
        archive = self._open(
            _write(os.path.join(self.tmp_dir, 'scan.tif'), pages))
        names = archive.list_contents()
        self.assertEqual(['page00001.tif', 'page00002.tif', 'page00003.tif'],
                         names)
        # Out of order, as the reader turns to them.
        for index in (2, 0, 1):
            written = self._extracted(archive, names[index])
            self.assertEqual(pages[index].mode, written.mode)
            self.assertEqual(pages[index].size, written.size)
            self.assertEqual(pages[index].tobytes(), written.tobytes())

    def test_a_page_is_written_the_way_up_it_is_to_be_seen(self):
        """The file says how each picture is turned; the page written
        out is turned, and says nothing."""
        archive = self._open(_write(os.path.join(self.tmp_dir, 'scan.tif'),
                                    _pages(), tiffinfo={274: 6}))
        written = self._extracted(archive, 'page00001.tif')
        self.assertEqual((60, 40), written.size)
        self.assertEqual((0, 0, 255), written.getpixel((59, 0)))

    def test_previews_are_no_pages(self):
        pages = _pages()
        archive = self._open(_with_previews(
            os.path.join(self.tmp_dir, 'scan.tif'), pages))
        names = archive.list_contents()
        self.assertEqual(3, len(names))
        for name, page in zip(names, pages):
            self.assertEqual(page.size, self._extracted(archive, name).size)

    def test_a_name_that_was_not_listed_writes_nothing(self):
        archive = self._open(
            _write(os.path.join(self.tmp_dir, 'scan.tif'), _pages()))
        archive.list_contents()
        for name in ('page00004.tif', 'page00000.tif', 'other.tif'):
            archive.extract(name, self.out)
        self.assertFalse(os.path.exists(self.out))

    def test_a_page_larger_than_pillow_opens_is_refused(self):
        archive = self._open(
            _write(os.path.join(self.tmp_dir, 'scan.tif'), _pages()))
        names = archive.list_contents()
        limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = 2000
        self.addCleanup(setattr, Image, 'MAX_IMAGE_PIXELS', limit)
        with self.assertRaises(Image.DecompressionBombError):
            archive.extract(names[0], self.out)
        archive.extract(names[1], self.out)
        self.assertEqual(['page00002.tif'], os.listdir(self.out))

    def test_closed_it_lets_go_of_the_file(self):
        path = _write(os.path.join(self.tmp_dir, 'scan.tif'), _pages())
        archive = self._open(path)
        archive.list_contents()
        archive.close()
        archive.extract('page00001.tif', self.out)
        self.assertFalse(os.path.exists(self.out))
        # Windows refuses to remove a file that is open.
        os.remove(path)


class WindowTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.handler = self.window.filehandler
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _open(self, path):
        self.handler.open_file(path)
        self.assertTrue(wait_for(
            lambda: self.handler.file_loaded
            and not self.handler.file_loading
            and self.window.imagehandler.get_number_of_pages() > 0))

    def test_it_opens_as_a_book_of_its_pages(self):
        folder = os.path.join(self.tmp_dir, 'scans')
        os.makedirs(folder)
        path = _write(os.path.join(folder, 'scan.tif'), _pages())
        _write(os.path.join(folder, 'other.tif'), _pages()[:1])
        self._open(path)
        images = self.window.imagehandler
        self.assertEqual(constants.TIFF, self.handler.archive_type)
        self.assertEqual(3, images.get_number_of_pages())
        self.assertEqual(path, self.handler.get_path_to_base())
        self.window.set_page(3)
        self.assertTrue(wait_for(lambda: images.page_is_available(3)))
        self.assertEqual((20, 80), images.get_size(3))

    def test_one_page_opens_among_the_images_of_its_folder(self):
        folder = os.path.join(self.tmp_dir, 'scans')
        os.makedirs(folder)
        _write(os.path.join(folder, 'scan.tif'), _pages())
        path = _write(os.path.join(folder, 'other.tif'), _pages()[:1])
        self._open(path)
        self.assertIsNone(self.handler.archive_type)
        self.assertEqual(2, self.window.imagehandler.get_number_of_pages())
