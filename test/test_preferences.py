import json
import os
import pickle
import stat

from . import MComixTest, default_prefs, wait_for

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

    def setUp(self) -> None:
        super().setUp()
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)

    def test_round_trips_through_the_file(self) -> None:
        prefs['lens size'] = 222
        preferences.write_preferences_file()
        prefs['lens size'] = 1
        preferences.read_preferences_file()
        self.assertEqual(prefs['lens size'], 222)

    def test_what_another_instance_changed_meanwhile_is_kept(self) -> None:
        """Every MComix window is a process of its own, each holding all
        of the preferences as they stood when it started.  One that wrote
        all of them back would undo everything another window changed
        while it was running, which reads as settings that do not stick.
        """
        prefs['lens size'] = 111
        prefs['thumbnail size'] = 80
        preferences.write_preferences_file()
        preferences.read_preferences_file()

        # This instance changes one preference; another changes a
        # different one and quits first.
        prefs['lens size'] = 222
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            elsewhere = json.load(config_file)
        elsewhere['thumbnail size'] = 250
        with open(constants.PREFERENCE_PATH, 'w') as config_file:
            json.dump(elsewhere, config_file)

        preferences.write_preferences_file()
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            stored = json.load(config_file)
        self.assertEqual(stored['lens size'], 222)
        self.assertEqual(stored['thumbnail size'], 250)

    def test_a_file_that_cannot_be_read_is_written_over(self) -> None:
        """There is nothing to merge with, and this instance's own
        preferences are a better answer than none."""
        with open(constants.PREFERENCE_PATH, 'w') as config_file:
            config_file.write('this is not json')
        prefs['lens size'] = 333
        preferences.write_preferences_file()
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            self.assertEqual(json.load(config_file)['lens size'], 333)

    def test_an_instance_that_read_nothing_writes_nothing(self) -> None:
        """Nothing in this module makes the file be read before it is
        written, and MComix is not the only thing that imports it: a
        script that builds a window and closes it again writes the
        preferences too.  With no baseline to compare against, every
        default counts as a change, and the whole default dictionary
        goes over a file full of the user's own answers.
        """
        stored = {'lens size': 250, 'stretch': True, 'colour scheme': 'black'}
        with open(constants.PREFERENCE_PATH, 'w') as config_file:
            json.dump(stored, config_file)
        # The state the module is in before read_preferences_file() runs.
        preferences._as_read = {}
        preferences.write_preferences_file()
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            written = json.load(config_file)
        del written[preferences._FORMAT_VERSION_KEY]
        self.assertEqual(written, stored)

    def test_the_file_says_which_format_it_is_in(self) -> None:
        prefs['lens size'] = 1
        preferences.write_preferences_file()
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            stored = json.load(config_file)
        self.assertEqual(stored['config format version'],
                         preferences.CONFIG_FORMAT_VERSION)


class IsolationTest(MComixTest):

    def test_reaching_inside_a_preference_leaves_the_defaults_alone(self) -> None:
        """The preferences are restored from a dictionary captured when
        the suite was imported, and a preference that holds a container
        has to be restored as a copy of it: a test that reaches inside
        one - the dictionary of remembered dialog answers, say - would
        otherwise change what every later test starts from."""
        prefs['stored dialog choices']['some-dialog'] = 1
        self.assertEqual({}, default_prefs['stored dialog choices'])

    def test_a_preference_holding_a_list_is_restored_as_a_copy(self) -> None:
        """This one is a constant as well, so writing through it would
        change what MComix considers a comment file for the rest of the
        run."""
        prefs['comment extensions'].append('leaked')
        self.assertNotIn('leaked', default_prefs['comment extensions'])
        self.assertNotIn('leaked', constants.ACCEPTED_COMMENT_EXTENSIONS)

    def test_configuration_paths_point_into_the_test_directory(self) -> None:
        # A test writing to the developer's own configuration would be a
        # good deal worse than a failing test.
        for name in self.REDIRECTED_PATHS:
            path = getattr(constants, name)
            self.assertTrue(path.startswith(self.tmp_dir),
                            '%s points outside the test directory: %s'
                            % (name, path))


class WriteOnChangeTest(MComixTest):

    """A preference is written when it changes, not only at quit.

    Everything but a clean quit used to lose the lot: a crash, a kill, a
    session ending under the window.
    """

    def setUp(self) -> None:
        super().setUp()
        os.makedirs(constants.CONFIG_DIR, exist_ok=True)
        # Waiting out the coalescing delay would only be waiting for GLib.
        self.delay = preferences._WRITE_DELAY_MS
        preferences._WRITE_DELAY_MS = 10

    def tearDown(self) -> None:
        preferences._WRITE_DELAY_MS = self.delay
        super().tearDown()

    def _written(self) -> dict:
        wait_for(lambda: os.path.isfile(constants.PREFERENCE_PATH))
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            return json.load(config_file)

    def test_changing_one_writes_it(self) -> None:
        prefs['lens size'] = 234
        self.assertEqual(self._written().get('lens size'), 234)

    def test_changing_one_back_leaves_it_out(self) -> None:
        """What is written is what differs from what was read, and the
        scheduled write asks that when it runs rather than when it was
        scheduled."""
        prefs['lens size'] = 234
        prefs['lens size'] = default_prefs['lens size']
        self.assertNotIn('lens size', self._written())

    def test_writing_the_same_value_again_schedules_nothing(self) -> None:
        prefs['lens size'] = prefs['lens size']
        self.assertFalse(preferences._write_source)

    def test_a_change_inside_a_preference_is_written_when_it_says_so(self) -> None:
        """The mapping cannot see a dictionary of its own being changed;
        whoever changes one says so."""
        prefs['stored dialog choices']['resume-from-last-read-page'] = -8
        self.assertFalse(preferences._write_source)
        preferences.changed()
        self.assertEqual(self._written().get('stored dialog choices'),
                         {'resume-from-last-read-page': -8})

    def test_reading_the_file_is_not_changing_it(self) -> None:
        with open(constants.PREFERENCE_PATH, 'w') as config_file:
            json.dump({'lens size': 250}, config_file)
        preferences.read_preferences_file()
        self.assertFalse(preferences._write_source)


# vim: expandtab:sw=4:ts=4
