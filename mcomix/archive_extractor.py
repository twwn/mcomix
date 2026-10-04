"""archive_extractor.py - Getting the pages of an archive onto disk.

MComix reads pages as files, so an archive has to be unpacked before
anything can be drawn.  The Extractor here does that in the background:
setup() opens the archive and starts a thread listing what is in it,
set_files() says which of those to unpack and in what order, and
extract() starts the threads that write them out one at a time.  Each
file that lands is announced twice over - through the file_extracted
callback, and by a notify on the Condition setup() hands back, which is
what lets a thread needing one particular page park until it is there
rather than poll for it.

The order matters because a reader is waiting on the page in front of
them: the file handler moves what is wanted to the head of the list as
the pages turn, so a book of two hundred pages opens on page one
without unpacking the other hundred and ninety-nine first.
"""


import os
import threading
import traceback

from mcomix import archive_tools
from mcomix import callback
from mcomix.archive import archive_base
from mcomix import log
from mcomix import tools
from mcomix.preferences import prefs
from mcomix.worker_thread import WorkerThread
from mcomix.i18n import _

from collections.abc import Iterable, Sequence


class Extractor:

    """One archive being unpacked, and the threads doing it.

    An extractor is used for one archive: setup() takes the archive and
    the directory to unpack it into, and close() ends it.  Between
    those, set_files() and extract() can be called as often as the
    reader turns pages - each call re-queues what is left in the new
    order.

    Three of its methods are callbacks rather than work:
    contents_listed(), listing_failed() and file_extracted() do nothing
    themselves and exist to be listened to, which mcomix.callback
    arranges to happen on the main thread whichever thread announced
    it.
    """

    def __init__(self) -> None:
        self._setupped = False
        self._archive: archive_base.BaseArchive | None = None
        # Everything else is filled in by setup(), which raises rather
        # than leaving any of it half done; nothing here works before
        # that has been called.
        self._dst: str
        self._files: list[str]
        self._extracted: set[str]
        self._contents_listed: bool
        self._extract_started: bool
        self._condition: threading.Condition
        self._list_thread: "WorkerThread[archive_base.BaseArchive]"
        self._extract_thread: "WorkerThread[str | list[str]]"

    @property
    def _opened_archive(self) -> archive_base.BaseArchive:
        """The archive setup() opened, which extracting anything needs.

        setup() raises rather than leaving this unset, so nothing here
        can be None; saying so beats an attribute error on None for
        whoever calls an extractor that was never set up.
        """
        if self._archive is None:
            raise ArchiveException('the extractor has not been set up')
        return self._archive

    def setup(self, src: str, dst: str,
              type: int | None = None) -> threading.Condition:
        """Open the archive <src> and unpack it into <dst> from now on.

        Returns the Condition that is notified after each file lands, so
        that a caller can wait on one becoming ready; is_ready() is what
        such a wait tests.  <type> names the format where the caller
        already knows it, and is worked out from the file otherwise.

        Raises ArchiveException where the format is not one MComix
        reads, rather than answering with a half-set-up extractor.
        Listing the archive starts here, in a thread of its own, and
        contents_listed() says when it is done.
        """
        self._dst = dst
        self._files = []
        self._extracted = set()
        self._archive = archive_tools.get_recursive_archive_handler(src, dst, type=type)
        if self._archive is None:
            msg = _('Non-supported archive format: %s') % os.path.basename(src)
            log.warning(msg)
            raise ArchiveException(msg)

        self._contents_listed = False
        self._extract_started = False
        self._condition = threading.Condition()
        self._list_thread = WorkerThread(self._list_contents, name='list')
        self._list_thread.append_order(self._archive)
        self._setupped = True

        return self._condition

    def get_files(self) -> list[str] | None:
        """Return a list of names of all the files the extractor is currently
        set for extracting. After a call to setup() this is by default all
        files found in the archive. The paths in the list are relative to
        the archive root and are not absolute for the files once extracted.
        """
        with self._condition:
            if not self._contents_listed:
                # The listing thread has not finished yet, so there is no
                # list to answer with rather than an empty one.
                return None
            return self._files[:]

    def get_directory(self) -> str:
        """Returns the root extraction directory of this extractor."""
        return self._dst

    def set_files(self, files: Iterable[str]) -> None:
        """Set the files that the extractor should extract from the archive in
        the order of extraction. Normally one would get the list of all files
        in the archive using get_files(), then filter and/or permute this
        list before sending it back using set_files().

        Files already unpacked are dropped from the list; a file being
        unpacked at this moment is not, so it is not begun again.  The
        order is only a request: a solid archive is unpacked in one pass
        in the order it is stored in, extract() below saying why, so
        what this sets for one of those is which files are wanted and
        not which comes first.

        Nothing happens for an archive that has not been listed yet,
        there being no list to filter.  The file handler sets the files
        again from contents_listed().
        """
        with self._condition:
            if not self._contents_listed:
                return
            self._files = [f for f in files if f not in self._extracted]
            if not self._files:
                # Nothing to do!
                return
            if self._extract_started:
                self.extract()

    def is_ready(self, name: str) -> bool:
        """Return True if the file <name> in the extractor's file list
        (as set by set_files()) is fully extracted.
        """
        with self._condition:
            return name in self._extracted

    def stop(self) -> None:
        """Signal the extractor to stop extracting and kill the extracting
        thread. Blocks until the extracting thread has terminated.
        """
        if self._setupped:
            self._list_thread.stop()
            if self._extract_started:
                self._extract_thread.stop()
                self._extract_started = False
            self._setupped = False

    def extract(self) -> None:
        """Start unpacking the files set_files() named, and return.

        Every file that lands notifies the Condition setup() returned
        and announces itself through file_extracted().  Calling this
        again while it is running drops the orders that have not been
        started and queues what is left over, which is how a page turn
        moves the page being waited for to the front.

        How many threads do the work is the archive's to say.  As many
        as the "max extract threads" preference allows where the format
        can be read by several at once, so that one slow page does not
        hold up the ones behind it; a single thread for a solid archive,
        where reaching a member means decompressing everything before it
        and the whole batch is cheaper in one pass than any one member
        is on its own.
        """
        with self._condition:
            if not self._contents_listed:
                return
            if not self._extract_started:
                if self._opened_archive.support_concurrent_extractions \
                   and not self._opened_archive.is_solid():
                    max_threads = tools.thread_count(
                        prefs['max extract threads'],
                        self._opened_archive.extraction_thread_memory)
                else:
                    max_threads = 1
                self._extract_thread = WorkerThread(self._extract_order,
                                                    name='extract',
                                                    max_threads=max_threads,
                                                    unique_orders=True)
                self._extract_started = True
            else:
                self._extract_thread.clear_orders()
            if self._opened_archive.is_solid():
                # One order for the batch, sorted: the worker thread
                # tells two orders apart by their first element, so the
                # same set of files has to come out under the same name
                # however the reader's page turns ordered it, or the
                # batch would be queued again beside the one running.
                self._extract_thread.append_order(sorted(self._files))
            else:
                self._extract_thread.extend_orders(self._files)

    @callback.Callback
    def contents_listed(self, extractor: 'Extractor',
                        files: list[str]) -> None:
        """Announce that the archive has been listed, with its files.

        A callback with no body of its own: whoever wants to know binds
        to it, and mcomix.callback runs them on the main thread.
        """
        pass

    @callback.Callback
    def listing_failed(self, extractor: 'Extractor', path: str) -> None:
        """Announce that the archive <path> could not be listed.

        contents_listed() is not called for it, and nothing is ever
        extracted from it.
        """
        pass

    @callback.Callback
    def file_extracted(self, extractor: 'Extractor',
                       filename: str) -> None:
        """Announce that <filename> is now on disk and can be read.

        The other half of the pair with contents_listed(): a listener
        that only wants to be told, rather than to wait, binds here
        instead of parking on the Condition.
        """
        pass

    def close(self) -> None:
        """Stop the threads and close the archive.

        Always called, whether anything was unpacked or not: this is
        what releases the handle the archive is open on, and stop()
        alone does not.  The files already unpacked are left where they
        are, their directory being the caller's to remove.
        """
        self.stop()
        if self._archive:
            self._archive.close()
            # Once only: the file handler closes the archive early,
            # once every member is out or before the book is moved or
            # written over, and again when the book itself is closed.
            self._archive = None

    def _extraction_finished(self, name: str) -> None:
        """Mark <name> as unpacked and wake everything waiting for it.

        A name that is no longer pending is still marked and still
        announced.  set_files() may narrow the list while a file is
        being unpacked - filtering it is what the method is for - and
        the file lands all the same; taking the wake-up away from it
        because the list had moved on would leave every thread in
        FileHandler.wait_on_file() parked on a page that is on disk.
        """
        with self._condition:
            if name in self._files:
                self._files.remove(name)
            self._extracted.add(name)
            self._condition.notify_all()
        self.file_extracted(self, name)

    def _extract_order(self, order: "str | list[str]") -> None:
        """Extract what one order names.

        A solid archive is extracted a batch at a time and any other one
        file at a time, so an order is either a list of names or a
        single name.
        """
        if isinstance(order, list):
            self._extract_all_files(order)
        else:
            self._extract_file(order)

    def _extract_all_files(self, files: Sequence[str]) -> None:
        """Unpack <files> in one pass, which is what a solid archive wants.

        The ones already on disk are dropped first: a batch queued
        before the last one finished can name files that have landed
        since, and unpacking a page twice would take it out of the
        pending list twice.  What is left is sorted, for the same reason
        the caller sorts - so that one set of files is one order.
        """
        with self._condition:
            files = list(set(files) - self._extracted)
            files.sort()

        try:
            for f in self._opened_archive.iter_extract(files, self._dst):
                if self._extract_thread.must_stop():
                    return
                self._extraction_finished(f)

            # A pass that ends without raising has still not always
            # handed over everything: the external handlers once
            # dropped every empty file.  What it left out is marked as
            # done, for the same reason as below.
            with self._condition:
                missing = [name for name in files
                           if name not in self._extracted]
            if missing:
                log.warning('! Not extracted in one pass: %s', ', '.join(missing))
            for name in missing:
                self._extraction_finished(name)

        except Exception as ex:
            # Logged rather than raised over, as _extract_file() does and
            # for the same reason: the window handles a missing page,
            # and a thread waiting on the condition does not handle a
            # file that never lands.  The pass stops at the first file it
            # cannot unpack, so every file after that one is missing too
            # and is marked done with it; left unmarked, each of them
            # kept whoever waited on it parked until the book was closed.
            log.error(_('! Extraction error: %s'), ex)
            log.debug('Traceback:\n%s', traceback.format_exc())
            if self._extract_thread.must_stop():
                return
            with self._condition:
                missing = [name for name in files
                           if name not in self._extracted]
            for name in missing:
                self._extraction_finished(name)

    def _extract_file(self, name: str) -> None:
        """Extract the file named <name> to the destination directory,
        mark the file as "ready", then signal a notify() on the Condition
        returned by setup().
        """

        try:
            self._opened_archive.extract(name, self._dst)

        except Exception as ex:
            # A file that cannot be unpacked is logged and left out
            # rather than raised over: the page is missing either way,
            # and the window handles a missing page, where a thread that
            # died here would leave whoever is waiting on the condition
            # waiting for good.
            log.error(_('! Extraction error: %s'), ex)
            log.debug('Traceback:\n%s', traceback.format_exc())

        if self._extract_thread.must_stop():
            return
        self._extraction_finished(name)

    def _list_contents(self, archive: archive_base.BaseArchive) -> None:
        """Read what is in <archive>, in the listing thread.

        Nothing is set until the whole listing is in hand, so a caller
        that asks get_files() part way through is told there is no list
        yet rather than handed half of one.  A listing that was stopped
        sets nothing at all.
        """
        files = []
        try:
            for f in archive.iter_contents():
                if self._list_thread.must_stop():
                    return
                files.append(f)
        except Exception:
            # The worker thread logs the error, but not which file it
            # was reading.
            log.error(_('! Could not read %s'), archive.archive)
            self.listing_failed(self, archive.archive)
            raise
        with self._condition:
            self._files = files
            self._contents_listed = True
        self.contents_listed(self, files)


class ArchiveException(Exception):
    """ Indicate error during extraction operations. """
    pass

# vim: expandtab:sw=4:ts=4
