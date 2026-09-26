""" Tests for the "Move to" submenu of the right-click menu. """

import datetime
import os
import sys
import unittest

from gi.repository import GLib, Gtk

from . import MComixTest, posix_byte_names, pump, wait_for

from mcomix import bookmark_backend
from mcomix import callback
from mcomix import constants
from mcomix import file_chooser_simple_dialog
from mcomix import move_menu
from mcomix import widgets
from mcomix.dialog import Response
from mcomix.preferences import prefs


class _StubFileHandler:

    file_loaded = True
    archive_type = None

    @callback.Callback
    def file_opened(self):
        pass

    @callback.Callback
    def file_closed(self):
        pass


class _StubImageHandler:

    path = None

    def get_real_path(self):
        return self.path


class _StubRecent:

    def __init__(self):
        self.recent_paths = []

    def paths(self):
        return self.recent_paths


class _StubFileActions:

    """Where the move lands, which the window keeps beside itself."""

    def __init__(self):
        self.moved_to = []

    def move_current_file(self, directory):
        self.moved_to.append(directory)


class _StubWindow(Gtk.Window):

    """A real window, so the menu's action group has somewhere to live."""

    def __init__(self):
        super().__init__()
        self.filehandler = _StubFileHandler()
        self.imagehandler = _StubImageHandler()
        self.file_actions = _StubFileActions()

    @property
    def moved_to(self):
        return self.file_actions.moved_to


class MoveToMenuTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.window = _StubWindow()
        self.recent = _StubRecent()
        self.store = bookmark_backend.BookmarksStore
        self.store._initialized = False
        self.store._bookmarks = []
        self.window.imagehandler.path = self._file('here', 'book.cbz')

    def tearDown(self):
        # Anything left on screen would be answered by the next test
        # that goes looking for a dialog.
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, file_chooser_simple_dialog
                          .SimpleFileChooserDialog):
                window.destroy()
        pump()
        super().tearDown()

    def _menu(self):
        return move_menu.MoveToMenu(self.window, self.recent)

    def _directory(self, *parts):
        """Make a directory under the test's own temporary one."""
        path = os.path.join(self.tmp_dir, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def _file(self, directory, name):
        """Make an empty file called <name> in <directory>."""
        path = os.path.join(self._directory(directory), name)
        with open(path, 'wb'):
            pass
        return path

    def _bookmark(self, path):
        self.store.add_bookmark_by_values(
            os.path.basename(path), path, 1, 20, None,
            datetime.datetime.now())

    @staticmethod
    def _sections(model):
        """The menu as a list of (section label, [(label, target)])."""
        sections = []
        for position in range(model.get_n_items()):
            label = model.get_item_attribute_value(position, 'label', None)
            section = model.get_item_link(position, 'section')
            entries = []
            for index in range(section.get_n_items()):
                entries.append((
                    section.get_item_attribute_value(index, 'label',
                                                     None).get_string(),
                    section.get_item_attribute_value(index, 'target', None)))
            sections.append((label.get_string() if label else None, entries))
        return sections

    @staticmethod
    def _path(target):
        """The directory a menu entry's target names."""
        return os.fsdecode(bytes(target.get_bytestring()))

    def _destinations(self, model):
        """Every directory the menu offers, in the order it offers them."""
        return [self._path(target)
                for _label, entries in self._sections(model)
                for _entry, target in entries if target is not None]

    def test_the_directories_moved_to_before_are_offered(self):
        first = self._directory('first')
        second = self._directory('second')
        prefs['recent move destinations'] = [first, second]

        self.assertEqual(self._destinations(self._menu().model),
                         [first, second])

    def test_the_directory_the_file_is_in_is_not_offered(self):
        """Moving a file to where it is would fail as a name that is taken."""
        here = self._directory('here')
        prefs['recent move destinations'] = [here, self._directory('other')]

        self.assertEqual(self._destinations(self._menu().model),
                         [os.path.join(self.tmp_dir, 'other')])

    def test_a_directory_that_is_no_longer_there_is_not_offered(self):
        gone = self._directory('gone')
        os.rmdir(gone)
        prefs['recent move destinations'] = [gone, self._directory('there')]

        self.assertEqual(self._destinations(self._menu().model),
                         [os.path.join(self.tmp_dir, 'there')])

    @unittest.skipIf(sys.platform == 'win32' or os.getuid() == 0,
                     'the mode bits hold back neither root nor anyone '
                     'on Windows')
    def test_a_directory_that_cannot_be_written_to_is_not_offered(self):
        closed = self._directory('closed')
        os.chmod(closed, 0o500)
        try:
            prefs['recent move destinations'] = [closed]
            self.assertEqual(self._destinations(self._menu().model), [])
        finally:
            os.chmod(closed, 0o700)

    def test_the_bookmarked_and_the_recently_opened_are_offered_too(self):
        self._bookmark(self._file('bookmarked', 'other.cbz'))
        self.recent.recent_paths = [self._file('opened', 'third.cbz')]
        prefs['recent move destinations'] = [self._directory('moved')]

        self.assertEqual(
            [(label, [self._path(target) if target is not None else entry
                      for entry, target in entries])
             for label, entries in self._sections(self._menu().model)],
            [('Moved to before', [os.path.join(self.tmp_dir, 'moved')]),
             ('From bookmarks', [os.path.join(self.tmp_dir, 'bookmarked')]),
             ('Opened before', [os.path.join(self.tmp_dir, 'opened')]),
             (None, ['Other folder...'])])

    @posix_byte_names
    def test_a_directory_whose_name_is_not_utf_8_is_offered_all_the_same(self):
        """A GVariant string and a menu label must both be UTF-8, and a
        directory name on disk need not be: a Latin-1 one raised
        UnicodeEncodeError while the menu was built, and it was built
        with nothing in it at all."""
        latin = os.fsdecode(os.path.join(os.fsencode(self.tmp_dir),
                                         'B\xfccher'.encode('latin-1')))
        os.makedirs(latin)
        plain = self._directory('plain')
        prefs['recent move destinations'] = [latin, plain]

        menu = self._menu()
        self.assertEqual(self._destinations(menu.model), [latin, plain])
        labels = [entry for _label, entries in self._sections(menu.model)
                  for entry, _target in entries]
        self.assertTrue(any('B\ufffdcher' in label for label in labels),
                        labels)

        menu._actions.activate_action(
            'move', GLib.Variant.new_bytestring(os.fsencode(latin)))
        self.assertEqual(self.window.file_actions.moved_to, [latin])

    def test_a_directory_on_two_lists_is_offered_once(self):
        shared = self._directory('shared')
        self._bookmark(self._file('shared', 'other.cbz'))
        prefs['recent move destinations'] = [shared]

        self.assertEqual(self._destinations(self._menu().model), [shared])

    def test_a_section_offers_no_more_than_five_directories(self):
        prefs['recent move destinations'] = [
            self._directory('d%d' % number) for number in range(8)]

        self.assertEqual(len(self._destinations(self._menu().model)),
                         move_menu.MoveToMenu.SECTION_LIMIT)

    def test_a_destination_moved_to_is_remembered_first(self):
        prefs['recent move destinations'] = ['/one', '/two']
        menu = self._menu()

        menu.remember('/two')

        self.assertEqual(prefs['recent move destinations'], ['/two', '/one'])

    def test_only_so_many_destinations_are_remembered(self):
        menu = self._menu()

        for number in range(move_menu.MoveToMenu.REMEMBERED + 3):
            menu.remember('/d%d' % number)

        self.assertEqual(len(prefs['recent move destinations']),
                         move_menu.MoveToMenu.REMEMBERED)
        self.assertEqual(prefs['recent move destinations'][0], '/d12')

    def test_an_underscore_in_a_directory_name_is_not_eaten(self):
        """A menu model's labels carry mnemonics.

        GTK builds every item of a Gio.Menu with use-underline set, so a
        path shown as it stands would lose an underscore to it and
        underline the letter after.
        """
        self.assertEqual(move_menu.MoveToMenu._label_for('/books/two_words'),
                         '/books/two__words')

    def test_the_home_directory_is_written_as_a_tilde(self):
        self.assertEqual(
            move_menu.MoveToMenu._label_for(
                os.path.join(constants.HOME_DIR, 'comics')),
            os.path.join('~', 'comics'))

    def test_a_path_too_long_to_show_has_its_middle_left_out(self):
        label = move_menu.MoveToMenu._label_for('/%s/end' % ('x' * 200))

        self.assertEqual(len(label), move_menu.MoveToMenu._LABEL_WIDTH)
        self.assertTrue(label.endswith('/end'), label)
        self.assertIn('...', label)

    def test_picking_a_destination_moves_the_file_there(self):
        destination = self._directory('destination')
        prefs['recent move destinations'] = [destination]
        menu = self._menu()

        menu._actions.activate_action(
            'move', GLib.Variant.new_bytestring(os.fsencode(destination)))

        self.assertEqual(self.window.moved_to, [destination])

    def test_the_chooser_reaches_a_folder_that_is_on_no_list(self):
        """The chooser asks for a folder, so what it hands back is one.

        Anywhere else it is asked for files, and a folder among the
        paths chosen is walked for the files it holds - which here would
        have been the books in the destination rather than the
        destination itself.
        """
        destination = self._directory('elsewhere')
        self._file('elsewhere', 'a-book-that-is-there.cbz')
        prefs['path of last browsed in filechooser'] = self.tmp_dir
        menu = self._menu()

        menu._actions.activate_action('other', None)
        pump()
        dialog = self._chooser()
        self.assertIsNotNone(dialog, 'no chooser was opened')
        widgets.set_chooser_folder(dialog.filechooser, destination)
        wait_for(lambda: widgets.chooser_folder(dialog.filechooser)
                 == destination)
        dialog.response(Response.OK)
        pump()

        self.assertEqual(self.window.moved_to, [destination])

    @staticmethod
    def _chooser():
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, file_chooser_simple_dialog
                          .SimpleFileChooserDialog):
                return window
        return None

    def test_there_is_nothing_to_move_with_no_file_open(self):
        menu = self._menu()
        self.window.filehandler.file_loaded = False

        self.window.filehandler.file_closed()

        self.assertFalse(menu._actions.lookup_action('move').get_enabled())
        self.assertFalse(menu._actions.lookup_action('other').get_enabled())

# vim: expandtab:sw=4:ts=4
