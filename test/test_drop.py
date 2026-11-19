"""Files dropped on the main window's page area."""

import unittest.mock

from gi.repository import Gdk, Gio

from . import MainWindowOpenTest, NORMAL_ZIP, get_testfile_path


class DropTest(MainWindowOpenTest):

    def setUp(self):
        super().setUp()
        patcher = unittest.mock.patch.object(self.window.filehandler,
                                             'open_file')
        self.opened = patcher.start()
        self.addCleanup(patcher.stop)

    def _drop(self, files, from_inside=False):
        """Drop <files> (Gio.File) as a drag from outside MComix would,
        or as one from inside it."""
        target = unittest.mock.Mock()
        drop = target.get_current_drop.return_value
        drop.get_drag.return_value = object() if from_inside else None
        return self.window.event_handler.drag_n_drop_event(
            target, Gdk.FileList.new_from_array(files), 0, 0)

    def _file(self, name):
        return Gio.File.new_for_path(get_testfile_path('archives', name))

    def test_a_book_dropped_is_opened(self):
        self.assertTrue(self._drop([self._file('01-ZIP-Normal.zip')]))
        self.opened.assert_called_once_with(NORMAL_ZIP)

    def test_several_books_dropped_are_opened_together(self):
        names = ('01-ZIP-Normal.zip', '02-TAR-Normal.tar')
        self.assertTrue(self._drop([self._file(name) for name in names]))
        self.opened.assert_called_once_with(
            [get_testfile_path('archives', name) for name in names])

    def test_a_drag_from_inside_mcomix_is_left_alone(self):
        self.assertFalse(self._drop([self._file('01-ZIP-Normal.zip')],
                                    from_inside=True))
        self.opened.assert_not_called()

    def test_files_with_no_path_here_open_nothing(self):
        remote = Gio.File.new_for_uri('https://example.com/book.cbz')
        self.assertIsNone(remote.get_path())
        self.assertFalse(self._drop([remote]))
        self.opened.assert_not_called()
