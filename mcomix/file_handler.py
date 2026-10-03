"""file_handler.py - Opening a book, and unpacking it as it is read.

A book is either an archive or a run of loose image files, and this is
what tells the two apart and hands the image handler a list of image
files either way.  For loose images that list is ready at once.  An
archive is unpacked into a temporary directory in the background, so
the list names files that do not exist yet: file_is_available() says
whether one has been written out, wait_on_file() blocks until it has,
and the file_available callback announces each one as it arrives.

Opening an archive is therefore not over when open_file() returns.  The
extractor lists the archive on a thread of its own and calls back into
_listed_contents(), which sorts the images out from the comment files
and goes on to _archive_opened() - and even that can end in a question
to the reader about resuming where they left off, whose answer arrives
later still.

Where the reader left off is kept in two places.  The library records
the last page read of each archive, which is what that question offers.
Separately, the file and page open at any moment are written to a
pickle of their own, and a start-up after "quit and save" reads it back
to reopen the book.
"""


import os
import shutil
import tempfile
import threading
import re
import pickle
from gi.repository import GLib, Gtk

from mcomix.preferences import prefs
from mcomix import archive_extractor
from mcomix import archive_tools
from mcomix import image_tools
from mcomix import tools
from mcomix import constants
from mcomix import file_provider
from mcomix import callback
from mcomix import log
from mcomix import last_read_page
from mcomix import message_dialog
from mcomix.library import backend
from mcomix import i18n
from mcomix.i18n import _

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # main imports this module, so the window it is handed can only be
    # named while the checker is reading and not while Python is.
    from mcomix import main
from mcomix.dialog import Response

from collections.abc import Callable


class FileHandler:

    """The FileHandler keeps track of the actual files/archives opened.

    While ImageHandler takes care of pages/images, this class provides
    the raw file names for archive members and image files, extracts
    archives, and lists directories for image files.
    """

    def __init__(self, window: 'main.MainWindow') -> None:
        #: Indicates if files/archives are currently loaded/loading.
        self.file_loaded = False
        self.file_loading = False
        #: None if current file is not an archive, or unrecognized format.
        self.archive_type: int | None = None

        #: The archive that is open, or the image file the book was
        #: opened at.  Not the page on screen: which page that is
        #: belongs to the image handler, and it moves as the book is
        #: read while this does not.
        self._current_file: str | None = None
        self._window = window
        #: Path to opened archive file, or directory containing current images.
        self._base_path: str | None = None
        #: Temporary directory used for extracting archives.
        self._tmp_dir: str | None = None
        #: Set when the file is closed, so that a thread waiting on an
        #: extraction gives up instead of waiting for a file that is no
        #: longer coming.
        self._stop_waiting = False
        #: List of comment files inside of the currently opened archive.
        self._comment_files: list[str] = []
        #: The members of the open archive that are neither pages nor
        #: comments: metadata files, above all, which nothing in MComix
        #: reads but which the archive is not the same archive without.
        self._other_files: list[str] = []
        #: Mapping of absolute paths to archive path names.
        self._name_table: dict[str, str] = {}
        #: Archive extractor.
        self._extractor = archive_extractor.Extractor()
        self._extractor.file_extracted += self._extracted_file
        self._extractor.contents_listed += self._listed_contents
        self._extractor.listing_failed += self._listing_failed
        #: Condition to wait on when extracting archives and waiting on files.
        self._condition: threading.Condition | None = None
        #: Provides a list of available files/archives in the open directory.
        self._file_provider: file_provider.FileProvider | None = None
        #: Which kind of file the walk through sibling directories is
        #: looking for, archives or images.
        self._directory_listmode = file_provider.FileProvider.IMAGES
        #: Keeps track of the last read page in archives
        self.last_read_page = last_read_page.LastReadPage(backend.LibraryBackend())
        #: Regexp used for determining which archive files are comment files.
        #: update_comment_extensions() just below fills it in.
        self._comment_re: re.Pattern[str]
        self.update_comment_extensions()

        self.last_read_page.set_enabled(bool(prefs['store recent file info']))

    @property
    def _archive_condition(self) -> threading.Condition:
        """The condition the extractor signals on, which an archive has.

        _open_archive() takes it from the extractor and puts it back to
        None if that raised, so an archive that opened has one.  Saying
        which invariant broke beats an attribute error on None for
        whoever asked about a file when no archive was open.
        """
        if self._condition is None:
            raise ValueError('no archive is open')
        return self._condition

    @property
    def _opened_provider(self) -> file_provider.FileProvider:
        """What lists the files beside the open one.

        There is one from _initialize_fileprovider() onwards, and
        close_file() is the only thing that takes it away again.
        """
        if self._file_provider is None:
            raise ValueError('no file has been opened')
        return self._file_provider

    def refresh_file(self, *args: object, **kwargs: object) -> None:
        """Close the current file(s)/archive and reload them.

        A file deleted since it was opened is replaced by the one nearest
        to it in its folder: the next in the folder's order, or the last
        where it was the last.  Only where the folder holds nothing of
        its kind is the reader told it is gone.
        """
        real_path = self._window.imagehandler.get_real_path()
        if self.file_loaded and real_path is not None:
            current_file = os.path.abspath(real_path)
            start_member = None
            if not os.path.exists(current_file):
                nearest = self._nearest_in_folder(current_file)
                if nearest is not None:
                    self.open_file(nearest, keep_fileprovider=True)
                    return
            if self.archive_type is not None:
                start_page = self._window.imagehandler.get_current_page()
                # The picture on screen, by its name in the archive: a
                # change to how the archive is sorted reopens it, and
                # the page number it had then names another picture.
                start_member = self.page_member(start_page)
            else:
                start_page = 0
            self.open_file(current_file, start_page, keep_fileprovider=True,
                           start_member=start_member)

    def _nearest_in_folder(self, gone: str) -> str | None:
        """The file of the open book's kind that is nearest to <gone> in
        its folder's order, or None where there is none."""
        mode = (file_provider.FileProvider.ARCHIVES
                if self.archive_type is not None
                else file_provider.FileProvider.IMAGES)
        files = [path for path in self._opened_provider.list_files(mode)
                 if path != gone and not archive_tools.is_later_volume(path)]
        if not files:
            return None
        # Where <gone> would be listed: sorted in among the rest, by a
        # key that may read the file, which then counts as empty and
        # old.
        placed = files + [gone]
        file_provider.FileProvider.sort_files(placed)
        index = placed.index(gone)
        return files[min(index, len(files) - 1)]

    def page_member(self, page: int) -> str | None:
        """The name within the open archive of the file of <page>, or
        None where no archive is open or the page has no file.

        What stays with a picture when the archive is sorted another
        way, which moves the page number.  Written with "/", as archives
        write it, whatever the system: it is kept in the preferences, the
        bookmarks and the library, which may be read on another system.
        """
        if self.archive_type is None or self._tmp_dir is None:
            return None
        path = self._window.imagehandler.get_path_to_page(page)
        if path is None:
            return None
        return os.path.relpath(path, self._tmp_dir).replace(os.sep, '/')

    def _extracted_path(self, member: str) -> str:
        """Where <member>, as page_member() names it, is extracted to."""
        return os.path.join(self._tmp_dir or '', os.path.normpath(member))

    def page_of_member(self, member: str) -> int | None:
        """The page of the open archive whose file is called <member>
        within it, or None where it has none."""
        if self.archive_type is None or self._tmp_dir is None:
            return None
        wanted = self._extracted_path(member)
        files = self._window.imagehandler.get_image_files()
        return files.index(wanted) + 1 if wanted in files else None

    def open_file(self, path: str | list[str], start_page: int = 0,
                  keep_fileprovider: bool = False,
                  start_member: str | None = None) -> bool:
        """Open the file pointed to by <path>.

        If <start_page> is 0 we show the first page, or the last read page
        if one was stored for this book. If it is positive we show that page,
        and if it is negative we show the last image.  <start_member>, the
        name of a file within an archive, is opened in preference to any
        of those where the archive still has it.

        Return True if the file is successfully loaded.  A book with
        changes that have not been written is asked about first, and
        the file is then opened once that question has been answered:
        the answer is not waited for, so the caller is told the file is
        being opened rather than that it failed to open.
        """
        def open_it() -> None:
            self._open_file(path, start_page, keep_fileprovider,
                            start_member)

        if self._window.file_actions.has_unsaved_changes():
            self._window.file_actions.before_closing(open_it)
            return True
        return self._open_file(path, start_page, keep_fileprovider,
                               start_member)

    def _open_file(self, path: str | list[str], start_page: int = 0,
                   keep_fileprovider: bool = False,
                   start_member: str | None = None) -> bool:
        """Open <path>, the book that was open having been dealt with."""

        self._close()

        # A later volume of a RAR set is the rest of the set from the
        # middle of a page on; the book is read from its first volume.
        if isinstance(path, str):
            path = archive_tools.first_volume(path) or path

        try:
            path = self._initialize_fileprovider(path, keep_fileprovider)
        except ValueError as ex:
            self._window.statusbar.set_message(str(ex))
            self._window.osd.show(str(ex))
            return False

        error_message = self._check_access(path)
        if error_message:
            # Nothing is open now: _close() has told the window about the
            # book that went, and file_opened() would mark this failure
            # as a book loaded.
            self._window.statusbar.set_message(error_message)
            self._window.osd.show(error_message)
            return False

        self.filelist = self._opened_provider.list_files()
        self.archive_type = archive_tools.archive_mime_type(path)
        self._directory_listmode = (file_provider.FileProvider.ARCHIVES
                                    if self.archive_type is not None
                                    else file_provider.FileProvider.IMAGES)
        self._start_page = start_page
        self._start_member = start_member
        self._current_file = os.path.abspath(path)
        self._stop_waiting = False

        # Actually open the file(s)/archive passed in path.
        if self.archive_type is not None:
            try:
                self._open_archive(self._current_file)
            except Exception as ex:
                self._window.statusbar.set_message(str(ex))
                self._window.osd.show(str(ex))
                # No archive is open, and nothing may take one for open:
                # _close() would wait on the condition it never got, and
                # raise, for this book and every one opened after it.
                self.archive_type = None
                self.file_opened()
                return False
            self.file_loading = True
            # The extractor is listing the archive on a thread of its own
            # and nothing is on screen until it answers, which on a large
            # archive is long enough to look like nothing happened.
            self._window.cursor_handler.set_busy(True)
        else:
            self._open_image_files()
            self._archive_opened(self.filelist)

        return True

    def _archive_opened(self, image_files: list[str]) -> None:
        """ Called once the archive has been opened and its contents listed.
        """

        self._window.cursor_handler.set_busy(False)
        self._window.imagehandler.set_image_files(image_files)
        self.file_opened()

        current_file = self._current_file or ''
        if not image_files:
            msg = _("No images in '%s'") % os.path.basename(current_file)
            self._window.statusbar.set_message(msg)
            self._window.osd.show(msg)

        else:
            if self.archive_type is None:
                # If no extraction is required, mark all files as available.
                self.file_available(self.filelist)
                # Set current page to current file.
                if self._current_file in self.filelist:
                    current_image_index = self.filelist.index(self._current_file)
                else:
                    current_image_index = 0
            else:
                last_image_index = self._get_index_for_page(self._start_page,
                                                            len(image_files),
                                                            current_file)
                start_member = self._start_member
                if start_member is None and self._start_page == 0:
                    # Where the book was left, found by its picture
                    # rather than its number where that was kept.
                    start_member = self.last_read_page.get_member(
                        current_file)
                if start_member is not None:
                    member = self._extracted_path(start_member)
                    if member in image_files:
                        last_image_index = image_files.index(member)
                # A page the caller asked for, or a standing "yes" to
                # the prompt below, opens the book where it was left.
                # That standing answer is the response the prompt was
                # last answered with, so it is compared against one
                # rather than asked whether it is there at all.
                remembered = prefs['stored dialog choices'].get(
                    message_dialog.RememberedDialog.RESUME_FROM_LAST_READ_PAGE)
                if self._start_page or remembered == Response.YES:
                    current_image_index = last_image_index
                else:
                    # The front of the book: either the prompt has still
                    # to be answered, or the standing answer is no.
                    current_image_index = 0
                if last_image_index != current_image_index:
                    # The prompt may yet turn to it, so it is unpacked
                    # right after the pages shown meanwhile.
                    self._window.imagehandler.set_resume_page(
                        last_image_index + 1)

            # A book opened at its end is arrived at backwards - from the
            # first page of the one after it - and is shown from the
            # bottom of its last page, as a page turned back to is.
            self._window.set_page(current_image_index + 1,
                                  at_bottom=self._start_page < 0)
            if (self._start_page < 0 and prefs['default double page']
                    and current_image_index + 2 == len(image_files)):
                self._window.arrive_at_end(current_image_index + 1)

            if self.archive_type is None:
                self.write_fileinfo_file()
            else:
                self._extractor.extract()
                if last_image_index == current_image_index:
                    self.write_fileinfo_file()
                else:
                    def resume(goto_last_read_page: bool) -> None:
                        """Finish opening once the prompt has been answered.

                        The file info records the current page, so it is
                        written when the answer has settled which that is."""
                        self._window.imagehandler.set_resume_page(None)
                        if goto_last_read_page:
                            self._window.set_page(last_image_index + 1)
                        self.write_fileinfo_file()

                    self._ask_goto_last_read_page(
                        current_file, last_image_index + 1, resume)

        self._window.uimanager.recent.add_path(current_file)

    @callback.Callback
    def file_opened(self) -> None:
        """ Called when a new set of files has successfully been opened. """
        self.file_loaded = True

    @callback.Callback
    def file_closed(self) -> None:
        """ Called when the current file has been closed. """
        pass

    def close_file(self) -> None:
        """Close the currently opened file and its provider.

        A book whose pages have been changed without being written is
        offered to the reader to write first: closing is what throws
        those changes away, and the offer made at the change itself may
        have been turned down by a reader who meant to go on editing.
        """
        self._window.file_actions.before_closing(
            lambda: self._close(close_provider=True))

    def _close(self, close_provider: bool = False) -> None:
        """Run tasks for "closing" the currently opened file(s)."""
        if self.file_loaded or self.file_loading:
            if close_provider:
                self._file_provider = None
            self.update_last_read_page()
            if self.archive_type is not None:
                # Wake whatever is parked in wait_on_file() before the
                # extractor stops.  The only notify_all() there is fires
                # when a file finishes extracting, and after this no
                # file will, so a waiter that is not woken here waits
                # for good - on a condition the next archive replaces.
                # The flag is set under the lock as well, or a waiter
                # that has just tested it and not yet parked would miss
                # the wake-up.  cleanup() below joins the caching
                # thread, which is one of the two that park there.
                with self._archive_condition:
                    self._stop_waiting = True
                    self._archive_condition.notify_all()
                self._extractor.close()
            self._window.imagehandler.cleanup()
            self.file_loaded = False
            self.file_loading = False
            self.archive_type = None
            self._current_file = None
            self._base_path = None
            self._stop_waiting = True
            self._comment_files = []
            self._other_files = []
            self._name_table.clear()
            # A listing that was still running will not reach
            # _archive_opened(), since _listed_contents() gives up on a
            # file_loading that has been cleared: the wait cursor has to go
            # from here or it would stay for the rest of the session.
            self._window.cursor_handler.set_busy(False)
            self.file_closed()
        # Catch up on UI events, so we don't leave idle callbacks.
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        tools.garbage_collect()
        if self._tmp_dir is not None:
            self.thread_delete(self._tmp_dir)
            self._tmp_dir = None

    def _initialize_fileprovider(self, path: str | list[str],
                                 keep_fileprovider: bool) -> str:
        """Set up what lists the files around <path>; return the one to open.

        A list of names is taken to be the whole of what should be
        available, and the first of them is the one to open.  A single
        name is the classic Comix way round: the file or directory named
        brings the rest of its directory with it, and the name itself is
        what opens.

        <keep_fileprovider> leaves a provider that is already there
        alone, which is how refreshing a file, paging on into the next
        archive and walking into the next directory keep the listing
        they have instead of starting a fresh one around the new file.

        Raises ValueError, carrying a message meant for the reader, for
        a single name that is neither a file nor a directory.
        """

        if isinstance(path, list) and not path:
            # This is a programming error and does not need translation.
            assert False, "Tried to open an empty list of files."

        elif isinstance(path, list) and path:
            # A list of files was passed - open only these files.
            if self._file_provider is None or not keep_fileprovider:
                self._file_provider = file_provider.get_file_provider(path)

            return path[0]
        else:
            # A single file was passed - use Comix' classic open mode
            # and open all files in its directory.
            assert isinstance(path, str)
            if self._file_provider is None or not keep_fileprovider:
                self._file_provider = file_provider.get_file_provider([path])

            return path

    def _check_access(self, path: str) -> str | None:
        """Return why <path> cannot be opened, or None if it can.

        The answer is shown to the reader, so it is translated.
        """
        if not os.path.exists(path):
            return _('Could not open %s: No such file.') % path

        elif not os.access(path, os.R_OK):
            return _('Could not open %s: Permission denied.') % path

        else:
            return None

    def _open_archive(self, path: str) -> None:
        """Point the extractor at the archive <path>, and return at once.

        Nothing has been listed and nothing extracted by the time this
        is done.  The extractor reads the archive on a thread of its own
        and calls _listed_contents() when it knows what is in there,
        which is where the opening carries on.  What is kept here is the
        temporary directory the archive will be unpacked into, and the
        condition the extractor signals on as files appear.

        An archive that cannot be opened - an unsupported format, most
        often - raises, and the condition is put back to None so that a
        later question about a file cannot find a half-open archive.
        """

        self._tmp_dir = tempfile.mkdtemp(prefix='mcomix.', suffix=os.sep)
        self._base_path = path
        try:
            self._condition = self._extractor.setup(self._base_path,
                                                    self._tmp_dir,
                                                    self.archive_type)
        except Exception:
            self._condition = None
            raise

    def _listed_contents(self, archive: archive_extractor.Extractor,
                         files: list[str]) -> None:

        if not self.file_loading:
            return
        self.file_loading = False

        archive_images = [image for image in files
                          if image_tools.is_image_file(image)
                          # Remove MacOS meta files from image list
                          and '__MACOSX' not in os.path.normpath(image).split(os.sep)]

        self._sort_archive_images(archive_images)
        # An archive is being listed, so it was extracted somewhere.
        tmp_dir = self._tmp_dir or ''
        image_files = [os.path.join(tmp_dir, f)
                       for f in archive_images]

        comment_files = list(filter(self._comment_re.search, files))
        tools.alphanumeric_sort(comment_files)
        self._comment_files = [os.path.join(tmp_dir, f)
                               for f in comment_files]

        # Whatever is left is carried rather than read: a ComicInfo.xml
        # the comment extensions do not cover, an OPF, a JSON sidecar.
        # MComix has nothing to do with any of it, but the archive
        # editor writes a new archive out of what it was given, so
        # anything not named here is dropped the moment a book is saved.
        # The files Finder leaves behind are not part of the book, and
        # are left out here as they are left out of the pages.
        accounted = set(archive_images) | set(comment_files)
        other_files = [name for name in files
                       if name not in accounted
                       and not name.endswith('/')
                       and '__MACOSX' not in
                       os.path.normpath(name).split(os.sep)]
        self._other_files = [os.path.join(tmp_dir, f) for f in other_files]

        self._name_table = dict(list(zip(image_files, archive_images)))
        self._name_table.update(list(zip(self._comment_files, comment_files)))
        self._name_table.update(list(zip(self._other_files, other_files)))

        self._extractor.set_files(archive_images + comment_files + other_files)

        self._archive_opened(image_files)

    def _listing_failed(self, archive: archive_extractor.Extractor,
                        path: str) -> None:
        """Tell the reader the archive <path> could not be read.

        Nothing is opened: as for a name that is not there, the book
        before it has gone and nothing claims to be open.  The archive
        is closed as one still being listed is, which lets go of the
        extractor's threads and the wait cursor; the folder's other
        books stay a page turn away.
        """
        if not self.file_loading or path != self._base_path:
            return
        self._close()
        message = _('Could not read %s') % os.path.basename(path)
        self._window.statusbar.set_message(message)
        self._window.osd.show(message)

    def _sort_archive_images(self, filelist: list[str]) -> None:
        """Sort <filelist> in place, by the archive sort preferences.

        One of the choices is not to sort at all, which leaves the order
        the archive itself gave; a descending sort order still reverses
        that.
        """

        if prefs['sort archive by'] == constants.SORT_NAME:
            tools.alphanumeric_sort(filelist)
        elif prefs['sort archive by'] == constants.SORT_NAME_LITERAL:
            filelist.sort()
        elif prefs['sort archive by'] == constants.SORT_NAME_GLIB:
            # Names the collation cannot tell apart are put in natural
            # order, rather than left in the order the archive lists them.
            filelist.sort(key=lambda filename: (
                GLib.utf8_collate_key_for_filename(os.path.basename(filename), -1),
                tools.AlphanumericSortKey(filename)))
        else:
            # No sorting
            pass

        if prefs['sort archive order'] == constants.SORT_DESCENDING:
            filelist.reverse()

    def _get_index_for_page(self, start_page: int, num_of_pages: int,
                            path: str) -> int:
        """The index, not the page number, to open the archive <path> at.

        A negative <start_page> means the end of the book, which in
        double page mode is the second page from the end so that the
        last pair is what shows.  Zero means wherever the book was left
        off, or its first page when nothing was recorded for it.
        Anything else is that page.

        The answer is clamped to the <num_of_pages> pages there are,
        because <start_page> is whatever the caller had - a bookmark,
        the page a "quit and save" ended on, a preference - and none of
        those need still fit this book.
        """
        if start_page < 0 and prefs['default double page']:
            current_image_index = num_of_pages - 2
        elif start_page < 0 and not prefs['default double page']:
            current_image_index = num_of_pages - 1
        elif start_page == 0:
            current_image_index = (self.last_read_page.get_page(path) or 1) - 1
        else:
            current_image_index = start_page - 1

        return min(max(0, current_image_index), num_of_pages - 1)

    def _ask_goto_last_read_page(self, path: str, last_read_page: int,
                                 on_answer: Callable[[bool], None]) -> None:
        """ If the user read an archive previously, ask whether to continue
        from where they stopped, or from page 1.

        Calls <on_answer> with True to resume.  The answer arrives later,
        so anything that depends on which page is current has to wait for
        it rather than follow this call. """

        read_date = self.last_read_page.get_date(path)
        if read_date is None:
            # The record went between the page and the date being read,
            # which is what another window closing the same book does,
            # so there is nothing left to resume to.  The answer still
            # comes from the main loop, as it does from the dialog.
            def no_record() -> bool:
                on_answer(False)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(no_record)
            return

        dialog = message_dialog.MessageDialog(
            self._window, modal=True, buttons=Gtk.ButtonsType.YES_NO)
        dialog.set_default_response(Response.YES)
        dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.RESUME_FROM_LAST_READ_PAGE)
        dialog.set_text(
            (_('Continue reading from page %d?') % last_read_page),
            _('You stopped reading here on %(date)s, %(time)s. '
              'If you choose "Yes", reading will resume on page %(page)d. Otherwise, '
              'the first page will be loaded.') % {'date': read_date.date().strftime("%x"),
                                                   'time': read_date.time().strftime("%X"), 'page': last_read_page})
        dialog.run_async(lambda response: on_answer(response == Response.YES))

    def _open_image_files(self) -> None:
        """Note the directory the loose image files sit in.

        The counterpart of _open_archive() for a book that is a
        directory of images, which needs no opening: they are already
        there, and what the rest of the handler wants is the base path.
        Which of them to show is worked out by _archive_opened(), the
        same way for both kinds of book.
        """

        self._base_path = self._opened_provider.get_directory()

    def get_file_number(self) -> tuple[int, int]:
        if self.archive_type is None:
            # No file numbers for images.
            return 0, 0
        file_list = self._opened_provider.list_files(
            file_provider.FileProvider.ARCHIVES)
        if self._current_file in file_list:
            current_index = file_list.index(self._current_file)
        else:
            current_index = 0
        return current_index + 1, len(file_list)

    def get_number_of_comments(self) -> int:
        """Return the number of comments in the current archive."""
        return len(self._comment_files)

    def get_comment_text(self, num: int) -> str | None:
        """Return the text in comment <num> or None if comment <num> is not
        readable.

        The file was read as text, which decodes it in whatever encoding
        the machine's locale names - so a comment written in another one
        raised UnicodeDecodeError and the dialog said it could not read
        the file at all.  Nothing says what encoding a text file inside
        an archive is in, so the bytes are read and i18n.to_unicode()
        works it out, as it does for the names of the files beside it.
        """
        self._wait_on_comment(num)
        try:
            with open(self._comment_files[num - 1], 'rb') as fd:
                data = fd.read()
        except Exception:
            return None
        return i18n.to_unicode(data)

    def get_comment_name(self, num: int) -> str:
        """Return the filename of comment <num>."""
        return self._comment_files[num - 1]

    def wait_for_files(self, paths: "Iterable[str]") -> None:
        """Block until every one of <paths> is out of the archive.

        What writing the open archive back over itself needs: a page
        that has not been extracted yet cannot be written into the new
        archive, and once the old one has been replaced the name it
        would have been read under is not in it any more.
        """
        for path in paths:
            self.wait_on_file(path)

    def release_archive(self) -> None:
        """Unpack what is left of the open archive, and close its file.

        Windows neither moves nor replaces a file that is open, and the
        extractor holds the archive open until every member is out
        (_extracted_file() lets go of it then), so moving the book or
        writing it back over itself soon after opening it failed there with
        "The process cannot access the file because it is being used by
        another process".  Whatever moves the archive or writes over it
        calls this first.  Every member is waited for before the file is
        closed, since nothing more comes out of it until the book is
        opened again.
        """
        if self.archive_type is None:
            return
        self.wait_for_files(list(self._name_table))
        self._extractor.close()

    def get_other_files(self) -> dict[str, str]:
        """The archive members that are neither pages nor comments.

        Keyed by the path each was extracted to, valued by the name it
        had in the archive - which is the name it has to go back under,
        directory and all, for the archive to still hold what it held.
        Each is waited for, since a file that is not out yet cannot be
        written into a new archive.
        """
        carried = {}
        for path in self._other_files:
            self.wait_on_file(path)
            if os.path.isfile(path):
                carried[path] = self._name_table[path]
        return carried

    def get_member_names(self) -> dict[str, str]:
        """Every archive member that is not a page - the comments and
        the files carried along with them - keyed by the path it is
        extracted to and valued by its name in the archive.

        Nothing is waited for.  This is for a caller on the main thread
        that only needs to know what is there: whether a member is out
        yet is for file_is_available() to say, and ask_for_files() moves
        it to the front of the queue.  The comments are in it because
        the default comment extensions take in .xml, which is where a
        ComicInfo.xml usually ends up.
        """
        return {path: self._name_table[path]
                for path in self._comment_files + self._other_files}

    def update_comment_extensions(self) -> None:
        """Update the regular expression used to filter out comments in
        archives by their filename.

        The extensions are what a reader typed into the preferences,
        not a pattern: joined into one as they stood, "c++" matched
        "cc", "a.b" matched "axb", and a lone bracket raised re.error
        here - in the handler's constructor, so MComix would not start
        at all until the preferences file was edited by hand.
        """
        self._comment_re = re.compile(
            r'\.' + tools.fixed_strings_regex(prefs['comment extensions'])
            + r'\s*$', re.I)

    def get_path_to_base(self) -> str | None:
        """Return the full path to the current base (path to archive or
        image directory.)
        """
        if self.archive_type is not None:
            return self._base_path
        # Otherwise it is the directory the current image sits in, and
        # there is no current image until a page has been chosen.
        path = self._window.imagehandler.get_path_to_page()
        return os.path.dirname(path) if path is not None else None

    def get_base_filename(self) -> str:
        """Return the filename of the current base (archive filename or
        directory name), or the empty string where there is no base yet.
        """
        base = self.get_path_to_base()
        return '' if base is None else os.path.basename(base)

    def get_pretty_current_filename(self) -> str:
        """Return a string with the name of the currently viewed file that is
        suitable for printing.
        """

        return self._window.imagehandler.get_pretty_current_filename()

    def open_next_archive(self, *args: object) -> bool:
        """Open the archive that comes directly after the currently loaded
        archive in that archive's directory listing, sorted alphabetically.
        Returns True if a new archive was opened, False otherwise.

        The later volumes of a RAR set are passed over: the set is read
        from its first volume, and one of the others opened by itself
        is what is left of the set from there on.
        """
        if self.archive_type is not None:

            files = self._opened_provider.list_files(
                file_provider.FileProvider.ARCHIVES)
            absolute_path = os.path.abspath(self._base_path or '')
            if absolute_path not in files:
                return False
            current_index = files.index(absolute_path)

            for path in files[current_index + 1:]:
                if archive_tools.archive_mime_type(path) is not None \
                        and not archive_tools.is_later_volume(path):
                    # open_file() closes this book itself, once it has
                    # asked about changes that have not been written.
                    self.open_file(path, keep_fileprovider=True)
                    return True

        return False

    def open_previous_archive(self, *args: object) -> bool:
        """Open the archive that comes directly before the currently loaded
        archive in that archive's directory listing, sorted alphabetically.
        Returns True if a new archive was opened, False otherwise.
        """
        if self.archive_type is not None:

            files = self._opened_provider.list_files(
                file_provider.FileProvider.ARCHIVES)
            absolute_path = os.path.abspath(self._base_path or '')
            if absolute_path not in files:
                return False
            current_index = files.index(absolute_path)

            for path in reversed(files[:current_index]):
                if archive_tools.archive_mime_type(path) is not None \
                        and not archive_tools.is_later_volume(path):
                    # See open_next_archive().
                    self.open_file(path, prefs['open first file in prev archive']-1,
                                   keep_fileprovider=True)
                    return True

        return False

    def next_archive(self, *args: object) -> bool:
        """The Next archive command: open_next_archive(), and past the
        folder's last archive, with "auto open next directory" on, the
        first book of the next folder that has one, as a page turn past
        the book's end opens it.

        Only the command goes on: deleting the last archive opens the one
        before it in its folder, and a page turn walks on by itself.
        """
        if self.open_next_archive():
            return True
        return self._at_end_of_archives(-1) and self.open_next_directory()

    def previous_archive(self, *args: object) -> bool:
        """The Previous archive command, next_archive() the other way."""
        if self.open_previous_archive():
            return True
        return self._at_end_of_archives(0) and self.open_previous_directory()

    def _at_end_of_archives(self, end: int) -> bool:
        """Whether the open book is the archive at the end <end> (0 or -1)
        of its folder's archives, the later volumes of RAR sets left out,
        and the walk past it is wanted."""
        if self.archive_type is None or not prefs['auto open next directory']:
            return False
        files = [path for path in self._opened_provider.list_files(
                     file_provider.FileProvider.ARCHIVES)
                 if not archive_tools.is_later_volume(path)]
        return bool(files) and \
            files[end] == os.path.abspath(self._base_path or '')

    def open_next_directory(self, *args: object) -> bool:
        """Open the first book in the next directory on the shelf that
        holds one (see file_provider.OrderedFileProvider).  Returns True
        if one was opened, or if it is being opened once the book has
        been dealt with.

        The walk moves the file provider on before anything is opened, so
        a book with changes that have not been written is asked about
        first, and the walk waits for the answer.
        """

        if self._file_provider is None:
            return False
        return self._once_dealt_with(self._open_next_directory)

    def _once_dealt_with(self, step: "Callable[[], bool]") -> bool:
        """Run <step> once the open book has been dealt with, and return
        what it answers, or True where it is waiting for an answer."""
        answer: list[bool] = []
        self._window.file_actions.before_closing(lambda: answer.append(step()))
        return answer[0] if answer else True

    def _open_next_directory(self) -> bool:
        """open_next_directory(), the book having been dealt with."""
        if self._file_provider is None:
            return False

        listmode = self._directory_listmode
        files: list[str] = []

        def has_books() -> bool:
            files[:] = self._books_in_directory(listmode)
            return bool(files)

        # Directories with no book in them are passed over; at the end
        # of the shelf the provider is left where it was.
        if not self._file_provider.next_directory(has_books):
            return False

        self._close()
        self.open_file(files[0], keep_fileprovider=True)
        # Whatever opened - a book of the other kind - the walk goes on
        # looking for the kind it set out over.
        self._directory_listmode = listmode
        return True

    def _books_in_directory(self, listmode: int) -> list[str]:
        """What a walk into the directory now listed opens one of.

        The files of the kind <listmode> names, the kind the walk set out
        over, or the other kind where the directory holds none of those:
        a walk from an archive into a directory of loose images opens the
        images, and one from loose images into a directory of archives
        opened the directory as a book with no pages.  Empty where the
        directory holds neither.
        """
        assert self._file_provider is not None
        other = (file_provider.FileProvider.IMAGES
                 if listmode == file_provider.FileProvider.ARCHIVES
                 else file_provider.FileProvider.ARCHIVES)
        for mode in (listmode, other):
            # The later volumes of a RAR set are read through its first,
            # and are not books to open by themselves.
            files = [path for path in self._file_provider.list_files(mode)
                     if not archive_tools.is_later_volume(path)]
            if files:
                return files
        return []

    def open_previous_directory(self, *args: object) -> bool:
        """Open a book in the previous directory on the shelf that holds
        one, the last unless the preferences say the first.  Returns as
        open_next_directory() does."""

        if self._file_provider is None:
            return False
        return self._once_dealt_with(self._open_previous_directory)

    def _open_previous_directory(self) -> bool:
        """open_previous_directory(), the book having been dealt with."""
        if self._file_provider is None:
            return False

        listmode = self._directory_listmode
        files: list[str] = []

        def has_books() -> bool:
            files[:] = self._books_in_directory(listmode)
            return bool(files)

        # See _open_next_directory().
        if not self._file_provider.previous_directory(has_books):
            return False

        self._close()
        path = files[prefs['open first file in prev directory']-1]
        self.open_file(path, (
            prefs['open first file in prev archive'] or
            prefs['open first file in prev directory'])-1,
                       keep_fileprovider=True)
        # See open_next_directory().
        self._directory_listmode = listmode
        return True

    def file_is_available(self, filepath: str | None) -> bool:
        """ Returns True if the file specified by "filepath" is available
        for reading, i.e. extracted to harddisk. """

        if filepath is None:
            # Asked about no file at all, which is never available.  This
            # was tested for after the archive branch below, which looked
            # the name up in a table keyed by path and raised a KeyError.
            return False

        elif self.archive_type is not None:
            with self._archive_condition:
                return self._extractor.is_ready(self._name_table[filepath])

        elif os.path.isfile(filepath):
            return True

        else:
            return False

    @callback.Callback
    def file_available(self, filepaths: list[str]) -> None:
        """Announce that the files named in <filepaths> can now be read.

        A callback, so what it does is whatever has subscribed to it:
        the image handler, which is waiting to draw those pages, and the
        comments dialog.  Loose image files are all announced in one go
        when the book opens, since none of them has to be extracted
        first.
        """
        pass

    def _extracted_file(self, extractor: archive_extractor.Extractor,
                        name: str) -> None:
        """ Called when the extractor finishes extracting the file at
        <name>. This name is relative to the temporary directory
        the files were extracted to. """
        if not self.file_loaded:
            return
        filepath = os.path.join(extractor.get_directory(), name)
        self.file_available([filepath])
        if self._extractor.get_files() == []:
            # Every member is out, and nothing more is read from the
            # archive until the book is opened again, so its file is let
            # go: Windows deletes, moves and renames no file that is
            # open, and the reader expects to do all three in Explorer
            # to a book they are only reading.  Closing again is a no-op.
            self._extractor.close()

    def _wait_on_comment(self, num: int) -> None:
        """Block the running (main) thread until the file corresponding to
        comment <num> has been fully extracted.
        """
        path = self._comment_files[num - 1]
        self.wait_on_file(path)

    def wait_on_file(self, path: str | None) -> None:
        """Block until the file <path> has been extracted, and return.

        Returns at once for a loose image, and for an archive member the
        extractor has already written out.  Otherwise it waits on the
        condition the extractor signals, so it blocks whichever thread
        called it: the main one when a page is turned to a file that is
        not out yet, and the image handler's caching thread when it
        reads ahead.  _stop_waiting, which closing the file sets, is the
        other way out of the wait.
        """
        if self.archive_type is None or path is None:
            return

        try:
            name = self._name_table[path]
            condition = self._archive_condition
            with condition:
                while not self._extractor.is_ready(name) and not self._stop_waiting:
                    condition.wait()
        except Exception as ex:
            log.error('Waiting on extraction of "%s" failed: %s', path, ex)
            return

    def ask_for_files(self, files: Sequence[str]) -> None:
        """Ask for <files> to be given priority for extraction.

        They go to the front in the order given, and whatever else is
        still to be unpacked follows in the order it was in.  The image
        handler names every page not unpacked yet on each page turn, so
        this is one pass over the list rather than a move per name.
        """
        if self.archive_type is None:
            return

        with self._archive_condition:
            extractor_files = self._extractor.get_files()
            if extractor_files is None:
                # The archive has not been listed yet, so there is no
                # order of extraction to move anything to the front of.
                return
            pending = set(extractor_files)
            first = list(dict.fromkeys(
                name for name in (self._name_table[path] for path in files)
                if name in pending))
            moved = set(first)
            self._extractor.set_files(
                first + [name for name in extractor_files if name not in moved])

    def thread_delete(self, path: str) -> None:
        """Start a threaded removal of the directory tree rooted at <path>.
        This is to avoid long blockings when removing large temporary dirs.
        """
        del_thread = threading.Thread(target=shutil.rmtree, args=(path, True))
        del_thread.name += '-delete'
        del_thread.daemon = False
        del_thread.start()

    def write_fileinfo_file(self) -> None:
        """Write current open file information."""

        if self.file_loaded:
            path = self._window.imagehandler.get_real_path()
            page = self._window.imagehandler.get_current_page()
            current_file_info = [path, page - 1]

            with tools.atomic_write(constants.FILEINFO_PICKLE_PATH, binary=True) as config:
                pickle.dump(current_file_info, config, pickle.HIGHEST_PROTOCOL)
                # The file of the page within an archive, in a record of
                # its own after the pair, which an older MComix stops
                # short of: it finds the page however the archive is
                # sorted by the time the file is read.
                pickle.dump(self.page_member(page), config,
                            pickle.HIGHEST_PROTOCOL)

    def read_fileinfo_file(self) -> "tuple[str, int, str | None] | None":
        """The file and page index a "quit and save" left off at, and
        the name within an archive of the page's file where it was kept.

        What the pickle holds is whatever was written to it, so the pair
        is checked rather than trusted: a file of the wrong shape says
        nothing about where to reopen.
        """

        fileinfo = None
        member = None

        if os.path.isfile(constants.FILEINFO_PICKLE_PATH):
            try:
                with open(constants.FILEINFO_PICKLE_PATH, 'rb') as config:
                    fileinfo = pickle.load(config)
                    try:
                        member = pickle.load(config)
                    except EOFError:
                        # Written by an older MComix.
                        member = None
            except Exception as ex:
                log.error(_('! Corrupt file "%s", deleting it; the last file '
                            'read will not be reopened.'),
                          constants.FILEINFO_PICKLE_PATH)
                log.info('Error was: %s', ex)
                os.remove(constants.FILEINFO_PICKLE_PATH)

        if not (isinstance(fileinfo, (list, tuple)) and len(fileinfo) == 2
                and isinstance(fileinfo[0], str)
                and isinstance(fileinfo[1], int)):
            return None
        return (fileinfo[0], fileinfo[1],
                member if isinstance(member, str) else None)

    def update_last_read_page(self) -> None:
        """ Stores the currently viewed page. """
        if self.archive_type is None or not self.file_loaded:
            return

        archive_path = self.get_path_to_base()
        if archive_path is None:
            return
        page = self._window.imagehandler.get_current_page()
        if page == 0:
            # No page at all: the archive had no pictures in it, or
            # could not be opened, and either still counts as loaded.
            # Storing it would file a book nobody read under "Recent".
            return
        # Do not store first page (first page is default
        # behaviour and would waste space unnecessarily)
        try:
            if page == 1:
                self.last_read_page.clear_page(archive_path)
            else:
                self.last_read_page.set_page(archive_path, page,
                                             self.page_member(page))
        except ValueError:
            # The book no longer exists in the library and has been deleted
            pass


# vim: expandtab:sw=4:ts=4
