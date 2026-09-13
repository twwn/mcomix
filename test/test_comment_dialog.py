"""The Comments dialog, which shows the text files an archive carries.

One notebook stands for the life of the dialog and is emptied and
filled in again whenever the book changes; it used to be taken off the
dialog and replaced by another.
"""

import os
import zipfile

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

    def test_the_comments_of_the_book_before_are_taken_off_the_dialog(self):
        self._open(self._archive_with_comments(
            'commented.zip', ('one.txt', 'first')))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 1, seconds=20)
        self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        wait_for(lambda: not self._tabs(), seconds=20)
        self.assertEqual(self._tabs(), [])

    def test_a_comment_that_was_extracted_late_is_shown(self):
        """The dialog is told when a file comes out of the archive, and
        adds the tab it could not add while the file was not there."""
        self._open(self._archive_with_comments(
            'commented.zip', ('late.txt', 'read me')))
        self.dialog = comment_dialog._CommentsDialog(self.window)
        wait_for(lambda: len(self._tabs()) == 1, seconds=20)
        self.assertEqual(self._tabs(), ['late.txt'])


# vim: expandtab:sw=4:ts=4
