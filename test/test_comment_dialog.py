"""The Comments dialog, which shows the text files an archive carries.

One notebook stands for the life of the dialog and is emptied and
filled in again whenever the book changes; it used to be taken off the
dialog and replaced by another.
"""

import os
import zipfile
from unittest import mock

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import comment_dialog
from mcomix import constants
from mcomix import icons
from mcomix import main


class CommentsDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = None
        self.dialog = None

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.destroy()
        if self.window is not None:
            self.window.terminate_program()
            self.window.destroy()
            main.set_main_window(None)
        pump()
        super().tearDown()

    def _archive_with_comments(self, name, *comments):
        """An archive of one page carrying <comments>, as (name, text)."""
        path = os.path.join(self.tmp_dir, name)
        image = get_testfile_path('images', 'blue.png')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.write(image, '001.png')
            for comment_name, text in comments:
                archive.writestr(comment_name, text)
        return path

    def _open(self, path):
        if self.window is None:
            self.window = main.MainWindow(open_path=path)
            main.set_main_window(self.window)
        else:
            self.window.filehandler.open_file(path)
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)
        wait_for(lambda: self.window.filehandler.get_number_of_comments() >= 0,
                 seconds=20)

    def _tabs(self):
        notebook = self.dialog._notebook
        return [notebook.get_tab_label_text(notebook.get_nth_page(index))
                for index in range(notebook.get_n_pages())]

    def test_every_comment_gets_a_tab_of_its_own(self):
        self._open(self._archive_with_comments(
            'commented.zip', ('one.txt', 'first'), ('two.txt', 'second')))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 2, seconds=20)
        self.assertEqual(sorted(self._tabs()), ['one.txt', 'two.txt'])

    def test_a_comment_announced_after_it_was_shown_is_not_shown_twice(self):
        """The extractor announces a file from the idle queue, and one
        that finished while the dialog was being built was both shown
        by it and announced to it after: a second tab of the same
        comment, seen once in a loaded run of the suite."""
        self._open(self._archive_with_comments(
            'commented.zip', ('one.txt', 'first'), ('two.txt', 'second')))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 2, seconds=20)
        self.dialog._on_file_available(list(self.dialog._comments))
        self.assertEqual(sorted(self._tabs()), ['one.txt', 'two.txt'])

    def test_the_comments_of_the_book_before_are_taken_off_the_dialog(self):
        self._open(self._archive_with_comments(
            'commented.zip', ('one.txt', 'first')))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 1, seconds=20)
        self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        wait_for(lambda: not self._tabs(), seconds=20)
        self.assertEqual(self._tabs(), [])
        # An empty notebook is hidden rather than shown with a tab strip
        # that has nothing in it, which GTK warns about.
        self.assertFalse(self.dialog._notebook.get_visible())

    def test_a_comment_that_was_extracted_late_is_shown(self):
        """The dialog is told when a file comes out of the archive, and
        adds the tab it could not add while the file was not there."""
        self._open(self._archive_with_comments(
            'commented.zip', ('late.txt', 'read me')))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 1, seconds=20)
        self.assertEqual(self._tabs(), ['late.txt'])
        self.assertTrue(self.dialog._notebook.get_visible())


    def _text_of(self, index):
        """What the text view on page <index> of the notebook holds."""
        page = self.dialog._notebook.get_nth_page(index)
        buffer = page.get_first_child().get_child().get_buffer()
        return buffer.get_text(*buffer.get_bounds(), False)

    def test_a_comment_is_shown_whatever_encoding_it_is_written_in(self):
        """Nothing says what encoding a text file in an archive is in.

        It was read as text, which decodes it in whatever encoding the
        machine's locale names: a comment written in another one raised
        UnicodeDecodeError, and the dialog showed "Could not read" in
        place of every line of it.
        """
        # A comment of a length a real one has: fifteen letters are too
        # few to tell a code page by, and chardet 7 reads "café à la
        # carte" as Windows-1251 however they are encoded.
        text = ('Ce volume réunit les épisodes parus dans le magazine '
                'entre 1998 et 2001. Traduction française et lettrage: '
                "l'équipe. Merci à tous les lecteurs, à bientôt!")
        self._open(self._archive_with_comments(
            'latin.zip', ('note.txt', text.encode('latin-1'))))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 1, seconds=20)
        self.assertEqual(text, self._text_of(0))

    def test_a_comment_in_utf_8_is_shown_as_it_was_written(self):
        self._open(self._archive_with_comments(
            'utf8.zip', ('note.txt', 'caf\xe9 \u3042'.encode('utf-8'))))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 1, seconds=20)
        self.assertEqual('caf\xe9 \u3042', self._text_of(0))

    def test_a_closed_dialog_does_not_read_the_comments_of_the_next_book(self):
        """A destroyed dialog stayed listening, and put a tab together for
        every comment of every book opened after it."""
        self._open(self._archive_with_comments(
            'first.zip', ('one.txt', 'first')))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 1, seconds=20)
        self.dialog.destroy()
        self.dialog = None
        pump()

        with mock.patch.object(comment_dialog._CommentsDialog,
                               '_add_comment') as added:
            self._open(self._archive_with_comments(
                'second.zip', ('two.txt', 'second')))
            handler = self.window.filehandler
            wait_for(lambda: handler.get_number_of_comments() == 1 and
                     handler.file_is_available(handler.get_comment_name(1)),
                     seconds=20)
            pump()
        added.assert_not_called()

# vim: expandtab:sw=4:ts=4
