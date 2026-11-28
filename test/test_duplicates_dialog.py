""""Find duplicates..." in the library (mcomix.library.duplicates_dialog),
from the command to what is done with the copies it finds."""

import os
import shutil
import threading
import unittest.mock
import zipfile

from gi.repository import Gtk

from . import (drawn_page, encoded, pump, stop_on_the_second, visible_prompts,
               wait_for)
from .test_library_dialog import _LibraryWindowTest
from mcomix.dialog import Response
from mcomix.library import duplicates
from mcomix.library import duplicates_dialog
from mcomix.library import fingerprint
from mcomix.preferences import prefs


class FindDuplicatesTest(_LibraryWindowTest):

    """Four books: two of the same file, one with those pages and one
    more, and one of other pages."""

    def setUp(self):
        super().setUp()
        self.library = self._open_all()
        self.first = self._book('first.cbz', (1, 2, 3))
        self.same = os.path.join(self.tmp_dir, 'same.cbz')
        shutil.copyfile(self.first, self.same)
        self.longer = self._book('longer.cbz', (1, 2, 3, 4))
        self.other = self._book('other.cbz', (7, 8, 9))

    def _book(self, name, seeds):
        path = os.path.join(self.tmp_dir, name)
        with zipfile.ZipFile(path, 'w') as book:
            for number, seed in enumerate(seeds, 1):
                book.writestr('%02d.png' % number,
                              encoded(drawn_page(seed, (300, 450)), 'PNG'))
        return path

    def _id(self, path):
        return self.library.backend.get_book_by_path(path).id

    def _found(self, *paths):
        """Hold <paths> in the library, give the command and answer with
        its window once it has shown what it found."""
        self._held(self.library, *paths)
        self.library.book_area.find_duplicates()
        found, = [window for window in Gtk.Window.list_toplevels()
                  if isinstance(window, duplicates_dialog.DuplicatesDialog)]
        self.addCleanup(found.destroy)
        self.assertTrue(wait_for(lambda: found.finished, seconds=20))
        pump()
        return found

    def test_the_copies_are_listed_and_all_but_one_ticked(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        # The one with most pages is kept.
        self.assertEqual({self._id(self.first): True,
                          self._id(self.same): True,
                          self._id(self.longer): False},
                         {book: tick.get_active()
                          for book, tick in found._ticks.items()})
        self.assertIsNotNone(found.get_widget_for_response(
            duplicates_dialog._SELECT))

    def test_the_books_ticked_are_selected_in_the_library(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        found._ticks[self._id(self.first)].set_active(False)
        found.response(duplicates_dialog._SELECT)
        pump()
        self.assertEqual(
            [self.same], [item.path for item in
                          self.library.book_area._selected_items()])

    def test_the_books_ticked_are_removed_once_asked(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        found.response(duplicates_dialog._REMOVE)
        pump()
        prompt, = visible_prompts()
        prompt.response(Response.OK)
        pump()
        self.assertEqual({self.longer, self.other},
                         set(self.library.book_area.shown_paths()))
        for path in (self.first, self.same):
            self.assertIsNone(self.library.backend.get_book_by_path(path))
            self.assertTrue(os.path.isfile(path), msg=path)
        self.assertEqual([], found.ticked())

    def test_a_library_without_copies(self):
        found = self._found(self.first, self.other)
        self.assertEqual({}, found._ticks)
        self.assertIsNone(found.get_widget_for_response(
            duplicates_dialog._SELECT))

    def test_a_book_read_once_is_not_read_again(self):
        self._found(self.first, self.same, self.longer, self.other).destroy()
        read = self.enterContext(unittest.mock.patch.object(
            fingerprint, 'make', wraps=fingerprint.make))
        self.library.book_area.find_duplicates()
        found, = [window for window in Gtk.Window.list_toplevels()
                  if isinstance(window, duplicates_dialog.DuplicatesDialog)
                  and window.is_visible()]
        self.addCleanup(found.destroy)
        self.assertTrue(wait_for(lambda: found.finished, seconds=20))
        read.assert_not_called()
        self.assertEqual(3, len(found._ticks))

    def test_stop_compares_what_was_read(self):
        """One book at a time, and the second held until Stop."""
        self.enterContext(unittest.mock.patch.dict(prefs,
                                                   {'max threads': 1}))
        go = threading.Event()
        made = fingerprint.make
        reads = []

        def make(path):
            reads.append(path)
            if len(reads) == 2:
                go.wait(10)
            return made(path)
        self.enterContext(unittest.mock.patch.object(fingerprint, 'make',
                                                     make))
        self._held(self.library, self.first, self.same, self.other)
        self.library.book_area.find_duplicates()
        found, = [window for window in Gtk.Window.list_toplevels()
                  if isinstance(window, duplicates_dialog.DuplicatesDialog)]
        self.addCleanup(found.destroy)
        stop_on_the_second(found, reads, go)
        self.assertIn('Stopped with 1 book not yet read.',
                      found._status.get_text())

    def test_the_copy_to_keep(self):
        def made(pages, width, size):
            return fingerprint.Fingerprint(size, 0, pages, (
                fingerprint.Sample(b'', b'', width, width),))
        books = {1: made(10, 100, 500), 2: made(12, 100, 900),
                 3: made(12, 200, 900), 4: made(12, 200, 800)}
        self.assertEqual(4, duplicates.to_keep((1, 2, 3, 4), books))
        self.assertEqual(3, duplicates.to_keep((1, 2, 3), books))
        self.assertEqual(2, duplicates.to_keep((1, 2), books))

    def test_a_row_activated_opens_its_book(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        opened = self.enterContext(unittest.mock.patch.object(
            self.library, 'open_book'))
        row = found._ticks[self._id(self.same)].get_ancestor(Gtk.ListBoxRow)
        row.activate()
        pump()
        opened.assert_called_once_with([self._id(self.same)],
                                       keep_library_open=True)
