"""The list of comment files in the archive editor.

It was a Gtk.TreeView over a Gtk.ListStore of three columns, the third
of which - the full path - is what the archive is packed from. The
paths are what the tests are about: whatever the list draws, packing an
archive reads them back out of it in the order they are shown.
"""

import os
import unittest.mock

from gi.repository import Gdk, GLib, Gtk

from . import MComixTest, pump

from mcomix import edit_comment_area
from mcomix.dialog import Response


class _StubHandler:

    def __init__(self, paths):
        self._paths = paths

    def get_number_of_comments(self):
        return len(self._paths)

    def get_comment_name(self, number):
        return self._paths[number - 1]


class _StubDialog:

    def __init__(self, paths):
        self.file_handler = _StubHandler(paths)
        #: What record_change() was told, so that a test can see the
        #: area asking for a change to be undoable.
        self.changes = 0

    def record_change(self):
        self.changes += 1


class _Event:

    """What a callback.Callback of the file handler is to its listeners:
    something to add oneself to and take oneself off."""

    def __init__(self):
        self.listeners = []

    def __iadd__(self, listener):
        self.listeners.append(listener)
        return self

    def __isub__(self, listener):
        self.listeners.remove(listener)
        return self

    def __call__(self, *args):
        for listener in list(self.listeners):
            listener(*args)


class CommentAreaTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.paths = []
        for name in ('one.txt', 'two.txt', 'three.txt'):
            path = os.path.join(self.tmp_dir, name)
            with open(path, 'w') as comment:
                comment.write(name)
            self.paths.append(path)
        # Held here: the area holds its editor only weakly, as the
        # editor holds the area.
        self.dialog = _StubDialog(self.paths)
        # The area asks the window whether a page holds a name a
        # comment file is being renamed to; this book has no pages.
        self.main_window = unittest.mock.MagicMock()
        self.main_window.file_actions.page_called.return_value = None
        self.file_available = _Event()
        self.main_window.filehandler.file_available = self.file_available
        self.area = edit_comment_area._CommentArea(self.dialog,
                                                   self.main_window)
        self.window = Gtk.Window()
        self.window.set_default_size(400, 300)
        self.window.set_child(self.area)
        self.window.present()
        pump()

    def tearDown(self):
        # A window left on screen is answered by whatever looks for one
        # next.
        self.window.destroy()
        pump()
        super().tearDown()

    def test_fetching_the_comments_lists_every_one_of_them(self):
        self.area.fetch_comments()
        self.assertEqual(self.area.get_file_listing(), self.paths)

    def test_fetching_twice_lists_each_comment_once(self):
        """The list of pages beside this one replaces what it shows, and
        a name here is read back by the path it came from, which two
        rows for one file cannot answer for."""
        self.area.fetch_comments()
        self.area.fetch_comments()
        self.assertEqual(self.area.get_file_listing(), self.paths)

    def test_an_imported_file_goes_on_the_end(self):
        self.area.fetch_comments()
        extra = os.path.join(self.tmp_dir, 'extra.txt')
        with open(extra, 'w') as comment:
            comment.write('extra')
        self.area.add_extra_file(extra)
        self.assertEqual(self.area.get_file_listing(), self.paths + [extra])

    def test_a_comment_not_out_of_the_archive_yet_is_listed_all_the_same(self):
        """The editor lists the comments as soon as the book is open,
        and reading the size of one the extractor had not reached raised
        FileNotFoundError: no comment was listed at all."""
        late = os.path.join(self.tmp_dir, 'late.txt')
        self.paths.append(late)
        self.area.fetch_comments()
        rows = list(self.area._list.each_row())
        self.assertEqual([row.path for row in rows], self.paths)
        self.assertEqual('', rows[-1].size)
        # Out of the archive now, and announced.
        with open(late, 'w') as comment:
            comment.write('late')
        self.file_available([late])
        self.assertEqual(GLib.format_size(4), rows[-1].size)

    def test_the_area_listens_for_files_only_while_it_is_shown(self):
        self.assertEqual([self.area._on_file_available],
                         self.file_available.listeners)
        self.window.destroy()
        pump()
        self.assertEqual([], self.file_available.listeners)

    def test_a_comment_shows_its_name_and_its_size(self):
        self.area.fetch_comments()
        row = self.area._list.get_row(0)
        self.assertEqual(row.name, 'one.txt')
        self.assertEqual(row.size, GLib.format_size(7))

    def test_removing_the_selected_comment_takes_it_out_of_the_listing(self):
        self.area.fetch_comments()
        self.area._list.select_only(1)
        self.area._remove_file()
        self.assertEqual(self.area.get_file_listing(),
                         [self.paths[0], self.paths[2]])

    def test_removing_with_nothing_selected_removes_nothing(self):
        self.area.fetch_comments()
        self.area._list.unselect_all()
        self.area._remove_file()
        self.assertEqual(self.area.get_file_listing(), self.paths)

    def test_delete_removes_the_selected_comment(self):
        self.area.fetch_comments()
        self.area._list.select_only(0)
        self.assertEqual(
            self.area._key_press(None, Gdk.KEY_Delete, 0, 0),
            Gdk.EVENT_STOP)
        self.assertEqual(self.area.get_file_listing(), self.paths[1:])

    # -- Renaming a comment file ------------------------------------------

    def _asked_for_a_name(self, row=0):
        """Ask to rename the file at <row>, and answer with what the
        dialog was given: the clash callable and the answer callable.

        The dialog itself is not built: its parent is the editor, which
        is a stub here, and what this area does is decide what clashes
        and what each answer means.
        """
        self.area.fetch_comments()
        self.area._list.select_only(row)
        with unittest.mock.patch.object(edit_comment_area.rename_dialog,
                                        'ask') as asked:
            self.area._rename_file()
        self.assertEqual(asked.call_count, 1, 'nothing asked for a name')
        return asked.call_args.kwargs['clash'], \
            asked.call_args.kwargs['answered']

    def test_a_comment_takes_the_name_that_was_typed(self):
        clash, answered = self._asked_for_a_name()
        self.assertIsNone(clash('Notes.txt'))
        answered(Response.OK, 'Notes.txt')
        self.assertEqual(self.area._list.get_row(0).name, 'Notes.txt')
        self.assertEqual(self.area.file_names()[self.paths[0]], 'Notes.txt')
        self.assertEqual(self.dialog.changes, 1,
                         'the name cannot be undone')

    def test_a_name_with_no_extension_keeps_the_old_one(self):
        clash, answered = self._asked_for_a_name()
        answered(Response.OK, 'Notes')
        self.assertEqual(self.area._list.get_row(0).name, 'Notes.txt')

    def test_a_name_another_file_holds_offers_a_swap_and_a_replace(self):
        clash, answered = self._asked_for_a_name()
        taken = clash('two.txt')
        self.assertIsNotNone(taken, 'the name was taken without a word')
        self.assertIn('two.txt', taken.told)
        self.assertTrue(taken.answers)

    def test_a_name_a_page_holds_is_warned_about_with_nothing_offered(self):
        """The page is in the other tab, which this list does not
        touch: it can be neither renamed nor removed from here."""
        self.main_window.file_actions.page_called.return_value = 4
        clash, answered = self._asked_for_a_name()
        taken = clash('Cover.png')
        self.assertIsNotNone(taken)
        self.assertIn('Cover.png', taken.told)
        self.assertFalse(taken.answers)

    def test_swapping_the_names_gives_each_file_the_others(self):
        clash, answered = self._asked_for_a_name()
        answered(edit_comment_area.rename_dialog.SWAP, 'two.txt')
        self.assertEqual([row.name for row in self.area._list.each_row()],
                         ['two.txt', 'one.txt', 'three.txt'])

    def test_replacing_takes_the_file_that_held_the_name_out(self):
        clash, answered = self._asked_for_a_name()
        answered(edit_comment_area.rename_dialog.REPLACE, 'two.txt')
        self.assertEqual(self.area.get_file_listing(),
                         [self.paths[0], self.paths[2]])
        self.assertEqual(self.area._list.get_row(0).name, 'two.txt')

    def test_a_name_that_says_nothing_renames_nothing(self):
        clash, answered = self._asked_for_a_name()
        answered(Response.OK, '   ')
        answered(Response.OK, 'one.txt')
        self.assertEqual([row.name for row in self.area._list.each_row()],
                         ['one.txt', 'two.txt', 'three.txt'])
        self.assertEqual(self.dialog.changes, 0)

    def test_f2_asks_for_a_name(self):
        self.area.fetch_comments()
        self.area._list.select_only(0)
        with unittest.mock.patch.object(self.area, '_rename_file') as asked:
            self.assertEqual(
                self.area._key_press(None, Gdk.KEY_F2, 0, 0),
                Gdk.EVENT_STOP)
        asked.assert_called_once_with()

    def test_another_key_is_left_to_whoever_wants_it(self):
        self.area.fetch_comments()
        self.assertEqual(
            self.area._key_press(None, Gdk.KEY_a, 0, 0),
            Gdk.EVENT_PROPAGATE)
        self.assertEqual(self.area.get_file_listing(), self.paths)

# vim: expandtab:sw=4:ts=4
