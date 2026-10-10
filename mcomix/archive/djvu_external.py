""" DjVu handler. """

from mcomix import log
from mcomix import process
from mcomix.archive import archive_base

import functools
import os
import subprocess
from collections.abc import Iterator
from typing import NamedTuple


class _DjVuLibre(NamedTuple):
    """The two DjVuLibre programs a DjVu book is read with."""

    #: Reports how many pages a document has.
    djvused: str
    #: Draws one page into an image file.
    ddjvu: str


@functools.cache
def _find_djvulibre() -> _DjVuLibre | None:
    """DjVuLibre's command line tools, or None if they are not
    installed."""
    djvused = process.find_executable(('djvused',))
    ddjvu = process.find_executable(('ddjvu',))
    if djvused is None or ddjvu is None:
        log.debug('djvused or ddjvu executable not found')
        log.info('DjVuLibre not available.')
        return None
    return _DjVuLibre(djvused, ddjvu)


class DjvuArchive(archive_base.BaseArchive):

    """The pages of a DjVu document, drawn one at a time by DjVuLibre
    (upstream feature request 50).

    As with a PDF read by MuPDF's tools, every page is an image named
    after its number, here a TIFF, which Pillow reads everywhere; a page
    is drawn when it is asked for, at the resolution the document keeps
    it in, by a ddjvu run of its own.
    """

    helper = 'ddjvu'
    # Every page is a process of its own.
    support_concurrent_extractions = True

    @property
    def _djvulibre(self) -> _DjVuLibre:
        """The DjVuLibre programs, for the code paths reached only once
        is_available() has answered True."""
        djvulibre = _find_djvulibre()
        if djvulibre is None:
            raise ValueError('DjVuLibre is not available.')
        return djvulibre

    def iter_contents(self) -> Iterator[str]:
        """Yield a name per page, which is all a DjVu document has to
        list."""
        # The absolute path: neither program takes "--", and a name that
        # starts with "-" would be read as an option.
        proc = subprocess.run(
            [self._djvulibre.djvused, '-e', 'n', os.path.abspath(self.archive)],
            stdout=subprocess.PIPE, encoding='utf-8',
            creationflags=process.CREATIONFLAGS)
        try:
            pages = int(proc.stdout.strip())
        except ValueError:
            log.warning('Could not read the pages of %s', self.archive)
            return
        for page in range(1, pages + 1):
            yield '%d.tif' % page

    def extract(self, filename: str, destination_dir: str) -> None:
        """Draw the page <filename> stands for into <destination_dir>."""
        self._create_directory(destination_dir)
        page = int(filename[:-len('.tif')])
        cmd = [self._djvulibre.ddjvu, '-format=tiff', '-page=%d' % page,
               os.path.abspath(self.archive),
               os.path.abspath(os.path.join(destination_dir, filename))]
        log.debug('rendering %s: %s', filename, ' '.join(cmd))
        process.call(cmd)

    @staticmethod
    def is_available() -> bool:
        """Whether DjVuLibre's command line tools are installed."""
        return _find_djvulibre() is not None

# vim: expandtab:sw=4:ts=4
