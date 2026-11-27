"""Fuzz target: the header code MComix runs on a page's own bytes, past
the decoders - mcomix.jpeg_turn, which turns a JPEG page by its Exif
orientation, and the PNG header read that tells whether a page can
become a WebP (archive_packer._png_header()).

with_orientation() and orientation_of() answer or raise ValueError,
which "Save rotation to file" shows; _png_header() answers None or the
size, depth and frame count.  Anything else, a hang or memory without
bound is a finding.
"""

import os
import sys
import tempfile

import _setup  # noqa: F401  # the path and the folders, before MComix

import atheris

with atheris.instrument_imports(include=['mcomix']):
    from mcomix import archive_packer
    from mcomix import jpeg_turn

FOLDER = tempfile.mkdtemp(prefix='mcomix-fuzz-pictures-')
PATH = os.path.join(FOLDER, 'page.png')


def TestOneInput(data: bytes) -> None:
    for orientation in (1, 6):
        try:
            jpeg_turn.with_orientation(data, orientation)
        except ValueError:
            pass
    try:
        jpeg_turn.orientation_of(data)
    except ValueError:
        pass
    with open(PATH, 'wb') as fp:
        fp.write(data)
    archive_packer._png_header(PATH)


if __name__ == '__main__':
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
