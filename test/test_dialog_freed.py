"""Every dialog is freed once it is closed.

GTK 4 does not dispose a destroyed window's widgets: gtk_window_destroy()
hides the window and drops GTK's own reference, and its children stay
where they are.  A child whose wrapper holds a closure over the dialog
then keeps the dialog alive for the rest of the session, and with it
whatever the dialog shows.  Each test opens a dialog, closes it the way
the user would, and checks that nothing is left holding it.
"""

import gc
import os
import threading
import types
import unittest.mock
import weakref

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import dialog
from mcomix import file_chooser_library_dialog
from mcomix import icons
from mcomix import main
from mcomix import message_dialog
from mcomix.library import add_progress_dialog
from mcomix.library import main_dialog
from mcomix.library import relocate_dialog
from mcomix.library import watchlist


def _holders(obj):
    """What refers to <obj>, named so that the code holding it can be
    found: bound methods and closures by their function, instance
    dictionaries by the class of their instance."""
    names = []
    for referrer in gc.get_referrers(obj):
        if isinstance(referrer, types.MethodType):
            names.append('bound %s' % referrer.__func__.__qualname__)
        elif isinstance(referrer, types.CellType):
            owners = [function.__qualname__
                      for cells in gc.get_referrers(referrer)
                      if isinstance(cells, tuple)
                      for function in gc.get_referrers(cells)
                      if isinstance(function, types.FunctionType)]
            names.append('closure %s' % ', '.join(owners))
        elif isinstance(referrer, dict):
            owners = [type(owner).__name__
                      for owner in gc.get_referrers(referrer)
                      if getattr(owner, '__dict__', None) is referrer]
            names.append('attribute of %s' % ', '.join(owners))
        elif not isinstance(referrer, types.FrameType):
            names.append(type(referrer).__name__)
    return names


class DialogFreedTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.parent = Gtk.Window()

    def tearDown(self):
        self.parent.destroy()
        pump()
        super().tearDown()

    def assertFreed(self, build, close=None):
        """Build a dialog with <build>, show it, close it with <close>
        (by default as the window manager would) and check it is gone.

        The dialog is only ever held here, so that the test itself is
        not what keeps it alive.
        """
        built = build()
        built.present()
        pump()
        if close is None:
            built.close()
        else:
            close(built)
        pump()
        ref = weakref.ref(built)
        del built
        gc.collect()
        pump()
        gc.collect()
        if ref() is not None:
            self.fail('a closed dialog is still alive, held by %s'
                      % _holders(ref()))

    def test_a_bare_dialog(self):
        def build():
            built = dialog.Dialog(transient_for=self.parent)
            built.add_button('_OK', dialog.Response.OK)
            return built
        self.assertFreed(build)

    def test_a_message_dialog(self):
        def build():
            built = message_dialog.MessageDialog(self.parent)
            built.connect('response', lambda d, r: d.destroy())
            return built
        self.assertFreed(build, lambda d: d.response(dialog.Response.OK))


class MainWindowDialogsFreedTest(MComixTest):

    """The dialogs the main window opens, each opened and closed."""

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0,
            seconds=20))
        pump()

    def tearDown(self):
        for window in Gtk.Window.list_toplevels():
            if window is not self.window and window.get_visible():
                window.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _opened_by(self, activate):
        """The window <activate> puts on screen."""
        before = set(Gtk.Window.list_toplevels())
        activate()
        pump()
        opened = [window for window in Gtk.Window.list_toplevels()
                  if window not in before and window.get_visible()]
        self.assertEqual(len(opened), 1, opened)
        return opened[0]

    def assertFreedOnClose(self, activate):
        """Open a dialog with <activate>, close it as the window manager
        would, and check that nothing holds it afterwards."""
        opened = self._opened_by(activate)
        name = type(opened).__name__
        ref = weakref.ref(opened)
        opened.close()
        del opened
        pump()
        gc.collect()
        pump()
        gc.collect()
        if ref() is not None:
            self.fail('the closed %s is still alive, held by %s'
                      % (name, _holders(ref())))

    def _ui_action(self, name):
        return self.window.actiongroup.get_action(name).activate

    def test_about(self):
        self.assertFreedOnClose(self._ui_action('about'))

    def test_comments(self):
        self.assertFreedOnClose(self._ui_action('comments'))

    def test_properties(self):
        self.assertFreedOnClose(self._ui_action('properties'))

    def test_preferences(self):
        self.assertFreedOnClose(self._ui_action('preferences'))

    def test_edit_archive(self):
        self.assertFreedOnClose(self._ui_action('edit_archive'))

    def test_open(self):
        self.assertFreedOnClose(self._ui_action('open'))

    def test_enhance_image(self):
        self.assertFreedOnClose(self._ui_action('enhance_image'))

    def test_library(self):
        self.assertFreedOnClose(self._ui_action('library'))

    def test_page_select(self):
        self.assertFreedOnClose(self.window.page_select)

    def test_bookmarks(self):
        self.assertFreedOnClose(
            lambda: self.window.activate_action('bookmarks.edit', None))

    def test_open_with_editor(self):
        self.assertFreedOnClose(
            lambda: self.window.activate_action('openwith.edit', None))

    def _freed_while_previewing(self, previewed, owner, slow):
        """The file chooser, closed while a preview of <previewed> waits
        on <owner>.<slow>, which the preview's thread is stuck in."""
        from mcomix import file_chooser_base_dialog as base
        release = threading.Event()
        real = getattr(owner, slow)

        def stuck(*args):
            release.wait(10)
            return real(*args)

        def preview_first(dialog):
            dialog._previewed = previewed
            dialog._update_preview()

        self.addCleanup(release.set)
        with unittest.mock.patch.object(owner, slow, stuck):
            def activate():
                self._ui_action('open')()
                pump()
                for window in Gtk.Window.list_toplevels():
                    if isinstance(window, base._BaseFileChooserDialog):
                        preview_first(window)
            self.assertFreedOnClose(activate)

    def test_a_file_chooser_closed_while_a_file_is_looked_into(self):
        """A file slow to look into, as one on a network share is, kept
        the closed chooser alive until the thread finding its details
        was done: the floors job on CI caught it once."""
        from mcomix import file_chooser_base_dialog
        self._freed_while_previewing(
            get_testfile_path('images', 'red.png'),
            file_chooser_base_dialog, 'file_details')

    def test_a_file_chooser_closed_while_a_folder_is_looked_into(self):
        from mcomix import file_provider
        self._freed_while_previewing(
            get_testfile_path('images'),
            file_provider.OrderedFileProvider, 'list_files')

    def _open_library(self):
        return self._opened_by(self._ui_action('library'))

    def test_the_librarys_file_chooser(self):
        library = self._open_library()
        try:
            self.assertFreedOnClose(
                lambda: file_chooser_library_dialog
                .open_library_filechooser_dialog(library))
        finally:
            library.close()

    def test_the_watch_list(self):
        library = self._open_library()
        try:
            self.assertFreedOnClose(lambda: watchlist.WatchListDialog(library))
        finally:
            library.close()

    def test_the_question_of_where_a_folder_of_books_went(self):
        library = self._open_library()
        try:
            self.assertFreedOnClose(
                lambda: relocate_dialog.RelocateDialog(library))
        finally:
            library.close()

    def test_the_progress_of_adding_books(self):
        """It closes itself once the books are in, so there is nothing
        to close; only to find it gone afterwards."""
        library = self._open_library()
        try:
            library.add_books(
                [get_testfile_path('archives', '01-ZIP-Normal.zip')])
            pump()
            gc.collect()
            left = [dialog for dialog in gc.get_objects()
                    if isinstance(dialog,
                                  add_progress_dialog._AddLibraryProgressDialog)]
            self.assertFalse(left, 'the progress dialog is still alive, '
                             'held by %s' % (left and _holders(left[0])))
        finally:
            library.close()

    def test_the_library_with_a_book_in_it(self):
        def activate():
            self._ui_action('library')()
            pump()
            main_dialog._dialog.add_books(
                [get_testfile_path('archives', '01-ZIP-Normal.zip')])
            main_dialog._dialog.book_area.display_covers(
                constants.COLLECTION_ALL)
            covers = main_dialog._dialog.book_area._covers
            self.assertTrue(wait_for(lambda: any(covers.each_item())),
                            'the book never showed')
        self.assertFreedOnClose(activate)
