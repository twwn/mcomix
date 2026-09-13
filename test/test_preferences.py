import json
import os
import pickle
import stat

from . import MComixTest

from mcomix import constants
from mcomix import preferences
from mcomix.preferences import prefs


class ReadPreferencesFileTest(MComixTest):

    def setUp(self) -> None:
        super().setUp()
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)
        self.path = constants.PREFERENCE_PATH
        self.broken = '%s.broken' % self.path

    def _write(self, text) -> None:
        with open(self.path, 'w') as config_file:
            config_file.write(text)

    def test_reads_stored_values(self) -> None:
        self._write(json.dumps({'lens size': 123}))
        preferences.read_preferences_file()
        self.assertEqual(prefs['lens size'], 123)

    def test_ignores_keys_it_does_not_know(self) -> None:
        self._write(json.dumps({'lens size': 123, 'no such preference': 1}))
        preferences.read_preferences_file()
        self.assertNotIn('no such preference', prefs)

    def test_moves_an_unparsable_file_aside(self) -> None:
        self._write('this is not json')
        preferences.read_preferences_file()
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.isfile(self.broken))

    def test_replaces_an_older_broken_file(self) -> None:
        with open(self.broken, 'w') as old:
            old.write('older breakage')
        self._write('this is not json either')
        preferences.read_preferences_file()
        with open(self.broken) as broken:
            self.assertEqual(broken.read(), 'this is not json either')

    def test_keeps_a_file_it_only_failed_to_open(self) -> None:
        # A file that cannot be read right now is not a corrupt file.
        self._write(json.dumps({'lens size': 123}))
        os.chmod(self.path, 0)
        try:
            if os.access(self.path, os.R_OK):
                self.skipTest('cannot make the file unreadable (running as root?)')
            preferences.read_preferences_file()
        finally:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        self.assertTrue(os.path.isfile(self.path))
        self.assertFalse(os.path.exists(self.broken))

    def test_reads_and_removes_the_legacy_pickle(self) -> None:
        with open(constants.PREFERENCE_PICKLE_PATH, 'wb') as legacy:
            pickle.dump(constants.VERSION, legacy, pickle.HIGHEST_PROTOCOL)
            pickle.dump({'lens size': 321}, legacy, pickle.HIGHEST_PROTOCOL)
        preferences.read_preferences_file()
        self.assertEqual(prefs['lens size'], 321)
        self.assertFalse(os.path.exists(constants.PREFERENCE_PICKLE_PATH))


class WritePreferencesFileTest(MComixTest):

    def test_round_trips_through_the_file(self) -> None:
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)
        prefs['lens size'] = 222
        preferences.write_preferences_file()
        prefs['lens size'] = 1
        preferences.read_preferences_file()
        self.assertEqual(prefs['lens size'], 222)


class IsolationTest(MComixTest):

    def test_configuration_paths_point_into_the_test_directory(self) -> None:
        # A test writing to the developer's own configuration would be a
        # good deal worse than a failing test.
        for name in self.REDIRECTED_PATHS:
            path = getattr(constants, name)
            self.assertTrue(path.startswith(self.tmp_dir),
                            '%s points outside the test directory: %s'
                            % (name, path))

# vim: expandtab:sw=4:ts=4
