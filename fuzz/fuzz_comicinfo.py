"""Fuzz target: mcomix.comicinfo reading a ComicInfo.xml that came out
of an archive, and writing one in its place when a book is saved.

describe() answers with the fields it read or none, reads_right_to_left()
with True or False, whatever the file holds; for_pages() answers with
None or a document that parses.  An exception, a hang or memory
without bound is a finding: the properties dialog and the main window
read the file on the main thread.
"""

import os
import sys
import tempfile
import xml.etree.ElementTree as ElementTree

import _setup  # noqa: F401  # the path and the folders, before MComix

import atheris

with atheris.instrument_imports(include=['mcomix']):
    from mcomix import comicinfo

FOLDER = tempfile.mkdtemp(prefix='mcomix-fuzz-comicinfo-')
PATH = os.path.join(FOLDER, comicinfo.NAME)
#: Pages that are not there: their sizes are left out, as for a page
#: whose picture cannot be read.
PAGES = [os.path.join(FOLDER, name) for name in ('01.jpg', '02.png', '03.webp')]


def TestOneInput(data: bytes) -> None:
    with open(PATH, 'wb') as fp:
        fp.write(data)
    comicinfo.describe(PATH)
    comicinfo.reads_right_to_left(PATH)
    for count in (len(PAGES), 1):
        written = comicinfo.for_pages(PAGES[:count], data)
        if written is not None:
            ElementTree.fromstring(written)


if __name__ == '__main__':
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
