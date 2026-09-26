"""image_handler.py - Image handler that takes care of cacheing and giving out images."""

import os
import threading

from gi.repository import GdkPixbuf

from mcomix.preferences import prefs
from mcomix import i18n
from mcomix import tools
from mcomix import image_tools
from mcomix import thumbnail_tools
from mcomix import constants
from mcomix import callback
from mcomix import log
from mcomix.worker_thread import WorkerThread

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # main imports this module, so the window it is handed can only be
    # named while the checker is reading and not while Python is.
    from mcomix import main


class ImageHandler:

    """The pages of the open book: their files, their pixbufs, the cache.

    Pages are numbered from 1 throughout, so the first page is page 1.

    A page's file is written by the extractor's thread, and until that
    has happened there is nothing to read at the path this hands out.
    Other modules should therefore ask the handler for a page rather
    than opening the file themselves: only the handler knows how to
    wait for one that has not arrived yet.
    """

    def __init__(self, window: 'main.MainWindow') -> None:

        #: Reference to main window
        self._window = window

        #: Caching thread
        self._thread = WorkerThread(self._cache_pixbuf, name='image',
                                    sort_orders=True)

        #: List of image file names, either from extraction or directory
        self._image_files: list[str] | None = None
        #: Map of image file name to its index in _image_files
        self._image_file_index: dict[str, int] = {}
        #: Whether each page is shown wide, by its path and whether pages
        #: are turned by their metadata: what spread_start() reads of
        #: every page back to the last wide one, on every turn back.
        self._wide: dict[tuple[str, bool], bool] = {}
        #: Index of current page, or None before one has been chosen
        self._current_image_index: int | None = None
        #: A page to unpack the surroundings of next, see set_resume_page()
        self._resume_page: int | None = None
        #: Indexes of the pages whose file is out of the archive and can
        #: therefore be decoded
        self._available_images: set[int] = set()
        #: List of pixbufs we want to cache
        self._wanted_pixbufs: list[int] = []
        #: Pixbuf map from page > Pixbuf
        self._raw_pixbufs: dict[int, GdkPixbuf.Pixbuf] = {}
        #: Held while replace_pages() swaps the listing and the cache,
        #: and while _get_pixbuf() files a page it has read, so that a
        #: page read under one listing is never filed under the next.
        self._cache_lock = threading.Lock()

        self._window.filehandler.file_available += self._file_available

    @property
    def _cache_pages(self) -> int:
        """How many pages to keep in cache, as the preferences say now.

        Read every time rather than once, when the handler is built: the
        preferences dialog writes a new value and asks the handler to
        cache again in the same breath.
        """
        return prefs['max pages to cache']

    def _get_pixbuf(self, index: int) -> GdkPixbuf.Pixbuf:
        """Return the pixbuf indexed by <index> from cache.

        A page not in the cache is waited for and read from disk, and
        whatever comes of that is what the cache holds from then on: a
        page that will not load answers with image_tools.missing_page()
        rather than being tried again on every page turn.

        The cache is read with one dict.get() rather than a test and a
        lookup, because this runs on the caching thread as well as on
        the main one, and do_cacheing() empties the cache from the main
        thread while it does.
        """
        pixbuf = self._raw_pixbufs.get(index)
        if pixbuf is not None:
            return pixbuf

        self._wait_on_page(index + 1)
        image_files = self._image_files
        if index >= len(image_files or []):
            # An order the caching thread took before pages were taken
            # out of the book, which asks for a number the book no
            # longer has.  There is nothing to read and nothing to file,
            # and it is not a page that would not load.
            log.debug('Page %u is no longer in the book', index + 1)
            return image_tools.missing_page()
        try:
            pixbuf = image_tools.load_pixbuf((image_files or [])[index])
            tools.garbage_collect()
        except Exception as e:
            log.error('Could not load pixbuf for page %u: %r', index + 1, e)
            pixbuf = image_tools.missing_page()
        # The caching thread reads while the archive editor may rewrite
        # the pages, and after a deletion the number it was asked for
        # belongs to the page behind: filed there, that page showed the
        # one it had replaced.  Every listing is a list of its own, so
        # one that is no longer held means the read is nobody's page.
        with self._cache_lock:
            if self._image_files is image_files:
                self._raw_pixbufs[index] = pixbuf
        return pixbuf

    def get_pixbufs(self, number_of_bufs: int) -> list[GdkPixbuf.Pixbuf]:
        """Returns number_of_bufs pixbufs for the image(s) that should be
        currently displayed. This method might fetch images from disk, so make
        sure that number_of_bufs is as small as possible.

        None of them before a page has been set: there is no page to
        show yet, which is not the same thing as a page that will not
        load.
        """
        if self._current_image_index is None:
            return []
        result = []
        for i in range(number_of_bufs):
            result.append(self._get_pixbuf(self._current_image_index + i))
        return result

    def do_cacheing(self) -> None:
        """Make sure that the correct pixbufs are stored in cache. These
        are (in the current implementation) the current image(s), and
        if cacheing is enabled, also the one or two pixbufs before and
        after the current page. All other pixbufs are dropped, so that a
        book being read holds no more of itself than that.
        """
        if not self._window.filehandler.file_loaded:
            return

        # Flush caching orders.
        self._thread.clear_orders()
        # Get list of wanted pixbufs.
        wanted_pixbufs = self._ask_for_pages(self.get_current_page())
        if -1 != self._cache_pages:
            # We're not caching everything, remove old pixbufs.
            for index in set(self._raw_pixbufs) - set(wanted_pixbufs):
                del self._raw_pixbufs[index]
        log.debug('Caching page(s) %s', ' '.join([str(index + 1) for index in wanted_pixbufs]))
        self._wanted_pixbufs = wanted_pixbufs
        # Start caching available images not already in cache.
        wanted_pixbufs = [index for index in wanted_pixbufs
                          if index in self._available_images
                          and index not in self._raw_pixbufs]
        # The order they are wanted in is the order to read them in.
        orders = list(enumerate(wanted_pixbufs))
        if -1 == self._cache_pages:
            # Everything else that is unpacked follows, nearest first:
            # clearing the orders above dropped whatever was queued
            # after the last turn, and nothing else queues it again.
            listed = set(self._wanted_pixbufs) | set(self._raw_pixbufs)
            orders += [(self._background_priority(index), index)
                       for index in self._available_images
                       if index not in listed]
        if orders:
            self._thread.extend_orders(orders)

    def _background_priority(self, index: int) -> int:
        """The caching priority of a page outside the wanted ones, when
        the whole book is cached: after every wanted page, and nearer
        the current page sooner, the page ahead before the page behind.
        """
        current = self._current_image_index or 0
        return (self.get_number_of_pages() + 2 * abs(index - current)
                + (index < current))

    def _cache_pixbuf(self, wanted: tuple[int, int]) -> None:
        """Read one page into the cache, on the caching thread."""
        _priority, index = wanted
        log.debug('Caching page %u', index + 1)
        self._get_pixbuf(index)

    def set_page(self, page_num: int) -> None:
        """Set up filehandler to the page <page_num>.
        """
        assert 0 < page_num <= self.get_number_of_pages()
        self._current_image_index = page_num - 1
        self.do_cacheing()

    def get_virtual_double_page(self, page: int | None = None) -> bool:
        """Return True if the current state warrants use of virtual
        double page mode (i.e. if double page mode is on, the corresponding
        preference is set, and one of the two images that should normally
        be displayed has a width that exceeds its height), or if currently
        on the first page.  With "skip broken pages" set, also where one
        of the two has been read and would not load.
        """
        if page is None:
            page = self.get_current_page()

        if (page == 1 and
                prefs['virtual double page for fitting images'] & constants.SHOW_DOUBLE_AS_ONE_TITLE and
                self._window.filehandler.archive_type is not None):
            return True

        if (prefs['skip broken pages'] and prefs['default double page']
                and page < self.get_number_of_pages()
                and (self.is_broken(page) or self.is_broken(page + 1))):
            # Shown on its own, so that the page that would not load
            # beside it can be turned past.
            return True

        if (not prefs['default double page'] or
                not prefs['virtual double page for fitting images'] & constants.SHOW_DOUBLE_AS_ONE_WIDE or
                page == self.get_number_of_pages()):
            return False

        for page in (page, page + 1):
            if not self.page_is_available(page):
                return False
            if self._is_wide(page):
                return True

        return False

    def is_broken(self, page: int) -> bool:
        """Whether <page> has been read, and would not load.

        Only a page in the cache is known either way, which the pages
        on screen always are once they have been drawn.
        """
        pixbuf = self._raw_pixbufs.get(page - 1)
        return pixbuf is not None and image_tools.is_missing_image(pixbuf)

    def _is_wide(self, page: int) -> bool:
        """Whether <page> is shown wider than it is tall."""
        path = self.get_path_to_page(page)
        key = (path or '', bool(prefs['auto rotate from exif']))
        wide = self._wide.get(key) if path is not None else None
        if wide is None:
            width, height = self._get_displayed_size(page)
            wide = width > height
            if path is not None:
                self._wide[key] = wide
        return wide

    def spread_start(self, page: int) -> int | None:
        """The first page of the spread <page> is shown in, turning
        forward through the book.

        Which pages are shown together depends on where the pairing
        started, so this pairs forward from the nearest page that starts
        a spread whatever came before it: the first page, a wide page -
        always shown on its own - or the page after one.  None where a
        page on the way has not been extracted yet, so that nothing is
        known of its size.
        """
        if not self.page_is_available(page):
            return None
        if self._is_wide(page):
            return page
        start = page
        while start > 1:
            if not self.page_is_available(start - 1):
                return None
            if self._is_wide(start - 1):
                break
            start -= 1
        # Every page from <start> to <page> is narrow, so they are paired
        # two by two from <start> - after the title page, where that is
        # shown on its own - and <page> is in the pair its distance from
        # there says.
        if start == 1 and page > 1 and self.get_virtual_double_page(1):
            start = 2
        return start + (page - start) // 2 * 2

    def _get_displayed_size(self, page: int) -> tuple[int, int]:
        """Return the (width, height) <page> will be displayed at.

        Reads the image's header rather than decoding it, unless it happens
        to be in the cache already.  Every page stepped over is asked this,
        so decoding each one of them made holding a page key down crawl.
        """
        pixbuf = self._raw_pixbufs.get(page - 1)
        if pixbuf is not None:
            width, height = pixbuf.get_width(), pixbuf.get_height()
            rotation = (image_tools.get_implied_rotation(pixbuf)
                        if prefs['auto rotate from exif'] else 0)
        elif (path := self.get_path_to_page(page)) is not None:
            width, height = image_tools.get_image_size(path)
            rotation = (image_tools.get_implied_rotation_from_file(path)
                        if prefs['auto rotate from exif'] else 0)
        else:
            # No such page, so nothing will be displayed for it.
            return (0, 0)
        if tools.rotation_swaps_axes(rotation):
            width, height = height, width
        return width, height

    def get_real_path(self) -> str | None:
        """Return the "real" path to the currently viewed file, i.e. the
        full path to the archive or the full path to the currently
        viewed image.
        """
        if self._window.filehandler.archive_type is not None:
            return self._window.filehandler.get_path_to_base()
        return self.get_path_to_page()

    def cleanup(self) -> None:
        """Run clean-up tasks. Should be called prior to exit."""

        self._thread.stop()
        self.set_image_files([])
        self._current_image_index = None
        self._available_images.clear()
        self._raw_pixbufs.clear()

    def page_is_available(self, page: int | None = None) -> bool:
        """ Returns True if <page> is available and calls to get_pixbufs
        would not block. If <page> is None, the current page(s) are assumed. """

        if page is None:
            current_page = self.get_current_page()
            if not current_page:
                # Current 'book' has no page.
                return False
            indexes = [current_page - 1]
            if self._window.displayed_double() and \
                    current_page < self.get_number_of_pages():
                indexes.append(current_page)
        else:
            indexes = [page - 1]

        return all(index in self._available_images for index in indexes)

    @callback.Callback
    def page_available(self, page: int) -> None:
        """ Called whenever a new page becomes available, i.e. the corresponding
        file has been extracted. """
        log.debug('Page %u is available', page)
        index = page - 1
        assert index not in self._available_images
        self._available_images.add(index)
        # Check if we need to cache it.
        priority = None
        if index in self._wanted_pixbufs:
            # In the list of wanted pixbufs.
            priority = self._wanted_pixbufs.index(index)
        elif -1 == self._cache_pages:
            # We're caching everything.
            priority = self._background_priority(index)
        if priority is not None:
            self._thread.append_order((priority, index))

    def set_image_files(self, image_files: list[str]) -> None:
        """Set the list of image files making up the current book."""
        self._image_files = image_files
        # Lookup table for _file_available(), which would otherwise have to
        # scan the whole list again for every single file that shows up.
        self._image_file_index = {path: index
                                  for index, path in enumerate(image_files)}
        self._wide = {}
        self._resume_page = None

    def replace_pages(self, image_files: list[str]) -> None:
        """Rewrite the pages of the book that is already open as <image_files>.

        What the archive editor does when pages are reordered, deleted
        or added.  Everything the handler holds about a page - whether
        it has been extracted, and the pixbuf read for it - is keyed by
        position, and the editor is free to move a file to another
        position or drop it altogether.  So both are carried across by
        path: a page that moved is neither decoded again nor waited for
        again, one that is gone takes what was read of it with it, and
        no page inherits the answers given for the file that used to
        hold its number.

        Both are replaced rather than emptied and refilled, so that the
        caching thread reading them meets one listing or the other and
        never a half-built one, and both under the lock _get_pixbuf()
        files a page with, so that a page it was reading while this ran
        is not filed under the new listing.
        """
        with self._cache_lock:
            old_files = self._image_files or []
            # A number past the end of the listing is dropped rather than
            # looked up: there is no file to carry it across by.
            available = {old_files[index] for index in self._available_images
                         if index < len(old_files)}
            pixbufs = {old_files[index]: pixbuf
                       for index, pixbuf in self._raw_pixbufs.items()
                       if index < len(old_files)}
            self.set_image_files(image_files)
            self._available_images = {index for index, path
                                      in enumerate(image_files)
                                      if path in available}
            self._raw_pixbufs = {index: pixbufs[path]
                                 for index, path in enumerate(image_files)
                                 if path in pixbufs}

    def _file_available(self, filepaths: Iterable[str]) -> None:
        """ Called by the filehandler when a new file becomes available. """
        # Find the pages that correspond to <filepaths>, in page order.
        indexes = sorted(index for index in
                         map(self._image_file_index.get, filepaths)
                         if index is not None)
        for index in indexes:
            self.page_available(index + 1)

    def get_number_of_pages(self) -> int:
        """Return the number of pages in the current archive/directory."""
        if self._image_files is not None:
            return len(self._image_files)
        else:
            return 0

    def get_image_files(self) -> list[str]:
        """The files of the open book's pages, in page order.

        A copy, so that a caller can change it without changing the
        book; empty where no book is open.
        """
        return list(self._image_files or [])

    def get_current_page(self) -> int:
        """Return the current page number (starting from 1), or 0 if no file is loaded."""
        if self._current_image_index is not None:
            return self._current_image_index + 1
        else:
            return 0

    def get_path_to_page(self, page: int | None = None) -> str | None:
        """Return the full path to the image file for <page>, or the current
        page if <page> is None.
        """
        index = self._current_image_index if page is None else page - 1

        # There is a page to answer with only once the book has files and
        # one of them has been chosen.  Between set_image_files() and the
        # first set_page() there is neither, and comparing the index that
        # is not there against a length raised.
        if index is None or not self._image_files:
            return None
        if 0 <= index < len(self._image_files):
            return self._image_files[index]
        return None

    def get_page_filename(
            self, page: int | None = None,
            double: bool = False) -> str | tuple[str, str] | None:
        """Return the filename of the <page>, or the filename of the
        currently viewed page if <page> is None. If <double> is True, return
        a tuple (p, p') where p is the filename of <page> (or the current
        page) and p' is the filename of the page after.
        """
        if page is None:
            page = self.get_current_page()

        first_path = self.get_path_to_page(page)
        if first_path is None:
            return None

        if double:
            second_path = self.get_path_to_page(page + 1)

            if second_path is not None:
                first = os.path.basename(first_path)
                second = os.path.basename(second_path)
            else:
                return None

            return first, second

        return os.path.basename(first_path)

    def get_page_filesize(
            self, page: int | None = None,
            double: bool = False) -> str | tuple[str, str]:
        """Return the filesize of the <page>, or the filesize of the
        currently viewed page if <page> is None. If <double> is True, return
        a tuple (s, s') where s is the filesize of <page> (or the current
        page) and s' is the filesize of the page after.
        """
        returnvalue_on_error = ('', '') if double else ''

        if not self.page_is_available():
            return returnvalue_on_error

        if page is None:
            page = self.get_current_page()

        first_path = self.get_path_to_page(page)
        if first_path is None:
            return returnvalue_on_error

        if double:
            second_path = self.get_path_to_page(page + 1)
            if second_path is not None:
                try:
                    first = tools.format_byte_size(os.stat(first_path).st_size)
                except OSError:
                    first = ''
                try:
                    second = tools.format_byte_size(os.stat(second_path).st_size)
                except OSError:
                    second = ''
            else:
                return ('', '')
            return first, second

        try:
            size = tools.format_byte_size(os.stat(first_path).st_size)
        except OSError:
            size = ''

        return size

    def get_pretty_current_filename(self) -> str:
        """Return a string with the name of the currently viewed file that is
        suitable for printing.
        """
        index = self._current_image_index
        if self._window.filehandler.archive_type is not None:
            name = self._window.filehandler.get_base_filename()
        elif self._image_files and index is not None:
            img_file = os.path.abspath(self._image_files[index])
            name = os.path.join(
                os.path.basename(os.path.dirname(img_file)),
                os.path.basename(img_file)
            )
        else:
            name = ''

        return i18n.to_unicode(name)

    def get_size(self, page: int | None = None) -> tuple[int, int]:
        """Return a tuple (width, height) with the size of <page>. If <page>
        is None, return the size of the current page.
        """
        self._wait_on_page(page)

        page_path = self.get_path_to_page(page)
        if page_path is None:
            return (0, 0)

        return image_tools.get_image_size(page_path)

    def get_mime_name(self, page: int | None = None) -> str | None:
        """Return a string with the name of the mime type of <page>. If
        <page> is None, return the mime type name of the current page.
        """
        self._wait_on_page(page)

        page_path = self.get_path_to_page(page)
        if page_path is None:
            return None

        return image_tools.get_image_header(page_path)[0]

    def get_thumbnail(self, page: int | None = None, width: int = 128,
                      height: int = 128, create: bool = False,
                      nowait: bool = False) -> GdkPixbuf.Pixbuf | None:
        """Return a thumbnail pixbuf of <page> that fit in a box with
        dimensions <width>x<height>. Return a thumbnail for the current
        page if <page> is None.

        If <create> is True, and <width>x<height> <= 128x128, the
        thumbnail is also stored on disk.

        If <nowait> is True, don't wait for <page> to be available.
        """
        if not self._wait_on_page(page, check_only=nowait):
            # Page is not available!
            return None
        path = self.get_path_to_page(page)

        if path is None:
            return None

        thumbnailer = thumbnail_tools.Thumbnailer(store_on_disk=create,
                                                  size=(width, height))
        pixbuf = thumbnailer.thumbnail(path)
        # None from the thumbnailer is a page that would not load, which
        # every view of it shows as the missing icon; None from here is
        # a page not extracted yet, which the callers ask for again.
        if pixbuf is None:
            return image_tools.missing_image_icon(width, height)
        return image_tools.turned_as_shown(pixbuf, path)

    def _wait_on_page(self, page: int | None,
                      check_only: bool = False) -> bool:
        """Block until the file behind <page> has been fully extracted.

        Whichever thread calls it is the one that blocks: the main one
        while a page is being shown, and the caching thread while it
        reads ahead through _get_pixbuf().  Returns True once the page
        is there, and False if there is no page to wait for.

        If <check_only> is True, only check (and return status), don't wait.
        """
        if page is None:
            index = self._current_image_index
        else:
            index = page - 1
        if index is None:
            # No page has been chosen, so there is nothing to wait for.
            return False
        if index in self._available_images:
            # Already extracted!
            return True
        if check_only:
            # Asked for check only...
            return False

        log.debug('Waiting for page %u', index + 1)
        path = self.get_path_to_page(page)
        self._window.filehandler.wait_on_file(path)
        return True

    def _cache_window(self, page: int) -> list[int]:
        """The indexes of the pages around <page> worth keeping decoded,
        in the order they are wanted in: the page itself and the ones
        after it, then the ones before, clipped to the book.
        """
        if prefs['default double page']:
            page_width = 2
        else:
            page_width = 1
        if self._cache_pages == 0:
            # Only ask for current page.
            num_pages = page_width
        elif -1 == self._cache_pages:
            # Ask for 10 pages.
            num_pages = min(10, self.get_number_of_pages())
        else:
            num_pages = self._cache_pages
        # However small the budget, it has to cover what is on screen: this
        # list doubles as the set of pixbufs worth keeping, so leaving the
        # current page out of it throws that page away as it is being shown.
        num_pages = max(num_pages, page_width)

        # Look back only as far as the budget reaches past the current page.
        lead = min(page_width, num_pages - page_width)
        page_list = [page - 1 - lead + n for n in range(num_pages)]

        # Current and next page first, followed by previous page.
        previous_page = page_list[0:lead]
        del page_list[0:lead]
        page_list[2*page_width:2*page_width] = previous_page
        return [index for index in page_list
                if 0 <= index < self.get_number_of_pages()]

    def set_resume_page(self, page: int | None) -> None:
        """Unpack the pages around <page> right after those around the
        current one, or stop doing so if <page> is None.

        The page a book was left at, while the reader is asked whether
        to go back to it: the book is shown from its front meanwhile,
        and a "yes" should not then wait for everything in between.
        Forgotten when the book changes.
        """
        self._resume_page = page

    def _ask_for_pages(self, page: int) -> list[int]:
        """Ask for pages around <page> to be given priority extraction,
        and return the indexes of those worth keeping decoded.
        """
        page_list = self._cache_window(page)

        log.debug('Ask for priority extraction around page %u: %s',
                  page, ' '.join([str(n + 1) for n in page_list]))

        order = list(page_list)
        if self._resume_page is not None:
            order += [index for index in self._cache_window(self._resume_page)
                      if index not in page_list]

        # Every other page follows, nearest first and the one ahead
        # before the one behind at the same distance, so that the pages
        # the reader is likeliest to turn to next are the next ones
        # unpacked: a book opened at its end, or a jump into its middle,
        # otherwise went on to unpack it from its first page.
        current = page - 1
        listed = set(order)
        order += sorted((index for index in range(self.get_number_of_pages())
                         if index not in listed),
                        key=lambda index: (abs(index - current), index < current))

        image_files = self._image_files or []
        files = [image_files[index] for index in order
                 if index not in self._available_images]
        if files:
            self._window.filehandler.ask_for_files(files)

        return page_list

# vim: expandtab:sw=4:ts=4
