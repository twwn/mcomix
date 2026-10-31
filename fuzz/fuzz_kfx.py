"""Fuzz target: a KFX book opened, listed and unpacked by
mcomix.archive.kfx, as the reader's file handler and extractor do.

The bytes are the book's one file: a KFX container, or a KFX-ZIP of
containers.  Opening it raises UnpackException or nothing, which the
file handler shows as "not a Kindle book MComix can read" or "protected
by DRM"; a book that opened lists its pages without raising, and each
page comes out without raising.  Any other exception, a hang or memory
without bound is a finding.  JPEG XR is not decoded: that runs
jxrlib's program, which is not MComix'.
"""

import os
import shutil
import sys
import tempfile

import _setup  # noqa: F401  # the path and the folders, before MComix

import atheris

with atheris.instrument_imports(include=['mcomix']):
    from mcomix.archive import kfx

kfx._jxr_decoder = lambda: None

FOLDER = tempfile.mkdtemp(prefix='mcomix-fuzz-kfx-')
BOOK = os.path.join(FOLDER, 'book', 'book.kfx')
OUT = os.path.join(FOLDER, 'out')
os.makedirs(os.path.dirname(BOOK))


def TestOneInput(data: bytes) -> None:
    with open(BOOK, 'wb') as fp:
        fp.write(data)
    try:
        archive = kfx.KfxArchive(BOOK)
    except kfx.UnpackException:
        return
    try:
        for name in archive.list_contents():
            archive.extract(name, OUT)
    finally:
        archive.close()
        shutil.rmtree(OUT, ignore_errors=True)


if __name__ == '__main__':
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
