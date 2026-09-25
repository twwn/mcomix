"""image_tools.py - Various image manipulations."""

import functools
import operator
import os
from gi.repository import GLib, GdkPixbuf, Gdk, Gtk
import PIL
from PIL import Image
from PIL import ImageDraw
from PIL import ImageEnhance
from PIL import ImageOps
from io import BytesIO

from mcomix.preferences import prefs
from mcomix import constants
from mcomix import log
from mcomix import tools
from mcomix.i18n import _

from collections.abc import Callable, Sequence
from typing import Any

PIL_VERSION = ('Pillow', PIL.__version__)

# Unfortunately gdk_pixbuf_version is not exported, so show the GTK+ version instead.
log.info(f'GDK version: {GdkPixbuf.PIXBUF_VERSION}, GTK+: {Gtk.get_major_version()}.{Gtk.get_minor_version()}, GLib: {GLib.MAJOR_VERSION}.{GLib.MINOR_VERSION}')
log.info('PIL version: %s [%s]', PIL_VERSION[0], PIL_VERSION[1])

#: The attribute that marks a pixbuf as missing_image_icon()'s.
MISSING_IMAGE = 'mcomix_missing_image'

#: A blank page with a warning sign on it, drawn for MComix.
_MISSING_IMAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'images', 'missing-image.svg')

#: The width and height the SVG is drawn at, which is what a page that
#: would not load is read as when nothing says how large it is shown.
_MISSING_PAGE_SIZE = (134, 200)


def missing_page() -> GdkPixbuf.Pixbuf:
    """What a page that would not load is read as.

    Whatever shows it draws it again at its own size - the main window,
    the thumbnails - so this one is only what is handed on as the page
    itself, to the clipboard or the lens: the picture at the size it was
    designed at rather than at the size of an icon.
    """
    return missing_image_icon(*_MISSING_PAGE_SIZE)


def missing_image_icon(width: int, height: int) -> GdkPixbuf.Pixbuf:
    """The pixbuf shown in place of an image that would not load, as
    large as fits in <width> x <height> pixels.

    It is drawn from an SVG at the size it is shown at, since a cover
    or a thumbnail is many times larger than an icon, and an icon
    scaled up to fill it comes out blurred.  Every one is marked, so
    that is_missing_image() knows it wherever it has been handed.
    """
    pixbuf = _draw_missing_image(width, height)
    setattr(pixbuf, MISSING_IMAGE, True)
    return pixbuf


# Bounded, because each library cover size and each thumbnail size asks
# for one of its own, and one the size of a large cover is megabytes.
@functools.lru_cache(maxsize=8)
def _draw_missing_image(width: int, height: int) -> GdkPixbuf.Pixbuf:
    """missing_image_icon(), drawn once for each size."""
    try:
        drawn = GdkPixbuf.Pixbuf.new_from_file_at_size(_MISSING_IMAGE_FILE,
                                                       width, height)
        if drawn is not None:
            return drawn
    except GLib.Error as error:
        # A gdk-pixbuf built without an SVG loader.
        log.debug('Could not draw %s: %s', _MISSING_IMAGE_FILE, error.message)
    # The theme's icon is built on the first call rather than at import:
    # GTK4 looks icon themes up per display, and there is no display yet
    # while this module is being imported.
    from mcomix import icons
    size = min(width, height)
    try:
        icon = icons.load_pixbuf('image-missing', size)
    except GLib.Error:
        # The theme's icon is an SVG as well.
        icon = None
    # A theme that keeps its icons in a GResource has no file to load
    # one from, and a blank square is still something to draw.
    icon = icon or GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                        size, size)
    # Pixbuf.new() answers with nothing only when the allocation fails,
    # and a square the size of a cover will not be what runs out.
    assert icon is not None
    return icon


# Bounded, as missing_image_icon() is: each thumbnail size asks for one.
@functools.lru_cache(maxsize=8)
def locked_image_icon(size: int) -> GdkPixbuf.Pixbuf:
    """The pixbuf shown in place of the cover of an encrypted archive,
    which is not opened to make one without its password, <size>
    pixels square.

    A padlock in dark grey on a light disc, drawn at the size of the
    thumbnail it stands for: drawn at 64 pixels, it was scaled up into
    a blur by the library, whose covers are made at 500.  The theme has
    the padlock only as a symbolic icon, a shape GTK recolours for the
    widget it stands in; loaded as a pixbuf it keeps the theme's dark
    grey, which would all but vanish on the library's black, hence the
    disc.
    """
    from mcomix import icons
    size = max(1, size)
    # Drawn larger and scaled down, which smooths the edge ImageDraw
    # leaves jagged: four times over, or as near as 1024 pixels allow.
    over = max(1, min(4, 1024 // size))
    disc = Image.new('RGBA', (size * over, size * over), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((0, 0, size * over - 1, size * over - 1),
                                 fill=(255, 255, 255, 230))
    disc = disc.resize((size, size), Image.Resampling.LANCZOS)
    lock = icons.load_pixbuf('changes-prevent-symbolic', size // 2)
    if lock is not None:
        shape = pixbuf_to_pil(lock).convert('RGBA')
        disc.paste((46, 52, 54, 255), ((size - shape.width) // 2,
                                       (size - shape.height) // 2),
                   mask=shape.getchannel('A'))
    return pil_to_pixbuf(disc)


def rgba(red: float, green: float, blue: float,
         alpha: float = 1.0) -> Gdk.RGBA:
    """The Gdk.RGBA of the components given, each between 0 and 1.

    Gdk.RGBA(red, green, blue, alpha) reads as the same thing, and is
    what PyGObject 3.56 builds.  But the floor MComix declares is 3.46,
    and PyGObject 3.46.0, 3.48.2 and 3.50.0 hand arguments to a boxed
    type's constructor to nothing, with a DeprecationWarning, so every
    colour built that way came out as transparent black.  Setting the
    fields one by one means the same on all of them.
    """
    colour = Gdk.RGBA()
    colour.red = red
    colour.green = green
    colour.blue = blue
    colour.alpha = alpha
    return colour


#: Colours are Gdk.RGBA components throughout: four floats between 0 and 1.
RGBA_BLACK = rgba(0.0, 0.0, 0.0, 1.0)
RGBA_WHITE = rgba(1.0, 1.0, 1.0, 1.0)


#: Which gdk-pixbuf rotation each quarter turn, clockwise in degrees, is.
_ROTATIONS = {
    0: GdkPixbuf.PixbufRotation.NONE,
    90: GdkPixbuf.PixbufRotation.CLOCKWISE,
    180: GdkPixbuf.PixbufRotation.UPSIDEDOWN,
    270: GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE,
}


def axis_to_gdkpixbuf_flip_horizontal(i: int) -> bool:
    """Whether flipping along axis <i> is a horizontal flip.

    <i> is a constants.PageAxis, and flipping a page along its width is
    what gdk-pixbuf calls flipping it horizontally.
    """
    return i == constants.PageAxis.WIDTH


def angle_to_gdkpixbuf_rotation(deg: int) -> GdkPixbuf.PixbufRotation:
    """Return the rotation gdk-pixbuf knows <deg> clockwise degrees by.

    Only the three quarter turns and no rotation at all: gdk-pixbuf
    rotates a pixbuf by moving pixels about and has nothing to offer for
    an angle that would have to interpolate.
    """
    try:
        return _ROTATIONS[deg]
    except KeyError:
        raise ValueError('illegal angle: %s' % deg) from None


def _allocated(pixbuf: GdkPixbuf.Pixbuf | None) -> GdkPixbuf.Pixbuf:
    """<pixbuf>, or a clear error where gdk-pixbuf answered with nothing.

    Allocating a pixbuf, rotating one and flipping one all answer with
    NULL when there is not room for the pixels, and every caller here
    goes on to use the result at once.  Saying so where it happens beats
    the attribute error on None that turns up a few lines later.
    """
    if pixbuf is None:
        raise MemoryError('gdk-pixbuf could not allocate the pixels')
    return pixbuf


def rotate_pixbuf(src: GdkPixbuf.Pixbuf, rotation: int) -> GdkPixbuf.Pixbuf:
    """Return <src> turned <rotation> degrees clockwise.

    <src> itself where there is nothing to turn, since a rotation of none
    would otherwise cost a copy of every page that is not rotated.
    """
    if rotation == 0:
        return src
    return _allocated(src.rotate_simple(angle_to_gdkpixbuf_rotation(rotation)))


def flip_pixbuf(src: GdkPixbuf.Pixbuf, axis: int) -> GdkPixbuf.Pixbuf:
    """Return <src> mirrored along <axis>, a constants.PageAxis."""
    return _allocated(
        src.flip(horizontal=axis_to_gdkpixbuf_flip_horizontal(axis)))


def get_fitting_size(source_size: Sequence[int], target_size: Sequence[int],
                     keep_ratio: bool = True,
                     scale_up: bool = False) -> tuple[int, int]:
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


def fit_pixbuf_to_rectangle(src: GdkPixbuf.Pixbuf, rect: Sequence[int],
                            rotation: int) -> GdkPixbuf.Pixbuf:
    """Return <src> turned <rotation> degrees and scaled to fill <rect>.

    Filling rather than fitting: the caller has already worked out the
    size it wants, from the aspect ratio among other things, so this is
    asked for exactly the rectangle it computed and neither keeps the
    ratio nor stops at the original size.
    """
    return fit_in_rectangle(src, rect[0], rect[1],
                            rotation=rotation,
                            keep_ratio=False,
                            scale_up=True)


def fit_in_rectangle(src: GdkPixbuf.Pixbuf, width: int, height: int,
                     keep_ratio: bool = True, scale_up: bool = False,
                     rotation: int = 0,
                     scaling_quality: GdkPixbuf.InterpType | None = None
                     ) -> GdkPixbuf.Pixbuf:
    """Scale (and return) a pixbuf so that it fits in a rectangle with
    dimensions <width> x <height>. A negative <width> or <height>
    means an unbounded dimension; both at once is a rectangle with no
    size to fit in, and raises ValueError. A side of zero is one pixel,
    which is the smallest rectangle there is rather than an error.

    If <rotation> is 90, 180 or 270 we rotate <src> first so that the
    rotated pixbuf is fitted in the rectangle.

    Unless <scale_up> is True we don't stretch images smaller than the
    given rectangle.

    If <keep_ratio> is True, the image ratio is kept, and the result
    dimensions may be smaller than the target dimensions.

    A pixbuf with an alpha channel is composited onto a background
    first - the grey chequerboard, or plain white, as the "checkered bg
    for transparent images" preference says - so what comes back is
    opaque either way.
    """
    # Normalize the angle, so callers can pass e.g. -90 or 450 as well.
    rotation %= 360

    if width < 0 and height < 0:
        # Unbounded in both directions is not a rectangle.  Bounding
        # only one side would leave the other to max() below, which
        # makes one pixel of it: a page quietly scaled to a line.
        raise ValueError('width and height cannot both be unbounded')

    # "Unbounded" really means "bounded to RENDER_SIZE_LIMIT" - for simplicity.
    # MComix would probably choke on larger images anyway.
    if width < 0:
        width = constants.RENDER_SIZE_LIMIT
    if height < 0:
        height = constants.RENDER_SIZE_LIMIT
    width = max(width, 1)
    height = max(height, 1)

    if tools.rotation_swaps_axes(rotation):
        width, height = height, width

    if scaling_quality is None:
        scaling_quality = scaling_quality_preference()

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
        src = _allocated(src.composite_color_simple(
            width, height, scaling_quality, 255, *composite_color_args))
    elif width != src_width or height != src_height:
        src = _allocated(src.scale_simple(width, height, scaling_quality))

    src = rotate_pixbuf(src, rotation)

    return src


def add_border(pixbuf: GdkPixbuf.Pixbuf, thickness: int,
               colour: int = 0x000000FF) -> GdkPixbuf.Pixbuf:
    """Return a pixbuf from <pixbuf> with a <thickness> px border of
    <colour> added.
    """
    canvas = _allocated(GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                             pixbuf.get_width() + thickness * 2,
                                             pixbuf.get_height() + thickness * 2))
    canvas.fill(colour)
    pixbuf.copy_area(0, 0, pixbuf.get_width(), pixbuf.get_height(),
                     canvas, thickness, thickness)
    return canvas


def get_most_common_edge_colour(pixbufs: GdkPixbuf.Pixbuf | Sequence[GdkPixbuf.Pixbuf],
                                edge: int = 2) -> list[float]:
    """The colour of the paper of <pixbufs>, as Gdk.RGBA components.

    This is where the dynamic background colour comes from, so what is
    wanted is the colour the page appears to fade into: it is read
    <edge> pixels deep down the two outer sides of what is on screen,
    the left and the right of a single page, or the left of the first
    of two and the right of the second.  The answer is (r, g, b, 1.0),
    each a float between 0 and 1, and black where there is no page at
    all.

    This could be done more cleanly with subpixbuf(), but that does not
    work as expected together with get_pixels().
    """

    def group_colors(colors: Sequence[tuple[int, Sequence[int]]],
                     steps: int = 10) -> Sequence[int]:
        """The commonest colour in <colors>, near shades counted as one.

        <colors> is (count, colour) pairs, the way Image.getcolors()
        counts them.  Each colour is rounded to the nearest multiple of
        <steps> - 128, 83, 10 becomes 130, 85, 10 at <steps> of 5 - and
        the colours that round alike make a group.  The answer is the
        commonest colour, unrounded, of the group whose colours cover
        the most pixels between them; ties go to whichever came first.

        Grouping is what lets a scanned margin answer with the grey it
        looks like, rather than with whichever of its hundred nearly
        equal greys happened to be counted once more than the rest.
        A group is every shade that rounds alike, not a run of
        neighbours in a list sorted by colour: two shades that round
        alike need not be neighbours there, and a shade of another
        group falling between them would count the group in pieces.
        """
        # Where a value exactly halfway rounds up, as it always has.
        middle = steps // 2 if steps % 2 == 0 else steps // 2 + 1

        def rounded(value: int) -> int:
            remainder = value % steps
            value += steps - remainder if remainder >= middle else -remainder
            return min(255, max(0, value))

        # Once per component value rather than once per component of
        # every colour: a noisy scan has thousands of them.
        table = [rounded(value) for value in range(256)]
        groups: dict[tuple[int, ...], list[tuple[int, Sequence[int]]]] = {}
        for count, color in colors:
            groups.setdefault(tuple([table[value] for value in color]),
                              []).append((count, color))
        prominent = max(groups.values(),
                        key=lambda members: sum(count for count, _c in members))
        return max(prominent, key=operator.itemgetter(0))[1]

    def get_edge_pixbuf(pixbuf: GdkPixbuf.Pixbuf, side: str,
                        edge: int) -> GdkPixbuf.Pixbuf:
        """The <edge> columns of <pixbuf> down its <side>, 'left' or
        'right'."""
        width = pixbuf.get_width()
        height = pixbuf.get_height()
        edge = min(edge, width, height)
        subpix = _allocated(GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,
                                                 pixbuf.get_has_alpha(), 8, edge, height))
        left = 0 if side == 'left' else width - edge
        pixbuf.copy_area(left, 0, edge, height, subpix, 0, 0)
        return subpix

    if not pixbufs:
        return [0.0, 0.0, 0.0, 1.0]

    if isinstance(pixbufs, GdkPixbuf.Pixbuf):
        left_edge = get_edge_pixbuf(pixbufs, 'left', edge)
        right_edge = get_edge_pixbuf(pixbufs, 'right', edge)
    else:
        assert len(pixbufs) == 2, 'Expected two pages in list'
        left_edge = get_edge_pixbuf(pixbufs[0], 'left', edge)
        right_edge = get_edge_pixbuf(pixbufs[1], 'right', edge)

    # Find all edge colors. Color count is separate for all four edges
    ungrouped_colors: list[tuple[int, Sequence[int]]] = []
    for edge_pixbuf in (left_edge, right_edge):
        im = pixbuf_to_pil(edge_pixbuf)
        for count, colour in im.getcolors(im.size[0] * im.size[1]) or ():
            # pixbuf_to_pil() always answers in RGB or RGBA, so a colour
            # is the tuple of components this counts on rather than the
            # single value a greyscale image would be counted in.
            assert not isinstance(colour, (int, float))
            ungrouped_colors.append((count, colour))

    # Sum up colors from all edges
    ungrouped_colors.sort(key=operator.itemgetter(1))
    most_used = group_colors(ungrouped_colors)[:3]
    return [component / 255.0 for component in most_used] + [1.0]


def _in_srgb(image: Image.Image) -> Image.Image:
    """<image> converted into sRGB from the colour profile it carries.

    Where glycin decodes for gdk-pixbuf, a picture with an embedded
    profile comes back converted into sRGB, and that is how a page is
    shown; PIL hands the stored numbers over as they are, so an Adobe
    RGB red of (200, 30, 30) read as (233, 24, 24) through one and
    (200, 30, 30) through the other.  A picture without a profile, or a
    PIL built without LittleCMS, is left as it is.  The Exif data goes
    along, since the orientation is read from it afterwards.
    """
    profile = image.info.get('icc_profile')
    if not profile:
        return image
    try:
        from PIL import ImageCms
    except ImportError:
        return image
    try:
        mode = 'RGBA' if 'A' in image.getbands() else 'RGB'
        converted = ImageCms.profileToProfile(
            image, BytesIO(profile), ImageCms.createProfile('sRGB'),
            outputMode=mode)
    except (ImageCms.PyCMSError, OSError, ValueError) as error:
        # A profile LittleCMS cannot read, or one that does not fit the
        # picture's mode.  ImageCms.PyCMSError is not an OSError, for
        # all that it wraps one.
        log.debug('Could not convert a picture into sRGB: %s', error)
        return image
    if converted is None:
        return image
    if 'exif' in image.info:
        converted.info['exif'] = image.info['exif']
    return converted


def pil_to_pixbuf(im: Image.Image,
                  keep_orientation: bool = False) -> GdkPixbuf.Pixbuf:
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


def pixbuf_to_pil(pixbuf: GdkPixbuf.Pixbuf) -> Image.Image:
    """Return a PIL image created from <pixbuf>."""
    dimensions = pixbuf.get_width(), pixbuf.get_height()
    stride = pixbuf.get_rowstride()
    pixels = pixbuf.get_pixels()
    mode = 'RGBA' if pixbuf.get_has_alpha() else 'RGB'
    im = Image.frombuffer(mode, dimensions, pixels, 'raw', mode, stride, 1)
    return im


def scaling_quality_preference() -> GdkPixbuf.InterpType:
    """How the scaling quality preference says pages should be scaled.

    The preference holds a plain number, because that is what survives a
    trip through the preferences file; every gdk-pixbuf call that scales
    wants the member it stands for.
    """
    return GdkPixbuf.InterpType(prefs['scaling quality'])


#: What load_pixbuf() writes the file a moving page came from under.
ANIMATION_PATH = 'animation_path'


def is_animation(pixbuf: GdkPixbuf.Pixbuf) -> bool:
    """Whether <pixbuf> is the still frame of a page that moves.

    GdkPixbuf.PixbufAnimation was an object of its own, and being one
    was the answer; GTK deprecated the whole of it in 4.10 with nothing
    in its place.  A moving page is the ordinary pixbuf of its first
    frame now, carrying the file the rest of them are read from.
    """
    return getattr(pixbuf, ANIMATION_PATH, None) is not None


def animation_path(pixbuf: GdkPixbuf.Pixbuf) -> "str | None":
    """The file the frames of <pixbuf> are read from, if it moves."""
    return getattr(pixbuf, ANIMATION_PATH, None)


def file_animates(path: str) -> bool:
    """Whether <path> holds more than one frame.

    Pillow answers from the header, which costs a few microseconds and
    is what MComix decodes animations with anyway.  What Pillow will not
    open at all is asked of glycin, which is the decoder gdk-pixbuf
    itself hands its loaders to.
    """
    try:
        with Image.open(path) as im:
            return bool(getattr(im, 'is_animated', False))
    except Exception:
        pass
    return _glycin_animates(path)


def is_missing_image(pixbuf: GdkPixbuf.Pixbuf) -> bool:
    """Whether <pixbuf> is what a page that would not load was read as."""
    return bool(getattr(pixbuf, MISSING_IMAGE, False))


def _glycin_animates(path: str) -> bool:
    """Whether glycin reads more than one frame out of <path>.

    A still image gives its one frame a delay of zero; an animated one
    says how long the frame lasts.  glycin ships with GTK on Linux and
    not at all on Windows, so a tree without it falls back on the
    deprecated GdkPixbuf.PixbufAnimation rather than losing the answer.
    """
    try:
        from gi.repository import Gio
        Gly = glycin()[0]
    except Exception:
        return _pixbuf_animates(path)
    try:
        image = Gly.Loader.new(Gio.File.new_for_path(path)).load()
        return bool(image.next_frame().get_delay() > 0)
    except Exception as error:
        log.debug('glycin will not read %s (%s)', path, error)
        return False


def _pixbuf_animates(path: str) -> bool:
    """Whether gdk-pixbuf reads more than one frame out of <path>.

    The last resort, for a tree with no glycin and a file Pillow will
    not open.  GdkPixbuf.PixbufAnimation is deprecated as of GTK 4.10.
    """
    try:
        animation = GdkPixbuf.PixbufAnimation.new_from_file(path)
    except GLib.GError:
        return False
    return animation is not None and not animation.is_static_image()


def glycin() -> tuple[Any, Any]:  # type: ignore[explicit-any]  # glycin is optional, so there is no Gly to name
    """The glycin modules, or raise if this tree has none.

    glycin ships with GTK on Linux, where it is what gdk-pixbuf hands
    its loaders to; the Windows build of GTK has none of it.
    """
    import gi
    gi.require_version('Gly', '2')
    gi.require_version('GlyGtk4', '2')
    from gi.repository import Gly, GlyGtk4
    return Gly, GlyGtk4


def pixbuf_to_texture(pixbuf: GdkPixbuf.Pixbuf) -> Gdk.Texture:
    """Return <pixbuf> as the Gdk.Texture GTK4 draws from.

    Gdk.Texture.new_for_pixbuf() is what this was, deprecated in GTK
    4.20 along with everything else that speaks in pixbufs; GTK's
    4-to-5 migration guide says the APIs "accepting or returning
    GdkPixbufs are being replaced by equivalent APIs using GdkTexture".
    The texture is built the way that call built it, out of the pixel
    format the pixbuf holds - always eight bits a sample, with or
    without alpha - and its rowstride, so a row that is padded out is
    still read correctly.

    read_pixel_bytes() copies the pixels, where the deprecated call
    handed the texture a reference to the pixbuf's own.  On a
    1600x2400 page that is 0.54ms against 0.002ms, measured; a page
    turn scales a pixbuf that size first, which costs 30.75ms, so the
    copy is under two per cent of one step the turn already takes.
    The texture therefore owns what it draws, and the caller may paint
    over the pixbuf afterwards.
    """
    memory_format = (Gdk.MemoryFormat.R8G8B8A8 if pixbuf.get_has_alpha()
                     else Gdk.MemoryFormat.R8G8B8)
    return Gdk.MemoryTexture.new(pixbuf.get_width(), pixbuf.get_height(),
                                 memory_format, pixbuf.read_pixel_bytes(),
                                 pixbuf.get_rowstride())


def pil_to_texture(im: Image.Image) -> Gdk.Texture:
    """Return the PIL image <im> as the Gdk.Texture GTK4 draws from."""
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGBA')
    has_alpha = im.mode == 'RGBA'
    memory_format = Gdk.MemoryFormat.R8G8B8A8 if has_alpha \
        else Gdk.MemoryFormat.R8G8B8
    width, height = im.size
    return Gdk.MemoryTexture.new(width, height, memory_format,
                                 GLib.Bytes.new(im.tobytes()),
                                 width * (4 if has_alpha else 3))


#: The providers load_pixbuf() tries, in order.
_PIXBUF_PROVIDERS = (constants.IMAGEIO_GDKPIXBUF, constants.IMAGEIO_PIL)


def _first_provider_that_loads(
        attempts: "Sequence[tuple[int, Callable[[], GdkPixbuf.Pixbuf | None]]]",
        subject: str) -> GdkPixbuf.Pixbuf:
    """The pixbuf the first of <attempts> that works produces.

    Each attempt pairs a provider from constants with the call that
    loads through it, and they are tried in order; <subject> says what
    is being loaded, for the log.  A provider that raises is passed
    over, and so is one that answers with nothing, which is what a
    gdk-pixbuf loader does when handed something it cannot read.

    When none of them worked the last exception is re-raised, because
    the callers all expect a pixbuf.  Where the failure left no
    exception behind - the loader that answered with nothing - the
    TypeError stands in for it.
    """
    last_error: "BaseException | None" = None
    for provider, load in attempts:
        try:
            pixbuf = load()
        except Exception as error:
            pixbuf, last_error = None, error
        if pixbuf is not None:
            log.debug('provider %s succeeded in loading %s', provider, subject)
            return pixbuf
        log.debug('provider %s failed to load %s', provider, subject)
    raise last_error or TypeError()


def load_pixbuf(path: str) -> GdkPixbuf.Pixbuf:
    """The whole picture at <path>, at the size it was stored at.

    gdk-pixbuf first and PIL after it, since between them they read more
    than either does alone; the last error is raised where neither could
    read the file.  A picture that animates carries the path it came
    from, because only its first frame is here and whoever draws the
    rest needs the file back.
    """
    # Asking get_image_info() which provider to prefer costs another pass
    # over the file - as much again as decoding it, where gdk-pixbuf's
    # loaders run sandboxed - and cannot change the outcome.  It puts PIL
    # first for exactly the files gdk-pixbuf could not identify, which are
    # the files gdk-pixbuf goes on to fail to load, handing them to PIL.
    def by_pil() -> GdkPixbuf.Pixbuf:
        # Whether or how animations work through PIL is undefined.
        return pil_to_pixbuf(_in_srgb(Image.open(path)),
                             keep_orientation=True)

    pixbuf = _first_provider_that_loads(
        ((constants.IMAGEIO_GDKPIXBUF,
          lambda: GdkPixbuf.Pixbuf.new_from_file(path)),
         (constants.IMAGEIO_PIL, by_pil)), path)
    if prefs['animation mode'] != constants.ANIMATION_DISABLED \
            and file_animates(path):
        # Whoever draws the frames needs the file back: what was loaded
        # here is the first of them.  See mcomix.animation.
        setattr(pixbuf, ANIMATION_PATH, path)
    return pixbuf


def load_pixbuf_size(path: str, width: int, height: int) -> GdkPixbuf.Pixbuf:
    """The picture at <path>, scaled to fit inside (<width>, <height>).

    Fitted rather than filled: the aspect ratio is kept, and a picture
    smaller than the box is left at its own size.  Both loaders are
    asked to do the scaling as they decode, which is what makes this
    cheaper than loading the whole picture and scaling it afterwards,
    and the result is fitted again at the end because neither of them
    promises the exact size asked for.

    A JPEG goes to PIL first.  Its draft() lets libjpeg decode at an
    eighth, a quarter or a half of the size, which gdk-pixbuf does too,
    but where gdk-pixbuf's loaders run sandboxed each call also pays
    for the sandbox: a thumbnail of a 1200x1800 page took 0.8 ms
    through PIL against 9-11 ms through gdk-pixbuf.  Everything else
    goes to gdk-pixbuf first, since draft() does nothing for a PNG and
    PIL then decodes the whole picture.
    """
    # A box with a zero side asks gdk-pixbuf for a scale it refuses -
    # "assertion 'width > 0 || width == -1' failed" - and then makes PIL
    # divide by it, so what came back was a ZeroDivisionError rather than
    # a picture.  Callers reach this with a widget that has not been
    # given its size yet.  Ask for the one pixel that fit_in_rectangle()
    # would have clamped it to anyway; a negative side still means
    # "unbounded" there, so leave those alone.
    if width == 0:
        width = 1
    if height == 0:
        height = 1
    # Only the format and the dimensions are wanted here, and asking
    # get_image_info() for them means a gdk-pixbuf header query, which
    # costs as much again as the decode below where its loaders run
    # sandboxed.  The provider order it also returns cannot change the
    # outcome, for the reason load_pixbuf() gives.
    image_format, image_dimensions = get_image_header(path)

    def by_gdk_pixbuf() -> "GdkPixbuf.Pixbuf | None":
        # gdk-pixbuf answers with nothing rather than raising for some
        # of what it cannot read, which is why this may be None.
        nonlocal width, height
        if (0, 0) == image_dimensions:
            # The header could not be read; let gdk-pixbuf load the file
            # anyway, so that it raises whatever is really wrong with it.
            return GdkPixbuf.Pixbuf.new_from_file(path)
        if image_format == 'GIF':
            # gdk-pixbuf scales a GIF while loading it to the wrong
            # thing: https://gitlab.gnome.org/GNOME/gdk-pixbuf/issues/45
            return GdkPixbuf.Pixbuf.new_from_file(path)
        image_width, image_height = image_dimensions
        if image_width <= width and image_height <= height:
            # Fit the box to the image rather than scaling the image up,
            # here and in the fit_in_rectangle() call below.
            width, height = image_width, image_height
        return GdkPixbuf.Pixbuf.new_from_file_at_size(path, width, height)

    def by_pil() -> GdkPixbuf.Pixbuf:
        image = Image.open(path)
        image.draft(None, (width, height))
        return pil_to_pixbuf(_in_srgb(image), keep_orientation=True)

    attempts = [(constants.IMAGEIO_GDKPIXBUF, by_gdk_pixbuf),
                (constants.IMAGEIO_PIL, by_pil)]
    if image_format == 'JPEG':
        attempts.reverse()
    pixbuf = _first_provider_that_loads(
        attempts, '%s at size %s' % (path, (width, height)))
    fitted = fit_in_rectangle(pixbuf, width, height,
                              scaling_quality=GdkPixbuf.InterpType.BILINEAR)
    if fitted is not pixbuf:
        # Scaling makes a new pixbuf, which knows nothing of the Exif
        # orientation the loader found; PIL's draft() nearly always
        # leaves a picture that still has to be scaled.
        orientation = getattr(pixbuf, 'orientation', None) \
            or pixbuf.get_option('orientation')
        if orientation is not None:
            setattr(fitted, 'orientation', orientation)
    return fitted


def load_pixbuf_data(imgdata: bytes) -> GdkPixbuf.Pixbuf:
    """The picture <imgdata> holds, for one that was never a file.

    The same two loaders in the same order as load_pixbuf(), fed from
    memory: an archive hands its pages over as bytes rather than
    unpacking them.  Nothing here looks for an animation, since there is
    no file for its later frames to be read out of.
    """
    def by_gdk_pixbuf() -> "GdkPixbuf.Pixbuf | None":
        loader = GdkPixbuf.PixbufLoader()
        loader.write(imgdata)
        loader.close()
        return loader.get_pixbuf()

    return _first_provider_that_loads(
        ((constants.IMAGEIO_GDKPIXBUF, by_gdk_pixbuf),
         (constants.IMAGEIO_PIL,
          lambda: pil_to_pixbuf(_in_srgb(Image.open(BytesIO(imgdata))),
                                keep_orientation=True))),
        '%s bytes' % len(imgdata))


def enhance(pixbuf: GdkPixbuf.Pixbuf, brightness: float = 1.0,
            contrast: float = 1.0, saturation: float = 1.0,
            sharpness: float = 1.0, autocontrast: bool = False,
            invert_color: bool = False) -> GdkPixbuf.Pixbuf:
    """Return a modified pixbuf from <pixbuf> where the enhancement operations
    corresponding to each argument has been performed. A value of 1.0 means
    no change. If <autocontrast> is True it overrides the <contrast> value.

    Transparency is kept as it is: ImageOps.autocontrast() and
    ImageOps.invert() take no image with an alpha channel, and
    invert() raises on one, so the colours are enhanced on their own.
    """
    im = pixbuf_to_pil(pixbuf)
    alpha = im.getchannel('A') if im.mode == 'RGBA' else None
    if alpha is not None:
        im = im.convert('RGB')
    if brightness != 1.0:
        im = ImageEnhance.Brightness(im).enhance(brightness)
    if autocontrast:
        im = ImageOps.autocontrast(im, cutoff=0.1)
    elif contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if saturation != 1.0:
        im = ImageEnhance.Color(im).enhance(saturation)
    if sharpness != 1.0:
        im = ImageEnhance.Sharpness(im).enhance(sharpness)
    if invert_color:
        im = ImageOps.invert(im)
    if alpha is not None:
        im.putalpha(alpha)
    return pil_to_pixbuf(im)


def _get_png_implied_rotation(
        pixbuf_or_image: GdkPixbuf.Pixbuf | Image.Image) -> str | None:
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
    if len(exif_lines) < 4 or exif_lines[1] != 'exif':
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
    raw_orientation = exif.get(_EXIF_ORIENTATION_TAG, None)
    return None if raw_orientation is None else str(raw_orientation)


#: Exif orientation tag, and the rotation each of its values implies.
_EXIF_ORIENTATION_TAG = 274
_IMPLIED_ROTATION = {'3': 180, '6': 90, '8': 270}


def _implied_rotation(orientation: object) -> int:
    """Return the rotation in degrees implied by an Exif <orientation>."""
    return _IMPLIED_ROTATION.get(str(orientation), 0)


def get_implied_rotation(pixbuf: GdkPixbuf.Pixbuf) -> int:
    """Return the implied rotation in degrees: 0, 90, 180, or 270.

    The implied rotation is the angle (in degrees) that the raw pixbuf should
    be rotated in order to be displayed "correctly". E.g. a photograph taken
    by a camera that is held sideways might store this fact in its Exif data,
    and the pixbuf loader will set the orientation option correspondingly.
    """
    orientation = getattr(pixbuf, 'orientation', None)
    if orientation is None:
        orientation = pixbuf.get_option('orientation')
    if orientation is None:
        # Maybe it's a PNG? Try alternative method.
        orientation = _get_png_implied_rotation(pixbuf)
    return _implied_rotation(orientation)


#: Set on a thumbnail that is stored upright - turned by its picture's
#: Exif orientation - rather than as the picture is in the file.  What
#: MComix stores is upright, as GNOME's and KDE's thumbnailers store
#: theirs; a thumbnail an older MComix stored is as in the file.
UPRIGHT = 'mcomix_upright'


def turned_as_shown(thumbnail: GdkPixbuf.Pixbuf,
                    path: str) -> GdkPixbuf.Pixbuf:
    """<thumbnail> of the picture at <path>, turned as the page is shown.

    A page is shown turned by the orientation its Exif data gives where
    'auto rotate from exif' says so, and as it is in the file where it
    does not; its thumbnail is drawn the same way.  One marked UPRIGHT is
    turned already, and is turned back where the preference is off; one
    that is not is turned where the preference is on.

    <path> may be an archive, whose thumbnail is of its cover: what the
    cover's orientation was is not to be had from the archive's path,
    and the thumbnailer keeps it with the thumbnail instead.
    """
    upright = bool(getattr(thumbnail, UPRIGHT, False))
    if upright == bool(prefs['auto rotate from exif']):
        return thumbnail
    if is_image_file(path):
        rotation = get_implied_rotation_from_file(path)
    else:
        rotation = get_implied_rotation(thumbnail)
    return rotate_pixbuf(thumbnail, (360 - rotation) % 360 if upright
                         else rotation)


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
    return get_image_info(path)


def get_image_size(path: str) -> tuple[int, int]:
    """Return the (width, height) of the image at <path> without decoding it."""
    return get_image_header(path)[1]


def get_size_rotation(width: int, height: int) -> int:
    """ Determines the rotation to be applied.
    Returns the degree of rotation (0, 90, 180, 270). """

    if width != height:
        arp = prefs['auto rotate depending on size']
        if height > width:
            if arp == constants.AUTOROTATE_HEIGHT_90:
                return 90
            elif arp == constants.AUTOROTATE_HEIGHT_270:
                return 270
        else:  # width > height
            if arp == constants.AUTOROTATE_WIDTH_90:
                return 90
            elif arp == constants.AUTOROTATE_WIDTH_270:
                return 270
    return 0


def combine_pixbufs(first: GdkPixbuf.Pixbuf, second: GdkPixbuf.Pixbuf,
                    axis: int = constants.DISTRIBUTION_AXIS
                    ) -> GdkPixbuf.Pixbuf:
    """Return <first> and <second> joined into one pixbuf along <axis>.

    <axis> is a constants.PageAxis, the one the two are distributed on:
    along the width they end up side by side with <first> on the left,
    and along the height stacked with <first> on top.  The caller settles
    which page is which, because that is a question about the view rather
    than about the pages - a manga reads right to left, and turning the
    view moves the pages about with it.

    The result is as long as the two together along <axis> and as long as
    the longer of them along the other axis, so where they differ - which
    is the usual case for scanned pages - part of the shorter one's band
    is covered by neither.  Those pixels are filled before anything is
    copied in, because GdkPixbuf.Pixbuf.new() does not clear the buffer
    it allocates and leaves what is in them undefined: transparent where
    either page has an alpha channel to be transparent in, and otherwise
    white, which is what MComix shows through a transparent page as well.
    """
    other_axis = (constants.PageAxis.HEIGHT
                  if axis == constants.PageAxis.WIDTH
                  else constants.PageAxis.WIDTH)
    sizes = [[pixbuf.get_width(), pixbuf.get_height()]
             for pixbuf in (first, second)]
    combined_size = [0, 0]
    combined_size[axis] = sizes[0][axis] + sizes[1][axis]
    combined_size[other_axis] = max(sizes[0][other_axis], sizes[1][other_axis])

    has_alpha = first.get_has_alpha() or second.get_has_alpha()
    combined = _allocated(GdkPixbuf.Pixbuf.new(
        colorspace=GdkPixbuf.Colorspace.RGB, has_alpha=has_alpha,
        bits_per_sample=8,
        width=combined_size[constants.PageAxis.WIDTH],
        height=combined_size[constants.PageAxis.HEIGHT]))
    combined.fill(convert_rgba_to_rgba8int((1.0, 1.0, 1.0,
                                            0.0 if has_alpha else 1.0)))

    offset = [0, 0]
    for pixbuf, size in zip((first, second), sizes):
        pixbuf.copy_area(0, 0, size[constants.PageAxis.WIDTH],
                         size[constants.PageAxis.HEIGHT], combined,
                         offset[constants.PageAxis.WIDTH],
                         offset[constants.PageAxis.HEIGHT])
        offset[axis] += size[axis]

    return combined


def is_image_file(path: str) -> bool:
    """Return True if <path> ends in an extension MComix can read.

    This is a decision about the name alone; nothing opens the file.
    get_supported_formats() is what settles which extensions those are.
    """
    return _SUPPORTED_IMAGE_REGEX.search(path) is not None


def convert_rgba_to_rgba8int(colour: Sequence[float]) -> int:
    """Return <colour> as the packed integer GdkPixbuf.Pixbuf.fill() takes.

    <colour> is a sequence of Gdk.RGBA components, each between 0 and 1.
    A shorter one is taken to be opaque.
    """
    def component(value: float) -> int:
        return min(255, max(0, int(round(value * 255))))
    red, green, blue = (component(value) for value in colour[:3])
    alpha = component(colour[3]) if len(colour) > 3 else 255
    return (red << 24) | (green << 16) | (blue << 8) | alpha


def rgb_to_y_601(colour: Sequence[float]) -> float:
    """Return the luma of <colour>, given as Gdk.RGBA components."""
    return colour[0] * 0.299 + colour[1] * 0.587 + colour[2] * 0.114


def text_color_for_background_color(bgcolour: Sequence[float]) -> Gdk.RGBA:
    """Return the text colour that reads best on <bgcolour>."""
    return RGBA_BLACK if rgb_to_y_601(bgcolour) >= 0.5 else RGBA_WHITE


def get_composite_color_args(variant: int) -> tuple[int, int, int]:
    """The check size and the two colours composite_color_simple() takes.

    Variant 0 is the grey chequerboard drawn behind a transparent page,
    in squares of eight pixels; variant 1 is plain white, both squares
    the same colour, so the size it is given never shows.
    """
    return ((8, 0x777777, 0x999999), (1024, 0xFFFFFF, 0xFFFFFF))[variant]


def get_image_info(path: str) -> tuple[str, tuple[int, int]]:
    """The format and size of the image at <path>, as gdk-pixbuf sees it.

    The answer is (format, (width, height)).  gdk-pixbuf is asked first,
    and PIL only about a file gdk-pixbuf cannot name; a file neither of
    them knows is an "Unknown filetype" of (0, 0), which the loaders
    read as "try anyway", so that one of them raises about the file
    rather than the caller having to invent an error.

    Asking gdk-pixbuf costs a header query, which is as expensive as
    decoding the image where its loaders run sandboxed.  Every caller
    but get_image_header() has been moved off this for that reason, and
    a new one wants get_image_header() too: it reads the same answer
    with PIL and falls back here only for a file PIL cannot identify.
    """
    image_format: str | None = None
    image_dimensions: tuple[int, int] | None = None
    try:
        gdk_image_info = GdkPixbuf.Pixbuf.get_file_info(path)
    except Exception:
        gdk_image_info = None

    # A format gdk-pixbuf cannot name is one it cannot describe either,
    # so it goes the same way as one it did not recognise at all.
    gdk_format = None if gdk_image_info is None else gdk_image_info[0]
    gdk_name = None if gdk_format is None else gdk_format.get_name()
    if gdk_image_info is not None and gdk_name is not None:
        image_format = gdk_name.upper()
        image_dimensions = gdk_image_info[1], gdk_image_info[2]
    else:
        try:
            im = Image.open(path)
            image_format = im.format
            image_dimensions = im.size
        except (OSError, Image.DecompressionBombError):
            # If the file cannot be found, or the image cannot be opened
            # and identified - or is larger than PIL will open, which it
            # says with an error that is not an OSError.
            pass
    if image_format is None or image_dimensions is None:
        image_format = _('Unknown filetype')
        image_dimensions = (0, 0)
    return (image_format, image_dimensions)


@functools.cache
def get_supported_formats() -> dict[str, tuple[set[str], set[str]]]:
    """The image formats a loader is installed for.

    A mapping of a format's name to its mime types and its extensions.
    """

    # Step 1: Collect PIL formats
    # Make sure all supported formats are registered.
    Image.init()
    # Not all PIL formats register a mime type,
    # fill in the blanks ourselves.
    supported_formats_pil: dict[str, tuple[list[str], list[str]]] = {
        'BMP': (['image/bmp', 'image/x-bmp', 'image/x-MS-bmp'], []),
        'ICO': (['image/x-icon', 'image/x-ico', 'image/x-win-bitmap'], []),
        'PCX': (['image/x-pcx'], []),
        'PPM': (['image/x-portable-pixmap'], []),
        'TGA': (['image/x-tga'], []),
    }
    for name, mime in Image.MIME.items():
        mime_types, extensions = supported_formats_pil.get(name, ([], []))
        supported_formats_pil[name] = mime_types + [mime], extensions
    for ext, name in Image.EXTENSION.items():
        assert ext[0] == '.'
        mime_types, extensions = supported_formats_pil.get(name, ([], []))
        supported_formats_pil[name] = mime_types, extensions + [ext[1:]]
    # Remove formats with no mime type or extension.
    supported_formats_pil = {
        name: (mime_types, extensions)
        for name, (mime_types, extensions) in supported_formats_pil.items()
        if mime_types and extensions}
    # Remove archives/videos formats.
    for name in (
        'MPEG',
        'PDF',
    ):
        if name in supported_formats_pil:
            del supported_formats_pil[name]

    # Step 2: Collect GDK Pixbuf formats
    supported_formats_gdk: dict[str, tuple[list[str], list[str]]] = {}
    for format in GdkPixbuf.Pixbuf.get_formats():
        format_name = format.get_name()
        gdk_mime_types = format.get_mime_types()
        gdk_extensions = format.get_extensions()
        # A format that will not say what it is called, what it
        # serves or what it is filed under describes nothing, and a
        # disabled one opens nothing.  gdk-pixbuf 2.44 offers its
        # legacy XPM loader under no extension, beside one that has it.
        if (not format_name or not gdk_mime_types or not gdk_extensions
                or format.is_disabled()):
            continue
        name = format_name.upper()
        if name in supported_formats_gdk:
            # The list of supported formats can sometimes contain duplicated entries
            continue

        supported_formats_gdk[name] = (gdk_mime_types, gdk_extensions)

    # Step 3: merge format collections
    supported_formats: dict[str, tuple[set[str], set[str]]] = {}
    for provider in (supported_formats_gdk, supported_formats_pil):
        for name, (mime_types, extensions) in provider.items():
            new_name = name.upper()
            new_mime_types, new_extensions = supported_formats.get(
                new_name, (set(), set()))
            new_mime_types.update(x.lower() for x in mime_types)
            new_extensions.update(x.lower() for x in extensions)
            supported_formats[new_name] = (new_mime_types, new_extensions)

    return supported_formats


# Set supported image extensions regexp from list of supported formats.
# Only used internally.
_SUPPORTED_IMAGE_REGEX = tools.formats_to_regex(get_supported_formats())
log.debug("_SUPPORTED_IMAGE_REGEX='%s'", _SUPPORTED_IMAGE_REGEX.pattern)

# vim: expandtab:sw=4:ts=4
