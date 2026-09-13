# -*- coding: utf-8 -*-

""" Tests for the password prompt, which is asked for by a thread that is
not the one that can show it. """

import threading

from gi.repository import Gtk

from . import MComixTest, get_testfile_path

from mcomix.archive import password as archive_password
from mcomix.archive import zip as zip_archive


def pump(rounds=200):
    """Let the main loop run through whatever is pending."""
    turns = 0
    while Gtk.events_pending() and turns < rounds:
        Gtk.main_iteration_do(False)
        turns += 1


def visible_prompts():
    """Every password prompt currently on screen."""
    return [window for window in Gtk.Window.list_toplevels()
            if isinstance(window, Gtk.MessageDialog) and window.get_visible()]


class PasswordDialogTest(MComixTest):

    def setUp(self):
        super(PasswordDialogTest, self).setUp()
        # test_archives.py replaces this for its own runs; make sure the
        # real dialog is what gets exercised here whatever the test order.
        self.real_ask_for_password = archive_password.ask_for_password

    def tearDown(self):
        for prompt in visible_prompts():
            prompt.destroy()
        pump()
        super(PasswordDialogTest, self).tearDown()

    def _wait_for_prompt(self, rounds=400):
        for _ in range(rounds):
            pump()
            prompts = visible_prompts()
            if prompts:
                return prompts[0]
        self.fail('no password prompt appeared')

    def _entry_in(self, widget):
        if isinstance(widget, Gtk.Entry):
            return widget
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                found = self._entry_in(child)
                if found is not None:
                    return found
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
        prompt.response(Gtk.ResponseType.OK)
        pump()
        self.assertEqual(answers, ['hunter2'])
        self.assertEqual(visible_prompts(), [])

    def test_cancelling_answers_with_no_password(self):
        answers = []
        self.real_ask_for_password('/nowhere/archive.zip', answers.append)
        prompt = self._wait_for_prompt()
        self._entry_in(prompt).set_text('hunter2')
        prompt.response(Gtk.ResponseType.CANCEL)
        pump()
        self.assertEqual(answers, [None])

    def test_an_empty_password_counts_as_none(self):
        answers = []
        self.real_ask_for_password('/nowhere/archive.zip', answers.append)
        prompt = self._wait_for_prompt()
        prompt.response(Gtk.ResponseType.OK)
        pump()
        self.assertEqual(answers, [None])

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
        prompt.response(Gtk.ResponseType.OK)

        for _ in range(400):
            pump()
            if listed:
                break
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), 'the listing thread never resumed')
        self.assertNotIn('error', listed, str(listed.get('error')))
        self.assertEqual(sorted(listed['names']),
                         ['arg.jpeg', 'bar.jpg', 'foo.JPG', 'meh.png'])

# vim: expandtab:sw=4:ts=4
