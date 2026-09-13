"""image_tools.py - Various image manipulations."""

import functools
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

from collections.abc import Callable, Sequence
from typing import Any

PIL_VERSION = ('Pillow', PIL.__version__)

# Unfortunately gdk_pixbuf_version is not exported, so show the GTK+ version instead.
log.info(f'GDK version: {GdkPixbuf.PIXBUF_VERSION}, GTK+: {Gtk.get_major_version()}.{Gtk.get_minor_version()}, GLib: {GLib.MAJOR_VERSION}.{GLib.MINOR_VERSION}')
log.info('PIL version: %s [%s]', PIL_VERSION[0], PIL_VERSION[1])

#: 24 pixels is what Gtk.IconSize.LARGE_TOOLBAR stood for.
_MISSING_IMAGE_SIZE = 24


@functools.cache
def missing_image_icon() -> GdkPixbuf.Pixbuf:
    """The pixbuf shown in place of an image that would not load.

    It is built on the first call rather than at import: GTK4 looks
    icon themes up per display, and there is no display yet while this
    module is being imported.
    """
    from mcomix import icons
    # A theme that keeps its icons in a GResource has no file to load
    # one from, and a blank square is still something to draw.
    icon = (icons.load_pixbuf('image-missing', _MISSING_IMAGE_SIZE)
            or GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                    _MISSING_IMAGE_SIZE,
                                    _MISSING_IMAGE_SIZE))
    # Pixbuf.new() answers with nothing only when the allocation fails,
    # and a square this small will not be what runs out.
    assert icon is not None
    return icon


#: Colours are Gdk.RGBA components throughout: four floats between 0 and 1.
RGBA_BLACK = Gdk.RGBA(0.0, 0.0, 0.0, 1.0)
RGBA_WHITE = Gdk.RGBA(1.0, 1.0, 1.0, 1.0)


def axis_to_gdkpixbuf_flip_horizontal(i: int) -> bool:
    return (True, False)[i]


def angle_to_gdkpixbuf_rotation(deg: int) -> GdkPixbuf.PixbufRotation:
    if deg == 0:
        return GdkPixbuf.PixbufRotation.NONE
    elif deg == 90:
        return GdkPixbuf.PixbufRotation.CLOCKWISE
    elif deg == 180:
        return GdkPixbuf.PixbufRotation.UPSIDEDOWN
    elif deg == 270:
        return GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE
    raise ValueError("illegal angle: " + str(deg))


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
    if rotation == 0:
        return src
    return _allocated(src.rotate_simple(angle_to_gdkpixbuf_rotation(rotation)))


def flip_pixbuf(src: GdkPixbuf.Pixbuf, axis: int) -> GdkPixbuf.Pixbuf:
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
        # Unbounded in both directions is not a rectangle.  It used to
        # bound the width and leave the height, which max() below then
        # turned into one pixel: a page scaled to a line, quietly.
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

        <colors> is (count, colour) pairs sorted by colour, the way
        Image.getcolors() counts them.  Each colour is rounded to the
        nearest multiple of <steps> - 128, 83, 10 becomes 130, 85, 10
        at <steps> of 5 - and neighbours that round alike make a group,
        which is why the pairs have to arrive sorted.  The answer is
        the commonest colour, unrounded, of the group whose colours
        cover the most pixels between them.

        Grouping is what lets a scanned margin answer with the grey it
        looks like, rather than with whichever of its hundred nearly
        equal greys happened to be counted once more than the rest.
        """

        # No group yet: the first colour read starts one.  This was a
        # (0, 0, 0) tuple, which no rounded colour could ever equal,
        # since those are lists - the comparison below was always false
        # on the first turn.  It made no difference, both branches
        # starting the same group from an empty one, but it said
        # something the code did not do.
        group: list[int] | None = None
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
                colors_in_group = [(count, color)]
                color_count_in_group = count

        # Cleanup if only one edge color group was found
        if color_count_in_group > color_count_in_prominent_group:
            colors_in_prominent_group = colors_in_group

        colors_in_prominent_group.sort(key=operator.itemgetter(0), reverse=True)
        # List is now sorted by color count, first color appears most often
        return colors_in_prominent_group[0][1]

    def get_edge_pixbuf(pixbuf: GdkPixbuf.Pixbuf, side: str,
                        edge: int) -> GdkPixbuf.Pixbuf:
        """ Returns a pixbuf corresponding to the side passed in <side>.
        Valid sides are 'left', 'right', 'top', 'bottom'. """
        width = pixbuf.get_width()
        height = pixbuf.get_height()
        edge = min(edge, width, height)

        if side in ('left', 'right'):
            sub_width, sub_height = edge, height
        elif side in ('top', 'bottom'):
            sub_width, sub_height = width, edge
        else:
            assert False, 'Invalid edge side'

        subpix = _allocated(GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,
                                                 pixbuf.get_has_alpha(), 8, sub_width, sub_height))
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
    """ Loads a pixbuf from a given image file. """
    # Asking get_image_info() which provider to prefer costs another pass
    # over the file - as much again as decoding it, where gdk-pixbuf's
    # loaders run sandboxed - and cannot change the outcome.  It puts PIL
    # first for exactly the files gdk-pixbuf could not identify, which are
    # the files gdk-pixbuf goes on to fail to load, handing them to PIL.
    def by_pil() -> GdkPixbuf.Pixbuf:
        # Whether or how animations work through PIL is undefined.
        return pil_to_pixbuf(Image.open(path), keep_orientation=True)

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
    """ Loads a pixbuf from a given image file and scale it to fit
    inside (width, height). """
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
        return pil_to_pixbuf(image, keep_orientation=True)

    pixbuf = _first_provider_that_loads(
        ((constants.IMAGEIO_GDKPIXBUF, by_gdk_pixbuf),
         (constants.IMAGEIO_PIL, by_pil)),
        '%s at size %s' % (path, (width, height)))
    return fit_in_rectangle(pixbuf, width, height,
                            scaling_quality=GdkPixbuf.InterpType.BILINEAR)


def load_pixbuf_data(imgdata: bytes) -> GdkPixbuf.Pixbuf:
    """ Loads a pixbuf from the data passed in <imgdata>. """
    def by_gdk_pixbuf() -> "GdkPixbuf.Pixbuf | None":
        loader = GdkPixbuf.PixbufLoader()
        loader.write(imgdata)
        loader.close()
        return loader.get_pixbuf()

    return _first_provider_that_loads(
        ((constants.IMAGEIO_GDKPIXBUF, by_gdk_pixbuf),
         (constants.IMAGEIO_PIL,
          lambda: pil_to_pixbuf(Image.open(BytesIO(imgdata)),
                                keep_orientation=True))),
        '%s bytes' % len(imgdata))


def enhance(pixbuf: GdkPixbuf.Pixbuf, brightness: float = 1.0,
            contrast: float = 1.0, saturation: float = 1.0,
            sharpness: float = 1.0, autocontrast: bool = False,
            invert_color: bool = False) -> GdkPixbuf.Pixbuf:
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


def combine_pixbufs(pixbuf1: GdkPixbuf.Pixbuf, pixbuf2: GdkPixbuf.Pixbuf,
                    are_in_manga_mode: bool) -> GdkPixbuf.Pixbuf:
    if are_in_manga_mode:
        r_source_pixbuf = pixbuf1
        l_source_pixbuf = pixbuf2
    else:
        l_source_pixbuf = pixbuf1
        r_source_pixbuf = pixbuf2

    has_alpha = False

    if l_source_pixbuf.get_property('has-alpha') or \
       r_source_pixbuf.get_property('has-alpha'):
        has_alpha = True

    bits_per_sample = 8

    l_source_pixbuf_width = l_source_pixbuf.get_property('width')
    r_source_pixbuf_width = r_source_pixbuf.get_property('width')

    l_source_pixbuf_height = l_source_pixbuf.get_property('height')
    r_source_pixbuf_height = r_source_pixbuf.get_property('height')

    new_width = l_source_pixbuf_width + r_source_pixbuf_width

    new_height = max(l_source_pixbuf_height, r_source_pixbuf_height)

    new_pix_buf = _allocated(GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                                  has_alpha=has_alpha,
                                                  bits_per_sample=bits_per_sample,
                                                  width=new_width, height=new_height))

    l_source_pixbuf.copy_area(0, 0, l_source_pixbuf_width,
                              l_source_pixbuf_height,
                              new_pix_buf, 0, 0)

    r_source_pixbuf.copy_area(0, 0, r_source_pixbuf_width,
                              r_source_pixbuf_height,
                              new_pix_buf, l_source_pixbuf_width, 0)

    return new_pix_buf


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
        except IOError:
            # If the file cannot be found, or the image
            # cannot be opened and identified.
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
        # serves or what it is filed under describes nothing.
        if (format_name is None or gdk_mime_types is None
                or gdk_extensions is None):
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
