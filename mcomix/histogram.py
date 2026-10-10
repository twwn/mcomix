"""histogram.py - Draw histograms (RGB) from pixbufs."""

import math

import PIL.Image as Image
import PIL.ImageOps as ImageOps

from gi.repository import GdkPixbuf

from typing import cast

from mcomix import image_tools


#: One pixel of an RGB image, as its pixel access hands it over.
type Rgb = tuple[int, int, int]


def draw_histogram(pixbuf: GdkPixbuf.Pixbuf, height: int = 170,
                   fill: int = 170,
                   logarithmic: bool = False) -> GdkPixbuf.Pixbuf:
    """Draw a histogram from <pixbuf> and return it as another pixbuf.

    The returned pixbuf will be 262x<height> px.

    The value of <fill> determines the colour intensity of the filled graphs,
    valid values are between 0 and 255.  <logarithmic> draws the counts
    on a logarithmic scale, where the few pixels of a colour still show
    beside a page that is mostly white (upstream feature request 70).
    """
    im = Image.new('RGB', (258, height - 4), (30, 30, 30))
    counts: list[float] = list(
        image_tools.pixbuf_to_pil(pixbuf).histogram()[:768])
    if logarithmic:
        counts = [math.log1p(count) for count in counts]
    maximum = max(counts + [1])
    y_scale = float(height - 6) / maximum
    r = [int(counts[n] * y_scale) for n in range(256)]
    g = [int(counts[n] * y_scale) for n in range(256, 512)]
    b = [int(counts[n] * y_scale) for n in range(512, 768)]
    pixels = im.load()
    # An image made in memory is loaded already, so there is always
    # something to reach its pixels through.
    assert pixels is not None
    # Draw the filling colours
    for x in range(256):
        for y in range(1, max(r[x], g[x], b[x]) + 1):
            r_px = y <= r[x] and fill or 0
            g_px = y <= g[x] and fill or 0
            b_px = y <= b[x] and fill or 0
            pixels[x + 1, height - 5 - y] = (r_px, g_px, b_px)
    # Draw the outlines
    for x in range(1, 256):
        for y in list(range(r[x-1] + 1, r[x] + 1)) + [r[x]] * (r[x] != 0):
            r_px, g_px, b_px = cast(Rgb, pixels[x + 1, height - 5 - y])
            pixels[x + 1, height - 5 - y] = (255, g_px, b_px)
        for y in range(r[x] + 1, r[x-1] + 1):
            r_px, g_px, b_px = cast(Rgb, pixels[x, height - 5 - y])
            pixels[x, height - 5 - y] = (255, g_px, b_px)
        for y in list(range(g[x-1] + 1, g[x] + 1)) + [g[x]] * (g[x] != 0):
            r_px, g_px, b_px = cast(Rgb, pixels[x + 1, height - 5 - y])
            pixels[x + 1, height - 5 - y] = (r_px, 255, b_px)
        for y in range(g[x] + 1, g[x-1] + 1):
            r_px, g_px, b_px = cast(Rgb, pixels[x, height - 5 - y])
            pixels[x, height - 5 - y] = (r_px, 255, b_px)
        for y in list(range(b[x-1] + 1, b[x] + 1)) + [b[x]] * (b[x] != 0):
            r_px, g_px, b_px = cast(Rgb, pixels[x + 1, height - 5 - y])
            pixels[x + 1, height - 5 - y] = (r_px, g_px, 255)
        for y in range(b[x] + 1, b[x-1] + 1):
            r_px, g_px, b_px = cast(Rgb, pixels[x, height - 5 - y])
            pixels[x, height - 5 - y] = (r_px, g_px, 255)
    im = ImageOps.expand(im, 1, (80, 80, 80))
    im = ImageOps.expand(im, 1, (0, 0, 0))
    return image_tools.pil_to_pixbuf(im)


# vim: expandtab:sw=4:ts=4
