"""image_handler.py - Image handler that takes care of cacheing and giving out images."""

import os
import traceback

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

from collections.abc import Iterable, Sequence
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

        #: Archive path, if currently opened file is archive
        self._base_path: str | None = None
        #: List of image file names, either from extraction or directory
        self._image_files: list[str] | None = None
        #: Map of image file name to its index in _image_files
        self._image_file_index: dict[str, int] = {}
        #: Index of current page, or None before one has been chosen
        self._current_image_index: int | None = None
        #: Indexes of the pages whose file is out of the archive and can
        #: therefore be decoded
        self._available_images: set[int] = set()
        #: List of pixbufs we want to cache
        self._wanted_pixbufs: list[int] = []
        #: Pixbuf map from page > Pixbuf
        self._raw_pixbufs: dict[int, GdkPixbuf.Pixbuf] = {}

        self._window.filehandler.file_available += self._file_available

    @property
    def _cache_pages(self) -> int:
        """How many pages to keep in cache, as the preferences say now.

        This was read once, when the handler was built, so changing the
        preference did nothing at all until the book was closed - even
        though the preferences dialog writes the new value and asks the
        handler to cache again in the same breath.
        """
        return prefs['max pages to cache']

    def _get_pixbuf(self, index: int) -> GdkPixbuf.Pixbuf:
        """Return the pixbuf indexed by <index> from cache.

        A page not in the cache is waited for and read from disk, and
        whatever comes of that is what the cache holds from then on: a
        page that will not load answers with the missing-image icon
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
        try:
            pixbuf = image_tools.load_pixbuf((self._image_files or [])[index])
            tools.garbage_collect()
        except Exception as e:
            log.error('Could not load pixbuf for page %u: %r', index + 1, e)
            pixbuf = image_tools.missing_image_icon()
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

    def get_pixbuf_auto_background(
            self,
            number_of_bufs: int) -> Sequence[float]:
        """ Returns an automatically calculated background color
        for the current page(s).

        <number_of_bufs> is one or two, the two page counts a screen
        can show.  The colour the preference names where there is no
        page to read one off, which is what the background is then
        painted in anyway.
        """

        pixbufs = self.get_pixbufs(number_of_bufs)

        if not pixbufs:
            fallback: Sequence[float] = prefs['bg colour']
            return fallback
        elif len(pixbufs) == 1:
            pixbufs[0] = self._window.enhancer.enhance(pixbufs[0])
            auto_bg = image_tools.get_most_common_edge_colour(pixbufs[0])
        elif len(pixbufs) == 2:
            left, right = pixbufs
            left = self._window.enhancer.enhance(left)
            right = self._window.enhancer.enhance(right)
            if self._window.is_manga_mode:
                left, right = right, left

            auto_bg = image_tools.get_most_common_edge_colour((left, right))
        else:
            assert False, 'Unexpected pixbuf count'

        return auto_bg

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
        if orders:
            self._thread.extend_orders(orders)

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
        on the first page.
        """
        if page is None:
            page = self.get_current_page()

        if (page == 1 and
                prefs['virtual double page for fitting images'] & constants.SHOW_DOUBLE_AS_ONE_TITLE and
                self._window.filehandler.archive_type is not None):
            return True

        if (not prefs['default double page'] or
                not prefs['virtual double page for fitting images'] & constants.SHOW_DOUBLE_AS_ONE_WIDE or
                page == self.get_number_of_pages()):
            return False

        for page in (page, page + 1):
            if not self.page_is_available(page):
                return False
            width, height = self._get_displayed_size(page)
            if width > height:
                return True

        return False

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
        self._base_path = None
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
            priority = self.get_number_of_pages()
        if priority is not None:
            self._thread.append_order((priority, index))

    def set_image_files(self, image_files: list[str]) -> None:
        """Set the list of image files making up the current book."""
        self._image_files = image_files
        # Lookup table for _file_available(), which would otherwise have to
        # scan the whole list again for every single file that shows up.
        self._image_file_index = {path: index
                                  for index, path in enumerate(image_files)}

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
        never a half-built one.
        """
        old_files = self._image_files or []
        # A number past the end of the listing is dropped rather than
        # looked up.  The caching thread writes into both of these, and
        # a page taken out of the book while it was reading one leaves
        # an entry behind for a page the book no longer has: _get_pixbuf
        # stores the missing-page icon under the number it failed on.
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
            name = '' if self._base_path is None \
                else os.path.basename(self._base_path)
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

        try:
            thumbnailer = thumbnail_tools.Thumbnailer(store_on_disk=create,
                                                      size=(width, height))
            return thumbnailer.thumbnail(path)
        except Exception:
            log.debug("Failed to create thumbnail for image `%s':\n%s",
                      path, traceback.format_exc())
            return image_tools.missing_image_icon()

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
        self._window.filehandler._wait_on_file(path)
        return True

    def _ask_for_pages(self, page: int) -> list[int]:
        """Ask for pages around <page> to be given priority extraction.
        """
        files = []
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
        page_list = [index for index in page_list
                     if 0 <= index < self.get_number_of_pages()]

        log.debug('Ask for priority extraction around page %u: %s',
                  page, ' '.join([str(n + 1) for n in page_list]))

        image_files = self._image_files or []
        for index in page_list:
            if index not in self._available_images:
                files.append(image_files[index])

        if files:
            self._window.filehandler._ask_for_files(files)

        return page_list

# vim: expandtab:sw=4:ts=4
