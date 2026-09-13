# -*- coding: utf-8 -*-

"""Multiprocessing PDF handler."""

import multiprocessing as mp
from mcomix.archive import archive_base
from mcomix.archive.native_pdf.manager import FitzProcessWrangler
from mcomix.log import getLevel

from collections.abc import Generator


class FitzArchive(archive_base.BaseArchive):
    """PDF file reader/extractor using PyMuPDF."""

    # Concurrent calls to extract welcome!
    support_concurrent_extractions = True

    def __init__(self, archive) -> None:
        """Initialize the object, first as a BaseArchive."""
        super().__init__(archive)
        self.log = mp.get_logger()
        self.log.setLevel(getLevel())
        self.log.debug("PDF contains %d pages", self.mgr.page_count())

    @staticmethod
    def is_available() -> bool:
        """Report whether this extractor is available (always true)."""
        return True

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

    def iter_contents(self) -> Generator[str, None, None]:
        """Generate page filenames."""
        return self.mgr.iter_contents()

    def extract(self, filename, destination_dir):
        """Extract the named page file to a directory."""
        self._create_directory(destination_dir)
        output = list(self.mgr.extract_pages([filename], destination_dir))
        if len(output) > 0:
            return True
        return False

    def iter_extract(self, entries: list[str], destination_dir: str) -> Generator[str, None, None]:
        """Return a generator of extracted filepaths."""
        self._create_directory(destination_dir)
        return self.mgr.extract_pages(entries, destination_dir)
