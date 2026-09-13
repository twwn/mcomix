# -*- coding: utf-8 -*-

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

# Make sure the GTK version MComix targets is selected before any module
# pulls in gi.repository; mcomix.run does this for the application itself.

import gi

gi.require_version('PangoCairo', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')

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

# Use a custom testcase class:
# - isolate tests: do not use or modify the user current
#   configuration for MComix (preferences, library, ...)
# - make sure MComix state is reset before each test

import shutil
import tempfile
import unittest

from mcomix import constants
from mcomix.preferences import prefs

default_prefs = {}
default_prefs.update(prefs)

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
        base_tmpdir = os.path.join(os.path.dirname(__file__), 'tmp')
        os.makedirs(base_tmpdir, exist_ok=True)
        name = '.'.join((
            self.__module__.split('.')[-1],
            self.__class__.__name__,
            self._testMethodName))
        self.tmp_dir = tempfile.mkdtemp(dir=base_tmpdir, prefix='%s.' % name)
        self._saved_environ = {var: os.environ.get(var)
                               for var in self.OVERRIDDEN_ENVIRONMENT}
        self._saved_tempdir = tempfile.tempdir
        self._saved_paths = {name: getattr(constants, name)
                             for name in self.REDIRECTED_PATHS}
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
        # Reset preferences to default.
        prefs.clear()
        prefs.update(default_prefs)

    def tearDown(self):
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

# Helper to get path to testsuite sample files.

def get_testfile_path(*components):
    return str(os.path.join(os.path.dirname(__file__), 'files', *components))

