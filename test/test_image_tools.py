import binascii
import os
import shutil
import tempfile
import unittest
import unittest.mock

from gi.repository import Gdk, GdkPixbuf, GLib

from collections import namedtuple
from PIL import Image, ImageDraw
from io import BytesIO
from difflib import unified_diff

from . import MComixTest, get_testfile_path

from mcomix import constants
from mcomix import image_tools
from mcomix import preferences
from mcomix.preferences import prefs


_IMAGE_MODES = (
    # Can be
    # saved    GDK     PIL
    # to PNG?  mode    mode
    (True, 'RGB', '1'),  # (1-bit pixels, black and white, stored with one pixel per byte)
    (True, 'RGB', 'L'),  # (8-bit pixels, black and white)
    (True, 'RGBA', 'LA'),  # (8-bit pixels, black and white with alpha)
    (True, 'RGBA', 'P'),  # (8-bit pixels, mapped to any other mode using a color palette)
    (True, 'RGB', 'RGB'),  # (3x8-bit pixels, true color)
    (True, 'RGBA', 'RGBA'),  # (4x8-bit pixels, true color with transparency mask)
    (False, 'RGB', 'RGBX'),  # (4x8-bit pixels, true color with padding)
    (False, 'RGB', 'CMYK'),  # (4x8-bit pixels, color separation)
    (False, 'RGB', 'YCbCr'),  # (3x8-bit pixels, color video format)
    (False, 'RGB', 'HSV'),  # (3x8-bit pixels, Hue, Saturation, Value color space)
    (False, 'RGB', 'I'),  # (32-bit signed integer pixels)
    (False, 'RGB', 'F'),  # (32-bit floating point pixels)
)

_TestImage = namedtuple('TestImage', 'name format size mode has_alpha rotation')

_TEST_IMAGES = (
    _TestImage('01-JPG-Indexed.jpg', 'JPEG', (1,   1), 'L', False, 0),
    _TestImage('02-JPG-RGB.jpg', 'JPEG', (1,   1), 'RGB', False, 0),
    _TestImage('03-PNG-RGB.png', 'PNG', (1,   1), 'RGB', False, 0),
    _TestImage('04-PNG-Indexed.png', 'PNG', (1,   1), 'P', False, 0),
    _TestImage('05-PNG-RGBA.png', 'PNG', (1,   1), 'RGBA', True, 0),
    _TestImage('animated.gif', 'GIF', (210, 210), 'RGBA', True, 0),
    _TestImage('blue.png', 'PNG', (100, 100), 'RGB', False, 0),
    _TestImage('checkerboard.png', 'PNG', (128, 128), 'RGBA', True, 0),
    _TestImage('landscape-exif-270-rotation.jpg', 'JPEG', (210, 297), 'L', False, 270),
    _TestImage('landscape-exif-270-rotation.png', 'PNG', (210, 297), 'LA', True, 270),
    _TestImage('landscape-no-exif.jpg', 'JPEG', (297, 210), 'L', False, 0),
    _TestImage('landscape-no-exif.png', 'PNG', (297, 210), 'LA', True, 0),
    _TestImage('pattern.jpg', 'JPEG', (200, 100), 'RGB', False, 0),
    _TestImage('pattern-opaque-rgba.png', 'PNG', (200, 100), 'RGBA', True, 0),
    _TestImage('pattern-opaque-rgb.png', 'PNG', (200, 100), 'RGB', False, 0),
    _TestImage('pattern-transparent-rgba.png', 'PNG', (200, 100), 'RGBA', True, 0),
    _TestImage('portrait-exif-180-rotation.jpg', 'JPEG', (210, 297), 'L', False, 180),
    _TestImage('portrait-exif-180-rotation.png', 'PNG', (210, 297), 'LA', True, 180),
    _TestImage('portrait-no-exif.jpg', 'JPEG', (210, 297), 'L', False, 0),
    _TestImage('portrait-no-exif.png', 'PNG', (210, 297), 'LA', True, 0),
    _TestImage('red.png', 'PNG', (100, 100), 'RGB', False, 0),
    _TestImage('transparent.png', 'PNG', (200, 150), 'RGBA', True, 0),
    _TestImage('transparent-indexed.png', 'PNG', (200, 150), 'P', True, 0),
)

_TEST_IMAGE_BY_NAME = {im.name: im for im in _TEST_IMAGES}

#: The test images carrying Exif rotation, and their unrotated counterparts.
_ROTATED_TEST_IMAGES = (
    # JPEG.
    'landscape-exif-270-rotation.jpg',
    'landscape-no-exif.jpg',
    'portrait-exif-180-rotation.jpg',
    'portrait-no-exif.jpg',
    # PNG.
    'landscape-exif-270-rotation.png',
    'landscape-no-exif.png',
    'portrait-exif-180-rotation.png',
    'portrait-no-exif.png',
)


def get_test_image(name):
    return _TEST_IMAGE_BY_NAME[name]


def get_image_path(basename):
    return get_testfile_path('images', basename)


def new_pixbuf(size, with_alpha, fill_colour):
    pixbuf = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                  has_alpha=with_alpha, bits_per_sample=8,
                                  width=size[0], height=size[1])
    pixbuf.fill(fill_colour)
    return pixbuf


# Example output:
#
#              ____ data in hexadecimal format, '*' indicate repeated content
#             v
#
# 0001800: ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff ffffffff
# 0000080: *
# 0001880: cbcbcbff 232323ff ffffffff ffffffff 717171ff 0e0e0eff 666666ff ffffffff
#
#    ^____ data address, or size of repeated content
#
def xhexdump(data, group_size=4):
    addr, size = 0, 0
    io = BytesIO(data)
    chunk_size = group_size * 8
    prev_addr, prev_hex = (0, '')

    def format_line(addr, hex):
        return '%07x: %s' % (addr, hex)

    while True:
        chunk = io.read(chunk_size)
        if not chunk:
            if addr > (prev_addr + chunk_size):
                yield format_line(addr - prev_addr, '*')
            break
        size += len(chunk)
        chunk = binascii.hexlify(chunk).decode('ascii')
        hex = []
        for s in range(0, chunk_size * 2, group_size * 2):
            hex.append(chunk[s:s+(group_size*2)])
        hex = ' '.join(hex)
        if hex != prev_hex:
            if addr > (prev_addr + chunk_size):
                yield format_line(addr - prev_addr, '*')
            yield format_line(addr, hex)
            prev_addr, prev_hex = addr, hex
        addr += chunk_size
    if size != prev_addr:
        yield '%07x' % size


def hexdump(data, group_size=4):
    return [line for line in xhexdump(data, group_size=group_size)]


#: Ghostscript's copy of the Adobe RGB (1998) profile, where it is installed.
_ADOBE_RGB_PROFILE = '/usr/share/ghostscript/iccprofiles/a98.icc'


class ImageToolsTest(MComixTest):

    def assertImagesEqual(self, im1, im2, msg=None, max_diff=20,
                          compare_content=True):
        def fail(diff_type, diff_fmt, *args):
            if msg is None:
                fmt = 'Images are not equal, result %(diff_type)s differs: %(diff)s'
            else:
                fmt = msg
            self.fail(fmt % {
                'diff_type': diff_type,
                'diff': diff_fmt % args,
            })

        def info(im):
            if isinstance(im, GdkPixbuf.Pixbuf):
                width, stride = im.get_width(), im.get_rowstride()
                line_size = width * im.get_n_channels()
                if stride == line_size:
                    pixels = im.get_pixels()
                else:
                    assert stride > line_size
                    io = BytesIO(im.get_pixels())
                    pixels = b''
                    while True:
                        line = io.read(line_size)
                        if not line:
                            break
                        pixels += line
                        leftover = io.read(stride - line_size)
                        if not leftover:
                            break
                        assert len(leftover) == (stride - line_size)
                mode = 'RGBA' if im.get_has_alpha() else 'RGB'
                return mode, (im.get_width(), im.get_height()), pixels
            if isinstance(im, Image.Image):
                return im.mode, im.size, im.tobytes()
            raise ValueError('unsupported class %s' % type(im))
        mode1, size1, pixels1 = info(im1)
        mode2, size2, pixels2 = info(im2)
        if mode1 != mode2:
            fail('mode', '%s instead of %s', mode1, mode2)
        if size1 != size2:
            fail('size', '%s instead of %s', size1, size2)
        if not compare_content:
            return
        assert mode1 in ('RGB', 'RGBA')
        group_size = 3 if 'RGB' == mode1 else 4
        hex1 = hexdump(pixels1, group_size=group_size)
        hex2 = hexdump(pixels2, group_size=group_size)
        diff = unified_diff(hex1, hex2, fromfile='result', tofile='expected', lineterm='')
        diff_lines = []
        for line in diff:
            if len(diff_lines) > max_diff:
                diff_lines.append('[...] diff truncated, change max_diff to increase limit.')
                break
            diff_lines.append(line)
        if diff_lines:
            fail('content', '\n%s\n', '\n'.join(diff_lines))

    def test_temporary_directory_outlives_a_test(self):
        # GTK4 decodes at a size through glycin, which unpacks into the
        # directory GLib pinned the first time anything asked it for one;
        # GLib caches that answer and never reads the environment again.
        # Point the environment at a directory that is already gone, the
        # way tearDown() leaves the one setUp() made, and the decode still
        # has to work - otherwise every sized load from the second test
        # onwards fails and load_pixbuf_size() quietly answers from PIL.
        gone = tempfile.mkdtemp()
        shutil.rmtree(gone)
        os.environ['TMPDIR'] = os.environ['TEMP'] = os.environ['TMP'] = gone
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            get_image_path('blue.png'), 50, 50)
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height()), (50, 50))

    def test_load_pixbuf_basic(self):
        for image in _TEST_IMAGES:
            image_path = get_image_path(image.name)
            expected_mode = 'RGBA' if image.has_alpha else 'RGB'
            im = Image.open(image_path).convert(expected_mode)
            pixbuf = image_tools.load_pixbuf(image_path)
            msg = (
                'load_pixbuf("%s") failed; '
                'result %%(diff_type)s differs: %%(diff)s'
                % (image.name,)
            )
            self.assertImagesEqual(pixbuf, im, msg=msg,
                                   compare_content=image.format != 'JPEG')

    def test_load_pixbuf_falls_back_to_pil(self):
        # load_pixbuf() no longer asks which loader to prefer, so a format
        # gdk-pixbuf has no loader for has to come back from PIL by way of
        # gdk-pixbuf failing on it first.
        path = os.path.join(self.tmp_dir, 'image.pcx')
        Image.new('RGB', (17, 11), (10, 20, 30)).save(path, 'PCX')
        pixbuf = image_tools.load_pixbuf(path)
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height()), (17, 11))

    def test_load_pixbuf_modes(self):
        tmp_file = tempfile.NamedTemporaryFile(prefix='image.',
                                               suffix='.png', delete=False)
        tmp_file.close()
        base_im = Image.open(get_image_path('transparent.png'))
        for supported, expected_pixbuf_mode, mode in _IMAGE_MODES:
            if not supported:
                continue
            input_im = base_im.convert(mode)
            input_im.save(tmp_file.name)
            pixbuf = image_tools.load_pixbuf(tmp_file.name)
            expected_im = input_im.convert(expected_pixbuf_mode)
            msg = (
                'load_pixbuf("%s") failed; '
                'result %%(diff_type)s differs: %%(diff)s'
                % (mode,)
            )
            self.assertImagesEqual(pixbuf, expected_im, msg=msg)

    def test_load_pixbuf_invalid(self):
        self.assertRaises(IOError, image_tools.load_pixbuf, os.devnull)

    def test_load_pixbuf_size_basic(self):
        # Same as test_load_pixbuf_basic:
        # load bunch of images at their
        # normal resolution.
        prefs['checkered bg for transparent images'] = False
        for image in _TEST_IMAGES:
            if image.name in (
                'transparent.png',
                'transparent-indexed.png',
            ):
                # Avoid complex transparent image, since PIL
                # and GdkPixbuf may yield different results.
                continue
            image_path = get_image_path(image.name)
            expected_mode = 'RGBA' if image.has_alpha else 'RGB'
            expected = Image.open(image_path).convert(expected_mode)
            if image.has_alpha:
                background = Image.new('RGBA', image.size, color='white')
                expected = Image.alpha_composite(background, expected)
            result = image_tools.load_pixbuf_size(image_path,
                                                  image.size[0],
                                                  image.size[1])
            msg = (
                'load_pixbuf("%s") failed; '
                'result %%(diff_type)s differs: %%(diff)s'
                % (image.name,)
            )
            self.assertImagesEqual(result, expected, msg=msg,
                                   compare_content=image.format != 'JPEG')

    def test_load_pixbuf_size_dimensions(self):
        # Use both:
        # - a format with support for resizing at the decoding stage: JPEG
        # - a format that does not support resizing at the decoding stage: PNG
        for name in (
            'pattern.jpg',
            'pattern-opaque-rgba.png',
        ):
            image = get_test_image(name)
            image_path = get_image_path(image.name)
            # Check image is unchanged if smaller than target dimensions.
            target_size = 2 * image.size[0], 2 * image.size[1]
            expected = image_tools.load_pixbuf_size(image_path, *image.size)
            result = image_tools.load_pixbuf_size(image_path, *target_size)
            msg = (
                'load_pixbuf_size("%s", %dx%d) failed; '
                'result %%(diff_type)s differs: %%(diff)s'
                % ((name,) + target_size)
            )
            self.assertImagesEqual(result, expected, msg=msg)
            # Check image is scaled down if bigger than target dimensions,
            # and that aspect ratio is kept.
            target_size = image.size[0], image.size[1] // 2
            result = image_tools.load_pixbuf_size(image_path,
                                                  *target_size)
            msg = (
                'load_pixbuf_size("%s", %dx%d) failed; '
                'result %%(diff_type)s differs: %%(diff)s'
                % ((name,) + target_size)
            )
            self.assertEqual((result.get_width(), result.get_height()),
                             (image.size[0] // 2, image.size[1] // 2))

    def test_load_pixbuf_size_of_nothing(self):
        # A widget that has not been given its size yet asks for a box
        # with a zero side.  gdk-pixbuf refuses that scale and PIL then
        # divides by it, so this used to raise ZeroDivisionError.
        path = get_image_path('pattern.jpg')  # 200x100
        for (width, height), expected in (((0, 0), (1, 1)),
                                          ((0, 50), (1, 1)),
                                          ((50, 0), (2, 1))):
            # A zero side asks for one pixel, and the ratio is kept, so
            # 50x0 of a 2:1 image is two pixels by one.
            pixbuf = image_tools.load_pixbuf_size(path, width, height)
            self.assertEqual((pixbuf.get_width(), pixbuf.get_height()),
                             expected,
                             'load_pixbuf_size(%d, %d)' % (width, height))

    def test_load_pixbuf_size_invalid(self):
        self.assertRaises(IOError, image_tools.load_pixbuf_size,
                          os.devnull, 50, 50)

    def test_a_jpeg_is_scaled_by_pil(self):
        """PIL's draft() decodes a JPEG at a fraction of its size, and
        where gdk-pixbuf's loaders are sandboxed it is several times
        faster: a thumbnail of a 1200x1800 page took 0.8 ms against
        9-11 ms."""
        real = GdkPixbuf.Pixbuf.new_from_file_at_size
        with unittest.mock.patch.object(GdkPixbuf.Pixbuf,
                                        'new_from_file_at_size',
                                        wraps=real) as by_gdk_pixbuf:
            pixbuf = image_tools.load_pixbuf_size(
                get_image_path('landscape-no-exif.jpg'), 64, 64)
        self.assertEqual(64, pixbuf.get_width())
        by_gdk_pixbuf.assert_not_called()

    def test_a_png_is_still_scaled_by_gdk_pixbuf(self):
        """draft() does nothing for a PNG, so PIL would decode all of it."""
        real = GdkPixbuf.Pixbuf.new_from_file_at_size
        with unittest.mock.patch.object(GdkPixbuf.Pixbuf,
                                        'new_from_file_at_size',
                                        wraps=real) as by_gdk_pixbuf:
            image_tools.load_pixbuf_size(
                get_image_path('landscape-no-exif.png'), 64, 64)
        by_gdk_pixbuf.assert_called_once()

    def test_a_scaled_jpeg_keeps_its_exif_orientation(self):
        """Scaling what draft() left makes a new pixbuf, which would
        otherwise say nothing of the orientation gdk-pixbuf reports."""
        pixbuf = image_tools.load_pixbuf_size(
            get_image_path('landscape-exif-270-rotation.jpg'), 64, 64)
        self.assertEqual(270, image_tools.get_implied_rotation(pixbuf))

    @unittest.skipUnless(os.path.isfile(_ADOBE_RGB_PROFILE),
                         'needs an Adobe RGB colour profile')
    def test_a_scaled_jpeg_with_a_colour_profile_comes_out_in_srgb(self):
        """glycin converts a picture with an embedded profile into
        sRGB, so a page read through gdk-pixbuf is shown converted;
        read through PIL, the thumbnail of the same page showed the
        stored numbers, and an Adobe RGB red came out duller."""
        from PIL import ImageCms
        with open(_ADOBE_RGB_PROFILE, 'rb') as fp:
            profile = fp.read()
        path = os.path.join(self.tmp_dir, 'adobe-rgb.jpg')
        Image.new('RGB', (64, 64), (200, 30, 30)).save(
            path, quality=98, icc_profile=profile)
        expected = ImageCms.profileToProfile(
            Image.new('RGB', (1, 1), (200, 30, 30)), BytesIO(profile),
            ImageCms.createProfile('sRGB')).getpixel((0, 0))

        pixbuf = image_tools.load_pixbuf_size(path, 32, 32)

        red = tuple(pixbuf.get_pixels()[:3])
        for got, want in zip(red, expected):
            self.assertAlmostEqual(got, want, delta=3, msg=(red, expected))

    @unittest.skipUnless(os.path.isfile(_ADOBE_RGB_PROFILE),
                         'needs an Adobe RGB colour profile')
    def test_a_page_pil_reads_in_gdk_pixbufs_place_comes_out_in_srgb(self):
        """A page gdk-pixbuf will not read is read by PIL, which hands
        over the stored numbers where glycin would have converted them;
        the same page would then look different depending on which of
        the two read it."""
        from PIL import ImageCms
        with open(_ADOBE_RGB_PROFILE, 'rb') as fp:
            profile = fp.read()
        path = os.path.join(self.tmp_dir, 'adobe-rgb.jpg')
        Image.new('RGB', (8, 8), (200, 30, 30)).save(
            path, quality=98, icc_profile=profile)
        with open(path, 'rb') as fp:
            data = fp.read()
        expected = ImageCms.profileToProfile(
            Image.new('RGB', (1, 1), (200, 30, 30)), BytesIO(profile),
            ImageCms.createProfile('sRGB')).getpixel((0, 0))

        def refuse(*args):
            raise GLib.Error('refused')

        with unittest.mock.patch.object(GdkPixbuf.Pixbuf, 'new_from_file',
                                        refuse), \
                unittest.mock.patch.object(GdkPixbuf, 'PixbufLoader',
                                           unittest.mock.Mock(
                                               side_effect=GLib.Error('no'))):
            for pixbuf in (image_tools.load_pixbuf(path),
                           image_tools.load_pixbuf_data(data)):
                red = tuple(pixbuf.get_pixels()[:3])
                for got, want in zip(red, expected):
                    self.assertAlmostEqual(got, want, delta=3,
                                           msg=(red, expected))

    # Expose a rounding error bug in load_pixbuf_size.
    def test_load_pixbuf_rounding_error(self):
        image_size = (2063, 3131)
        target_size = (500, 500)
        expected_size = (329, 500)
        tmp_file = tempfile.NamedTemporaryFile(prefix='image.',
                                               suffix='.png', delete=False)
        tmp_file.close()
        im = Image.new('RGB', image_size)
        im.save(tmp_file.name)
        pixbuf = image_tools.load_pixbuf_size(tmp_file.name, *target_size)
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height()), expected_size)

    def test_convert_rgba_to_rgba8int(self):
        # What GdkPixbuf.Pixbuf.fill() takes, from the Gdk.RGBA
        # components the background colour preference holds.
        for colour, expected in (
                ([0.0, 0.0, 0.0, 1.0], 0x000000FF),
                ([1.0, 1.0, 1.0, 1.0], 0xFFFFFFFF),
                ([1.0, 0.0, 0.0, 1.0], 0xFF0000FF),
                ([0.0, 1.0, 0.0, 0.0], 0x00FF0000),
                # The default grey, which is what 5000 >> 8 gave
                # when these were 16-bit components.
                (preferences.DEFAULT_BG_COLOUR, 0x131313FF),
                # Short of an alpha, and out of range.
                ([0.0, 0.0, 1.0], 0x0000FFFF),
                ([-1.0, 2.0, 0.5, 1.0], 0x00FF80FF),
        ):
            self.assertEqual(image_tools.convert_rgba_to_rgba8int(colour),
                             expected,
                             'convert_rgba_to_rgba8int(%r)' % (colour,))

    def test_the_lens_can_fill_its_canvas_with_the_background_colour(self):
        # The colour preferences became Gdk.RGBA components, and this is
        # the one place still reading them as 16-bit integers: the lens
        # raised TypeError on every use.
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
        pixbuf.fill(image_tools.convert_rgba_to_rgba8int(prefs['bg colour']))
        self.assertEqual(pixbuf.get_pixels()[:4], bytes((0x13, 0x13, 0x13, 0xFF)))

    def test_pixbuf_to_pil(self):
        for image in (
            'transparent.png',
            'transparent-indexed.png',
            'pattern-opaque-rgb.png',
            'pattern-opaque-rgba.png',
            'pattern-transparent-rgba.png',
        ):
            pixbuf = image_tools.load_pixbuf(get_image_path(image))
            im = image_tools.pixbuf_to_pil(pixbuf)
            msg = (
                'pixbuf_to_pil("%s") failed; '
                'result %%(diff_type)s differs: %%(diff)s'
                % (image,)
            )
            self.assertImagesEqual(im, pixbuf, msg=msg)

    def test_pil_to_pixbuf(self):
        base_im = Image.open(get_image_path('transparent.png'))
        for _, expected_pixbuf_mode, mode in _IMAGE_MODES:
            input_im = base_im.convert(mode)
            pixbuf = image_tools.pil_to_pixbuf(input_im)
            expected_im = input_im.convert(expected_pixbuf_mode)
            msg = (
                'pil_to_pixbuf("%s") failed; '
                'result %%(diff_type)s differs: %%(diff)s'
                % (mode,)
            )
            self.assertImagesEqual(pixbuf, expected_im, msg=msg)
        # TODO: test keep_orientation

    def _check_image_info(self, path, expected, description):
        image_format, dimensions = image_tools.get_image_info(path)
        result = (image_format,) + tuple(dimensions)
        msg = (
            'get_image_info(%s) failed; '
            'result differs: %s:%dx%d instead of %s:%dx%d'
            % ((description,) + result + expected)
        )
        self.assertEqual(result, expected, msg=msg)

    def test_get_image_info(self):
        for image in _TEST_IMAGES:
            self._check_image_info(get_image_path(image.name),
                                   (image.format,) + image.size,
                                   '"%s"' % image.name)

    def test_get_image_info_invalid(self):
        self._check_image_info(os.devnull, ('Unknown filetype', 0, 0),
                               'invalid image')

    def test_get_implied_rotation(self):
        for name in _ROTATED_TEST_IMAGES:
            image = get_test_image(name)
            pixbuf = image_tools.load_pixbuf(get_image_path(name))
            rotation = image_tools.get_implied_rotation(pixbuf)
            self.assertEqual(rotation, image.rotation,
                             msg='get_implied_rotation(%s) failed: %u instead of %u'
                             % (image, rotation, image.rotation))

    def test_get_implied_rotation_from_file(self):
        # Reading the header has to agree with decoding the image; the
        # virtual double page check relies on it instead of loading a
        # pixbuf for every page it is asked about.
        for name in _ROTATED_TEST_IMAGES:
            image = get_test_image(name)
            rotation = image_tools.get_implied_rotation_from_file(get_image_path(name))
            self.assertEqual(rotation, image.rotation,
                             msg='get_implied_rotation_from_file(%s) failed: %u instead of %u'
                             % (image, rotation, image.rotation))

    def test_get_implied_rotation_from_file_invalid(self):
        self.assertEqual(image_tools.get_implied_rotation_from_file(os.devnull), 0)

    def test_get_image_header(self):
        # load_pixbuf_size() takes the format and the dimensions from here
        # rather than from get_image_info(), so the two have to agree.
        for image in _TEST_IMAGES:
            path = get_image_path(image.name)
            self.assertEqual(image_tools.get_image_header(path),
                             image_tools.get_image_info(path),
                             msg='get_image_header("%s") disagrees with '
                                 'get_image_info()' % image.name)

    def test_get_image_header_invalid(self):
        # Nothing identifies it, so the answer has to be the one
        # load_pixbuf_size() reads as "let the loader raise".
        self.assertEqual(image_tools.get_image_header(os.devnull),
                         ('Unknown filetype', (0, 0)))

    def test_get_image_size(self):
        for image in _TEST_IMAGES:
            self.assertEqual(image_tools.get_image_size(get_image_path(image.name)),
                             image.size,
                             msg='get_image_size("%s") failed' % image.name)

    def test_get_image_size_invalid(self):
        self.assertEqual(image_tools.get_image_size(os.devnull), (0, 0))

    def test_fit_in_rectangle_one_unbounded_dimension(self):
        # A negative side means "as large as it likes in this
        # direction", bounded only by RENDER_SIZE_LIMIT, so the other
        # side is what decides the scale.
        pixbuf = new_pixbuf((200, 400), False, 0)
        for width, height, expected in ((-1, 100, (50, 100)),
                                        (100, -1, (100, 200))):
            result = image_tools.fit_in_rectangle(pixbuf, width, height)
            self.assertEqual((result.get_width(), result.get_height()),
                             expected,
                             msg='fit_in_rectangle(200x400 => %dx%d) failed'
                                 % (width, height))

    def test_fit_in_rectangle_both_dimensions_unbounded(self):
        # There is no rectangle to fit in.  This used to bound the width
        # and leave the height negative, which the clamp below turned
        # into one pixel: a 200x400 page came back 1 pixel high.
        pixbuf = new_pixbuf((200, 400), False, 0)
        self.assertRaises(ValueError,
                          image_tools.fit_in_rectangle, pixbuf, -1, -1)

    def test_fit_in_rectangle_a_side_of_zero_is_one_pixel(self):
        # load_pixbuf_size() relies on this: it clamps a zero side to one
        # itself, saying that fit_in_rectangle() would have anyway.
        pixbuf = new_pixbuf((200, 400), False, 0)
        result = image_tools.fit_in_rectangle(pixbuf, 0, 0)
        self.assertEqual((result.get_width(), result.get_height()), (1, 1))

    def test_fit_in_rectangle_dimensions(self):
        # Test dimensions handling.
        for input_size, target_size, scale_up, keep_ratio, expected_size in (
            # Exactly the same size.
            ((200, 100), (200, 100), False, False, (200, 100)),
            ((200, 100), (200, 100), False,  True, (200, 100)),
            ((200, 100), (200, 100),  True, False, (200, 100)),
            ((200, 100), (200, 100),  True,  True, (200, 100)),
            # Smaller.
            ((200, 100), (400, 400), False, False, (200, 100)),
            ((200, 100), (400, 400), False,  True, (200, 100)),
            ((200, 100), (400, 400),  True, False, (400, 400)),
            ((200, 100), (400, 400),  True,  True, (400, 200)),
            # Bigger.
            ((800, 600), (200, 200), False, False, (200, 200)),
            ((800, 600), (200, 200), False,  True, (200, 150)),
            ((800, 600), (200, 200),  True, False, (200, 200)),
            ((800, 600), (200, 200),  True,  True, (200, 150)),
            # One dimension bigger, the other smaller.
            ((200, 400), (200, 200), False, False, (200, 200)),
            ((200, 400), (200, 200), False,  True, (100, 200)),
            ((200, 400), (200, 200),  True, False, (200, 200)),
            ((200, 400), (200, 200),  True,  True, (100, 200)),
        ):
            for invert_dimensions in (False, True):
                if invert_dimensions:
                    input_size = input_size[1], input_size[0]
                    target_size = target_size[1], target_size[0]
                    expected_size = expected_size[1], expected_size[0]
                pixbuf = new_pixbuf(input_size, False, 0)
                result = image_tools.fit_in_rectangle(pixbuf,
                                                      target_size[0],
                                                      target_size[1],
                                                      scale_up=scale_up,
                                                      keep_ratio=keep_ratio)
                result_size = result.get_width(), result.get_height()
                msg = (
                    'fit_in_rectangle(%dx%d => %dx%d, scale up=%s, keep ratio=%s) failed; '
                    'result size differs: %dx%d instead of %dx%d' % (
                        input_size + target_size +
                        (scale_up, keep_ratio) +
                        result_size + expected_size
                    )
                )
                self.assertEqual(result_size, expected_size, msg=msg)

    def test_fit_in_rectangle_rotation(self):
        image_size = 128
        rect_size = 32
        # Start with a black image.
        im = Image.new('RGB', (image_size, image_size), color='black')
        draw = ImageDraw.Draw(im)
        # Paint top-left corner white.
        draw.rectangle((0, 0, rect_size, rect_size), fill='white')
        # Corner colors, starting top-left, rotating clock-wise.
        corners_colors = ('white', 'black', 'black', 'black')
        pixbuf = image_tools.pil_to_pixbuf(im)
        for rotation in (
            0, 90, 180, 270,
            -90, -180, -270,
            90 * 5, -90 * 7
        ):
            for target_size in (
                (image_size, image_size),
                (image_size // 2, image_size // 2),
            ):
                result = image_tools.fit_in_rectangle(pixbuf,
                                                      target_size[0],
                                                      target_size[1],
                                                      rotation=rotation)
                # First check size.
                input_size = (image_size, image_size)
                result_size = result.get_width(), result.get_height()
                msg = (
                    'fit_in_rectangle(%dx%d => %dx%d, rotation=%d) failed; '
                    'result size: %dx%d' % (
                        input_size + target_size + (rotation,) + result_size
                    )
                )
                self.assertEqual(result_size, target_size, msg=msg)
                # And then check corners.
                expected_corners_colors = list(corners_colors)
                for _ in range(1, 1 + (rotation % 360) // 90):
                    expected_corners_colors.insert(0, expected_corners_colors.pop(-1))
                result_corners_colors = []
                corner = new_pixbuf((1, 1), False, 0x888888)
                corners_positions = [0, 0, target_size[0] - 1, target_size[0] - 1]
                for _ in range(4):
                    x, y = corners_positions[0:2]
                    result.copy_area(x, y, 1, 1, corner, 0, 0)
                    color = corner.get_pixels()[0:3]
                    color = binascii.hexlify(color).decode('ascii')
                    if 'ffffff' == color:
                        color = 'white'
                    elif '000000' == color:
                        color = 'black'
                    result_corners_colors.append(color)
                    corners_positions.insert(0, corners_positions.pop(-1))
                # Swap bottom corners for spatial display.
                result_corners_colors.append(result_corners_colors.pop(-2))
                expected_corners_colors.append(expected_corners_colors.pop(-2))
                msg = (
                    'fit_in_rectangle(%dx%d => %dx%d, rotation=%d) failed; '
                    'result corners differs:\n'
                    '%s\t%s\n'
                    '%s\t%s\n'
                    'instead of:\n'
                    '%s\t%s\n'
                    '%s\t%s\n' % (
                        input_size + target_size + (rotation, ) +
                        tuple(result_corners_colors) +
                        tuple(expected_corners_colors)
                    )
                )
                self.assertEqual(result_corners_colors,
                                 expected_corners_colors,
                                 msg=msg)

    def test_fit_in_rectangle_opaque_no_resize(self):
        # Check opaque image is unchanged when not resizing.
        for image in (
            'pattern-opaque-rgb.png',
            'pattern-opaque-rgba.png',
        ):
            input = image_tools.load_pixbuf(get_image_path(image))
            width, height = input.get_width(), input.get_height()
            for scaling_quality in range(4):
                prefs['scaling quality'] = scaling_quality
                result = image_tools.fit_in_rectangle(input, width, height,
                                                      scaling_quality=scaling_quality)
                msg = (
                    'fit_in_rectangle("%s", scaling quality=%d) failed; '
                    'result %%(diff_type)s differs: %%(diff)s'
                    % (image, scaling_quality)
                )
                self.assertImagesEqual(result, input, msg=msg)

    def test_fit_in_rectangle_transparent_no_resize(self):
        # And with a transparent test image, check alpha blending.
        image = 'pattern-transparent-rgba.png'
        control = Image.open(get_image_path(image))
        # Create checkerboard background.
        checker_bg = Image.new('RGBA', control.size)
        checker = Image.open(get_image_path('checkerboard.png'))
        for x in range(0, control.size[0], checker.size[0]):
            for y in range(0, control.size[1], checker.size[1]):
                checker_bg.paste(checker, (x, y))
        # Create whhite background.
        white_bg = Image.new('RGBA', control.size, color='white')
        assert control.size == white_bg.size
        width, height = control.size
        for use_checker_bg in (False, True):
            prefs['checkered bg for transparent images'] = use_checker_bg
            expected = Image.alpha_composite(
                checker_bg if use_checker_bg else white_bg,
                control
            )
            for scaling_quality in range(4):
                prefs['scaling quality'] = scaling_quality
                result = image_tools.fit_in_rectangle(image_tools.pil_to_pixbuf(control),
                                                      width, height,
                                                      scaling_quality=scaling_quality)
                msg = (
                    'fit_in_rectangle("%s", scaling quality=%d, background=%s) failed; '
                    'result %%(diff_type)s differs: %%(diff)s'
                    % (image, scaling_quality, 'checker' if checker_bg else 'white')
                )
                self.assertImagesEqual(result, expected, msg=msg)


class EnhanceTest(MComixTest):

    """The enhancements of the dialog, on a picture that has an alpha
    channel: a thumbnail of a transparent page, or the library's
    cover of a book with no page that will load."""

    def _transparent(self):
        im = Image.new('RGBA', (4, 2), (40, 80, 120, 255))
        im.putpixel((3, 1), (200, 100, 0, 0))
        im.putpixel((2, 1), (10, 250, 60, 128))
        return image_tools.pil_to_pixbuf(im)

    def test_inverted_colours_keep_their_transparency(self):
        im = image_tools.pixbuf_to_pil(image_tools.enhance(
            self._transparent(), invert_color=True))
        self.assertEqual('RGBA', im.mode)
        self.assertEqual((215, 175, 135, 255), im.getpixel((0, 0)))
        self.assertEqual(0, im.getpixel((3, 1))[3])
        self.assertEqual((245, 5, 195, 128), im.getpixel((2, 1)))

    def test_automatic_contrast_is_applied_and_keeps_the_transparency(self):
        """It was left out for a picture with an alpha channel."""
        im = Image.new('RGBA', (2, 2), (100, 100, 100, 255))
        im.putpixel((1, 0), (150, 150, 150, 255))
        im.putpixel((1, 1), (120, 120, 120, 0))
        im = image_tools.pixbuf_to_pil(image_tools.enhance(
            image_tools.pil_to_pixbuf(im), autocontrast=True))
        self.assertEqual('RGBA', im.mode)
        self.assertEqual((0, 0, 0, 255), im.getpixel((0, 0)))
        self.assertEqual((255, 255, 255, 255), im.getpixel((1, 0)))
        self.assertEqual(0, im.getpixel((1, 1))[3])


class MissingImageIconTest(MComixTest):

    """The picture shown for an image that would not load."""

    def test_it_is_drawn_as_large_as_fits_the_size_asked_for(self):
        # The page it shows is 134 by 200.
        for box, size in (((134, 200), (134, 200)),
                          ((400, 400), (268, 400)),
                          ((134, 1000), (134, 200)),
                          ((64, 64), (43, 64))):
            with self.subTest(box=box):
                icon = image_tools.missing_image_icon(*box)
                self.assertEqual(size, (icon.get_width(), icon.get_height()))

    def test_the_same_size_is_drawn_once(self):
        self.assertIs(image_tools.missing_image_icon(40, 60),
                      image_tools.missing_image_icon(40, 60))

    def test_it_is_known_for_what_it_is_after_the_cache_has_moved_on(self):
        """The main window draws a page that would not load again at the
        size it is shown at, and tells it by this: an identity test
        against the cache failed once eight other sizes had pushed the
        page's own one out."""
        page = image_tools.missing_page()
        for side in range(30, 40):
            image_tools.missing_image_icon(side, side)
        self.assertTrue(image_tools.is_missing_image(page))
        self.assertFalse(image_tools.is_missing_image(
            GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)))

    def test_without_an_svg_loader_it_is_a_square_the_size_asked_for(self):
        """gdk-pixbuf can be built without one, and then the icon theme
        has nothing to offer either where its icon is an SVG, as
        Adwaita's is."""
        real = GdkPixbuf.Pixbuf.new_from_file_at_size

        def without_svg(path, width, height):
            if path.endswith('.svg'):
                raise GLib.Error('Unrecognized image file format')
            return real(path, width, height)

        image_tools._draw_missing_image.cache_clear()
        self.addCleanup(image_tools._draw_missing_image.cache_clear)
        with unittest.mock.patch.object(GdkPixbuf.Pixbuf,
                                        'new_from_file_at_size',
                                        without_svg):
            icon = image_tools.missing_image_icon(48, 64)
        self.assertEqual((48, 48), (icon.get_width(), icon.get_height()))


class PixbufToTextureTest(MComixTest):

    """Gdk.Texture.new_for_pixbuf() is deprecated as of GTK 4.20, so the
    texture is built out of the pixbuf's own memory format instead."""

    def _drawn(self, has_alpha):
        """A small pixbuf with a different colour in each quarter."""
        channels = 4 if has_alpha else 3
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, has_alpha,
                                      8, 6, 4)
        pixbuf.fill(0x102030ff)
        pixbuf.new_subpixbuf(0, 0, 3, 2).fill(0xff8000ff)
        pixbuf.new_subpixbuf(3, 2, 3, 2).fill(0x0080ffff)
        self.assertEqual(pixbuf.get_n_channels(), channels)
        return pixbuf

    def _downloaded(self, texture):
        """The texture's pixels, as RGBA rows with no padding.

        Gdk.Texture.download() writes Cairo's premultiplied BGRA, and a
        downloader is what asks for a format of one's own.
        """
        downloader = Gdk.TextureDownloader.new(texture)
        downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
        data, stride = downloader.download_bytes()
        pixels = data.get_data()
        width = texture.get_width() * 4
        return b''.join(pixels[y * stride:y * stride + width]
                        for y in range(texture.get_height()))

    def _expected(self, pixbuf):
        """The same pixels, read off the pixbuf a row at a time.

        A pixbuf's rows are padded out to a rowstride that is wider than
        the pixels in them, so a texture built with the wrong stride
        comes out sheared rather than merely wrong.
        """
        pixels = pixbuf.get_pixels()
        stride = pixbuf.get_rowstride()
        channels = pixbuf.get_n_channels()
        rows = []
        for y in range(pixbuf.get_height()):
            row = pixels[y * stride:y * stride + pixbuf.get_width() * channels]
            if channels == 3:
                row = b''.join(row[x:x + 3] + b'\xff'
                               for x in range(0, len(row), 3))
            rows.append(row)
        return b''.join(rows)

    def test_a_texture_holds_the_pixels_the_pixbuf_held(self):
        for has_alpha in (True, False):
            with self.subTest(has_alpha=has_alpha):
                pixbuf = self._drawn(has_alpha)
                texture = image_tools.pixbuf_to_texture(pixbuf)
                self.assertEqual(texture.get_width(), pixbuf.get_width())
                self.assertEqual(texture.get_height(), pixbuf.get_height())
                self.assertEqual(self._downloaded(texture),
                                 self._expected(pixbuf))

    def test_the_texture_keeps_what_it_was_given(self):
        """It used to be handed the pixbuf's own pixels, so painting
        over the pixbuf painted over the texture."""
        pixbuf = self._drawn(True)
        texture = image_tools.pixbuf_to_texture(pixbuf)
        before = self._downloaded(texture)
        pixbuf.fill(0x000000ff)
        self.assertEqual(self._downloaded(texture), before)


class CombinePixbufsTest(MComixTest):

    """Two pages copied into the one image a spread makes.

    Only the clipboard asks for this, and it asks with the pages at the
    size they came in at rather than the size they are shown at, so two
    scans of different heights are the usual case rather than a corner.
    It also asks along whichever axis the view distributes the pages on,
    which a quarter turn of the view changes from the width to the
    height.
    """

    def _solid(self, width, height, colour, has_alpha=False):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, has_alpha,
                                      8, width, height)
        pixbuf.fill(colour)
        return pixbuf

    def _pixel(self, pixbuf, x, y):
        channels = pixbuf.get_n_channels()
        offset = y * pixbuf.get_rowstride() + x * channels
        return tuple(pixbuf.get_pixels()[offset:offset + channels])

    #: Opaque red and opaque green, as Pixbuf.fill() takes them.
    RED = 0xFF0000FF
    GREEN = 0x00FF00FF

    def test_the_first_page_goes_on_the_left(self):
        combined = image_tools.combine_pixbufs(
            self._solid(4, 6, self.RED), self._solid(4, 6, self.GREEN))
        self.assertEqual((8, 6),
                         (combined.get_width(), combined.get_height()))
        self.assertEqual((255, 0, 0), self._pixel(combined, 1, 1))
        self.assertEqual((0, 255, 0), self._pixel(combined, 5, 1))

    def test_the_first_page_goes_on_top_along_the_height(self):
        """A view turned by a quarter turn stacks the two pages, and asks
        for them stacked the same way."""
        combined = image_tools.combine_pixbufs(
            self._solid(6, 4, self.RED), self._solid(6, 4, self.GREEN),
            constants.PageAxis.HEIGHT)
        self.assertEqual((6, 8),
                         (combined.get_width(), combined.get_height()))
        self.assertEqual((255, 0, 0), self._pixel(combined, 1, 1))
        self.assertEqual((0, 255, 0), self._pixel(combined, 1, 5))

    def test_what_neither_page_covers_is_filled(self):
        """The result is as tall as the taller page, so the shorter one's
        column has pixels below it that no copy_area() writes.
        GdkPixbuf.Pixbuf.new() does not clear the buffer it allocates, so
        what was there was undefined - black on this machine, but not
        promised to be anything."""
        combined = image_tools.combine_pixbufs(
            self._solid(4, 3, self.RED), self._solid(4, 6, self.GREEN))
        self.assertEqual((8, 6),
                         (combined.get_width(), combined.get_height()))
        self.assertEqual((255, 0, 0), self._pixel(combined, 1, 1),
                         'the short page is not where it should be')
        self.assertEqual((255, 255, 255), self._pixel(combined, 1, 5),
                         'the gap below the short page was left undefined')

    def test_what_neither_page_covers_is_filled_when_stacked(self):
        """The same gap, on the axis the pages are not distributed on."""
        combined = image_tools.combine_pixbufs(
            self._solid(3, 4, self.RED), self._solid(6, 4, self.GREEN),
            constants.PageAxis.HEIGHT)
        self.assertEqual((6, 8),
                         (combined.get_width(), combined.get_height()))
        self.assertEqual((255, 0, 0), self._pixel(combined, 1, 1),
                         'the narrow page is not where it should be')
        self.assertEqual((255, 255, 255), self._pixel(combined, 5, 1),
                         'the gap beside the narrow page was left undefined')

    def test_the_gap_is_transparent_where_there_is_an_alpha_channel(self):
        """A page with transparency in it is copied onto a pixbuf that has
        somewhere to put it, and then the gap can be transparent rather
        than a colour the pages never had."""
        combined = image_tools.combine_pixbufs(
            self._solid(4, 3, self.RED, has_alpha=True),
            self._solid(4, 6, self.GREEN, has_alpha=True))
        self.assertTrue(combined.get_has_alpha())
        self.assertEqual((255, 255, 255, 0), self._pixel(combined, 1, 5))

    def test_one_page_with_an_alpha_channel_is_enough_to_keep_it(self):
        combined = image_tools.combine_pixbufs(
            self._solid(4, 6, self.RED, has_alpha=True),
            self._solid(4, 6, self.GREEN))
        self.assertTrue(combined.get_has_alpha(),
                        'the transparency of the first page was dropped')

class RgbaTest(unittest.TestCase):

    """Colours built with rgba() carry the components they were given."""

    def test_the_colour_constants_are_black_and_white(self):
        # Built as Gdk.RGBA(0.0, 0.0, 0.0, 1.0), both were transparent
        # black on PyGObject 3.50 and earlier, which ignores the arguments.
        self.assertEqual('rgb(0,0,0)', image_tools.RGBA_BLACK.to_string())
        self.assertEqual('rgb(255,255,255)', image_tools.RGBA_WHITE.to_string())

    def test_every_component_is_the_one_given(self):
        colour = image_tools.rgba(0.25, 0.5, 0.75, 0.5)
        self.assertEqual([0.25, 0.5, 0.75, 0.5],
                         [colour.red, colour.green, colour.blue, colour.alpha])

    def test_a_colour_is_opaque_unless_said_otherwise(self):
        self.assertEqual(1.0, image_tools.rgba(0.1, 0.2, 0.3).alpha)


# vim: expandtab:sw=4:ts=4


class _Format:

    """Enough of a GdkPixbuf.PixbufFormat for get_supported_formats()."""

    def __init__(self, name, mime_types, extensions, disabled=False):
        self._answers = name, mime_types, extensions
        self._disabled = disabled

    def get_name(self):
        return self._answers[0]

    def get_mime_types(self):
        return self._answers[1]

    def get_extensions(self):
        return self._answers[2]

    def is_disabled(self):
        return self._disabled


class SupportedFormatsTest(MComixTest):

    def _gdk_formats(self, *formats):
        """The formats get_supported_formats() makes of gdk-pixbuf
        offering <formats>, leaving out what Pillow offers."""
        with unittest.mock.patch.object(GdkPixbuf.Pixbuf, 'get_formats',
                                        return_value=list(formats)), \
                unittest.mock.patch.object(Image, 'MIME', {}), \
                unittest.mock.patch.object(Image, 'EXTENSION', {}), \
                unittest.mock.patch.object(Image, 'init'):
            return image_tools.get_supported_formats.__wrapped__()

    def test_a_format_filed_under_no_extension_is_not_offered(self):
        """gdk-pixbuf 2.44 offers its legacy XPM loader with a mime type
        and no extension, beside the XPM loader that has one, and the
        file chooser listed "LEGACY-XPM images" as a format of its own."""
        formats = self._gdk_formats(
            _Format('legacy-xpm', ['image/x-xpixmap'], []),
            _Format('xpm', ['image/x-xpixmap'], ['xpm']))
        self.assertEqual(formats, {'XPM': ({'image/x-xpixmap'}, {'xpm'})})

    def test_a_disabled_format_is_not_offered(self):
        formats = self._gdk_formats(
            _Format('png', ['image/png'], ['png'], disabled=True))
        self.assertEqual(formats, {})


class EdgeColourTest(MComixTest):

    """The colour of the paper, which the dynamic background is painted
    in: the commonest colour of the group of near shades that covers the
    most of the two outer edges."""

    def _page(self, *rows):
        """A page one pixel wide, of (count, colour) runs top to bottom;
        both of its edges are that one column."""
        colours = [colour for count, colour in rows for _ in range(count)]
        image = Image.new('RGB', (1, len(colours)))
        image.putdata(colours)
        return image_tools.pil_to_pixbuf(image)

    def _expect(self, colour, answer):
        self.assertEqual([component / 255.0 for component in colour] + [1.0],
                         answer)

    def test_no_page_is_black(self):
        self.assertEqual([0.0, 0.0, 0.0, 1.0],
                         image_tools.get_most_common_edge_colour([]))

    def test_one_colour_is_that_colour(self):
        self._expect((250, 245, 240), image_tools.get_most_common_edge_colour(
            self._page((10, (250, 245, 240)))))

    def test_near_shades_are_counted_together(self):
        """Three greys a shade apart outnumber the one red that is
        commoner than any of them alone."""
        page = self._page((4, (201, 201, 201)), (3, (199, 200, 200)),
                          (3, (202, 199, 200)), (5, (200, 30, 30)))
        self._expect((201, 201, 201),
                     image_tools.get_most_common_edge_colour(page))

    def test_a_group_is_counted_whole_whatever_lies_between_its_shades(self):
        """Sorted by colour, a shade of another group can fall between
        two of one group's; the group was then counted in two halves and
        lost to a smaller one."""
        page = self._page((3, (186, 0, 0)), (4, (187, 100, 0)),
                          (3, (188, 0, 0)))
        self._expect((186, 0, 0), image_tools.get_most_common_edge_colour(page))

    def test_two_pages_are_read_at_their_outer_edges(self):
        white = self._page((10, (255, 255, 255)))
        black = self._page((10, (0, 0, 0)))
        wide = Image.new('RGB', (10, 10), (0, 0, 0))
        wide.paste((255, 255, 255), (0, 0, 2, 10))
        left = image_tools.pil_to_pixbuf(wide)
        self._expect((255, 255, 255),
                     image_tools.get_most_common_edge_colour((left, white)))
        self._expect((0, 0, 0),
                     image_tools.get_most_common_edge_colour((black, black)))


class RawExifProfileTest(MComixTest):

    """The orientation ImageMagick writes into a PNG as a text chunk,
    "Raw profile type exif", in hex, rather than as an eXIf chunk."""

    @staticmethod
    def _profile(orientation=6, header='exif', size=None, hexdata=None):
        exif = Image.Exif()
        exif[0x0112] = orientation
        data = exif.tobytes()
        return '\n%s\n%8d\n%s\n' % (
            header, len(data) if size is None else size,
            data.hex() if hexdata is None else hexdata)

    def _pixbuf(self, profile):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 2)
        pixbuf.set_option('tEXt::Raw profile type exif', profile)
        return pixbuf

    def test_the_turn_is_read_out_of_the_profile(self):
        self.assertEqual(90, image_tools.get_implied_rotation(
            self._pixbuf(self._profile(6))))
        self.assertEqual(270, image_tools.get_implied_rotation(
            self._pixbuf(self._profile(8))))

    def test_a_profile_that_does_not_hold_up_turns_nothing(self):
        for name, profile in (
                ('another header', self._profile(header='iptc')),
                ('a size that does not match', self._profile(size=3)),
                ('something other than hex', self._profile(hexdata='xyz')),
                ('too few lines', '\nexif\n')):
            with self.subTest(name):
                self.assertEqual(0, image_tools.get_implied_rotation(
                    self._pixbuf(profile)))
