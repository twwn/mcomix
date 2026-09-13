"""The Properties dialog, which is about the archive and the page.

A loose image is in no archive, so there was nothing on the Archive
page and nothing to choose between: it is offered only where there is
an archive to describe.
"""

import os

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

# vim: expandtab:sw=4:ts=4
