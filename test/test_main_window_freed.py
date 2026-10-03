"""A closed main window is freed.

MComix builds one main window per process, so a window that outlived
being closed cost a reader nothing; the test suite builds one per test,
and every one of them stayed alive with everything it showed, which made
each test in a process slower than the one before.  GTK 4 does not
dispose a destroyed window's widgets, and the handlers Python connected
to them, held in C, keep the window from Python's collector.
"""

import gc
import os
import weakref
from unittest import mock

from gi.repository import Gtk

from . import MComixTest, get_testfile_path, pump, wait_for
from .test_dialog_freed import _holders

from mcomix import constants
from mcomix import icons
from mcomix import keybindings
from mcomix import main


class MainWindowFreedTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        keybindings._manager = None

    def assertFreedOnClose(self, open_path=None):
        """Build a main window on <open_path>, close it as the tests and
        a quit do, and check that nothing holds it afterwards.

        The window is only ever held here, so that the test itself is
        not what keeps it alive.
        """
        window = main.MainWindow(open_path=open_path)
        main.set_main_window(window)
        if open_path is not None:
            pages = window.imagehandler
            self.assertTrue(wait_for(
                lambda: pages.get_number_of_pages() > 0, seconds=20))
            del pages
        pump()
        ref = weakref.ref(window)
        window.terminate_program()
        window.destroy()
        main.set_main_window(None)
        del window
        pump()
        gc.collect()
        pump()
        gc.collect()
        if ref() is not None:
            self.fail('the closed main window is still alive, held by %s'
                      % sorted(set(_holders(ref()))))

    def test_an_empty_window(self):
        self.assertFreedOnClose()

    def test_a_window_with_a_book(self):
        self.assertFreedOnClose(
            get_testfile_path('archives', '01-ZIP-Normal.zip'))

    def test_the_title_bar_is_left_to_the_window(self):
        # On Windows GTK draws the title bar itself, in a header bar it
        # makes a child of the window and takes off again only when it
        # disposes of the window.  Taken off and freed before that, it
        # was unparented a second time, freed, and the test workers on
        # Windows died of access violations in the collector.  A title
        # bar set from here stands in for it: GTK keeps it the same way.
        # Set before the window is shown, as GTK sets its own.
        finalized = []
        shown = main.MainWindow.present

        def present(window):
            bar = Gtk.HeaderBar()
            bar.weak_ref(finalized.append, 'title bar')
            window.set_titlebar(bar)
            shown(window)

        with mock.patch.object(main.MainWindow, 'present', present):
            window = main.MainWindow()
        main.set_main_window(window)
        pump()
        window.terminate_program()
        window.destroy()
        main.set_main_window(None)
        pump()
        self.assertEqual(finalized, [], 'the title bar went before its window')
        del window
        gc.collect()
        pump()
        self.assertEqual(finalized, ['title bar'])
