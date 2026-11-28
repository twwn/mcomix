"""Pages shrunk to a limit as WebP (mcomix.page_shrink), and the archive
writer's option that does it to a book's pages."""

import os
import struct
import zipfile

from PIL import Image, PngImagePlugin

from . import MComixTest, drawn_page, encoded
from mcomix import archive_packer
from mcomix import page_shrink
from mcomix.page_shrink import Shrink, scaled_size

#: The limit and the quality the tests shrink with.
_SHRINK = Shrink(limit=600, quality=80)


class ScaledSizeTest(MComixTest):

    def test_a_page_taller_than_the_limit_is_made_as_tall(self):
        self.assertEqual((400, 600), scaled_size(1000, 1500, 600))

    def test_a_page_no_taller_than_the_limit_is_not_shrunk(self):
        self.assertIsNone(scaled_size(400, 600, 600))
        self.assertIsNone(scaled_size(399, 599, 600))

    def test_a_spread_is_judged_by_its_height(self):
        self.assertEqual((1200, 600), scaled_size(3000, 1500, 600))

    def test_a_long_strip_is_never_shrunk_for_its_height(self):
        """A strip 400 wide, as wide as a page of 2:3 at the limit, stays
        as it is however tall."""
        self.assertIsNone(scaled_size(400, 20000, 600))
        # Just short of a strip's shape, it is a page.
        self.assertEqual((240, 600), scaled_size(400, 1000, 600))

    def test_a_long_strip_wider_than_a_page_is_made_as_wide(self):
        self.assertEqual((400, 4000), scaled_size(800, 8000, 600))


class ShrinkInsteadTest(MComixTest):

    """shrink_instead() over pages written into a folder of their own."""

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp_dir, 'pages')
        os.mkdir(self.folder)

    def _page(self, name, data):
        path = os.path.join(self.folder, name)
        with open(path, 'wb') as file:
            file.write(data)
        return path

    def _shrunk(self, path, shrink=_SHRINK):
        return page_shrink.shrink_instead(path, self.folder, 'shrunk.webp',
                                          shrink)

    def test_a_jpeg_over_the_limit_becomes_a_smaller_webp_as_tall(self):
        path = self._page('page.jpg', encoded(
            drawn_page(1, (1000, 1500)), 'JPEG', quality=95))
        shrunk = self._shrunk(path)
        self.assertEqual(os.path.join(self.folder, "shrunk.webp"), shrunk)
        with Image.open(shrunk) as picture:
            self.assertEqual(('WEBP', (400, 600)),
                             (picture.format, picture.size))
        self.assertLess(os.path.getsize(shrunk), os.path.getsize(path))

    def test_the_colour_profile_and_exif_go_along(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        profile = b'a stand-in colour profile'
        path = self._page('page.png', encoded(
            drawn_page(2, (1000, 1500)), 'PNG', icc_profile=profile,
            exif=exif))
        with Image.open(self._shrunk(path)) as picture:
            self.assertEqual(profile, picture.info.get('icc_profile'))
            self.assertEqual(6, picture.getexif().get(0x0112))

    def test_a_grey_page_keeps_no_grey_profile_and_comes_out_grey(self):
        path = self._page('page.png', encoded(
            drawn_page(3, (1000, 1500)).convert('L'), 'PNG',
            icc_profile=b'a stand-in grey profile'))
        with Image.open(self._shrunk(path)) as picture:
            self.assertIsNone(picture.info.get('icc_profile'))
            red, green, blue = picture.convert('RGB').split()
            self.assertEqual(red.tobytes(), blue.tobytes())

    def test_transparency_is_kept(self):
        page = drawn_page(4, (1000, 1500)).convert('RGBA')
        page.putpixel((0, 0), (0, 0, 0, 0))
        page.paste((0, 0, 0, 0), (0, 0, 200, 200))
        path = self._page('page.png', encoded(page, 'PNG'))
        with Image.open(self._shrunk(path)) as picture:
            self.assertEqual('RGBA', picture.mode)
            self.assertEqual(0, picture.getpixel((10, 10))[3])

    def test_a_page_not_over_the_limit_is_left_alone(self):
        path = self._page('page.jpg', encoded(
            drawn_page(5, (400, 600)), 'JPEG', quality=95))
        self.assertIsNone(self._shrunk(path))
        self.assertEqual(['page.jpg'], os.listdir(self.folder))

    def test_a_webp_no_smaller_is_not_kept(self):
        """A page all of one colour packs into next to nothing as a
        palette PNG; at the highest quality, its WebP is larger."""
        path = self._page('page.png', encoded(
            Image.new('P', (1000, 1500)), 'PNG', optimize=True))
        self.assertIsNone(self._shrunk(path, Shrink(600, 100)))
        self.assertEqual(['page.png'], os.listdir(self.folder))

    def test_pages_that_would_lose_more_than_detail_are_left_alone(self):
        frames = [drawn_page(seed, (1000, 1500)) for seed in (6, 7)]
        gamma = PngImagePlugin.PngInfo()
        gamma.add(b'gAMA', struct.pack('>I', 100000))
        pages = {
            'animated.gif': encoded(frames[0], 'GIF', save_all=True,
                                    append_images=frames[1:]),
            'deep.png': encoded(Image.new('I;16', (1000, 1500)), 'PNG'),
            'cmyk.jpg': encoded(frames[0].convert('CMYK'), 'JPEG'),
            # A gamma of 1.0, which a WebP could not carry.
            'gamma.png': encoded(frames[0], 'PNG', pnginfo=gamma),
        }
        for name, data in pages.items():
            with self.subTest(name):
                self.assertIsNone(self._shrunk(self._page(name, data)))
        self.assertEqual(sorted(pages), sorted(os.listdir(self.folder)))

    def test_a_strip_too_tall_for_a_webp_even_shrunk_is_left_alone(self):
        """800 by 40000, made 400 wide, would still be 20000 tall."""
        path = self._page('strip.png', encoded(
            Image.new('L', (800, 40000), 'white'), 'PNG'))
        self.assertIsNone(self._shrunk(path))

    def test_the_cost_is_the_pages_pixels_and_nothing_for_what_is_not_one(self):
        path = self._page('page.jpg', encoded(
            drawn_page(8, (100, 150)), 'JPEG'))
        self.assertEqual(100 * 150 * page_shrink._BYTES_PER_PIXEL,
                         page_shrink.cost(path))
        self.assertEqual(0, page_shrink.cost(self._page('notes.txt', b'x')))


class WriteShrunkTest(MComixTest):

    """write_archive(shrink=...) over a book of three pages."""

    def setUp(self):
        super().setUp()
        self.pages = {}
        for name, size in (('01.jpg', (1000, 1500)), ('02.jpg', (400, 600)),
                           ('03.png', (1000, 1500))):
            path = os.path.join(self.tmp_dir, name)
            drawn_page(len(self.pages), size).save(path, quality=95)
            self.pages[path] = name
        self.book = os.path.join(self.tmp_dir, 'book.cbz')

    def _write(self, **options):
        return archive_packer.write_archive(
            self.book, list(self.pages), [], page_names=self.pages,
            add_comic_info=False, shrink=_SHRINK, **options)

    def test_the_pages_over_the_limit_are_written_shrunk_as_webp(self):
        written = self._write()
        self.assertEqual(['01.webp', '02.jpg', '03.webp'],
                         sorted(written.values()))
        with zipfile.ZipFile(self.book) as book:
            self.assertEqual(['01.webp', '02.jpg', '03.webp'],
                             sorted(book.namelist()))
            with book.open('03.webp') as member, Image.open(member) as page:
                self.assertEqual((400, 600), page.size)

    def test_a_book_with_no_page_shrunk_is_not_written(self):
        for path in list(self.pages):
            if self.pages[path] != '02.jpg':
                del self.pages[path]
        with self.assertRaises(archive_packer.Unchanged):
            self._write(only_converted=True)
        self.assertFalse(os.path.exists(self.book))

# vim: expandtab:sw=4:ts=4
