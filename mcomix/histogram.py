"""histogram.py - Draw histograms (RGB) from pixbufs."""

import math

import PIL.Image as Image
import PIL.ImageDraw as ImageDraw
import PIL.ImageOps as ImageOps

from gi.repository import GdkPixbuf

from mcomix import image_tools


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
    # Draw the filling colours.  A column is one colour from the bottom
    # up to its lowest channel's height, another from there to the next
    # one's, and so on: three lines at most, each drawn at once rather
    # than pixel by pixel.
    draw = ImageDraw.Draw(im)
    for x in range(256):
        bottom = 1
        for top in sorted({r[x], g[x], b[x]}):
            if top < bottom:
                continue
            draw.line([(x + 1, height - 5 - top), (x + 1, height - 5 - bottom)],
                      fill=(fill if top <= r[x] else 0,
                            fill if top <= g[x] else 0,
                            fill if top <= b[x] else 0))
            bottom = top + 1
    # Draw the outlines: a channel's outline is that channel at full
    # intensity, whatever the filling or another outline left in the
    # other two, so each is drawn into its own band.
    bands = im.split()
    for band, heights in zip(bands, (r, g, b)):
        outline = ImageDraw.Draw(band)
        for x in range(1, 256):
            before, now = heights[x - 1], heights[x]
            # Up a rise, in the column that rose, and the top of every
            # bar, risen or not...
            if now:
                outline.line([(x + 1, height - 5 - now),
                              (x + 1, height - 5 - min(before + 1, now))],
                             fill=255)
            # ...and down a fall, in the column before it.
            if before > now:
                outline.line([(x, height - 5 - before),
                              (x, height - 5 - (now + 1))], fill=255)
    im = Image.merge('RGB', bands)
    im = ImageOps.expand(im, 1, (80, 80, 80))
    im = ImageOps.expand(im, 1, (0, 0, 0))
    return image_tools.pil_to_pixbuf(im)


# vim: expandtab:sw=4:ts=4
