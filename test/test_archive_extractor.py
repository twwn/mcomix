"""The extractor that gets an archive's pages onto disk.

Nothing covered this module directly, although it is where a page turn
meets three threads and a condition variable: the tests it had were the
ones that opened a whole window and read a page out of the other end.
These drive the Extractor on its own, which is what makes the states
that only a page turn arriving at the wrong moment would otherwise
reach - a file landing after the list it was on had been narrowed -
something a test can set up.
"""

import os
import threading
import unittest.mock

from . import MComixTest, get_testfile_path, wait_for

from mcomix import archive_extractor
from mcomix import log


class _ExtractorTest(MComixTest):

    """One extractor over the ZIP fixture, set up and listed."""

    #: What 01-ZIP-Normal.zip holds, less the directory entry.
    #: As MComix lists them: with the system's separator.
    MEMBERS = tuple(os.path.join('images', name) for name in (
        '01-JPG-Indexed.jpg', '02-JPG-RGB.jpg', '03-PNG-RGB.png',
        '04-PNG-Indexed.png', 'Comment.txt'))

    def setUp(self):
        super().setUp()
        self.destination = os.path.join(self.tmp_dir, 'extracted')
        os.makedirs(self.destination)
        self.extractor = archive_extractor.Extractor()
        self.condition = self.extractor.setup(
            get_testfile_path('archives', '01-ZIP-Normal.zip'),
            self.destination)
        self.assertTrue(wait_for(lambda: self.extractor.get_files() is not None,
                                 seconds=20),
                        'the archive was never listed')

    def tearDown(self):
        self.extractor.close()
        super().tearDown()


class ExtractorSetupTest(_ExtractorTest):

    def test_the_listing_holds_every_member_of_the_archive(self):
        self.assertEqual(sorted(self.MEMBERS),
                         sorted(name for name in self.extractor.get_files()
                                if not name.endswith('/')))

    def test_the_directory_is_the_one_it_was_set_up_with(self):
        self.assertEqual(self.destination, self.extractor.get_directory())

    def test_an_unsupported_format_raises_rather_than_answering(self):
        """setup() promised a None it has never returned."""
        not_an_archive = os.path.join(self.tmp_dir, 'not-an-archive.txt')
        with open(not_an_archive, 'w') as fp:
            fp.write('nothing an archive handler reads')
        with self.assertRaises(archive_extractor.ArchiveException):
            archive_extractor.Extractor().setup(not_an_archive,
                                                self.destination)

    def test_a_listing_that_fails_names_the_archive(self):
        """The worker thread's message named the method and the error,
        and a reader had no way to tell which file would not open."""
        path = get_testfile_path('archives', '01-ZIP-Normal.zip')
        extractor = archive_extractor.Extractor()
        errors = []
        with unittest.mock.patch(
                'mcomix.archive.zip.ZipArchive.iter_contents',
                side_effect=UnicodeEncodeError('charmap', 'x', 0, 1, 'test')), \
                unittest.mock.patch.object(
                    log, 'error',
                    side_effect=lambda message, *args: errors.append(
                        message % (args[0] if len(args) == 1 else args))):
            extractor.setup(path, self.destination)
            try:
                self.assertTrue(wait_for(lambda: errors, seconds=20))
            finally:
                extractor.close()
        self.assertIn(path, errors[0])

    def test_nothing_is_ready_before_anything_is_extracted(self):
        for name in self.MEMBERS:
            with self.subTest(name=name):
                self.assertFalse(self.extractor.is_ready(name))


class ExtractionTest(_ExtractorTest):

    def _extract(self, names):
        self.extractor.set_files(names)
        self.extractor.extract()
        self.assertTrue(
            wait_for(lambda: all(self.extractor.is_ready(name)
                                 for name in names), seconds=20),
            'the files asked for never landed')

    def test_every_file_asked_for_lands_on_disk(self):
        self._extract(list(self.MEMBERS))
        for name in self.MEMBERS:
            with self.subTest(name=name):
                self.assertTrue(
                    os.path.isfile(os.path.join(self.destination, name)))

    def test_a_narrowed_list_leaves_the_rest_alone(self):
        wanted = self.MEMBERS[:2]
        self._extract(list(wanted))
        for name in self.MEMBERS[2:]:
            with self.subTest(name=name):
                self.assertFalse(self.extractor.is_ready(name))

    def test_setting_the_files_again_drops_what_already_landed(self):
        self._extract([self.MEMBERS[0]])
        self.extractor.set_files(self.MEMBERS)
        self.assertNotIn(self.MEMBERS[0], self.extractor.get_files())


class LateExtractionTest(_ExtractorTest):

    """A file landing after the list it was on has moved on.

    set_files() exists to be handed a filtered list, and the file
    handler narrows one at every page turn. A file being unpacked at
    that moment is not on the new list, and _extraction_finished() used
    to take it out of the pending list with a bare list.remove(): the
    ValueError that raised was caught and logged by the worker thread,
    which meant the notify_all() on the line after it never ran and
    every thread waiting on that page waited for the rest of the
    session.
    """

    def test_a_file_no_longer_on_the_list_still_counts_as_extracted(self):
        landing = self.MEMBERS[0]
        self.extractor.set_files([name for name in self.MEMBERS
                                  if name != landing])
        self.extractor._extraction_finished(landing)
        self.assertTrue(self.extractor.is_ready(landing))

    def test_it_is_announced_like_any_other(self):
        landing = self.MEMBERS[0]
        announced = []
        self.extractor.file_extracted += \
            lambda extractor, name: announced.append(name)
        self.extractor.set_files([name for name in self.MEMBERS
                                  if name != landing])
        self.extractor._extraction_finished(landing)
        self.assertEqual([landing], announced)

    def test_a_thread_waiting_for_it_is_woken(self):
        """The harm the bare remove() did: not the exception, which was
        logged and swallowed, but the wake-up that never came."""
        landing = self.MEMBERS[0]
        self.extractor.set_files([name for name in self.MEMBERS
                                  if name != landing])
        woken = threading.Event()

        def wait_for_the_page():
            with self.condition:
                while not self.extractor.is_ready(landing):
                    self.condition.wait()
            woken.set()

        waiter = threading.Thread(target=wait_for_the_page, daemon=True)
        waiter.start()
        # Parked on the condition, which is where the page turn leaves
        # the caching thread; without that the notify could be missed
        # for a reason this test is not about.
        self.assertTrue(wait_for(lambda: not woken.is_set() and waiter.is_alive(),
                                 seconds=20))
        self.extractor._extraction_finished(landing)
        self.assertTrue(woken.wait(timeout=20),
                        'the thread waiting for the page was never woken')
        waiter.join(timeout=20)

# vim: expandtab:sw=4:ts=4


class FailedBatchTest(_ExtractorTest):

    """A solid archive whose one pass stops part way through.

    A solid archive is unpacked in one pass, and a pass that raises - a
    damaged member, a destination that cannot be written - stops there.
    _extract_file() marks a file it could not unpack as done all the
    same, so that the window shows a missing page.  The pass marked
    nothing after the file it stopped at, and a thread waiting for one
    of those waited for the rest of the session: the main thread, when
    it turned to such a page or saved the archive.
    """

    class _StopsAfterOne:

        """The fixture's archive as a solid one, whose pass raises after
        its first file."""

        def __init__(self, archive):
            self._archive = archive

        def __getattr__(self, name):
            return getattr(self._archive, name)

        def is_solid(self):
            return True

        def iter_extract(self, entries, destination_dir):
            first = sorted(entries)[0]
            self._archive.extract(first, destination_dir)
            yield first
            raise OSError('the next member is damaged')

    def setUp(self):
        super().setUp()
        self.extractor._archive = self._StopsAfterOne(self.extractor._archive)

    def test_the_files_after_the_one_it_stopped_at_are_not_waited_for(self):
        names = sorted(self.MEMBERS)
        self.extractor.set_files(names)
        with unittest.mock.patch.object(log, 'error') as error:
            self.extractor.extract()
            self.assertTrue(
                wait_for(lambda: all(self.extractor.is_ready(name)
                                     for name in names), seconds=5),
                'never marked: %s' % [name for name in names
                                      if not self.extractor.is_ready(name)])
        error.assert_called()
        self.assertTrue(os.path.isfile(os.path.join(self.destination, names[0])))
        self.assertFalse(os.path.exists(os.path.join(self.destination, names[1])))


class ShortBatchTest(_ExtractorTest):

    """A solid archive whose one pass ends without handing over every
    file it was asked for, and without raising: what the external
    handlers did with an empty member (b28479f3, f1a9de5d)."""

    class _LeavesOneOut:

        def __init__(self, archive):
            self._archive = archive

        def __getattr__(self, name):
            return getattr(self._archive, name)

        def is_solid(self):
            return True

        def iter_extract(self, entries, destination_dir):
            for name in sorted(entries)[1:]:
                self._archive.extract(name, destination_dir)
                yield name

    def setUp(self):
        super().setUp()
        self.extractor._archive = self._LeavesOneOut(self.extractor._archive)

    def test_a_file_the_pass_left_out_is_not_waited_for(self):
        names = sorted(self.MEMBERS)
        self.extractor.set_files(names)
        with unittest.mock.patch.object(log, 'warning') as warning:
            self.extractor.extract()
            self.assertTrue(
                wait_for(lambda: all(self.extractor.is_ready(name)
                                     for name in names), seconds=5),
                'never marked: %s' % [name for name in names
                                      if not self.extractor.is_ready(name)])
        warning.assert_called_once()
        self.assertIn(names[0], warning.call_args.args[1])
