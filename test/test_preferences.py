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


class MigratePreferencesTest(MComixTest):

    """A file written by an older MComix is brought forward on the next
    start, and kept as it was before anything rewrites it."""

    #: The near-black grey MComix has always defaulted to, in the 16-bit
    #: components colours were stored as before format version 1.
    OLD_DEFAULT = [5000, 5000, 5000]

    def setUp(self) -> None:
        super().setUp()
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)
        self.path = constants.PREFERENCE_PATH
        self.backup = '%s.v0' % self.path

    def _write(self, stored) -> None:
        with open(self.path, 'w') as config_file:
            json.dump(stored, config_file)

    def test_colours_become_rgba_components(self) -> None:
        self._write({'bg colour': self.OLD_DEFAULT,
                     'thumb bg colour': [65535, 0, 32768]})
        preferences.read_preferences_file()
        for component in prefs['bg colour']:
            self.assertLessEqual(component, 1.0)
        self.assertAlmostEqual(prefs['bg colour'][0], 5000 / 65535)
        self.assertEqual(len(prefs['bg colour']), 4)
        self.assertAlmostEqual(prefs['thumb bg colour'][0], 1.0)
        self.assertAlmostEqual(prefs['thumb bg colour'][1], 0.0)
        self.assertAlmostEqual(prefs['thumb bg colour'][3], 1.0)

    def test_the_old_file_is_kept(self) -> None:
        self._write({'bg colour': self.OLD_DEFAULT, 'lens size': 222})
        preferences.read_preferences_file()
        self.assertTrue(os.path.isfile(self.backup))
        with open(self.backup) as backup:
            self.assertEqual(json.load(backup)['bg colour'], self.OLD_DEFAULT)

    def test_an_existing_backup_is_not_overwritten(self) -> None:
        self._write({'bg colour': self.OLD_DEFAULT})
        with open(self.backup, 'w') as backup:
            backup.write('the original, from an earlier upgrade')
        preferences.read_preferences_file()
        with open(self.backup) as backup:
            self.assertEqual(backup.read(), 'the original, from an earlier upgrade')

    def test_a_current_file_is_left_alone(self) -> None:
        current = {preferences._FORMAT_VERSION_KEY: preferences.CONFIG_FORMAT_VERSION,
                   'bg colour': [0.5, 0.25, 0.125, 1.0]}
        self._write(current)
        preferences.read_preferences_file()
        self.assertEqual(prefs['bg colour'], [0.5, 0.25, 0.125, 1.0])
        self.assertFalse(os.path.exists(self.backup),
                         'nothing was migrated, so nothing should be backed up')

    def test_the_version_is_stored_so_it_only_migrates_once(self) -> None:
        self._write({'bg colour': self.OLD_DEFAULT})
        preferences.read_preferences_file()
        self.assertEqual(prefs[preferences._FORMAT_VERSION_KEY],
                         preferences.CONFIG_FORMAT_VERSION)
        preferences.write_preferences_file()
        migrated = list(prefs['bg colour'])
        preferences.read_preferences_file()
        self.assertEqual(prefs['bg colour'], migrated,
                         'a second read must not divide the colour again')

    def test_a_colour_that_is_not_one_falls_back_to_the_default(self) -> None:
        self._write({'bg colour': 'not a colour'})
        preferences.read_preferences_file()
        self.assertEqual(prefs['bg colour'], preferences.DEFAULT_BG_COLOUR)


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
