# -*- coding: utf-8 -*-

"""Multiprocessing PDF handler."""

import multiprocessing as mp
from mcomix.archive import archive_base
from mcomix.archive.native_pdf.manager import FitzProcessWrangler
from mcomix.log import getLevel

from collections.abc import Iterable, Iterator


class FitzArchive(archive_base.BaseArchive):
    """PDF file reader/extractor using PyMuPDF."""

    # Concurrent calls to extract welcome!
    support_concurrent_extractions = True

    def __init__(self, archive: str) -> None:
        """Initialize the object, first as a BaseArchive."""
        super().__init__(archive)
        self.log = mp.get_logger()
        self.log.setLevel(getLevel())
        self.log.debug("PDF contains %d pages", self.mgr.page_count())

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
        if not hasattr(self, '_mgr'):
            return self._open_doc()
        return self._mgr

    def iter_contents(self) -> Iterator[str]:
        """Generate page filenames."""
        return self.mgr.iter_contents()

    def extract(self, filename: str, destination_dir: str) -> None:
        """Extract the named page file to a directory."""
        self._create_directory(destination_dir)
        list(self.mgr.extract_pages([filename], destination_dir))

    def iter_extract(self, entries: Iterable[str], destination_dir: str) -> Iterator[str]:
        """Return a generator of extracted filepaths."""
        self._create_directory(destination_dir)
        return self.mgr.extract_pages(entries, destination_dir)
