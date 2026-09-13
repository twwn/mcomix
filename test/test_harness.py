"""The harness every other test is built on.

MComixTest points a dozen paths MComix resolved at import time into a
temporary home, and nothing else keeps the suite off the reader's own
configuration.  Where that redirection is undone therefore matters as
much as that it happens: a test that closes its window from a cleanup -
which is where a window opened mid-test belongs, since a failing
assertion skips the rest of the body - had that cleanup run after the
real paths were back, and MComix wrote its bookmarks and its file
information into the reader's data directory.
"""

import os
import tempfile

from . import MComixTest

from mcomix import constants
from mcomix import preferences
from mcomix.preferences import prefs


class RedirectionTest(MComixTest):

    """Where MComix writes while a test, and its cleanups, are running."""

    def test_the_paths_point_into_the_temporary_home(self):
        for name in self.REDIRECTED_PATHS:
            path = getattr(constants, name)
            self.assertTrue(path.startswith(self.tmp_dir),
                            '%s is %s, outside the temporary home'
                            % (name, path))

    def test_a_file_chooser_starts_out_in_the_temporary_home(self):
        """The folders a chooser starts in default to the home
        directory, which preferences took from constants at import time
        just as the paths above were, so a chooser with no book open to
        start from listed the reader's own home."""
        for key in ('path of last browsed in filechooser',
                    'path of last saved in filechooser'):
            self.assertTrue(prefs[key].startswith(self.tmp_dir),
                            '%s is %s, outside the temporary home'
                            % (key, prefs[key]))
            self.assertEqual(preferences._as_read[key], prefs[key],
                             'resetting %s would be written as a change'
                             % key)

    def test_a_cleanup_still_writes_into_the_temporary_home(self):
        """Cleanups run in the reverse of the order they were added in,
        so one a test registers must run before the harness undoes the
        redirection it registered first."""
        self.addCleanup(self._paths_are_still_redirected,
                        {name: getattr(constants, name)
                         for name in self.REDIRECTED_PATHS})

    def _paths_are_still_redirected(self, during_the_test):
        for name, path in during_the_test.items():
            self.assertEqual(getattr(constants, name), path,
                             '%s was put back before the cleanups ran' % name)

    def test_a_cleanup_still_has_the_temporary_directory(self):
        """It is removed once the cleanups are done, so that a cleanup
        writing a file has somewhere to write it."""
        self.addCleanup(self._temporary_directory_is_still_there)

    def _temporary_directory_is_still_there(self):
        self.assertTrue(os.path.isdir(self.tmp_dir),
                        '%s was removed before the cleanups ran'
                        % self.tmp_dir)

    def test_the_temporary_directory_is_where_tempfile_puts_things(self):
        self.assertTrue(
            tempfile.gettempdir().startswith(self.tmp_dir),
            'tempfile hands out %s' % tempfile.gettempdir())

# vim: expandtab:sw=4:ts=4
