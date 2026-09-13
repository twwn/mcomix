""" Walking from one directory to the next, and back again. """

import os
import pickle
import shutil
import threading
import zipfile
from unittest import mock

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import file_handler
from mcomix import icons
from mcomix import main
from mcomix.dialog import Response
from mcomix.preferences import prefs


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

    def test_opening_a_directory_of_images_leaves_the_archives_behind(self):
        """ Opening a directory by hand, rather than walking into it,
        starts a walk over the images in it. """
        self._open(self._put_archive('a'))
        self._put_image('b')
        image = self._put_image('c')
        self._open(os.path.join(self.root, 'b'))
        self.handler.open_next_directory()
        self.assertEqual(image, self._opened_file())


class AnArchiveThatWillNotOpenTest(MComixTest):

    """An archive the extractor refuses - a format with no handler
    installed, most often - is reported and left, and the window goes on
    working."""

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


class RememberedResumeAnswerTest(MComixTest):

    """Opening a book the reader has stopped in before.

    MComix offers to carry on where they left off, and the prompt can be
    answered once and for all.  A standing "yes" resumes without asking;
    a standing "no" opens at the front, also without asking.
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
        window.imagehandler.get_real_path.return_value = '/book/page.png'
        window.imagehandler.get_current_page.return_value = 1
        return file_handler.FileHandler(window)

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

    class _StubWindow:

        def __init__(self):
            self.imagehandler = CloseWakesWaitersTest._StubImageHandler()
            self.cursor_handler = \
                CloseWakesWaitersTest._StubCursorHandler()

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

    def test_the_file_and_page_come_back(self):
        self._write(pickle.dumps(['/books/a.zip', 41]))

        self.assertEqual(('/books/a.zip', 41),
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
