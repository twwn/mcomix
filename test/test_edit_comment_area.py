"""The list of comment files in the archive editor.

It was a Gtk.TreeView over a Gtk.ListStore of three columns, the third
of which - the full path - is what the archive is packed from. The
paths are what the tests are about: whatever the list draws, packing an
archive reads them back out of it in the order they are shown.
"""

import os

from gi.repository import Gdk, Gtk

from . import MComixTest, pump

from mcomix import edit_comment_area


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
        self.area = edit_comment_area._CommentArea(self.dialog)
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

    def test_an_imported_file_goes_on_the_end(self):
        self.area.fetch_comments()
        extra = os.path.join(self.tmp_dir, 'extra.txt')
        with open(extra, 'w') as comment:
            comment.write('extra')
        self.area.add_extra_file(extra)
        self.assertEqual(self.area.get_file_listing(), self.paths + [extra])

    def test_a_comment_shows_its_name_and_its_size(self):
        self.area.fetch_comments()
        row = self.area._list.get_row(0)
        self.assertEqual(row.name, 'one.txt')
        self.assertEqual(row.size, '7 B')

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

    def test_another_key_is_left_to_whoever_wants_it(self):
        self.area.fetch_comments()
        self.assertEqual(
            self.area._key_press(None, Gdk.KEY_a, 0, 0),
            Gdk.EVENT_PROPAGATE)
        self.assertEqual(self.area.get_file_listing(), self.paths)

# vim: expandtab:sw=4:ts=4
