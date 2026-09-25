"""The Properties dialog, which is about the archive and the page.

A loose image is in no archive, so there was nothing on the Archive
page and nothing to choose between: it is offered only where there is
an archive to describe.
"""

import os
import zipfile
from unittest import mock

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix import properties_dialog


class PropertiesDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()

    def tearDown(self):
        for window in Gtk.Window.list_toplevels():
            if window.get_visible():
                window.destroy()
        pump()
        super().tearDown()

    def _open(self, path):
        self.window = main.MainWindow(open_path=path)
        main.set_main_window(self.window)
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)
        self.addCleanup(self._close)
        self.dialog = properties_dialog._PropertiesDialog(self.window)
        pump()
        return self.dialog

    def _close(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()

    def test_a_closed_dialog_does_not_read_the_pages_turned_to(self):
        """A destroyed dialog stayed listening, and read every page turned
        to - its file, its size, its thumbnail - for the rest of the
        session."""
        self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        with mock.patch.object(properties_dialog._PropertiesDialog,
                               '_update_image_page') as updated:
            self.window.flip_page(+1)
            wait_for(self.window.imagehandler.page_is_available)
            pump()
            self.assertTrue(updated.called, 'an open dialog did not follow')
            updated.reset_mock()

            self.dialog.destroy()
            pump()
            self.window.flip_page(+1)
            wait_for(self.window.imagehandler.page_is_available)
            pump()
        updated.assert_not_called()

    def _tabs(self):
        notebook = self.dialog._notebook
        return [notebook.get_tab_label_text(notebook.get_nth_page(index))
                for index in range(notebook.get_n_pages())]

    def _rows(self, page):
        """What a page says about the file, top box first."""
        rows = []
        for box in (page._mainbox, page._extrabox):
            child = box.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.Label):
                    rows.append(child.get_text())
                child = child.get_next_sibling()
        return rows

    def test_an_archive_is_described_on_a_page_of_its_own(self):
        dialog = self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        self.assertEqual(self._tabs(), ['Archive', 'Image'])
        self.assertTrue(dialog._notebook.get_show_tabs())

    def test_a_loose_image_is_offered_no_archive_page(self):
        self._open(get_testfile_path('images', 'blue.png'))
        self.assertEqual(self._tabs(), ['Image'])

    def test_one_page_is_shown_without_tabs_to_choose_between(self):
        dialog = self._open(get_testfile_path('images', 'blue.png'))
        self.assertFalse(dialog._notebook.get_show_tabs())

    def test_the_page_says_which_archive_is_open(self):
        dialog = self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        rows = self._rows(dialog._archive_page)
        self.assertIn('01-ZIP-Normal.zip', rows)
        self.assertTrue([row for row in rows if row.endswith(' pages')], rows)

    def test_one_page_and_one_comment_are_counted_in_the_singular(self):
        """The counts were written with one form for every number, so
        a book of one page with one comment said "1 pages, 1 comments"."""
        path = os.path.join(self.tmp_dir, 'single.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.write(get_testfile_path('images', 'blue.png'), 'blue.png')
            archive.writestr('notes.txt', 'Scanned by nobody.')
        rows = self._rows(self._open(path)._archive_page)
        self.assertIn('1 page', rows)
        self.assertIn('1 comment', rows)

    def test_describing_the_archive_again_does_not_say_it_twice(self):
        """Every update resets the page first, and a reset that left the
        rows behind would stack the next book's on top of them."""
        dialog = self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        before = self._rows(dialog._archive_page)
        dialog._update_archive_page()
        pump()
        self.assertEqual(self._rows(dialog._archive_page), before)

    def test_the_archive_page_comes_back_when_there_is_one_to_show(self):
        """Opening an archive after a loose image puts the page back,
        and the tabs with it."""
        dialog = self._open(get_testfile_path('images', 'blue.png'))
        self.assertEqual(self._tabs(), ['Image'])
        dialog._offer_archive_page(True)
        self.assertEqual(self._tabs(), ['Archive', 'Image'])
        self.assertTrue(dialog._notebook.get_show_tabs())

    def test_offering_the_page_that_is_already_there_changes_nothing(self):
        dialog = self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        dialog._offer_archive_page(True)
        self.assertEqual(self._tabs(), ['Archive', 'Image'])

    def test_an_open_dialog_follows_the_book_to_a_loose_image_and_back(self):
        """The tabs follow each book opened while the dialog stands."""
        self._open(get_testfile_path('archives', '01-ZIP-Normal.zip'))
        self.assertEqual(self._tabs(), ['Archive', 'Image'])
        self.window.filehandler.open_file(
            get_testfile_path('images', 'blue.png'))
        self.assertTrue(wait_for(lambda: self._tabs() == ['Image'],
                                 seconds=10), self._tabs())
        self.assertFalse(self.dialog._notebook.get_show_tabs())
        self.window.filehandler.open_file(
            get_testfile_path('archives', '01-ZIP-Normal.zip'))
        self.assertTrue(wait_for(lambda: self._tabs() == ['Archive', 'Image'],
                                 seconds=10), self._tabs())
        self.assertTrue(self.dialog._notebook.get_show_tabs())

    # -- What the archive's ComicInfo.xml says ----------------------------

    def _book(self, comicinfo=None):
        """Two of the test pages zipped up, with <comicinfo> as the
        archive's ComicInfo.xml where one is given."""
        path = os.path.join(self.tmp_dir, 'Described.cbz')
        with zipfile.ZipFile(path, 'w') as book:
            for name in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg'):
                book.write(get_testfile_path('images', name), name)
            if comicinfo is not None:
                book.writestr('ComicInfo.xml', comicinfo)
        return path

    @staticmethod
    def _texts(widget):
        """Every label's text under <widget>, depth first."""
        texts = []
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label):
                texts.append(child.get_text())
            texts.extend(PropertiesDialogTest._texts(child))
            child = child.get_next_sibling()
        return texts

    def test_the_archive_page_says_what_its_comicinfo_says(self):
        dialog = self._open(self._book(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<ComicInfo><Title>The Long Night</Title>'
            '<Series>Night Watch</Series><Number>3</Number>'
            '<Writer>A. Writer</Writer></ComicInfo>'))
        page = dialog._archive_page
        self.assertTrue(
            wait_for(lambda: 'Night Watch' in self._texts(page), seconds=10),
            'the series never appeared: %r' % self._texts(page))
        texts = self._texts(page)
        for label, value in (('Series:', 'Night Watch'), ('Number:', '3'),
                             ('Title:', 'The Long Night'),
                             ('Writer:', 'A. Writer')):
            self.assertIn(label, texts)
            self.assertIn(value, texts)
        # What the file on disk is still follows what the comic is.
        self.assertIn('Location:', texts)

    def test_an_archive_without_comicinfo_names_no_series(self):
        dialog = self._open(self._book())
        page = dialog._archive_page
        self.assertTrue(wait_for(lambda: 'Location:' in self._texts(page),
                                 seconds=10))
        pump()
        self.assertNotIn('Series:', self._texts(page))

    def test_a_comicinfo_that_does_not_parse_leaves_the_page_as_it_was(self):
        dialog = self._open(self._book('<ComicInfo><Series>Broken'))
        page = dialog._archive_page
        self.assertTrue(wait_for(lambda: 'Location:' in self._texts(page),
                                 seconds=10))
        wait_for(lambda: False, seconds=0.5)
        self.assertNotIn('Series:', self._texts(page))

    def test_a_file_whose_owner_has_no_name_here_is_described(self):
        """A file from another system - a USB stick, an unpacked
        download - can be owned by a user id this one has no name for.
        pwd.getpwuid() raised KeyError for it, and the page was left
        without its file's size, dates and owner."""
        if not properties_dialog._has_pwd:
            self.skipTest('no user database to lack the owner')

        def nobody(uid):
            raise KeyError('getpwuid(): uid not found: %d' % uid)

        with mock.patch('pwd.getpwuid', nobody):
            dialog = self._open(get_testfile_path('images', 'blue.png'))
            page = dialog._image_page
            self.assertTrue(
                wait_for(lambda: 'Owner:' in self._texts(page), seconds=10),
                'the page was left without its file: %r' % self._texts(page))
        uid = str(os.stat(get_testfile_path('images', 'blue.png')).st_uid)
        self.assertIn(uid, self._texts(page))

# vim: expandtab:sw=4:ts=4
