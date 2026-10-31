"""Fuzz target: an EPUB opened, listed and unpacked by
mcomix.archive.epub.

The ZIP container itself is Python's zipfile's to read; what is fuzzed
is what MComix reads out of it.  The bytes are the members, in this
order, separated by SEPARATOR: META-INF/container.xml, the package
document OEBPS/content.opf, the pages OEBPS/p1.xhtml and OEBPS/p2.svg,
META-INF/encryption.xml and ComicInfo.xml, each left out where the
bytes end first; two pictures are always there.  Opening the book
raises UnpackException (DRM) or nothing; a book that opened lists its
pages and each comes out without raising.  Any other exception, a hang
or memory without bound is a finding.
"""

import os
import shutil
import sys
import tempfile
import zipfile

import _setup  # noqa: F401  # the path and the folders, before MComix

import atheris

with atheris.instrument_imports(include=['mcomix']):
    from mcomix.archive import epub

SEPARATOR = b'\n--8<--\n'
MEMBERS = ('META-INF/container.xml', 'OEBPS/content.opf', 'OEBPS/p1.xhtml',
           'OEBPS/p2.svg', 'META-INF/encryption.xml', 'ComicInfo.xml')
PICTURES = {'OEBPS/images/a.png': b'\x89PNG\r\n\x1a\n',
            'OEBPS/images/b.jpg': b'\xff\xd8\xff\xe0'}

FOLDER = tempfile.mkdtemp(prefix='mcomix-fuzz-epub-')
BOOK = os.path.join(FOLDER, 'book.epub')
OUT = os.path.join(FOLDER, 'out')


def TestOneInput(data: bytes) -> None:
    with zipfile.ZipFile(BOOK, 'w') as book:
        book.writestr('mimetype', epub.MIMETYPE)
        for name, content in zip(MEMBERS, data.split(SEPARATOR)):
            book.writestr(name, content)
        for name, content in PICTURES.items():
            book.writestr(name, content)
    if not epub.is_epub(BOOK):
        raise AssertionError('a book with its mimetype is not taken for an EPUB')
    try:
        archive = epub.EpubArchive(BOOK)
    except epub.UnpackException:
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
