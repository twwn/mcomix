""" Walking from one directory to the next, and back again. """

import io
import os
import pickle
import shutil
import sys
import threading
import unittest
import zipfile
from unittest import mock

from gi.repository import Gtk
from PIL import Image

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import archive_extractor
from mcomix import constants
from mcomix import file_handler
from mcomix import icons
from mcomix import main
from mcomix import message_dialog
from mcomix.dialog import Response
from mcomix.preferences import prefs

from .test_main_window import _descriptors_on


class DirectoryWalkTest(MComixTest):

    """ The next/previous directory commands, over directories that hold
    an archive, images, or nothing worth opening. """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        self.root = os.path.join(self.tmp_dir, 'books')
        for name in ('a', 'b', 'c'):
            os.makedirs(os.path.join(self.root, name))
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.handler = self.window.filehandler
        pump()

    def tearDown(self):
        # Only terminate_program() stops the worker threads, and a GTK4
        # toplevel that is never destroyed goes on taking part in the
        # display's layout.
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _put_archive(self, directory):
        """ Copies the test archive into <directory>, and returns its path. """
        path = os.path.join(self.root, directory, '01-ZIP-Normal.zip')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), path)
        return path

    def _put_image(self, directory):
        """ Copies a test image into <directory>, and returns its path. """
        path = os.path.join(self.root, directory, '01-JPG-Indexed.jpg')
        shutil.copy(get_testfile_path('images', '01-JPG-Indexed.jpg'), path)
        return path

    def _open(self, path):
        self.handler.open_file(path)
        self.assertTrue(wait_for(lambda: self.handler.file_loaded and
                                 self.window.imagehandler.get_number_of_pages() > 0),
                        "'%s' never finished opening" % path)

    def _opened_file(self):
        """ The file the handler currently has open. """
        pump()
        wait_for(lambda: not self.handler.file_loading, seconds=3)
        return self.handler._current_file

    def test_walking_back_out_of_an_empty_directory_reopens_the_archive(self):
        """ A directory with nothing to open leaves no archive open, and
        the walk used to take that to mean it was looking for images from
        then on - so coming back found none of the archives it left. """
        archive = self._put_archive('a')
        self._open(archive)
        self.handler.open_next_directory()
        self.assertEqual(os.path.join(self.root, 'b'), self._opened_file())
        self.handler.open_previous_directory()
        self.assertEqual(archive, self._opened_file())

    def test_walking_on_past_an_empty_directory_finds_the_next_archive(self):
        archive = self._put_archive('a')
        last = self._put_archive('c')
        self._open(archive)
        self.handler.open_next_directory()
        self.handler.open_next_directory()
        self.assertEqual(last, self._opened_file())

    def test_walking_on_past_an_empty_directory_finds_the_next_images(self):
        image = self._put_image('a')
        last = self._put_image('c')
        self._open(image)
        self.handler.open_next_directory()
        self.handler.open_next_directory()
        self.assertEqual(last, self._opened_file())

    def test_walking_from_images_into_a_directory_of_archives_opens_one(self):
        """The walk looks for the kind of book it left, and takes the
        other kind where the directory has none: from loose images into
        a directory of archives it opened the directory, a book with no
        pages."""
        self._open(self._put_image('a'))
        archive = self._put_archive('b')
        self.assertTrue(self.handler.open_next_directory())
        self.assertEqual(archive, self._opened_file())
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 4))

    def test_walking_back_from_images_into_a_directory_of_archives(self):
        archive = self._put_archive('a')
        self._open(self._put_image('b'))
        self.assertTrue(self.handler.open_previous_directory())
        self.assertEqual(archive, self._opened_file())

    def test_a_walk_goes_on_over_the_kind_of_book_it_set_out_over(self):
        """From an archive, through a directory of loose images, into
        one with both: its archive, not its images."""
        self._open(self._put_archive('a'))
        self._put_image('b')
        self._put_image('c')
        archive = self._put_archive('c')
        self.handler.open_next_directory()
        self._opened_file()
        self.assertIsNone(self.handler.archive_type)
        self.assertEqual(1, self.window.imagehandler.get_number_of_pages())
        self.handler.open_next_directory()
        self.assertEqual(archive, self._opened_file())

    def test_opening_a_directory_of_images_leaves_the_archives_behind(self):
        """ Opening a directory by hand, rather than walking into it,
        starts a walk over the images in it. """
        self._open(self._put_archive('a'))
        self._put_image('b')
        image = self._put_image('c')
        self._open(os.path.join(self.root, 'b'))
        self.handler.open_next_directory()
        self.assertEqual(image, self._opened_file())

    def test_walking_back_into_a_directory_with_no_book_opens_it(self):
        """As walking on into one does: the directory is what is open,
        and the walk goes on from there."""
        image = self._put_image('b')
        self._open(image)
        self.assertTrue(self.handler.open_previous_directory())
        self.assertEqual(os.path.join(self.root, 'a'), self._opened_file())

    @unittest.skipIf(sys.platform == 'win32',
                     'Windows deletes no archive MComix holds open')
    def test_an_archive_gone_from_its_directory_is_not_walked_from(self):
        """Its place among the others cannot be told once it is not
        listed, so neither the next nor the previous archive opens."""
        first = os.path.join(self.root, 'b', 'first.cbz')
        last = os.path.join(self.root, 'b', 'last.cbz')
        middle = os.path.join(self.root, 'b', 'middle.cbz')
        for path in (first, middle, last):
            shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                        path)
        self._open(middle)
        os.remove(middle)
        self.assertFalse(self.handler.open_next_archive())
        self.assertFalse(self.handler.open_previous_archive())
        self.assertEqual(middle, self._opened_file())

    def _put_rar_set(self, directory):
        """Copy the RAR set packed in three volumes into <directory>, and
        return the path of its first volume."""
        from mcomix.archive import rar, rar_external
        if not (rar.RarArchive.is_available()
                or rar_external.RarArchive.is_available()):
            self.skipTest('nothing here reads RAR')
        for part in (1, 2, 3):
            name = 'Multivolume.part%d.rar' % part
            shutil.copy(get_testfile_path('archives', name),
                        os.path.join(self.root, directory, name))
        return os.path.join(self.root, directory, 'Multivolume.part1.rar')

    def test_the_later_volumes_of_a_rar_set_are_not_books_of_their_own(self):
        """Opened by itself, part2 is the rest of the set from the middle
        of a page on; the set is read through part1."""
        first = self._put_rar_set('b')
        after = os.path.join(self.root, 'b', 'z.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), after)
        self._open(first)
        self.assertTrue(self.handler.open_next_archive())
        self.assertEqual(after, self._opened_file())
        self.assertTrue(self.handler.open_previous_archive())
        self.assertEqual(first, self._opened_file())

    def test_a_later_volume_opened_by_hand_opens_the_whole_book(self):
        """From the file chooser, the command line or Recent: what the
        reader wants is the book, not its rest from the middle of a
        page on."""
        first = self._put_rar_set('b')
        self._open(os.path.join(self.root, 'b', 'Multivolume.part3.rar'))
        self.assertEqual(first, self._opened_file())
        self.assertEqual(4, self.window.imagehandler.get_number_of_pages())

    def test_without_its_first_volume_a_later_one_opens_as_it_is(self):
        self._put_rar_set('b')
        os.remove(os.path.join(self.root, 'b', 'Multivolume.part1.rar'))
        second = os.path.join(self.root, 'b', 'Multivolume.part2.rar')
        self._open(second)
        self.assertEqual(second, self._opened_file())

    def test_walking_back_into_a_rar_set_opens_its_first_volume(self):
        """The walk back opens the last book of the directory before,
        which is the set, not its last volume."""
        first = self._put_rar_set('b')
        self._open(self._put_archive('c'))
        self.assertTrue(self.handler.open_previous_directory())
        self.assertEqual(first, self._opened_file())

    def test_there_is_nothing_before_the_first_directory(self):
        archive = self._put_archive('a')
        self._open(archive)
        self.assertFalse(self.handler.open_previous_directory())
        self.assertEqual(archive, self._opened_file())
        self.assertTrue(self.handler.file_loaded)

    def test_there_is_nothing_after_the_last_directory(self):
        archive = self._put_archive('c')
        self._open(archive)
        self.assertFalse(self.handler.open_next_directory())
        self.assertEqual(archive, self._opened_file())
        self.assertTrue(self.handler.file_loaded)

    def test_a_loose_page_is_available_for_as_long_as_its_file_is_there(self):
        """Pages that are files of their own need no extracting: they
        are there to be read, until something takes them away."""
        image = self._put_image('a')
        self._open(image)
        self.assertTrue(self.handler.file_is_available(image))

        def removed():
            # Windows removes no open file, and the page is read by the
            # window and the thumbnail bar as it opens: WinError 32 on
            # GitHub's runner.
            try:
                os.remove(image)
            except PermissionError:
                return False
            return True
        self.assertTrue(wait_for(removed))
        self.assertFalse(self.handler.file_is_available(image))


class _WindowTest(MComixTest):

    """A main window with nothing open, and its file handler."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.handler = self.window.filehandler
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()


class AnArchiveThatWillNotOpenTest(_WindowTest):

    """An archive the extractor refuses - a format with no handler
    installed, most often - is reported and left, and the window goes on
    working."""

    def test_closing_it_and_opening_another_still_work(self):
        """The failure left the handler marked as holding an archive with
        no condition to wait on, so the next close raised ValueError: no
        other book would open after it, and quitting raised before the
        library was closed and the threads were joined."""
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        with mock.patch.object(self.handler._extractor, 'setup',
                               side_effect=Exception('no handler')):
            self.assertFalse(self.handler.open_file(path))
        self.handler.close_file()
        self.assertTrue(self.handler.open_file(path))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0))


class APathThatCannotBeOpenedTest(_WindowTest):

    """A name that is not there, or not a file or a folder, opened over
    a book: the book is closed, the reason is shown, and nothing claims
    to be open."""

    def _over_a_book(self, path):
        self.assertTrue(self.handler.open_file(
            get_testfile_path('archives', '01-ZIP-Normal.zip')))
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0))
        pump()
        with mock.patch.object(self.window.osd, 'show') as shown:
            self.assertFalse(self.handler.open_file(path))
        pump()
        return shown

    def _closed(self):
        self.assertFalse(self.handler.file_loaded)
        self.assertFalse(self.window.actiongroup.get_action('close')
                         .get_sensitive())

    def test_a_name_that_is_not_there(self):
        """The failure was answered with file_opened(), which marks a
        book as loaded: the Close, Save and page menus came back for a
        window with nothing in it."""
        path = os.path.join(self.tmp_dir, 'gone.cbz')
        shown = self._over_a_book(path)
        self.assertIn('No such file', shown.call_args.args[0])
        self._closed()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Windows has no named pipes '
                         'in the file system')
    def test_a_name_that_is_neither_file_nor_folder(self):
        path = os.path.join(self.tmp_dir, 'pipe')
        os.mkfifo(path)
        shown = self._over_a_book(path)
        self.assertIn('Invalid path', shown.call_args.args[0])
        self._closed()

    def test_a_file_that_cannot_be_read(self):
        path = os.path.join(self.tmp_dir, 'locked.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), path)
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        if os.access(path, os.R_OK):
            self.skipTest('cannot make the file unreadable (running as root?)')
        shown = self._over_a_book(path)
        self.assertIn('Permission denied', shown.call_args.args[0])
        self._closed()


class RememberedResumeAnswerTest(MComixTest):

    """Opening a book the reader has stopped in before.

    MComix offers to carry on where they left off, and the prompt can be
    answered once and for all.  A standing "yes" resumes without asking;
    a standing "no" opens at the front, also without asking.  With no
    standing answer the book opens at the front while the prompt waits,
    and turns to where it was left only on a "yes".
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        self.archive = os.path.join(self.tmp_dir, '01-ZIP-Normal.zip')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                    self.archive)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.handler = self.window.filehandler
        self.handler.last_read_page.set_enabled(True)
        self.handler.last_read_page.set_page(self.archive, 3)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _open_and_settle(self):
        self.handler.open_file(self.archive)
        wait_for(lambda: self.handler.file_loaded and
                 self.window.imagehandler.get_number_of_pages() > 0)
        # The answer, remembered or not, arrives from the main loop.
        for _round in range(10):
            pump()
        return self.window.imagehandler.get_current_page()

    def test_a_standing_yes_opens_the_book_where_it_was_left(self):
        prefs['stored dialog choices']['resume-from-last-read-page'] = \
            int(Response.YES)
        self.assertEqual(3, self._open_and_settle())

    def test_a_standing_no_opens_the_book_at_the_front(self):
        # Both answers are stored as their response number, and both of
        # those are negative, so asking whether one is there at all took
        # "no" for a "yes" and resumed anyway.
        prefs['stored dialog choices']['resume-from-last-read-page'] = \
            int(Response.NO)
        self.assertEqual(1, self._open_and_settle())

    def _answer_the_prompt(self, response):
        """Open the book with no standing answer, answer the prompt that
        comes up with <response>, and give the page shown then."""
        self._open_and_settle()
        prompts = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, message_dialog.MessageDialog)
                   and window.get_transient_for() is self.window]
        self.assertEqual(1, len(prompts), 'nothing asked where to resume')
        self.assertEqual(1, self.window.imagehandler.get_current_page(),
                         'the book was not shown from the front while '
                         'the prompt waited')
        prompts[0].response(response)
        for _round in range(10):
            pump()
        return self.window.imagehandler.get_current_page()

    def test_a_record_gone_before_its_date_was_read_asks_nothing(self):
        """Another window closing the same book takes the record away
        between the page being read and its date: there is nothing to
        resume to, so nothing is asked and the book stays at its front."""
        with mock.patch.object(self.handler.last_read_page, 'get_date',
                               return_value=None), \
                mock.patch.object(self.handler, 'write_fileinfo_file') \
                as recorded:
            page = self._open_and_settle()
        # The answer that there is nothing to resume to finishes the
        # opening as an answer from the prompt would.
        recorded.assert_called_once_with()
        prompts = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, message_dialog.MessageDialog)
                   and window.get_transient_for() is self.window]
        self.assertEqual([], prompts)
        self.assertEqual(1, page)

    def test_answering_yes_turns_to_the_page_where_it_was_left(self):
        self.assertEqual(3, self._answer_the_prompt(Response.YES))

    def test_answering_no_stays_at_the_front(self):
        self.assertEqual(1, self._answer_the_prompt(Response.NO))


class ExtractionOrderTest(MComixTest):

    """The order an archive's pages are unpacked in, opened at a page
    other than the first.

    The pages around the one shown come first, and the rest follow
    nearest first: a book resumed at its end was unpacked from its
    first page onwards, so turning back from the end waited on every
    page before the one turned to.
    """

    PAGES = 12

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        self.archive = os.path.join(self.tmp_dir, 'book.zip')
        with open(get_testfile_path('images', 'red.png'), 'rb') as image:
            data = image.read()
        with zipfile.ZipFile(self.archive, 'w') as book:
            for number in range(1, self.PAGES + 1):
                book.writestr('%02d.png' % number, data)
        prefs['max extract threads'] = 1
        prefs['max pages to cache'] = 7
        prefs['default double page'] = False
        prefs['stored dialog choices']['resume-from-last-read-page'] = \
            int(Response.YES)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.handler = self.window.filehandler
        self.handler.last_read_page.set_enabled(True)
        pump()

        self.unpacked = []
        extract_file = archive_extractor.Extractor._extract_file

        def recording(extractor, name):
            self.unpacked.append(name)
            extract_file(extractor, name)

        patcher = mock.patch.object(archive_extractor.Extractor,
                                    '_extract_file', recording)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _unpacked(self):
        self.assertTrue(wait_for(lambda: len(self.unpacked) == self.PAGES))
        return [int(name[:2]) for name in self.unpacked]

    def test_a_book_opened_at_its_end_is_unpacked_back_to_front(self):
        """As turning back from the next book opens it."""
        self.handler.open_file(self.archive, -1)
        self.assertEqual(list(range(self.PAGES, 0, -1)), self._unpacked())
        self.assertEqual(self.PAGES,
                         self.window.imagehandler.get_current_page())

    def test_a_book_resumed_in_its_middle_is_unpacked_outwards(self):
        self.handler.last_read_page.set_page(self.archive, 6)
        self.handler.open_file(self.archive)
        # The cache window first: the page shown, the one before it and
        # the five after it.  Then the rest, nearest first.
        self.assertEqual([6, 7, 5, 8, 9, 10, 11, 4, 3, 2, 1, 12],
                         self._unpacked())
        self.assertEqual(6, self.window.imagehandler.get_current_page())

    def test_the_page_offered_to_resume_at_comes_after_the_front(self):
        """While the reader is asked whether to go back to page 10, the
        book is shown from its front, and page 10 is unpacked next."""
        del prefs['stored dialog choices']['resume-from-last-read-page']
        self.handler.last_read_page.set_page(self.archive, 10)
        self.handler.open_file(self.archive)
        unpacked = self._unpacked()
        prompts = []
        self.assertTrue(wait_for(lambda: prompts.extend(
            window for window in Gtk.Window.list_toplevels()
            if isinstance(window, message_dialog.MessageDialog)
            and window.get_transient_for() is self.window) or prompts))
        prompts[0].response(Response.YES)
        pump()
        self.assertEqual([1, 2, 3, 4, 5, 6, 10, 11, 9, 12, 7, 8], unpacked)
        self.assertEqual(10, self.window.imagehandler.get_current_page())
        self.assertIsNone(self.window.imagehandler._resume_page)


@unittest.skipUnless(os.path.isdir('/proc/self/fd'),
                     'the open descriptors are read from /proc')
class AnUnpackedArchiveIsLetGoTest(_WindowTest):

    """Windows deletes, moves and renames no file that is open, and the
    extractor held the archive open for as long as the book was, though
    nothing more came out of it once every member was unpacked: Explorer
    refused to touch a book that was only being read."""

    def test_the_archive_is_closed_once_every_member_is_out(self):
        source = os.path.join(self.tmp_dir, 'Book.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), source)
        self.handler.open_file(source)
        self.assertTrue(wait_for(
            lambda: self.handler.file_loaded
            and self.handler._extractor.get_files() == [], seconds=20),
            'the archive was never unpacked')
        pump()
        self.assertEqual([], _descriptors_on(source))
        # The pages are still there to be read, from the unpacked files.
        pages = self.window.imagehandler.get_number_of_pages()
        self.assertGreater(pages, 2)
        self.window.set_page(pages)
        pump()
        self.assertEqual(pages, self.window.imagehandler.get_current_page())


class ABookOpenedAtItsEndTest(_WindowTest):

    """A book opened at its end, as going back past the first page of
    the next one does, showed the top of its last page; a page turned
    back to within a book is shown from its bottom (upstream bug 70)."""

    def test_its_last_page_is_shown_from_the_bottom(self):
        prefs['zoom mode'] = constants.ZoomMode.WIDTH
        self.window.change_zoom_mode()
        source = os.path.join(self.tmp_dir, 'tall.cbz')
        with zipfile.ZipFile(source, 'w') as archive:
            for name in ('1.png', '2.png'):
                page = io.BytesIO()
                Image.new('RGB', (100, 3000), (90, 90, 90)).save(page, 'PNG')
                archive.writestr(name, page.getvalue())
        self.handler.open_file(source, -1)
        self.assertTrue(wait_for(
            lambda: self.handler.file_loaded
            and self.window.imagehandler.page_is_available(2), seconds=20))
        pump()
        adjustment = self.window.page_area.get_vadjustment()
        self.assertTrue(wait_for(
            lambda: adjustment.get_upper() > adjustment.get_page_size()))
        self.assertEqual(2, self.window.imagehandler.get_current_page())
        self.assertAlmostEqual(
            adjustment.get_upper() - adjustment.get_page_size(),
            adjustment.get_value())


class ABookOpenedAtItsEndUnderATitleBarTest(ABookOpenedAtItsEndTest):

    """The same, in a window with a title bar of its own, as GTK draws
    on Windows: the room for the pages was worked out from the window's
    height, title bar and all, so its last page stopped 39 px short of
    the bottom there, and a page fitted to the height was 39 px too
    tall."""

    def setUp(self):
        shown = main.MainWindow.present

        def present(window):
            # Before the window is shown, as GTK sets its own.
            window.set_titlebar(Gtk.HeaderBar())
            shown(window)

        with mock.patch.object(main.MainWindow, 'present', present):
            super().setUp()

    def test_the_room_for_the_pages_leaves_out_the_title_bar(self):
        self.assertEqual(self.window.page_area.get_height(),
                         self.window.get_visible_area_size()[1])


class ABookOpenedAtItsEndInDoublePageTest(_WindowTest):

    """Double page mode, wide pages shown on their own: a book opened
    at its end, as going back from the next one does, showed its last
    page but one when that was wide, and never its last page (upstream
    bug 95)."""

    def _open(self, sizes):
        prefs['default double page'] = True
        prefs['virtual double page for fitting images'] = \
            constants.SHOW_DOUBLE_AS_ONE_WIDE
        source = os.path.join(self.tmp_dir, 'book.cbz')
        with zipfile.ZipFile(source, 'w') as archive:
            for number, size in enumerate(sizes, 1):
                page = io.BytesIO()
                Image.new('RGB', size, (90, 90, 90)).save(page, 'PNG')
                archive.writestr('%d.png' % number, page.getvalue())
        self.handler.open_file(source, -1)
        self.assertTrue(wait_for(
            lambda: self.handler.file_loaded and all(
                self.window.imagehandler.page_is_available(page)
                for page in range(1, len(sizes) + 1)), seconds=20))
        pump()

    def test_a_wide_page_before_the_last_leaves_the_last_on_its_own(self):
        self._open([(100, 150), (300, 150), (100, 150)])
        self.assertEqual(3, self.window.imagehandler.get_current_page())

    def test_two_narrow_pages_at_the_end_are_shown_together(self):
        self._open([(100, 150), (300, 150), (100, 150), (100, 150)])
        self.assertEqual(3, self.window.imagehandler.get_current_page())
        self.assertEqual(2, self.window.displayed_page_count())


class ABookWithNoPagesTest(MComixTest):

    """Closing an archive that has no pictures in it.

    It opens - the handler counts it as loaded, and says there are no
    images - but no page is ever shown, so there is no page to remember
    and no reading to file under "Recent".
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        self.archive = os.path.join(self.tmp_dir, 'no-pictures.zip')
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('readme.txt', 'Nothing to look at.')
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.handler = self.window.filehandler
        self.handler.last_read_page.set_enabled(True)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def test_closing_it_does_not_file_it_as_read(self):
        self.assertTrue(self.handler.open_file(self.archive))
        wait_for(lambda: self.handler.file_loaded)
        pump()
        self.assertEqual(0, self.window.imagehandler.get_current_page())

        self.handler.close_file()
        pump()

        self.assertIsNone(self.handler.last_read_page.get_page(self.archive))
        self.assertIsNone(
            self.handler.last_read_page.backend.get_book_by_path(
                self.archive),
            'a book no page of which was shown went into the library')


class BeforeAPageIsChosenTest(MComixTest):

    """What the handler answers between being given a book and being told
    which page of it is showing.

    set_image_files() and set_page() are two separate calls, so there is a
    moment where the image handler knows the files but not the page.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def test_there_is_no_base_path_before_a_page_is_chosen(self):
        """Outside an archive the base is the directory the current image
        sits in, and the index of that image is None until set_page() has
        run.  Indexing the list of files with it raised."""
        self.window.imagehandler.set_image_files(['/nowhere/one.jpg',
                                                  '/nowhere/two.jpg'])
        self.window.imagehandler._current_image_index = None
        self.assertIsNone(self.window.filehandler.archive_type)
        self.assertIsNone(self.window.filehandler.get_path_to_base())

    def test_there_is_no_base_filename_before_a_page_is_chosen(self):
        """get_base_filename() handed whatever get_path_to_base()
        answered straight to os.path.basename(), which raised on the None
        that means no file is open."""
        self.assertEqual(self.window.filehandler.get_base_filename(), '')

    def test_the_base_filename_is_the_directory_name_once_there_is_one(self):
        self.window.imagehandler.set_image_files(['/nowhere/books/one.jpg'])
        self.window.imagehandler._current_image_index = 0
        self.assertEqual(self.window.filehandler.get_base_filename(), 'books')

    def test_no_file_at_all_is_never_available_inside_an_archive_either(self):
        """Asking about no file reached the archive branch first, which
        goes to the extractor and looks the path up in a table keyed by
        path; the test for None came only after it.  Setting the archive
        type is enough to take that branch."""
        self.window.filehandler.archive_type = constants.ZIP
        self.assertFalse(self.window.filehandler.file_is_available(None))

    def test_the_base_path_is_the_directory_once_a_page_is_chosen(self):
        self.window.imagehandler.set_image_files(['/nowhere/one.jpg',
                                                  '/nowhere/two.jpg'])
        self.window.imagehandler._current_image_index = 1
        self.assertEqual(self.window.filehandler.get_path_to_base(),
                         '/nowhere')

# vim: expandtab:sw=4:ts=4


class BusyCursorTest(MComixTest):

    """Whether the wait cursor covers the stretch it is meant to.

    open_file() points the extractor at the archive and returns at once;
    nothing is on screen until the listing thread answers, which on a large
    archive is long enough to look like nothing happened.
    """

    class _StubCursorHandler:

        def __init__(self):
            self.calls = []

        def set_busy(self, busy):
            self.calls.append(busy)

        def set_cursor_type(self, cursor):
            pass

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.cursor = self._StubCursorHandler()

    def _handler(self):
        """A file handler over a window that answers anything.

        The two attributes given real values are the ones that leave the
        program: write_fileinfo() pickles the path and the page number, and
        a MagicMock cannot be pickled.
        """
        window = mock.MagicMock()
        window.cursor_handler = self.cursor
        # A book with changes that have not been written stops to ask
        # about them before it closes; this window holds no book.
        window.file_actions.has_unsaved_changes.return_value = False
        window.imagehandler.get_real_path.return_value = '/book/page.png'
        window.imagehandler.get_current_page.return_value = 1
        handler = file_handler.FileHandler(window)
        # The handler opens the library database for the last page read,
        # and only a real window's terminate_program() closes it.
        self.addCleanup(handler.last_read_page.backend.close)
        return handler

    def test_listing_an_archive_sets_the_wait_cursor(self):
        handler = self._handler()
        handler.open_file(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        try:
            self.assertIn(True, self.cursor.calls,
                          'nothing said the program was working')
        finally:
            handler._close(close_provider=True)

    def test_a_directory_of_images_sets_no_wait_cursor(self):
        """Listing a directory is not threaded, so there is no wait to
        report and the pointer must not flicker."""
        handler = self._handler()
        handler.open_file(get_testfile_path('images', 'blue.png'))
        try:
            self.assertNotIn(True, self.cursor.calls)
        finally:
            handler._close(close_provider=True)

    def test_closing_while_a_listing_runs_clears_the_wait_cursor(self):
        """_listed_contents() gives up on a file_loading that has been
        cleared, so _archive_opened() is never reached and _close() is the
        only place left to clear it."""
        handler = self._handler()
        handler.open_file(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        self.cursor.calls.clear()
        handler._close(close_provider=True)
        self.assertIn(False, self.cursor.calls,
                      'the wait cursor would have stayed for the session')


class CloseWakesWaitersTest(MComixTest):

    """Closing a file wakes whatever is parked in wait_on_file().

    That wait parks on the extractor's condition, and the only
    notify_all() the extractor makes fires when a file has finished
    extracting.  Closing stops the extractor, so no file will finish
    after it: a waiter closing does not wake is never woken, on a
    condition the next archive opened replaces.  It matters because
    _close() goes on to call ImageHandler.cleanup(), which joins the
    caching thread - one of the two threads that park there - so a
    waiter left parked hangs the main thread inside close_file().
    """

    class _StubImageHandler:

        def cleanup(self):
            pass

    class _StubCursorHandler:

        """_close() clears the wait cursor the archive listing set, so the
        stub window has to have one to clear."""

        def __init__(self):
            self.busy = None

        def set_busy(self, busy):
            self.busy = busy

    class _StubFileActions:

        """Closing asks this whether the book has changes to write."""

        @staticmethod
        def has_unsaved_changes():
            return False

        @staticmethod
        def before_closing(then):
            then()

    class _StubWindow:

        def __init__(self):
            self.imagehandler = CloseWakesWaitersTest._StubImageHandler()
            self.cursor_handler = \
                CloseWakesWaitersTest._StubCursorHandler()
            self.file_actions = CloseWakesWaitersTest._StubFileActions()

    PAGE = '/book/page.png'

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.handler = file_handler.FileHandler(self._StubWindow())
        # An open archive with one member that is never extracted.  The
        # real extractor answers is_ready() out of a set setup() fills
        # in, and setting it up would need an archive to extract.
        self.handler.file_loaded = True
        self.handler.archive_type = constants.ZIP
        self.handler._condition = threading.Condition()
        self.handler._name_table = {self.PAGE: 'page.png'}
        self.asked = threading.Event()

        def is_ready(name):
            self.asked.set()
            return False

        self.handler._extractor.is_ready = is_ready
        self.returned = threading.Event()
        self.waiter = threading.Thread(target=self._wait, name='test-waiter')
        self.waiter.daemon = True

    def tearDown(self):
        # Wake the waiter whatever the test found, so that a failure
        # leaves no thread parked on the condition.
        with self.handler._archive_condition:
            self.handler._stop_waiting = True
            self.handler._archive_condition.notify_all()
        self.waiter.join(timeout=5)
        self.handler.last_read_page.backend.close()
        super().tearDown()

    def _wait(self):
        self.handler.wait_on_file(self.PAGE)
        self.returned.set()

    def _park_the_waiter(self):
        """Start the waiting thread and return once it is parked.

        is_ready() is called with the condition held, and the wait that
        follows is what releases it, so a caller that then takes the
        lock cannot get it until the thread is parked.
        """
        self.waiter.start()
        self.assertTrue(self.asked.wait(timeout=5),
                        'the waiting thread never asked about the file')

    def test_closing_the_file_wakes_a_parked_waiter(self):
        self._park_the_waiter()

        self.handler.close_file()

        self.assertTrue(self.returned.wait(timeout=5),
                        'the thread waiting on an extraction was still '
                        'parked after the file was closed')

    def test_a_waiter_is_not_woken_while_the_file_is_open(self):
        self._park_the_waiter()

        self.assertFalse(self.returned.wait(timeout=0.2),
                         'the wait ended without the file being extracted '
                         'or closed')


class FileInfoTest(MComixTest):

    """The file and page "Save and quit" leaves behind for the next start.

    read_fileinfo_file() has to answer for whatever is in that file,
    which is a pickle no other program writes but which any of them can
    truncate: nothing about it is trusted, and one that cannot be read
    is removed rather than left to fail the same way at every start.
    """

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        # read_fileinfo_file() reads the pickle and nothing else, so a
        # handler without a window is all it needs.
        self.handler = file_handler.FileHandler(None)

    def tearDown(self):
        # Building a handler opens the library backend, which is a
        # singleton: left behind, it hands every later test a connection
        # to a database in a temporary directory that is about to be
        # removed.
        self.handler.last_read_page.backend.close()
        super().tearDown()

    def _write(self, content):
        with open(constants.FILEINFO_PICKLE_PATH, 'wb') as pickle_file:
            pickle_file.write(content)

    def test_an_archive_s_pages_of_one_name_come_in_path_order(self):
        """GLib's order compares the names alone, so the first page of
        each chapter of an archive - "b/01.jpg" and "a/01.jpg" - tied,
        and kept the order the archive listed them in."""
        prefs['sort archive by'] = constants.SORT_NAME_GLIB
        prefs['sort archive order'] = constants.SORT_ASCENDING
        for listed in (['b/01.jpg', 'a/01.jpg'], ['a/01.jpg', 'b/01.jpg']):
            files = list(listed)
            self.handler._sort_archive_images(files)
            self.assertEqual(['a/01.jpg', 'b/01.jpg'], files)

    def test_each_archive_order_and_its_reverse(self):
        """Natural order counts, literal order compares characters - a
        capital first - and no sorting keeps the archive's own order;
        descending turns each of them round."""
        listed = ['p10.jpg', 'P3.jpg', 'p2.jpg']
        for key, ascending in (
                (constants.SORT_NAME, ['p2.jpg', 'P3.jpg', 'p10.jpg']),
                (constants.SORT_NAME_LITERAL, ['P3.jpg', 'p10.jpg', 'p2.jpg']),
                (0, listed)):
            for order, expected in (
                    (constants.SORT_ASCENDING, ascending),
                    (constants.SORT_DESCENDING, ascending[::-1])):
                with self.subTest(key=key, order=order):
                    prefs['sort archive by'] = key
                    prefs['sort archive order'] = order
                    files = list(listed)
                    self.handler._sort_archive_images(files)
                    self.assertEqual(expected, files)

    def test_a_negative_page_opens_at_the_end_of_the_book(self):
        """At the last page, or at the last two in double page mode, so
        that the last pair is what shows; a page past the end is the
        last one."""
        for double, start, expected in ((False, -1, 9), (True, -1, 8),
                                        (False, 50, 9), (False, 3, 2)):
            with self.subTest(double=double, start=start):
                prefs['default double page'] = double
                self.assertEqual(expected, self.handler._get_index_for_page(
                    start, 10, '/books/a.zip'))

    def test_the_file_and_page_come_back(self):
        """As an older MComix wrote them, without the file of the page."""
        self._write(pickle.dumps(['/books/a.zip', 41]))

        self.assertEqual(('/books/a.zip', 41, None),
                         self.handler.read_fileinfo_file())

    def test_the_file_of_the_page_comes_back_with_them(self):
        """Written in a record after the pair, which is all an older
        MComix reads."""
        self._write(pickle.dumps(['/books/a.zip', 41])
                    + pickle.dumps('pages/42.jpg'))

        self.assertEqual(('/books/a.zip', 41, 'pages/42.jpg'),
                         self.handler.read_fileinfo_file())

    def test_no_file_is_no_answer(self):
        self.assertIsNone(self.handler.read_fileinfo_file())

    def test_a_pair_of_the_wrong_types_is_refused(self):
        self._write(pickle.dumps([41, '/books/a.zip']))

        self.assertIsNone(self.handler.read_fileinfo_file())
        self.assertTrue(os.path.isfile(constants.FILEINFO_PICKLE_PATH),
                        'a readable file was deleted for holding the wrong '
                        'pair')

    def test_a_file_that_cannot_be_read_is_deleted(self):
        self._write(b'not a pickle at all')

        self.assertIsNone(self.handler.read_fileinfo_file())
        self.assertFalse(os.path.isfile(constants.FILEINFO_PICKLE_PATH),
                         'a file that could not be unpickled was left to '
                         'fail again at the next start')

    def test_the_message_about_a_corrupt_file_names_that_file(self):
        """It used to call it the preferences file, which is a different
        file that this code does not touch."""
        self._write(b'not a pickle at all')
        messages = []
        with mock.patch.object(file_handler.log, 'error',
                               lambda text, *args: messages.append(text % args)):
            self.handler.read_fileinfo_file()

        self.assertEqual(1, len(messages), messages)
        self.assertIn(constants.FILEINFO_PICKLE_PATH, messages[0])
        self.assertNotIn('preferences', messages[0])


class CommentExtensionsTest(MComixTest):

    """The extensions that say which files in an archive are comments.

    They are what a reader typed into the preferences, and they went
    into a regular expression as they stood: a lone bracket raised
    re.error inside the file handler's constructor, so MComix would not
    start until the preferences file was edited by hand.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        pump()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _pattern_for(self, *extensions):
        prefs['comment extensions'] = list(extensions)
        self.window.filehandler.update_comment_extensions()
        return self.window.filehandler._comment_re

    def test_a_bracket_is_an_extension_rather_than_a_syntax_error(self):
        pattern = self._pattern_for('(', 'txt')
        self.assertTrue(pattern.search('read me.txt'))
        self.assertFalse(pattern.search('read me.doc'))

    def test_an_extension_is_matched_as_the_text_it_is(self):
        pattern = self._pattern_for('c++')
        self.assertTrue(pattern.search('notes.c++'))
        self.assertFalse(pattern.search('notes.cc'),
                         'the plus signs were read as "one or more"')

    def test_a_dot_in_an_extension_matches_only_a_dot(self):
        pattern = self._pattern_for('a.b')
        self.assertTrue(pattern.search('notes.a.b'))
        self.assertFalse(pattern.search('notes.axb'))
