""""Find duplicates..." in the library (mcomix.library.duplicates_dialog),
from the command to what is done with the copies it finds."""

import os
import shutil
import threading
import unittest.mock
import zipfile

from gi.repository import GLib, Gtk

from . import (descendants, drawn_page, encoded, pump, stop_on_the_second,
               visible_prompts, wait_for)
from .test_library_dialog import _LibraryWindowTest
from mcomix.dialog import Response
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

    def test_every_book_found_is_put_in_the_duplicates_collection(self):
        """Ticked or not, each book listed goes into "Duplicates", made
        for it and shown among the collections; a second time adds no
        second collection and no book twice."""
        found = self._found(self.first, self.same, self.longer, self.other)
        found._ticks[self._id(self.first)].set_active(False)
        for _ in range(2):
            found.response(duplicates_dialog._COLLECT)
            pump()
        backend = self.library.backend
        collection = backend.get_collection_by_name('Duplicates')
        self.assertIsNotNone(collection)
        self.assertEqual(
            sorted(self._id(path)
                   for path in (self.first, self.same, self.longer)),
            sorted(backend.get_books_in_collection(collection.id)))
        self.assertEqual(['Duplicates'], [
            name for name in map(backend.get_collection_name,
                                 backend.get_all_collections())
            if name == 'Duplicates'])

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

    @unittest.skipIf(os.name == 'nt', 'a symbolic link needs a privilege')
    def test_a_link_is_ticked_rather_than_its_file(self):
        """A book and a symbolic link to it are listed as copies; the
        link is ticked even where its book was added first, so trashing
        the copies ticked keeps the file."""
        link = os.path.join(self.tmp_dir, 'link.cbz')
        os.symlink(self.first, link)
        found = self._found(link, self.first)
        self.assertEqual([self._id(link)], found.ticked())

    def _ticks(self, found):
        return {path: found._ticks[self._id(path)].get_active()
                for path in (self.first, self.same, self.longer)}

    def test_untick_all_and_tick_recommended(self):
        """"Untick All" leaves nothing to act on; "Tick Recommended"
        ticks again every copy but the one to keep."""
        found = self._found(self.first, self.same, self.longer, self.other)
        found.untick_all()
        self.assertEqual([], found.ticked())
        self.assertFalse(found._removing.get_sensitive())
        self.assertFalse(
            found.get_widget_for_response(duplicates_dialog._SELECT)
            .get_sensitive())
        found.tick_recommended()
        self.assertEqual({self.first: True, self.same: True,
                          self.longer: False}, self._ticks(found))
        self.assertTrue(found._removing.get_sensitive())

    def test_a_group_ticked_by_hand_gets_its_ticks_back(self):
        """The reader kept another copy in a group: "Tick Recommended"
        gives that back rather than what the window would keep, after
        "Untick All" as well."""
        found = self._found(self.first, self.same, self.longer, self.other)
        found._ticks[self._id(self.longer)].set_active(True)
        found._ticks[self._id(self.first)].set_active(False)
        mine = {self.first: False, self.same: True, self.longer: True}
        found.tick_recommended()
        self.assertEqual(mine, self._ticks(found))
        found.untick_all()
        found.tick_recommended()
        self.assertEqual(mine, self._ticks(found))

    def test_the_remove_menu_holds_the_covers_three_removals(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        menu = found._removing.get_menu_model()
        self.assertEqual(
            [duplicates_dialog._REMOVE, duplicates_dialog._TRASH,
             duplicates_dialog._DELETE],
            [menu.get_item_attribute_value(
                place, 'target', GLib.VariantType.new('i')).get_int32()
             for place in range(menu.get_n_items())])
        found.activate_action('duplicates.respond',
                              GLib.Variant('i', duplicates_dialog._REMOVE))
        pump()
        prompt, = visible_prompts()
        self.addCleanup(prompt.destroy)
        self.assertIs(found, prompt.get_transient_for())

    def test_the_books_ticked_are_moved_to_the_trash_once_asked(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        tools = duplicates_dialog.tools
        with unittest.mock.patch.object(tools, 'trash_refuses',
                                        return_value=False), \
                unittest.mock.patch.object(tools, 'move_to_trash') as trash:
            found.response(duplicates_dialog._TRASH)
            pump()
            prompt, = visible_prompts()
            self.assertIs(found, prompt.get_transient_for())
            prompt.response(Response.YES)
            pump()
        self.assertEqual({self.first, self.same},
                         {call.args[0] for call in trash.call_args_list})
        for path in (self.first, self.same):
            self.assertIsNone(self.library.backend.get_book_by_path(path))
        self.assertEqual({self.longer, self.other},
                         set(self.library.book_area.shown_paths()))
        self.assertEqual([], found.ticked())

    def test_the_books_ticked_are_deleted_for_good_once_asked(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        found._ticks[self._id(self.same)].set_active(False)
        found.response(duplicates_dialog._DELETE)
        pump()
        prompt, = visible_prompts()
        self.assertIs(found, prompt.get_transient_for())
        self.assertIn('first.cbz', ' '.join(
            widget.get_text() for widget in descendants(prompt)
            if isinstance(widget, Gtk.Label)))
        prompt.response(Response.OK)
        pump()
        self.assertFalse(os.path.exists(self.first))
        self.assertTrue(os.path.isfile(self.same))
        self.assertIsNone(self.library.backend.get_book_by_path(self.first))
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

    def test_a_row_activated_opens_its_book(self):
        found = self._found(self.first, self.same, self.longer, self.other)
        opened = self.enterContext(unittest.mock.patch.object(
            self.library, 'open_book'))
        row = found._ticks[self._id(self.same)].get_ancestor(Gtk.ListBoxRow)
        row.activate()
        pump()
        opened.assert_called_once_with([self._id(self.same)],
                                       keep_library_open=True)
