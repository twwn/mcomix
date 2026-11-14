"""Fuzz target: what MComix reads of every file in a folder it lists,
before anything opens one - mcomix.archive_tools.archive_mime_type(),
which tells the format by the first bytes and counts a TIFF's pages,
and is_later_volume() and
first_volume(), which read a RAR volume's main header and a KFX part's
container header.

None of them raises, whatever the file holds: an exception would stop
the listing of the whole folder, the library's scan of a watched one,
or the walk to the next book.  A hang or memory without bound is a
finding too.
"""

import os
import sys
import tempfile

import _setup  # noqa: F401  # the path and the folders, before MComix

import atheris

with atheris.instrument_imports(include=['mcomix']):
    from mcomix import archive_tools

FOLDER = tempfile.mkdtemp(prefix='mcomix-fuzz-sniff-')
#: The names the volume checks read a file under: a later volume of a
#: RAR set, and a KFX part, each with the file of the other kind beside;
#: and the name a TIFF is looked into under.
NAMES = [os.path.join(FOLDER, name)
         for name in ('book.part2.rar', 'book.kfx', 'book.tif')]


def TestOneInput(data: bytes) -> None:
    for path in NAMES:
        with open(path, 'wb') as fp:
            fp.write(data)
    for path in NAMES:
        archive_tools.archive_mime_type(path)
        archive_tools.is_later_volume(path)
        archive_tools.first_volume(path)


if __name__ == '__main__':
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
