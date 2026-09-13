"""Manager code for spawned processes in multiprocessing implementation
of PDF extractor."""

import sys
import threading
import multiprocessing as mp
from multiprocessing.managers import BaseManager, BaseProxy

from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, cast

from .child import FitzWorker


class GeneratorProxy(BaseProxy):
    """Proxy type for generator objects.

    A manager hands back a proxy rather than a value, and the default
    proxy has no way to step a generator: what crosses the process
    boundary here is a __next__ call at a time, so a listing arrives
    page by page rather than all at once at the end.
    """

    _exposed_ = ['__next__']

    def __iter__(self) -> 'GeneratorProxy':
        return self

    def __next__(self) -> str:
        # typeshed declares _callmethod as returning None; it actually hands
        # back whatever the proxied call returned, here a page filename.
        return cast(str, self._callmethod('__next__'))


class WorkerProxy(BaseProxy):
    """Proxy type for FitzWorker methods.

    This code will run in the child processes, when triggered by
    the registered methods of the Manager.
    """

    filename: str | None = None

    @classmethod
    def _open(cls, filename: str) -> None:
        """Remember which document the calls below are about.

        The worker process holds this for as long as it lives, so the
        document is named once rather than with every call.
        """
        cls.filename = filename

    @classmethod
    def _count_pages(cls) -> int:
        """How many pages the document has."""
        w = FitzWorker(cls.filename)
        return w.page_count()

    @classmethod
    def _list_pages(cls) -> Iterator[str]:
        """A name for every page, as a generator the parent steps."""
        w = FitzWorker(cls.filename)
        return w.iter_contents()

    @classmethod
    def _extract_pages(cls, entries: Iterable[str], save_path: str) -> Iterator[str]:
        """Write each of <entries> into <save_path>, naming it as it lands."""
        w = FitzWorker(cls.filename)
        for e in entries:
            w.extract_file(e, save_path)
            yield e


class FitzManager(BaseManager):
    """Multiprocessing manager to hold proxied worker callables.

    The register() calls below install each of these as a method of the
    class, so they exist only at run time; they are declared here for
    what they take and give back.
    """

    if TYPE_CHECKING:
        def open(self, filename: str) -> None: ...
        def page_count(self) -> int: ...
        def iter_contents(self) -> Iterator[str]: ...
        def extract_pages(self, entries: Iterable[str],
                          save_path: str) -> Iterator[str]: ...


FitzManager.register('open', WorkerProxy._open)
FitzManager.register('page_count', WorkerProxy._count_pages)
FitzManager.register('iter_contents', WorkerProxy._list_pages, proxytype=GeneratorProxy)
FitzManager.register('extract_pages', WorkerProxy._extract_pages, proxytype=GeneratorProxy)


class FitzProcessWrangler(threading.local):
    """Thread-local state object holding a FitzManager instance.

    This is necessary so that each Mcomix extractor thread has its own
    FitzManager instance (and, therefore, its own worker process).
    """

    def __init__(self, filename: str, log_level: int | None) -> None:
        self.mgr = FitzManager()
        self.mgr.start()
        self.mgr.open(filename)
        self.log = mp.get_logger()
        if log_level is not None:
            self.log.setLevel(log_level)

    def page_count(self) -> int:
        """Get the number of pages in the PDF."""
        return self.mgr.page_count()

    def iter_contents(self) -> Iterator[str]:
        """Return an iterator over all the page filenames in the PDF."""
        return self.mgr.iter_contents()

    def extract_pages(self, page_list: Iterable[str],
                      destination_dir: str) -> Iterator[str]:
        """Extract the listed pages to the given directory."""
        return self.mgr.extract_pages(page_list, destination_dir)


# Test code, this module can be called directly with one argument (a PDF
# filename), and will print a list of all pages in the PDF (produced by
# a spawned FitzWorker process)
if __name__ == "__main__":
    mp.freeze_support()
    mp.set_start_method('spawn')
    infile = sys.argv[1]
    import logging
    wrangler = FitzProcessWrangler(infile, log_level=logging.DEBUG)

    print(f"All pages in PDF {infile}:")
    for file in wrangler.iter_contents():
        print(f"  {file}")
