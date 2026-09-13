""" PDF handler. """

from mcomix import log
from mcomix import process
from mcomix.version_tools import Version
from mcomix.archive import archive_base
from mcomix.constants import PDF_RENDER_DPI_DEF, PDF_RENDER_DPI_MAX

import functools
import math
import os
import re
import subprocess
from collections.abc import Iterator
from typing import NamedTuple


class _MuPdf(NamedTuple):
    """ The MuPDF commands _find_mupdf() resolved.  Which executable draws
    a page, and which arguments make it trace one, depend on the version:
    mutool grew a draw subcommand in 1.8, and before 1.7 tracing was -x on
    a separate mudraw. """

    version: Version
    mutool: list[str]
    mudraw: list[str]
    trace_args: list[str]


@functools.cache
def _find_mupdf() -> _MuPdf | None:
    """ Look for the MuPDF command line tools, and return what they can do,
    or None if they are not installed. """
    mutool = process.find_executable(('mutool',))
    if mutool is None:
        log.debug('mutool executable not found')
        log.info('MuPDF not available.')
        return None

    # Find MuPDF version; assume 1.6 version since
    # the '-v' switch is only supported from 1.7 onward...
    version_string = '1.6'
    proc = process.popen([mutool, '-v'],
                         stdout=process.NULL,
                         stderr=process.PIPE)
    assert proc.stderr is not None
    try:
        output = proc.stderr.read()
        if output.startswith(b'mutool version '):
            version_string = output[15:].rstrip().decode()
    finally:
        proc.stderr.close()
        proc.wait()
    version = Version(version_string)

    if version >= Version('1.8'):
        # Mutool executable with draw support.
        mupdf = _MuPdf(version, [mutool], [mutool, 'draw'], ['-F', 'trace'])
    else:
        # Separate mudraw executable.
        mudraw = process.find_executable(('mudraw',))
        if mudraw is None:
            log.debug('mudraw executable not found')
            log.info('MuPDF not available.')
            return None
        trace_args = ['-F', 'trace'] if version >= Version('1.7') else ['-x']
        mupdf = _MuPdf(version, [mutool], [mudraw], trace_args)

    log.info('Using MuPDF version: %s', mupdf.version)
    log.debug('mutool: %s', ' '.join(mupdf.mutool))
    log.debug('mudraw: %s', ' '.join(mupdf.mudraw))
    log.debug('mudraw trace arguments: %s', ' '.join(mupdf.trace_args))
    return mupdf


class PdfArchive(archive_base.BaseArchive):

    """The pages of a PDF, rendered one at a time by MuPDF's tools.

    Every page is a PNG named after its number, so the pages sort the
    way they are numbered.  Nothing is unpacked in advance: a page is
    rendered when it is asked for, by a mutool run of its own, which is
    why several may be in flight at once.
    """

    # Concurrent calls to extract welcome!
    support_concurrent_extractions = True

    _fill_image_regex = re.compile(r'^\s*<fill_image\b.*\b(matrix|transform)="(?P<matrix>[^"]+)".*\bwidth="(?P<width>\d+)".*\bheight="(?P<height>\d+)".*/>\s*$')

    @property
    def _mupdf(self) -> _MuPdf:
        """ The MuPDF commands, for the code paths reached only once
        is_available() has answered True. """
        mupdf = _find_mupdf()
        if mupdf is None:
            raise ValueError('MuPDF is not available.')
        return mupdf

    def iter_contents(self) -> Iterator[str]:
        """Yield a name per page, which is all a PDF has to list."""
        proc = subprocess.run(self._mupdf.mutool + ['show', '--', self.archive, 'pages'],
                              stdout=subprocess.PIPE, encoding='utf-8')
        for line in proc.stdout.splitlines():
            if line.startswith('page '):
                yield line.split()[1] + '.png'

    def extract(self, filename: str, destination_dir: str) -> None:
        """Render the page <filename> stands for into <destination_dir>.

        A PDF page has no resolution of its own, so one is chosen: the
        page is traced first, which reports every image it draws and the
        matrix it is drawn under, and the resolution that would render
        the largest of those images at its own pixel size is the one
        used.  A page of scanned paper is then rendered at the scan's
        own resolution rather than at a default that would blur it or
        one that would waste memory, bounded by PDF_RENDER_DPI_MAX.
        """
        mupdf = self._mupdf
        self._create_directory(destination_dir)
        destination_path = os.path.join(destination_dir, filename)
        page_num = int(filename[0:-4])
        # Try to find optimal DPI.
        cmd = mupdf.mudraw + mupdf.trace_args + ['--', self.archive, str(page_num)]
        log.debug('finding optimal DPI for %s: %s', filename, ' '.join(cmd))
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, encoding='utf-8', errors='replace')
        max_size = 0
        max_dpi = PDF_RENDER_DPI_DEF
        for line in proc.stdout.splitlines():
            match = self._fill_image_regex.match(line)
            if not match:
                continue
            matrix = [float(f) for f in match.group('matrix').split()]
            for size, coeff1, coeff2 in (
                (int(match.group('width')), matrix[0], matrix[1]),
                (int(match.group('height')), matrix[2], matrix[3]),
            ):
                if size < max_size:
                    continue
                render_size = math.sqrt(coeff1 * coeff1 + coeff2 * coeff2)
                dpi = int(size * 72 / render_size)
                if dpi > PDF_RENDER_DPI_MAX:
                    dpi = PDF_RENDER_DPI_MAX
                max_size = size
                max_dpi = dpi
        # Render...
        cmd = mupdf.mudraw + ['-r', str(max_dpi), '-o', destination_path, '--', self.archive, str(page_num)]
        log.debug('rendering %s: %s', filename, ' '.join(cmd))
        process.call(cmd)

    @staticmethod
    def is_available() -> bool:
        """Whether the MuPDF command line tools are installed."""
        return _find_mupdf() is not None

# vim: expandtab:sw=4:ts=4
