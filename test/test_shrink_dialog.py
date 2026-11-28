""""Shrink oversized pages..." in the library (mcomix.shrink_dialog), from
the limit asked for to the books written smaller."""

import errno
import os
import types
import unittest.mock
import zipfile

from gi.repository import Gtk
from PIL import Image

from . import drawn_page, encoded, pump, visible_prompts, wait_for
from .test_library_dialog import _LibraryWindowTest
from mcomix import shrink_dialog
from mcomix import webp_dialog
from mcomix.dialog import Response
from mcomix.preferences import prefs


class ShrinkPagesTest(_LibraryWindowTest):

    """Three books: two with a page over the limit, one without."""

    def setUp(self):
        super().setUp()
        self.library = self._open_all()
        self.large = self._book('large.cbz', (1000, 1500))
        self.larger = self._book('larger.cbz', (2000, 3000))
        self.small = self._book('small.cbz', (400, 600))
        self.enterContext(unittest.mock.patch.dict(
            prefs, {'shrink page height': 600, 'shrink page quality': 70}))

    def _book(self, name, size):
        path = os.path.join(self.tmp_dir, name)
        with zipfile.ZipFile(path, 'w') as book:
            book.writestr('01.jpg', encoded(drawn_page(len(name), size),
                                            'JPEG', quality=95))
            book.writestr('02.png', encoded(drawn_page(1, (400, 600)), 'PNG'))
        return path

    def _asked(self, *paths):
        """Hold <paths> in the library, select every cover and give the
        command; answer with its window."""
        self._held(self.library, *paths)
        self.library.book_area._covers.select_all()
        self.library.book_area.shrink_pages()
        asked, = [window for window in Gtk.Window.list_toplevels()
                  if isinstance(window, shrink_dialog.ShrinkDialog)]
        self.addCleanup(asked.destroy)
        return asked

    def _found(self, *paths):
        asked = self._asked(*paths)
        asked.response(shrink_dialog._FIND)
        self.assertTrue(wait_for(lambda: asked.surveyed, seconds=20))
        pump()
        return asked

    def test_the_limit_and_quality_are_those_set_last(self):
        asked = self._asked(self.large)
        self.assertEqual((600, 70),
                         (asked.shrink.limit, asked.shrink.quality))
        asked._limit.set_value(800)
        asked.response(shrink_dialog._FIND)
        self.assertTrue(wait_for(lambda: asked.surveyed, seconds=20))
        self.assertEqual(800, prefs['shrink page height'])

    def test_the_books_over_the_limit_are_listed_ticked(self):
        asked = self._found(self.large, self.larger, self.small)
        self.assertEqual(sorted([self.large, self.larger]),
                         sorted(asked.ticked()))
        self.assertEqual(sorted([self.large, self.larger]),
                         sorted(path for path, _found in asked.found))
        status = asked._status.get_text()
        self.assertIn('2 books have pages over the limit', status)
        self.assertIn('1 book left as it was: no page over the limit',
                      status)
        shrink = asked.get_widget_for_response(Response.OK)
        self.assertTrue(shrink.get_sensitive())
        for tick in asked.ticks.values():
            tick.set_active(False)
        self.assertFalse(shrink.get_sensitive())

    def test_only_the_books_left_ticked_are_shrunk_and_trashed(self):
        asked = self._found(self.large, self.larger, self.small)
        asked.ticks[self.larger].set_active(False)
        before = {path: os.path.getsize(path)
                  for path in (self.large, self.larger, self.small)}
        progress = self._written(asked)
        with zipfile.ZipFile(self.large) as book:
            self.assertEqual(['01.webp', '02.png'], sorted(book.namelist()))
            with book.open('01.webp') as member, Image.open(member) as page:
                self.assertEqual((400, 600), page.size)
        for path in (self.larger, self.small):
            self.assertEqual(before[path], os.path.getsize(path))
        self.assertEqual(1, len(os.listdir(self.trash_dir)))
        self.assertTrue(progress._status.get_text().startswith(
            '1 book shrunk'))

    def test_a_full_disk_stops_the_books_left(self):
        """Every book after the one with no room would be unpacked only
        to fail; the summary says why, and where the room went."""
        third = self._book('largest.cbz', (1500, 2200))
        asked = self._found(self.large, self.larger, third)
        real = webp_dialog.webp_books.convert
        calls = []

        def convert(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                return real(path, *args, **kwargs)
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), path)

        with unittest.mock.patch.object(webp_dialog.webp_books, 'convert',
                                        convert), \
                self.assertLogs('mcomix', level='WARNING'):
            progress = self._written(asked)
        self.assertEqual(2, len(calls), 'the third book was still tried')
        text = progress._status.get_text()
        self.assertIn('not yet looked at', text)
        self.assertIn('in the trash', text)
        self.assertIn('The disk is full', progress.log_text())

    def _short_of_room(self):
        """Found and asked to shrink with no room on the disk; answer
        with the window that found them and the question."""
        asked = self._found(self.large, self.larger)
        room = types.SimpleNamespace(free=1)
        with unittest.mock.patch.object(shrink_dialog.shutil, 'disk_usage',
                                        return_value=room):
            asked.response(Response.OK)
        pump()
        prompt, = visible_prompts()
        self.addCleanup(prompt.destroy)
        self.assertIs(prompt.get_default_widget(),
                      prompt.get_widget_for_response(Response.CANCEL))
        return asked, prompt

    def test_short_of_room_asks_before_writing_and_cancel_writes_nothing(
            self):
        before = {path: os.path.getsize(path)
                  for path in (self.large, self.larger)}
        _asked, prompt = self._short_of_room()
        prompt.response(Response.CANCEL)
        pump()
        self.assertEqual([], [window for window in Gtk.Window.list_toplevels()
                              if isinstance(window,
                                            webp_dialog._ProgressDialog)])
        self.assertEqual(before, {path: os.path.getsize(path)
                                  for path in before})

    def test_short_of_room_the_originals_can_be_deleted_instead(self):
        asked, prompt = self._short_of_room()
        progress = self._written(prompt)
        self.assertTrue(progress._status.get_text().startswith(
            '2 books shrunk'))
        self.assertFalse(os.path.exists(self.trash_dir), 'trashed')
        with zipfile.ZipFile(self.larger) as book:
            self.assertIn('01.webp', book.namelist())

    def test_a_fault_in_one_book_does_not_stop_the_window(self):
        """An exception that is no OSError ended the thread, and the
        window never showed its summary."""
        asked = self._found(self.large, self.larger)
        real = webp_dialog.webp_books.convert

        def convert(path, *args, **kwargs):
            if path == self.large:
                raise TypeError('a fault')
            return real(path, *args, **kwargs)

        with unittest.mock.patch.object(webp_dialog.webp_books, 'convert',
                                        convert), \
                self.assertLogs('mcomix', level='ERROR'):
            progress = self._written(asked)
        self.assertEqual([(self.large, 'a fault')], progress._failed)
        self.assertTrue(progress._status.get_text().startswith(
            '1 book shrunk'))

    def test_nothing_over_the_limit_offers_only_to_close(self):
        asked = self._found(self.small)
        self.assertEqual([], asked.ticked())
        self.assertIsNone(asked.get_widget_for_response(Response.OK))
        asked.response(Response.CANCEL)
        pump()
        self.assertFalse(asked.get_visible())

# vim: expandtab:sw=4:ts=4
