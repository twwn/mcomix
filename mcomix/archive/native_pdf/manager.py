"""Manager code for spawned processes in multiprocessing implementation
of PDF extractor."""

import sys
import threading
import multiprocessing as mp
from multiprocessing.managers import BaseManager, BaseProxy

from collections.abc import Generator

from .child import FitzWorker


class GeneratorProxy(BaseProxy):
    """Proxy type for generator objects."""

    _exposed_ = ['__next__']

    def __iter__(self):
        return self

    def __next__(self):
        return self._callmethod('__next__')


class WorkerProxy(BaseProxy):
    """Proxy type for FitzWorker methods.

    This code will run in the child processes, when triggered by
    the registered methods of the Manager.
    """

    filename: str | None = None

    @classmethod
    def _open(cls, filename):
        cls.filename = filename

    @classmethod
    def _count_pages(cls) -> int:
        w = FitzWorker(cls.filename)
        return w.page_count()

    @classmethod
    def _list_pages(cls) -> Generator[str, None, None]:
        w = FitzWorker(cls.filename)
        return w.iter_contents()

    @classmethod
    def _extract_pages(cls, entries, save_path: str) -> Generator[str, None, None]:
        w = FitzWorker(cls.filename)
        for e in entries:
            w.extract_file(e, save_path)
            yield e


class FitzManager(BaseManager):
    """Multiprocessing manager to hold proxied worker callables."""

    pass


FitzManager.register('open', WorkerProxy._open)
FitzManager.register('page_count', WorkerProxy._count_pages)
FitzManager.register('iter_contents', WorkerProxy._list_pages, proxytype=GeneratorProxy)
FitzManager.register('extract_pages', WorkerProxy._extract_pages, proxytype=GeneratorProxy)


class FitzProcessWrangler(threading.local):
    """Thread-local state object holding a FitzManager instance.

    This is necessary so that each Mcomix extractor thread has its own
    FitzManager instance (and, therefore, its own worker process).
    """

    def __init__(self, filename, log_level):
        self.mgr = FitzManager()
        self.mgr.start()
        self.mgr.open(filename)
        self.log = mp.get_logger()
        if log_level is not None:
            self.log.setLevel(log_level)

    def page_count(self) -> int:
        """Get the number of pages in the PDF."""
        return self.mgr.page_count()

    def iter_contents(self) -> Generator[str, None, None]:
        """Return an iterator over all the page filenames in the PDF."""
        return self.mgr.iter_contents()

    def extract_pages(self, page_list, destination_dir) -> Generator[str, None, None]:
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
