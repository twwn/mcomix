""" Tests for the password prompt, which is asked for by a thread that is
not the one that can show it. """

import os
import threading
import unittest.mock

from gi.repository import GLib, Gtk

from . import MComixTest, get_testfile_path, pump as _pump, wait_for

from mcomix import archive_extractor
from mcomix import message_dialog
from mcomix.archive import password as archive_password
from mcomix.archive import zip as zip_archive
from mcomix.dialog import Response


def pump(rounds=200):
    """Let the main loop run through whatever is pending."""
    _pump(rounds)


def visible_prompts():
    """Every password prompt currently on screen."""
    return [window for window in Gtk.Window.list_toplevels()
            if isinstance(window, message_dialog.MessageDialog)
            and window.get_visible()]


class PasswordDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        # test_archives.py replaces this for its own runs; make sure the
        # real dialog is what gets exercised here whatever the test order.
        self.real_ask_for_password = archive_password.ask_for_password

    def tearDown(self):
        for prompt in visible_prompts():
            prompt.destroy()
        pump()
        super().tearDown()

    def _wait_for_prompt(self, rounds=400):
        for _ in range(rounds):
            pump()
            prompts = visible_prompts()
            if prompts:
                return prompts[0]
        self.fail('no password prompt appeared')

    def _entry_in(self, widget):
        """Find the password entry. GTK4 has no Gtk.Container to ask for
        a list of children; every widget walks its own."""
        if isinstance(widget, Gtk.Entry):
            return widget
        child = widget.get_first_child()
        while child is not None:
            found = self._entry_in(child)
            if found is not None:
                return found
            child = child.get_next_sibling()
        return None

    def test_asking_does_not_wait_for_the_answer(self):
        # Gtk.Dialog.run() did wait, in a nested main loop that kept the
        # idle queue turning, which is how a second prompt could open on
        # top of the first.
        answers = []
        self.real_ask_for_password('/nowhere/archive.zip', answers.append)
        self.assertEqual(answers, [])
        self._wait_for_prompt()

    def test_the_password_reaches_the_caller(self):
        answers = []
        self.real_ask_for_password('/nowhere/archive.zip', answers.append)
        prompt = self._wait_for_prompt()
        self._entry_in(prompt).set_text('hunter2')
        prompt.response(Response.OK)
        pump()
        self.assertEqual(answers, ['hunter2'])
        self.assertEqual(visible_prompts(), [])

    def test_cancelling_answers_with_no_password(self):
        answers = []
        self.real_ask_for_password('/nowhere/archive.zip', answers.append)
        prompt = self._wait_for_prompt()
        self._entry_in(prompt).set_text('hunter2')
        prompt.response(Response.CANCEL)
        pump()
        self.assertEqual(answers, [None])

    def test_an_empty_password_counts_as_none(self):
        answers = []
        self.real_ask_for_password('/nowhere/archive.zip', answers.append)
        prompt = self._wait_for_prompt()
        prompt.response(Response.OK)
        pump()
        self.assertEqual(answers, [None])

    def test_an_archive_name_with_an_ampersand_is_shown(self):
        """The prompt names the archive on its second line.  That line
        used to be set as Pango markup, and an ampersand starts an
        entity there, so the line failed to parse and the label was left
        empty: no path, and no instruction under it either."""
        self.real_ask_for_password('/nowhere/Tom & Jerry.cbz', [].append)
        prompt = self._wait_for_prompt()
        self.assertIn('Tom & Jerry.cbz', prompt._secondary.get_text())

    def test_an_archive_name_that_reads_as_markup_is_shown_as_it_is(self):
        """A name is a name, so angle brackets in one are two characters
        of the name rather than a tag around the rest of it."""
        self.real_ask_for_password('/nowhere/<b>Bold</b>.cbz', [].append)
        prompt = self._wait_for_prompt()
        self.assertIn('<b>Bold</b>.cbz', prompt._secondary.get_text())

    def test_an_encrypted_archive_listed_on_the_main_thread_does_not_hang(self):
        """The library adds books on the main thread, between turns of the
        main loop, so listing an encrypted archive there asks for its
        password there.  The prompt does not wait for its answer, and
        _get_password() waiting on its event stopped the only loop that
        could deliver one: MComix froze with the prompt on screen."""
        archive = zip_archive.ZipArchive(
            get_testfile_path('archives', 'Encrypted.zip'))
        self.addCleanup(archive.close)
        answered = []

        def answer():
            prompts = visible_prompts()
            if not prompts:
                return GLib.SOURCE_CONTINUE
            self._entry_in(prompts[0]).set_text('password')
            prompts[0].response(Response.OK)
            answered.append(True)
            return GLib.SOURCE_REMOVE

        source = GLib.timeout_add(50, answer)
        self.addCleanup(lambda: answered or GLib.source_remove(source))

        # Fail rather than hang the suite: without the main loop turning,
        # nothing else would ever set the event.
        def give_up():
            if not archive._event.is_set():
                archive._password = ''
                archive._event.set()
        watchdog = threading.Timer(10, give_up)
        watchdog.start()
        self.addCleanup(watchdog.cancel)

        names = archive.list_contents()
        self.assertTrue(answered, 'the prompt was never answered')
        self.assertEqual(sorted(names),
                         ['arg.jpeg', 'bar.jpg', 'foo.JPG', 'meh.png'])

    def test_an_encrypted_archive_is_listed_once_the_password_is_given(self):
        """The whole path: a worker thread asks, the main thread shows the
        prompt and keeps running, and the worker carries on once answered."""
        archive = zip_archive.ZipArchive(
            get_testfile_path('archives', 'Encrypted.zip'))
        self.addCleanup(archive.close)
        listed = {}

        def list_contents():
            try:
                listed['names'] = archive.list_contents()
            except Exception as error:
                listed['error'] = error

        worker = threading.Thread(target=list_contents)
        worker.daemon = True
        worker.start()

        prompt = self._wait_for_prompt()
        self._entry_in(prompt).set_text('password')
        prompt.response(Response.OK)

        for _ in range(400):
            pump()
            if listed:
                break
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), 'the listing thread never resumed')
        self.assertNotIn('error', listed, str(listed.get('error')))
        self.assertEqual(sorted(listed['names']),
                         ['arg.jpeg', 'bar.jpg', 'foo.JPG', 'meh.png'])


class SessionPasswordTest(MComixTest):

    """A password typed once is kept in memory until MComix closes, so
    that reopening an encrypted book does not ask again (upstream feature
    request 110), and dropped when a page will not unpack with it."""

    ARCHIVE = get_testfile_path('archives', 'Encrypted.zip')
    MEMBER = 'arg.jpeg'

    def setUp(self):
        super().setUp()
        self.asked = []
        self.answer = 'password'

        def ask(archive, on_password):
            self.asked.append(archive)
            on_password(self.answer)

        patcher = unittest.mock.patch.object(
            archive_password, 'ask_for_password', ask)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _extract_with_a_new_archive(self):
        archive = zip_archive.ZipArchive(self.ARCHIVE)
        self.addCleanup(archive.close)
        archive.list_contents()
        archive.extract(self.MEMBER, self.tmp_dir)
        return os.path.join(self.tmp_dir, self.MEMBER)

    def test_reopening_the_book_does_not_ask_again(self):
        self.assertTrue(os.path.isfile(self._extract_with_a_new_archive()))
        os.remove(os.path.join(self.tmp_dir, self.MEMBER))
        self.assertTrue(os.path.isfile(self._extract_with_a_new_archive()))
        self.assertEqual([self.ARCHIVE], self.asked)

    def test_what_works_unasked_does_not_use_it(self):
        """A thumbnail of an encrypted book would put its pages in the
        desktop's shared cache."""
        self._extract_with_a_new_archive()
        archive = zip_archive.ZipArchive(self.ARCHIVE)
        self.addCleanup(archive.close)
        with archive_password.never_asked():
            self.assertEqual('', archive._get_password())
        self.assertEqual('password', archive_password.remembered(self.ARCHIVE))

    def test_a_page_that_will_not_unpack_forgets_it(self):
        self.answer = 'wrong'
        destination = os.path.join(self.tmp_dir, 'extracted')
        os.makedirs(destination)
        extractor = archive_extractor.Extractor()
        extractor.setup(self.ARCHIVE, destination)
        self.addCleanup(extractor.close)
        self.assertTrue(wait_for(lambda: extractor.get_files() is not None,
                                 seconds=20))
        extractor.set_files([self.MEMBER])
        extractor.extract()
        self.assertTrue(wait_for(lambda: extractor.is_ready(self.MEMBER),
                                 seconds=20))
        self.assertEqual([self.ARCHIVE], self.asked)
        self.assertIsNone(archive_password.remembered(self.ARCHIVE))
        self.answer = 'password'
        self.assertTrue(os.path.isfile(self._extract_with_a_new_archive()))
        self.assertEqual([self.ARCHIVE, self.ARCHIVE], self.asked)

# vim: expandtab:sw=4:ts=4
