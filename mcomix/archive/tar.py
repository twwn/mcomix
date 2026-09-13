# -*- coding: utf-8 -*-

""" Unicode-aware wrapper for tarfile.TarFile. """

import os
import tarfile
from collections.abc import Iterable, Iterator
from typing import Literal

from . import archive_base

#: The read modes tarfile accepts for the compressions MComix names.
ReadMode = Literal['r:', 'r:bz2', 'r:gz', 'r:xz']

#: The mode tarfile is to open a file beginning with each magic in.  A
#: tarball compressed with xz or lzma is one tarfile reads itself.
_COMPRESSION_MODES: tuple[tuple[bytes, ReadMode], ...] = (
    (b'BZh',               'r:bz2'),
    (b'\037\213',          'r:gz'),
    (b'\xFD7zXZ',          'r:xz'),
    (b']\x00\x00\x80\x00', 'r:xz'),
)

def open_mode(magic: bytes) -> ReadMode:
    """Return the mode tarfile is to open a file beginning with <magic> in.

    Left to guess, tarfile offers the file to every decompressor it knows,
    and lzma takes almost any byte for a header: on a file that is not a
    tar at all, that guess reads and inflates the whole of it before saying
    so.  Naming the compression the magic asks for leaves the one
    decompressor that can answer.
    """
    for prefix, mode in _COMPRESSION_MODES:
        if magic.startswith(prefix):
            return mode
    return 'r:'

def read_magic(path: str) -> bytes:
    """Return the bytes at the head of <path> that name its compression."""
    with open(path, 'rb') as fd:
        return fd.read(5)

class TarArchive(archive_base.NonUnicodeArchive):
    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        # Track if archive contents have been listed at least one time: this
        # must be done before attempting to extract contents.
        self._contents_listed = False
        self._contents: list[str] = []
        self.tar: tarfile.TarFile | None = None

    @property
    def _opened_tar(self) -> tarfile.TarFile:
        """ The open tarball, for the code paths that list it first.
        Raising here names the invariant rather than failing on None. """
        if self.tar is None:
            raise ValueError('The tarball %s is not open.' % self.archive)
        return self.tar

    def is_solid(self) -> bool:
        return True

    def iter_contents(self) -> Iterator[str]:
        if self._contents_listed:
            for name in self._contents:
                yield name
            return
        # Make sure we start back at the beginning of the tar.
        self.tar = tarfile.open(self.archive, open_mode(read_magic(self.archive)))
        self._contents = []
        while True:
            info = self.tar.next()
            if info is None:
                break
            name = self._unicode_filename(info.name)
            self._contents.append(name)
            yield name
        self._contents_listed = True

    def list_contents(self) -> list[str]:
        return list(self.iter_contents())

    def extract(self, filename: str, destination_dir: str) -> None:
        if not self._contents_listed:
            self.list_contents()
        file_object = self._opened_tar.extractfile(self._original_filename(filename))
        if file_object is None:
            # A directory or a link: there is no content to write.
            return
        with file_object:
            with self._create_file(os.path.join(destination_dir, filename)) as new:
                new.write(file_object.read())

    def iter_extract(self, entries: Iterable[str], destination_dir: str) -> Iterator[str]:
        if not self._contents_listed:
            self.list_contents()
        yield from super().iter_extract(entries, destination_dir)

    def close(self) -> None:
        if self.tar is not None:
            self.tar.close()
            self.tar = None

# vim: expandtab:sw=4:ts=4
