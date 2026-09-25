import os
import sys

# Useful to be able to run the current testsuite with another MComix version.
mcomix_path = os.environ.get('MCOMIXPATH', None)
if mcomix_path is not None:
    sys.path.insert(0, mcomix_path)

# Keep the test windows off the user's own desktop.

# GTK connects to Wayland whenever WAYLAND_DISPLAY is set, whatever
# DISPLAY says, so running the suite under xvfb-run isolated nothing:
# every window it opened went to the real compositor, where the user's
# mouse and keyboard reach it - and where the compositor, rather than the
# test, decides whether a window is mapped and how large it comes out.
# Pin the backend to the X server DISPLAY names, which is the one
# xvfb-run started.

if os.environ.get('DISPLAY'):
    os.environ['GDK_BACKEND'] = 'x11'
    os.environ.pop('WAYLAND_DISPLAY', None)

# On Xvfb, which has no DRI3, GTK turns GL down (Mesa has only llvmpipe to
# offer there) and takes its Vulkan renderer, on whatever Vulkan device the
# machine has. Setting one up and tearing it down for every test window
# costs over a quarter of the suite's time, and its unrealize has aborted
# an xdist worker on a GSK assertion. The tests check what MComix draws, not
# how GSK composites it, so the cairo renderer does; a renderer named in the
# environment is kept.
os.environ.setdefault('GSK_RENDERER', 'cairo')

# Make sure the GTK version MComix targets is selected before any module
# pulls in gi.repository; mcomix.run does this for the application itself.

import gi

gi.require_version('PangoCairo', '1.0')
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')

# Pin the temporary directory GLib hands out.

# GLib caches the answer to g_get_tmp_dir() the first time anything asks
# and never looks at the environment again.  GTK4 decodes images through
# glycin, which unpacks into a file there, so whichever directory is
# current when the first image is decoded is the one every later decode
# uses.  MComixTest gives each test a temporary directory of its own and
# removes it afterwards, which left the second test onwards decoding into
# a deleted directory: every gdk-pixbuf load failed and quietly fell back
# to PIL.  Give GLib a directory that outlives any single test, and pin it
# now, before a test can point the environment somewhere shorter-lived.

import atexit
import copy
import gc
import shutil
import tempfile
import traceback

_TMP_ROOT = os.path.join(os.path.dirname(__file__), 'tmp')
os.makedirs(_TMP_ROOT, exist_ok=True)
_SESSION_TMPDIR = tempfile.mkdtemp(dir=_TMP_ROOT, prefix='session.')
os.environ['TMPDIR'] = os.environ['TEMP'] = os.environ['TMP'] = _SESSION_TMPDIR
tempfile.tempdir = _SESSION_TMPDIR
atexit.register(shutil.rmtree, _SESSION_TMPDIR, True)

from gi.repository import GLib, Gtk

assert GLib.get_tmp_dir() == _SESSION_TMPDIR, GLib.get_tmp_dir()

# Pin the recent files store the same way, and for the same reason.

# Gtk.RecentManager's default reads the data directory once, when it is
# first asked for, and writes there for the rest of the process.  Built
# inside the temporary home of whichever test opened a window first, it
# went on writing into a directory later tests had already removed:
# every change raised "Attempting to store changes into
# .../recently-used.xbel, but failed" (29 and 17 of them in two runs at
# 2e91651f), and a write that landed between the listing and the rmdir
# of that removal left the whole test directory behind with "Directory
# not empty".  This store is in the session's own directory, which lasts
# as long as the process, and every test is handed it in place of the
# default.
_RECENT_STORE = Gtk.RecentManager(
    filename=os.path.join(_SESSION_TMPDIR, 'recent.xbel'))
Gtk.RecentManager.get_default = staticmethod(lambda: _RECENT_STORE)

# Pin multiprocessing's temporary directory the same way.  It is worked
# out once per process, the first time a manager or a forkserver needs a
# socket, and it would otherwise land in the directory MComixTest gives
# the first such test: named after the test, that made the socket's path
# too long for AF_UNIX on Python 3.12 and 3.13, where the socket is a
# file, and it is removed when that test ends.

import multiprocessing.util

multiprocessing.util.get_temp_dir()

# Configure locale.

import locale

locale.setlocale(locale.LC_ALL, '')

# Since some of MComix' modules depend on gettext being installed for _(),
# add such a function here that simply returns the string passed into it.

import builtins

if '_' not in builtins.__dict__:
    builtins.__dict__['_'] = str

# Enable debug logging to make post-mortem analysis easier.

from mcomix import log

log.setLevel('DEBUG')


# The cyclic garbage collector is run by whichever thread happens to set
# it off, and a GTK object it frees is finalised on that thread.  Under
# PyGObject 3.46 and GTK 4.14 - the floors job on GitHub - a thumbnail
# worker that set it off took its xdist worker down, with "Fatal Python
# error: Aborted" and the worker's stack "Garbage-collecting".  So the
# suite runs the collector itself, on the main thread, between tests,
# and never lets a worker thread start it.  Every test would triple the
# time the suite takes; every so many costs next to nothing.
gc.disable()
_COLLECT_EVERY = 25
_tests_since_collecting = 0


def _collect_garbage_now_and_then():
    """Run the collector on the main thread every _COLLECT_EVERY tests."""
    global _tests_since_collecting
    _tests_since_collecting += 1
    if _tests_since_collecting >= _COLLECT_EVERY:
        _tests_since_collecting = 0
        gc.collect()


def pump(rounds=4000):
    """Let the main loop run through whatever is pending.

    GTK4 has no Gtk.events_pending()/Gtk.main_iteration_do(); the main
    context they stood for is still there.
    """
    from gi.repository import GLib
    context = GLib.MainContext.default()
    turns = 0
    while context.pending() and turns < rounds:
        context.iteration(False)
        turns += 1


def hold_open(popover):
    """Keep <popover> open whatever the other xdist workers do.

    Every worker draws on the one X server xvfb-run started, and an
    autohide popover closes when its window loses the focus, which
    another worker's window takes whenever it is presented: a test that
    opened a menu and looked a main loop turn later found it closed in
    about one run in two when 24 copies ran under coverage.  What the
    tests ask is whether MComix opened the menu, which does not depend
    on it hiding itself.
    """
    popover.set_autohide(False)


def wait_for(predicate, seconds=5):
    """Run the main loop until <predicate> holds, or time runs out.

    Draining what is pending is not enough to see a GTK4 widget laid
    out or drawn: both happen when the frame clock next ticks, which
    takes time rather than turns of the loop.
    """
    import time
    from gi.repository import GLib
    context = GLib.MainContext.default()
    # So that iteration() always has something to come back from.
    heartbeat = GLib.timeout_add(10, lambda: GLib.SOURCE_CONTINUE)
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            context.iteration(True)
        return predicate()
    finally:
        GLib.source_remove(heartbeat)


# Use a custom testcase class:
# - isolate tests: do not use or modify the user current
#   configuration for MComix (preferences, library, ...)
# - make sure MComix state is reset before each test

import unittest

from mcomix import constants
from mcomix import preferences
from mcomix.preferences import prefs

# Start the way run.py starts.

# GLib.set_prgname() is what names the program to GLib: the window class
# is taken from it, and so is the application name a recent files entry
# is registered under.  run.py sets it before it builds a window; the
# suite builds windows without run.py, so nothing set it, and every
# recorded book raised "Attempting to add ... to the list of recently
# used resources, but no name of the application that is registering it
# was defined" - 337 of them in one run at 1dbe0a91.

GLib.set_prgname(constants.APPNAME)

#: The preferences as MComix defines them, kept aside so that every test
#: can start from them.  Deep, because several of them hold a container -
#: and one of those containers is a constant of MComix' own.
default_prefs = copy.deepcopy(dict(prefs))


class MComixTest(unittest.TestCase):

    #: Global state setUp() overwrites and tearDown() has to put back.
    OVERRIDDEN_ENVIRONMENT = ('HOME', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME',
                              'TMPDIR', 'TEMP', 'TMP')

    #: constants resolves these once, at import time, so setting the
    #: environment above is not enough to keep tests off the real
    #: configuration - they have to be repointed as well.
    REDIRECTED_PATHS = ('HOME_DIR', 'CONFIG_DIR', 'DATA_DIR', 'THUMBNAIL_PATH',
                        'LIBRARY_DATABASE_PATH', 'LASTPAGE_DATABASE_PATH',
                        'LIBRARY_COVERS_PATH', 'PREFERENCE_PATH',
                        'KEYBINDINGS_CONF_PATH', 'BOOKMARK_PICKLE_PATH',
                        'FILEINFO_PICKLE_PATH', 'PREFERENCE_PICKLE_PATH')

    def setUp(self):
        name = '.'.join((
            self.__module__.split('.')[-1],
            self.__class__.__name__,
            self._testMethodName))
        self.tmp_dir = tempfile.mkdtemp(dir=_TMP_ROOT, prefix='%s.' % name)
        self._saved_environ = {var: os.environ.get(var)
                               for var in self.OVERRIDDEN_ENVIRONMENT}
        self._saved_tempdir = tempfile.tempdir
        self._saved_paths = {name: getattr(constants, name)
                             for name in self.REDIRECTED_PATHS}
        # Put all of that back from a cleanup rather than from
        # tearDown(), because cleanups run in the reverse of the order
        # they were registered in: whatever the test itself registers -
        # closing a window it opened, and with it the writes
        # terminate_program() makes - then runs while the paths below
        # still point into the temporary home.  Undoing the redirection
        # in tearDown() put the real paths back first, and a window
        # closed from addCleanup wrote the reader's own bookmarks and
        # file information into their data directory.
        self.addCleanup(self._restore)
        # PyGObject prints an exception raised in a signal handler or a
        # main loop callback and carries on, so the test whose code
        # raised it passed.  Collect them instead, and check once the
        # cleanups below have pumped the main loop for the last time.
        self._callback_errors = []
        self.addCleanup(setattr, sys, 'excepthook', sys.excepthook)
        sys.excepthook = self._callback_raised
        self.addCleanup(self._nothing_raised_in_a_callback)
        # Registered after _restore so that it runs before it, once the
        # test's own tearDown and cleanups have closed what they opened.
        self.addCleanup(self._no_window_left_on_screen)
        self.addCleanup(self._no_library_left_open)
        # The recent files store is one for the process, so what a test
        # puts in it would otherwise be there for the next one.
        try:
            _RECENT_STORE.purge_items()
        except GLib.Error:
            # Nothing to purge, which GTK reports as an error.
            pass
        # So is the file the last file chooser was answered with, which
        # the next chooser opens on and starts to preview: a test that
        # chose the test archive left every later chooser on the worker
        # selecting it, and whatever the preview found out about it
        # arriving in the middle of the next test.
        chooser = sys.modules.get('mcomix.file_chooser_base_dialog')
        if chooser is not None:
            chooser._BaseFileChooserDialog._last_activated_file = None
        # Change storage directories.
        home_dir = os.path.join(self.tmp_dir, 'home')
        os.mkdir(home_dir)
        os.environ['HOME'] = home_dir
        os.environ['XDG_DATA_HOME'] = os.path.join(home_dir, 'data')
        os.environ['XDG_CONFIG_HOME'] = os.path.join(home_dir, 'config')
        # Create and setup temporary directory.
        temp_dir = os.path.join(self.tmp_dir, 'tmp')
        os.mkdir(temp_dir)
        os.environ['TMPDIR'] = os.environ['TEMP'] = os.environ['TMP'] = temp_dir
        # Make sure tempfile module uses the correct directory.
        tempfile.tempdir = temp_dir
        # Point the paths constants resolved at import time into the
        # temporary home as well.
        constants.HOME_DIR = home_dir
        constants.CONFIG_DIR = os.path.join(home_dir, 'config', 'mcomix')
        constants.DATA_DIR = os.path.join(home_dir, 'data', 'mcomix')
        constants.THUMBNAIL_PATH = os.path.join(home_dir, 'cache', 'thumbnails', 'normal')
        constants.LIBRARY_DATABASE_PATH = os.path.join(constants.DATA_DIR, 'library.db')
        constants.LASTPAGE_DATABASE_PATH = os.path.join(constants.DATA_DIR, 'lastreadpage.db')
        constants.LIBRARY_COVERS_PATH = os.path.join(constants.DATA_DIR, 'library_covers')
        constants.PREFERENCE_PATH = os.path.join(constants.CONFIG_DIR, 'preferences.conf')
        constants.KEYBINDINGS_CONF_PATH = os.path.join(constants.CONFIG_DIR, 'keybindings.conf')
        constants.BOOKMARK_PICKLE_PATH = os.path.join(constants.DATA_DIR, 'bookmarks.pickle')
        constants.FILEINFO_PICKLE_PATH = os.path.join(constants.DATA_DIR, 'file.pickle')
        constants.PREFERENCE_PICKLE_PATH = os.path.join(constants.CONFIG_DIR, 'preferences.pickle')
        # Reset preferences to default, and with them the baseline a
        # write is measured against: a test starts as an instance that
        # has just read a file holding exactly the defaults.
        prefs.clear()
        # A copy, so that a test reaching inside a preference that holds
        # a container changes its own copy rather than what every later
        # test starts from.
        prefs.update(copy.deepcopy(default_prefs))
        preferences._as_read = copy.deepcopy(default_prefs)
        # The folders a file chooser starts in default to the home
        # directory, which preferences read from constants at import
        # time as well: a chooser with nothing open to start from would
        # otherwise list the reader's own home.
        for key, value in default_prefs.items():
            if value == self._saved_paths['HOME_DIR']:
                prefs[key] = preferences._as_read[key] = home_dir
        # Resetting them is not changing them, and a write left over
        # from an earlier test is not this one's to make.
        preferences.cancel_scheduled_write()

    def _no_window_left_on_screen(self):
        """Fail the test that leaves a window up, rather than a later one.

        A dialog left on screen is found by the next test on the same
        worker that goes looking for a dialog, which then counts it or
        answers it, and fails over a window it never opened.  Which
        test that is depends on how xdist shared the suite out.
        """
        if 'gi.repository.Gtk' not in sys.modules:
            return
        from gi.repository import Gtk
        pump()
        left = [window for window in Gtk.Window.list_toplevels()
                if window.get_visible()]
        for window in left:
            window.destroy()
        pump()
        _collect_garbage_now_and_then()
        if left:
            self.fail('left on screen: %s'
                      % ', '.join(type(window).__name__ for window in left))

    def _callback_raised(self, kind, value, trace):
        """Keep what PyGObject would have printed and gone on from."""
        self._callback_errors.append((kind, value, trace))

    def _nothing_raised_in_a_callback(self):
        """Fail the test during which a callback raised an exception."""
        if self._callback_errors:
            self.fail('raised in a callback:\n' + ''.join(
                ''.join(traceback.format_exception(kind, value, trace))
                for kind, value, trace in self._callback_errors))

    def _no_library_left_open(self):
        """Fail the test that leaves the library database open.

        LibraryBackend() hands out one backend per process, opened on
        the database under the temporary home of whichever test asked
        first; a MainWindow asks as it is built, and only
        terminate_program() closes it.  Left open, it went to the next
        test on the same worker that asked for the library, pointing at
        a database whose directory had been removed, and every write
        there failed with "attempt to write a readonly database".
        """
        backend = sys.modules.get('mcomix.library.backend')
        if backend is None or backend._backend is None:
            return
        backend._backend.close()
        self.fail('left the library database open')

    def _restore(self):
        # Nothing this test changed is worth writing after it, and the
        # directory it would be written into is about to be gone.
        preferences.cancel_scheduled_write()
        # Restore the global state setUp() changed. Leaving tempfile.tempdir
        # pointing into the temporary directory removed below would break
        # every later test that creates a temporary file of its own.
        for var, value in self._saved_environ.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
        tempfile.tempdir = self._saved_tempdir
        for name, value in self._saved_paths.items():
            setattr(constants, name, value)
        # Leave the temporary directory behind for post-mortem analysis
        # when the test did not pass.
        if not self._test_failed():
            shutil.rmtree(self.tmp_dir)

    def _test_failed(self):
        """Return True if the running test has already failed.

        There is no public API for this. Python 3.11 dropped the
        _resultForDoCleanups attribute this used to be read from, so go
        through the (private) outcome object instead where available.
        """
        result = getattr(getattr(self, '_outcome', None), 'result', None)
        if result is None:
            result = getattr(self, '_resultForDoCleanups', None)

        if hasattr(result, '_excinfo'):
            # When running under pytest.
            return any(exc.typename != 'XFailed'
                       for exc in result._excinfo or ())

        # When running under plain unittest.
        problems = list(getattr(result, 'failures', ())) + \
            list(getattr(result, 'errors', ()))
        return any(test.id() == self.id() for test, _traceback in problems)


def session_tmp_dir():
    """A temporary directory that lasts as long as the test run.

    For what a test cannot take with it: a GObject that keeps writing to
    a file after the test that made it has passed, and whose own
    directory is removed the moment it does.
    """
    return _SESSION_TMPDIR


# Helper to get path to testsuite sample files.

def get_testfile_path(*components):
    return str(os.path.join(os.path.dirname(__file__), 'files', *components))
