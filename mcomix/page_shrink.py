"""page_shrink.py - Making pages far larger than any screen shows smaller.

Unlike archive_packer's lossless conversions, this loses detail: a page
taller than the limit the reader chose is scaled down to it and stored
as a WebP at the quality they chose.  A long strip - manhwa, webtoons,
pages made to be scrolled through - is far taller than it is wide, and
meant to be: it is judged by its width only, never shrunk for its
height.

Nothing here touches GTK; archive_packer.Packer calls shrink_instead()
on its threads.
"""

import os
from dataclasses import dataclass

from mcomix import log

#: How many times taller than wide a page is at least to be a long strip.
#: A comic's page is about one and a half; a strip's page of a webtoon
#: is anything from three to twenty.
STRIP_SHAPE = 2.5

#: The width a long strip is held to, as a share of the limit: that of
#: a page of 2:3 as tall as the limit, the shape of most comics' pages.
STRIP_WIDTH = 2 / 3

#: The largest width or height a WebP can have.
_WEBP_MAX_SIDE = 16383

#: The modes of the pictures shrunk.  Every other one stays as it was:
#: 16 or 32 bits a channel (a WebP holds 8), and CMYK, whose profile
#: would not fit the RGB of a WebP.
_MODES = ('1', 'L', 'LA', 'P', 'PA', 'RGB', 'RGBA')

#: The modes whose colour profile, where they carry one, is a grey
#: one, which does not fit the RGB of a WebP either: it is left out.
_GREY = ('1', 'L', 'LA')

#: The bytes a pixel of the page costs while it is shrunk: decoded as
#: RGBA, converted, and the encoder's own.
_BYTES_PER_PIXEL = 12


@dataclass(frozen=True)
class Shrink:

    """How pages are to be shrunk."""

    #: The height in pixels a page is shrunk to where it is taller.
    limit: int
    #: The WebP quality the shrunk pages are written at, from 1 to 100.
    quality: int


def scaled_size(width: int, height: int,
                limit: int) -> "tuple[int, int] | None":
    """The size a page of <width> by <height> pixels is shrunk to for
    <limit>, its shape kept; None where it is not over the limit.

    A long strip (STRIP_SHAPE) is over it only where it is wider than
    a page of the shape STRIP_WIDTH tells, and is then made that wide.
    """
    if height > STRIP_SHAPE * width:
        bound = round(limit * STRIP_WIDTH)
        if width <= bound:
            return None
        scale = bound / width
    elif height > limit:
        scale = limit / height
    else:
        return None
    return max(1, round(width * scale)), max(1, round(height * scale))


def cost(path: str) -> int:
    """The bytes shrinking the picture at <path> costs, from its size
    as its header gives it; 0 for what Pillow does not read."""
    from PIL import Image

    try:
        with Image.open(path) as picture:
            width, height = picture.size
    except Exception:
        # Pillow refuses a broken picture with whatever it found.
        return 0
    return width * height * _BYTES_PER_PIXEL


def shrink_instead(path: str, directory: str, name: str,
                   shrink: Shrink) -> "str | None":
    """Write the picture at <path> into <directory> as <name>, shrunk
    as <shrink> says and as a WebP, and answer with its path; or answer
    None, writing nothing, where it is not over the limit, is not shrunk
    (animated, too large for a WebP still, or of a mode in which it would
    lose more than detail), or the WebP is no smaller.

    Its colour profile and Exif go along, the Exif orientation with
    them: the picture is scaled as it is stored, so the orientation
    still says how to show it.
    """
    from PIL import Image, features

    if not features.check('webp'):
        _kept_as_it_was(path, 'this Pillow writes no WebP')
        return None
    target = os.path.join(directory, name)
    with Image.open(path) as picture:
        size = scaled_size(*picture.size, shrink.limit)
        gamma = picture.info.get('gamma')
        if size is None:
            return None
        if getattr(picture, 'n_frames', 1) > 1:
            why = 'it is animated'
        elif picture.mode not in _MODES:
            why = 'its mode is %s' % picture.mode
        elif max(size) > _WEBP_MAX_SIDE:
            why = 'shrunk it is %dx%d pixels, a WebP at most %d ' \
                'either way' % (size + (_WEBP_MAX_SIDE,))
        elif gamma is not None and abs(float(gamma) - 1 / 2.2) > 0.001:
            # A WebP has no place for it, so it would look otherwise.
            why = "its gamma, %s, is not sRGB's" % gamma
        else:
            why = None
        if why is not None:
            _kept_as_it_was(path, why)
            return None
        options = {key: picture.info[key]
                   for key in ('icc_profile', 'exif') if picture.info.get(key)}
        if picture.mode in _GREY:
            options.pop('icc_profile', None)
        mode = 'RGBA' if picture.has_transparency_data else 'RGB'
        # A JPEG is decoded at the smallest scale of its own no smaller
        # than the page will be, an eighth at most: a fraction of the
        # time and memory of the whole.
        picture.draft(picture.mode, size)
        shrunk = picture.convert(mode).resize(size, Image.Resampling.LANCZOS)
    shrunk.save(target, 'WEBP', quality=shrink.quality, method=4, **options)
    if os.path.getsize(target) >= os.path.getsize(path):
        os.remove(target)
        _kept_as_it_was(path, 'the WebP was no smaller')
        return None
    return target


def _kept_as_it_was(path: str, reason: str) -> None:
    """Say at debug level why the page at <path>, over the limit, was
    not shrunk."""
    log.debug('Did not shrink "%s": %s', path, reason)

# vim: expandtab:sw=4:ts=4
