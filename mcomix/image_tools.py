"""image_tools.py - Various image manipulations."""

import operator
from gi.repository import GLib, GdkPixbuf, Gdk, Gtk
import PIL
from PIL import Image
from PIL import ImageEnhance
from PIL import ImageOps
from io import BytesIO

from mcomix.preferences import prefs
from mcomix import constants
from mcomix import log
from mcomix import tools
from mcomix.i18n import _

PIL_VERSION = ('Pillow', PIL.__version__)

# Unfortunately gdk_pixbuf_version is not exported, so show the GTK+ version instead.
log.info(f'GDK version: {GdkPixbuf.PIXBUF_VERSION}, GTK+: {Gtk.get_major_version()}.{Gtk.get_minor_version()}, GLib: {GLib.MAJOR_VERSION}.{GLib.MINOR_VERSION}')
log.info('PIL version: %s [%s]', PIL_VERSION[0], PIL_VERSION[1])

# Fallback pixbuf for missing images.
MISSING_IMAGE_ICON = None

# 24 pixels is what Gtk.IconSize.LARGE_TOOLBAR stood for.
MISSING_IMAGE_ICON = Gtk.IconTheme.get_default().load_icon('image-missing', 24, 0)
assert MISSING_IMAGE_ICON

#: Colours are Gdk.RGBA components throughout: four floats between 0 and 1.
RGBA_BLACK = Gdk.RGBA(0.0, 0.0, 0.0, 1.0)
RGBA_WHITE = Gdk.RGBA(1.0, 1.0, 1.0, 1.0)


def axis_to_gdkpixbuf_flip_horizontal(i):
    return (True, False)[i]

def angle_to_gdkpixbuf_rotation(deg):
    if deg == 0:
        return GdkPixbuf.PixbufRotation.NONE
    elif deg == 90:
        return GdkPixbuf.PixbufRotation.CLOCKWISE
    elif deg == 180:
        return GdkPixbuf.PixbufRotation.UPSIDEDOWN
    elif deg == 270:
        return GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE
    raise ValueError("illegal angle: " + str(deg))

def rotate_pixbuf(src, rotation):
    return src if rotation == 0 else src.rotate_simple(angle_to_gdkpixbuf_rotation(rotation))

def flip_pixbuf(src, axis):
    return src.flip(horizontal=axis_to_gdkpixbuf_flip_horizontal(axis))

def get_fitting_size(source_size, target_size,
                     keep_ratio=True, scale_up=False):
    """ Return a scaled version of <source_size>
    small enough to fit in <target_size>.

    Both <source_size> and <target_size>
    must be (width, height) tuples.

    If <keep_ratio> is True, aspect ratio is kept.

    If <scale_up> is True, <source_size> is scaled up
    when smaller than <target_size>.
    """
    width, height = target_size
    src_width, src_height = source_size
    if not scale_up and src_width <= width and src_height <= height:
        width, height = src_width, src_height
    else:
        if keep_ratio:
            if float(src_width) / width > float(src_height) / height:
                height = int(max(src_height * width / src_width, 1))
            else:
                width = int(max(src_width * height / src_height, 1))
    return (width, height)

def fit_pixbuf_to_rectangle(src, rect, rotation):
    return fit_in_rectangle(src, rect[0], rect[1],
                            rotation=rotation,
                            keep_ratio=False,
                            scale_up=True)

def fit_in_rectangle(src, width, height, keep_ratio=True, scale_up=False, rotation=0, scaling_quality=None):
    """Scale (and return) a pixbuf so that it fits in a rectangle with
    dimensions <width> x <height>. A negative <width> or <height>
    means an unbounded dimension - both cannot be negative.

    If <rotation> is 90, 180 or 270 we rotate <src> first so that the
    rotated pixbuf is fitted in the rectangle.

    Unless <scale_up> is True we don't stretch images smaller than the
    given rectangle.

    If <keep_ratio> is True, the image ratio is kept, and the result
    dimensions may be smaller than the target dimensions.

    If <src> has an alpha channel it gets a checkboard background.
    """
    # Normalize the angle, so callers can pass e.g. -90 or 450 as well.
    rotation %= 360

    # "Unbounded" really means "bounded to RENDER_SIZE_LIMIT" - for simplicity.
    # MComix would probably choke on larger images anyway.
    if width < 0:
        width = constants.RENDER_SIZE_LIMIT
    elif height < 0:
        height = constants.RENDER_SIZE_LIMIT
    width = max(width, 1)
    height = max(height, 1)

    if tools.rotation_swaps_axes(rotation):
        width, height = height, width

    if scaling_quality is None:
        scaling_quality = prefs['scaling quality']

    src_width = src.get_width()
    src_height = src.get_height()

    width, height = get_fitting_size((src_width, src_height),
                                     (width, height),
                                     keep_ratio=keep_ratio,
                                     scale_up=scale_up)

    if src.get_has_alpha():
        composite_color_args = get_composite_color_args(0
            if prefs['checkered bg for transparent images'] else 1)
        if width == src_width and height == src_height:
            # Using anything other than nearest interpolation will result in a
            # modified image if no resizing takes place (even if it's opaque).
            scaling_quality = GdkPixbuf.InterpType.NEAREST
        src = src.composite_color_simple(width, height, scaling_quality,
                                         255, *composite_color_args)
    elif width != src_width or height != src_height:
        src = src.scale_simple(width, height, scaling_quality)

    src = rotate_pixbuf(src, rotation)

    return src


def add_border(pixbuf, thickness, colour=0x000000FF):
    """Return a pixbuf from <pixbuf> with a <thickness> px border of
    <colour> added.
    """
    canvas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
        pixbuf.get_width() + thickness * 2,
        pixbuf.get_height() + thickness * 2)
    canvas.fill(colour)
    pixbuf.copy_area(0, 0, pixbuf.get_width(), pixbuf.get_height(),
        canvas, thickness, thickness)
    return canvas


def get_most_common_edge_colour(pixbufs, edge=2):
    """Return the most commonly occurring pixel value along the four edges
    of <pixbuf>. The return value is a sequence of Gdk.RGBA components,
    (r, g, b, a). If <pixbuf> is a tuple, the edges will be computed from
    both the left and the right image.

    Note: This could be done more cleanly with subpixbuf(), but that
    doesn't work as expected together with get_pixels().
    """

    def group_colors(colors, steps=10):
        """ This rounds a list of colors in C{colors} to the next nearest value,
        i.e. 128, 83, 10 becomes 130, 85, 10 with C{steps}=5. This compensates for
        dirty colors where no clear dominating color can be made out.

        @return: The color that appears most often in the prominent group."""

        # Start group
        group = (0, 0, 0)
        # List of (count, color) pairs, group contains most colors
        colors_in_prominent_group = []
        color_count_in_prominent_group = 0
        # List of (count, color) pairs, current color group
        colors_in_group = []
        color_count_in_group = 0

        for count, color in colors:

            # Round color
            rounded = [0] * len(color)
            for i, color_value in enumerate(color):
                if steps % 2 == 0:
                    middle = steps // 2
                else:
                    middle = steps // 2 + 1

                remainder = color_value % steps
                if remainder >= middle:
                    color_value = color_value + (steps - remainder)
                else:
                    color_value = color_value - remainder

                rounded[i] = min(255, max(0, color_value))

            # Change prominent group if necessary
            if rounded == group:
                # Color still fits in the previous color group
                colors_in_group.append((count, color))
                color_count_in_group += count
            else:
                # Color group changed, check if current group has more colors
                # than last group
                if color_count_in_group > color_count_in_prominent_group:
                    colors_in_prominent_group = colors_in_group
                    color_count_in_prominent_group = color_count_in_group

                group = rounded
                colors_in_group = [ (count, color) ]
                color_count_in_group = count

        # Cleanup if only one edge color group was found
        if color_count_in_group > color_count_in_prominent_group:
            colors_in_prominent_group = colors_in_group

        colors_in_prominent_group.sort(key=operator.itemgetter(0), reverse=True)
        # List is now sorted by color count, first color appears most often
        return colors_in_prominent_group[0][1]

    def get_edge_pixbuf(pixbuf, side, edge):
        """ Returns a pixbuf corresponding to the side passed in <side>.
        Valid sides are 'left', 'right', 'top', 'bottom'. """
        pixbuf = static_image(pixbuf)
        width = pixbuf.get_width()
        height = pixbuf.get_height()
        edge = min(edge, width, height)

        if side in ('left', 'right'):
            sub_width, sub_height = edge, height
        elif side in ('top', 'bottom'):
            sub_width, sub_height = width, edge
        else:
            assert False, 'Invalid edge side'

        subpix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,
                pixbuf.get_has_alpha(), 8, sub_width, sub_height)
        if side == 'left':
            pixbuf.copy_area(0, 0, edge, height, subpix, 0, 0)
        elif side == 'right':
            pixbuf.copy_area(width - edge, 0, edge, height, subpix, 0, 0)
        elif side == 'top':
            pixbuf.copy_area(0, 0, width, edge, subpix, 0, 0)
        else:
            pixbuf.copy_area(0, height - edge, width, edge, subpix, 0, 0)

        return subpix

    if not pixbufs:
        return [0.0, 0.0, 0.0, 1.0]

    if not isinstance(pixbufs, (tuple, list)):
        left_edge = get_edge_pixbuf(pixbufs, 'left', edge)
        right_edge = get_edge_pixbuf(pixbufs, 'right', edge)
    else:
        assert len(pixbufs) == 2, 'Expected two pages in list'
        left_edge = get_edge_pixbuf(pixbufs[0], 'left', edge)
        right_edge = get_edge_pixbuf(pixbufs[1], 'right', edge)

    # Find all edge colors. Color count is separate for all four edges
    ungrouped_colors = []
    for edge in (left_edge, right_edge):
        im = pixbuf_to_pil(edge)
        ungrouped_colors.extend(im.getcolors(im.size[0] * im.size[1]))

    # Sum up colors from all edges
    ungrouped_colors.sort(key=operator.itemgetter(1))
    most_used = group_colors(ungrouped_colors)[:3]
    return [component / 255.0 for component in most_used] + [1.0]

def pil_to_pixbuf(im, keep_orientation=False):
    """Return a pixbuf created from the PIL <im>."""
    if im.mode.startswith('RGB'):
        has_alpha = im.mode == 'RGBA'
    elif im.mode in ('LA', 'P'):
        has_alpha = True
    else:
        has_alpha = False
    target_mode = 'RGBA' if has_alpha else 'RGB'
    if im.mode != target_mode:
        im = im.convert(target_mode)
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(im.tobytes()), GdkPixbuf.Colorspace.RGB,
        has_alpha, 8,
        im.size[0], im.size[1],
        (4 if has_alpha else 3) * im.size[0]
    )
    if keep_orientation:
        # Keep orientation metadata.
        orientation = None
        exif = im.getexif()
        orientation = exif.get(274, None)
        if orientation is None:
            # Maybe it's a PNG? Try alternative method.
            orientation = _get_png_implied_rotation(im)
        if orientation is not None:
            setattr(pixbuf, 'orientation', str(orientation))
    return pixbuf

def pixbuf_to_pil(pixbuf):
    """Return a PIL image created from <pixbuf>."""
    dimensions = pixbuf.get_width(), pixbuf.get_height()
    stride = pixbuf.get_rowstride()
    pixels = pixbuf.get_pixels()
    mode = 'RGBA' if pixbuf.get_has_alpha() else 'RGB'
    im = Image.frombuffer(mode, dimensions, pixels, 'raw', mode, stride, 1)
    return im

def is_animation(pixbuf):
    return isinstance(pixbuf, GdkPixbuf.PixbufAnimation)

def static_image(pixbuf):
    """ Returns a non-animated version of the specified pixbuf. """
    if is_animation(pixbuf):
        return pixbuf.get_static_image()
    return pixbuf

def set_from_pixbuf(image, pixbuf):
    if is_animation(pixbuf):
        return image.set_from_animation(pixbuf)
    else:
        return image.set_from_pixbuf(pixbuf)

#: The providers load_pixbuf() tries, in order.
_PIXBUF_PROVIDERS = (constants.IMAGEIO_GDKPIXBUF, constants.IMAGEIO_PIL)

def load_pixbuf(path):
    """ Loads a pixbuf from a given image file. """
    pixbuf = None
    last_error = None
    # Asking get_image_info() which provider to prefer costs another pass
    # over the file - as much again as decoding it, where gdk-pixbuf's
    # loaders run sandboxed - and cannot change the outcome.  It puts PIL
    # first for exactly the files gdk-pixbuf could not identify, which are
    # the files gdk-pixbuf goes on to fail to load, handing them to PIL.
    for provider in _PIXBUF_PROVIDERS:
        try:
            # TODO use dynamic dispatch instead of "if" chain
            if provider == constants.IMAGEIO_GDKPIXBUF:
                if prefs['animation mode'] != constants.ANIMATION_DISABLED:
                    try:
                        pixbuf = GdkPixbuf.PixbufAnimation.new_from_file(path)
                        if pixbuf.is_static_image():
                            pixbuf = pixbuf.get_static_image()
                    except GLib.GError:
                        # NOTE: Broken JPEGs sometimes result in this exception.
                        # However, one may be able to load them using
                        # Gdk.pixbuf_new_from_file, so we need to continue.
                        pass
                if pixbuf is None:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            elif provider == constants.IMAGEIO_PIL:
                # TODO When using PIL, whether or how animations work is
                # currently undefined.
                im = Image.open(path)
                pixbuf = pil_to_pixbuf(im, keep_orientation=True)
            else:
                raise TypeError()
        except Exception as e:
            # current provider could not load image
            last_error = e
        if pixbuf is not None:
            # stop loop on success
            log.debug("provider %s succeeded in loading %s", provider, path)
            break
        log.debug("provider %s failed to load %s", provider, path)
    if pixbuf is None:
        # raising necessary because caller expects pixbuf to be not None
        raise last_error or TypeError()
    return pixbuf

def load_pixbuf_size(path, width, height):
    """ Loads a pixbuf from a given image file and scale it to fit
    inside (width, height). """
    # TODO similar to load_pixbuf, should be merged using callbacks etc.
    pixbuf = None
    last_error = None
    # Only the format and the dimensions are wanted here, and asking
    # get_image_info() for them means a gdk-pixbuf header query, which
    # costs as much again as the decode below where its loaders run
    # sandboxed.  The provider order it also returns cannot change the
    # outcome, for the reason load_pixbuf() gives.
    image_format, image_dimensions = get_image_header(path)
    for provider in _PIXBUF_PROVIDERS:
        try:
            # TODO use dynamic dispatch instead of "if" chain
            if provider == constants.IMAGEIO_GDKPIXBUF:
                # If we could not get the image info, still try to load
                # the image to let GdkPixbuf raise the appropriate exception.
                if (0, 0) == image_dimensions:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                # Work around GdkPixbuf bug: https://bugzilla.gnome.org/show_bug.cgi?id=735422
                # (currently https://gitlab.gnome.org/GNOME/gdk-pixbuf/issues/45)
                elif 'GIF' == image_format:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                else:
                    # Don't upscale if smaller than target dimensions!
                    image_width, image_height = image_dimensions
                    if image_width <= width and image_height <= height:
                        width, height = image_width, image_height
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, width, height)
            elif provider == constants.IMAGEIO_PIL:
                im = Image.open(path)
                im.draft(None, (width, height))
                pixbuf = pil_to_pixbuf(im, keep_orientation=True)
            else:
                raise TypeError()
        except Exception as e:
            # current provider could not load image
            last_error = e
        if pixbuf is not None:
            # stop loop on success
            log.debug("provider %s succeeded in loading %s at size %s", provider, path, (width, height))
            break
        log.debug("provider %s failed to load %s at size %s", provider, path, (width, height))
    if pixbuf is None:
        # raising necessary because caller expects pixbuf to be not None
        raise last_error or TypeError()
    return fit_in_rectangle(pixbuf, width, height, scaling_quality=GdkPixbuf.InterpType.BILINEAR)

def load_pixbuf_data(imgdata):
    """ Loads a pixbuf from the data passed in <imgdata>. """
    # TODO similar to load_pixbuf, should be merged using callbacks etc.
    pixbuf = None
    last_error = None
    for provider in (constants.IMAGEIO_GDKPIXBUF, constants.IMAGEIO_PIL):
        try:
            # TODO use dynamic dispatch instead of "if" chain
            if provider == constants.IMAGEIO_GDKPIXBUF:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(imgdata)
                loader.close()
                pixbuf = loader.get_pixbuf()
            elif provider == constants.IMAGEIO_PIL:
                pixbuf = pil_to_pixbuf(Image.open(BytesIO(imgdata)), keep_orientation=True)
            else:
                raise TypeError()
        except Exception as e:
            # current provider could not load image
            last_error = e
        if pixbuf is not None:
            # stop loop on success
            log.debug("provider %s succeeded in decoding %s bytes", provider, len(imgdata))
            break
        log.debug("provider %s failed to decode %s bytes", provider, len(imgdata))
    if pixbuf is None:
        # raising necessary because caller expects pixbuf to be not None
        raise last_error
    return pixbuf

def enhance(pixbuf, brightness=1.0, contrast=1.0, saturation=1.0,
  sharpness=1.0, autocontrast=False, invert_color=False):
    """Return a modified pixbuf from <pixbuf> where the enhancement operations
    corresponding to each argument has been performed. A value of 1.0 means
    no change. If <autocontrast> is True it overrides the <contrast> value,
    but only if the image mode is supported by ImageOps.autocontrast (i.e.
    it is L or RGB.)
    """
    im = pixbuf_to_pil(pixbuf)
    if brightness != 1.0:
        im = ImageEnhance.Brightness(im).enhance(brightness)
    if autocontrast and im.mode in ('L', 'RGB'):
        im = ImageOps.autocontrast(im, cutoff=0.1)
    elif contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if saturation != 1.0:
        im = ImageEnhance.Color(im).enhance(saturation)
    if sharpness != 1.0:
        im = ImageEnhance.Sharpness(im).enhance(sharpness)
    if invert_color:
        im = ImageOps.invert(im)
    return pil_to_pixbuf(im)

def _get_png_implied_rotation(pixbuf_or_image):
    """Same as <get_implied_rotation> for PNG files.

    Lookup for Exif data in the tEXt chunk.
    """
    if isinstance(pixbuf_or_image, GdkPixbuf.Pixbuf):
        raw_exif = pixbuf_or_image.get_option('tEXt::Raw profile type exif')
    elif isinstance(pixbuf_or_image, Image.Image):
        raw_exif = pixbuf_or_image.info.get('Raw profile type exif')
    else:
        raise ValueError()
    if raw_exif is None:
        return None
    exif_lines = raw_exif.split('\n')
    if len(exif_lines) < 4 or 'exif' != exif_lines[1]:
        # Not valid Exif data.
        return None
    size = int(exif_lines[2])
    try:
        data = bytes.fromhex(''.join(exif_lines[3:]))
    except ValueError:
        # Not valid hexadecimal content.
        return None
    if size != len(data):
        # Sizes should match.
        return None
    exif = Image.Exif()
    exif.load(data)
    orientation = exif.get(274, None) # Orientation tag
    if orientation is not None:
        orientation = str(orientation)
    return orientation

#: Exif orientation tag, and the rotation each of its values implies.
_EXIF_ORIENTATION_TAG = 274
_IMPLIED_ROTATION = {'3': 180, '6': 90, '8': 270}

def _implied_rotation(orientation: object) -> int:
    """Return the rotation in degrees implied by an Exif <orientation>."""
    return _IMPLIED_ROTATION.get(str(orientation), 0)

def get_implied_rotation(pixbuf):
    """Return the implied rotation in degrees: 0, 90, 180, or 270.

    The implied rotation is the angle (in degrees) that the raw pixbuf should
    be rotated in order to be displayed "correctly". E.g. a photograph taken
    by a camera that is held sideways might store this fact in its Exif data,
    and the pixbuf loader will set the orientation option correspondingly.
    """
    pixbuf = static_image(pixbuf)
    orientation = getattr(pixbuf, 'orientation', None)
    if orientation is None:
        orientation = pixbuf.get_option('orientation')
    if orientation is None:
        # Maybe it's a PNG? Try alternative method.
        orientation = _get_png_implied_rotation(pixbuf)
    return _implied_rotation(orientation)

def get_implied_rotation_from_file(path: str) -> int:
    """Same as <get_implied_rotation>, for an image that has not been loaded.

    Only the image's header is read; the image itself is not decoded.
    """
    try:
        with Image.open(path) as image:
            orientation = image.getexif().get(_EXIF_ORIENTATION_TAG)
            if orientation is None:
                orientation = _get_png_implied_rotation(image)
    except Exception:
        return 0
    return _implied_rotation(orientation)

def get_image_header(path: str) -> tuple[str, tuple[int, int]]:
    """Return the (format, (width, height)) of the image at <path>
    without decoding it.

    get_image_info() answers this as well, but by way of gdk-pixbuf, whose
    header query costs as much as decoding the whole image where its
    loaders run sandboxed.  This gets asked about pages that are only
    being passed over, so read the header with PIL, and keep gdk-pixbuf
    for the files PIL cannot identify.
    """
    try:
        with Image.open(path) as image:
            if image.format is not None:
                return image.format, image.size
    except Exception:
        pass
    image_format, image_dimensions, _providers = get_image_info(path)
    return image_format, image_dimensions

def get_image_size(path: str) -> tuple[int, int]:
    """Return the (width, height) of the image at <path> without decoding it."""
    return get_image_header(path)[1]


def get_size_rotation(width, height):
    """ Determines the rotation to be applied.
    Returns the degree of rotation (0, 90, 180, 270). """

    if width != height:
        arp = prefs['auto rotate depending on size']
        if height > width:
            if arp == constants.AUTOROTATE_HEIGHT_90:
                return 90
            elif arp == constants.AUTOROTATE_HEIGHT_270:
                return 270
        else: # width > height
            if arp == constants.AUTOROTATE_WIDTH_90:
                return 90
            elif arp == constants.AUTOROTATE_WIDTH_270:
                return 270
    return 0

def combine_pixbufs( pixbuf1, pixbuf2, are_in_manga_mode ):
    if are_in_manga_mode:
        r_source_pixbuf = pixbuf1
        l_source_pixbuf = pixbuf2
    else:
        l_source_pixbuf = pixbuf1
        r_source_pixbuf = pixbuf2

    has_alpha = False

    if l_source_pixbuf.get_property( 'has-alpha' ) or \
       r_source_pixbuf.get_property( 'has-alpha' ):
        has_alpha = True

    bits_per_sample = 8

    l_source_pixbuf_width = l_source_pixbuf.get_property( 'width' )
    r_source_pixbuf_width = r_source_pixbuf.get_property( 'width' )

    l_source_pixbuf_height = l_source_pixbuf.get_property( 'height' )
    r_source_pixbuf_height = r_source_pixbuf.get_property( 'height' )

    new_width = l_source_pixbuf_width + r_source_pixbuf_width

    new_height = max( l_source_pixbuf_height, r_source_pixbuf_height )

    new_pix_buf = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                       has_alpha=has_alpha,
                                       bits_per_sample=bits_per_sample,
                                       width=new_width, height=new_height)

    l_source_pixbuf.copy_area( 0, 0, l_source_pixbuf_width,
                                     l_source_pixbuf_height,
                                     new_pix_buf, 0, 0 )

    r_source_pixbuf.copy_area( 0, 0, r_source_pixbuf_width,
                                     r_source_pixbuf_height,
                                     new_pix_buf, l_source_pixbuf_width, 0 )

    return new_pix_buf

def is_image_file(path):
    """Return True if the file at <path> is an image file recognized by PyGTK.
    """
    return _SUPPORTED_IMAGE_REGEX.search(path) is not None

def convert_rgb16list_to_rgba8int(c):
    return 0x000000FF | (c[0] >> 8 << 24) | (c[1] >> 8 << 16) | (c[2] >> 8 << 8)

def rgb_to_y_601(colour):
    """Return the luma of <colour>, given as Gdk.RGBA components."""
    return colour[0] * 0.299 + colour[1] * 0.587 + colour[2] * 0.114

def text_color_for_background_color(bgcolour):
    """Return the text colour that reads best on <bgcolour>."""
    return RGBA_BLACK if rgb_to_y_601(bgcolour) >= 0.5 else RGBA_WHITE

def get_composite_color_args(variant):
    return ((8, 0x777777, 0x999999), (1024, 0xFFFFFF, 0xFFFFFF))[variant]

def get_image_info(path):
    """Return information about and select preferred providers for loading
    the image specified by C{path}. The result is a tuple
    C{(format, (width, height), providers)}.
    """
    image_format = None
    image_dimensions = None
    providers = ()
    try:
        gdk_image_info = GdkPixbuf.Pixbuf.get_file_info(path)
    except Exception:
        gdk_image_info = None

    if gdk_image_info is not None and gdk_image_info[0] is not None:
        image_format = gdk_image_info[0].get_name().upper()
        image_dimensions = gdk_image_info[1], gdk_image_info[2]
        # Prefer loading via GDK/Pixbuf if Gdk.pixbuf_get_file_info appears
        # to be able to handle this path.
        providers = (constants.IMAGEIO_GDKPIXBUF, constants.IMAGEIO_PIL)
    else:
        try:
            im = Image.open(path)
            image_format = im.format
            image_dimensions = im.size
            providers = (constants.IMAGEIO_PIL, constants.IMAGEIO_GDKPIXBUF)
        except IOError:
            # If the file cannot be found, or the image
            # cannot be opened and identified.
            pass
    if image_format is None:
        image_format = _('Unknown filetype')
        image_dimensions = (0, 0)
        # Nothing could identify the file, but let the loaders try anyway,
        # so that they raise a meaningful error rather than the caller
        # having to make one up.
        providers = (constants.IMAGEIO_GDKPIXBUF, constants.IMAGEIO_PIL)
    return (image_format, image_dimensions, providers)

def get_supported_formats():
    global _SUPPORTED_IMAGE_FORMATS
    if _SUPPORTED_IMAGE_FORMATS is None:

        # Step 1: Collect PIL formats
        # Make sure all supported formats are registered.
        Image.init()
        # Not all PIL formats register a mime type,
        # fill in the blanks ourselves.
        supported_formats_pil = {
            'BMP': (['image/bmp', 'image/x-bmp', 'image/x-MS-bmp'], []),
            'ICO': (['image/x-icon', 'image/x-ico', 'image/x-win-bitmap'], []),
            'PCX': (['image/x-pcx'], []),
            'PPM': (['image/x-portable-pixmap'], []),
            'TGA': (['image/x-tga'], []),
        }
        for name, mime in list(Image.MIME.items()):
            mime_types, extensions = supported_formats_pil.get(name, ([], []))
            supported_formats_pil[name] = mime_types + [mime], extensions
        for ext, name in list(Image.EXTENSION.items()):
            assert '.' == ext[0]
            mime_types, extensions = supported_formats_pil.get(name, ([], []))
            supported_formats_pil[name] = mime_types, extensions + [ext[1:]]
        # Remove formats with no mime type or extension.
        for name in list(supported_formats_pil.keys()):
            mime_types, extensions = supported_formats_pil[name]
            if not mime_types or not extensions:
                del supported_formats_pil[name]
        # Remove archives/videos formats.
        for name in (
            'MPEG',
            'PDF',
        ):
            if name in supported_formats_pil:
                del supported_formats_pil[name]

        # Step 2: Collect GDK Pixbuf formats
        supported_formats_gdk = {}
        for format in GdkPixbuf.Pixbuf.get_formats():
            name = format.get_name().upper()
            if name in supported_formats_gdk:
                # The list of supported formats can sometimes contain duplicated entries
                continue

            supported_formats_gdk[name] = (
                format.get_mime_types(),
                format.get_extensions(),
            )

        # Step 3: merge format collections
        supported_formats = {}
        for provider in (supported_formats_gdk, supported_formats_pil):
            for name in list(provider.keys()):
                mime_types, extentions = provider[name]
                new_name = name.upper()
                new_mime_types, new_extensions = supported_formats.get( \
                    new_name, (set(), set()))
                new_mime_types.update([x.lower() for x in mime_types])
                new_extensions.update([x.lower() for x in extentions])
                supported_formats[new_name] = (new_mime_types, new_extensions)

        _SUPPORTED_IMAGE_FORMATS = supported_formats
    return _SUPPORTED_IMAGE_FORMATS

_SUPPORTED_IMAGE_FORMATS = None
# Set supported image extensions regexp from list of supported formats.
# Only used internally.
_SUPPORTED_IMAGE_REGEX = tools.formats_to_regex(get_supported_formats())
log.debug("_SUPPORTED_IMAGE_REGEX='%s'", _SUPPORTED_IMAGE_REGEX.pattern)

# vim: expandtab:sw=4:ts=4
