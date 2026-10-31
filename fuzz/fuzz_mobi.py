"""Fuzz target: a MobiPocket (AZW3) book opened, listed and unpacked by
mcomix.archive.mobi.

Opening it raises UnpackException or nothing, which the file handler
shows; a book that opened lists its pictures and each comes out without
raising.  Any other exception, a hang or memory without bound is a
finding.
"""

import os
import shutil
import sys
import tempfile

import _setup  # noqa: F401  # the path and the folders, before MComix

import atheris

with atheris.instrument_imports(include=['mcomix']):
    from mcomix.archive import mobi

FOLDER = tempfile.mkdtemp(prefix='mcomix-fuzz-mobi-')
BOOK = os.path.join(FOLDER, 'book.azw3')
OUT = os.path.join(FOLDER, 'out')


def TestOneInput(data: bytes) -> None:
    with open(BOOK, 'wb') as fp:
        fp.write(data)
    try:
        archive = mobi.MobiArchive(BOOK)
    except mobi.UnpackException:
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
