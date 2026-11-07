"""Multiprocessing PDF handler."""

import multiprocessing as mp
import os
import threading

from mcomix import comicinfo
from mcomix.archive import archive_base
from mcomix.archive.native_pdf.manager import FitzProcessWrangler
from mcomix.log import getLevel

from collections.abc import Iterable, Iterator


class FitzArchive(archive_base.BaseArchive):
    """PDF file reader/extractor using PyMuPDF."""

    helper = 'PyMuPDF'
    # Concurrent calls to extract welcome!
    support_concurrent_extractions = True
    # Each extraction thread has a worker process of its own (see
    # FitzProcessWrangler), and one with PyMuPDF loaded and a book open
    # came to about 125 MB (proportional set size, at 44451e29).
    extraction_thread_memory = 130 * 2**20

    def __init__(self, archive: str) -> None:
        """Initialize the object, first as a BaseArchive."""
        super().__init__(archive)
        self.log = mp.get_logger()
        self.log.setLevel(getLevel())
        self.log.debug("PDF contains %d pages", self.mgr.page_count())
        # The ComicInfo.xml of the outline's chapters, made once, by
        # whichever thread lists or extracts first.
        self._made = threading.Lock()
        self._comic_info: bytes | None = None
        self._comic_info_made = False

    def _outline(self) -> bytes | None:
        """A ComicInfo.xml naming the chapters of the PDF's outline, as
        an EPUB's are named (comicinfo.of_book()), or None for a PDF
        without one."""
        with self._made:
            if not self._comic_info_made:
                self._comic_info = comicinfo.of_book(
                    None, None, (), None, False, self.mgr.page_count(),
                    self.mgr.table_of_contents())
                self._comic_info_made = True
            return self._comic_info

    def _open_doc(self) -> FitzProcessWrangler:
        """Create a new FitzManager instance for processes accessing the archive."""
        self.close()
        self._mgr = FitzProcessWrangler(self.archive, log_level=self.log.level)
        return self._mgr

    def close(self) -> None:
        """Destroy the wrangler object and free resources."""
        if hasattr(self, '_mgr'):
            del self._mgr

    @property
    def mgr(self) -> FitzProcessWrangler:
        """The worker for this thread, started on first use."""
        if not hasattr(self, '_mgr'):
            return self._open_doc()
        return self._mgr

    def iter_contents(self) -> Iterator[str]:
        """Generate page filenames, then a ComicInfo.xml of the
        outline where the PDF has one."""
        yield from self.mgr.iter_contents()
        if self._outline() is not None:
            yield comicinfo.NAME

    def extract(self, filename: str, destination_dir: str) -> None:
        """Extract the named page file to a directory."""
        self._create_directory(destination_dir)
        if filename == comicinfo.NAME:
            self._write_outline(destination_dir)
            return
        list(self.mgr.extract_pages([filename], destination_dir))

    def _write_outline(self, destination_dir: str) -> None:
        document = self._outline()
        if document is None:
            return
        with self._create_file(os.path.join(destination_dir,
                                            comicinfo.NAME)) as new:
            new.write(document)

    def iter_extract(self, entries: Iterable[str], destination_dir: str) -> Iterator[str]:
        """Return a generator of extracted filepaths."""
        self._create_directory(destination_dir)
        entries = list(entries)
        if comicinfo.NAME in entries:
            entries.remove(comicinfo.NAME)
            self._write_outline(destination_dir)
            yield comicinfo.NAME
        yield from self.mgr.extract_pages(entries, destination_dir)
