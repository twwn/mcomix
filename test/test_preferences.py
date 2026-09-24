import ast
import glob
import json
import os
import pickle
import stat

from . import MComixTest, default_prefs, wait_for

from mcomix import constants
from mcomix import preferences
from mcomix.preferences import prefs
from mcomix.preferences import _FORMAT_VERSION_KEY


def _sources():
    """Every module of MComix, as a path."""
    found = []
    for pattern in ('mcomix/*.py', 'mcomix/archive/*.py',
                    'mcomix/archive/native_pdf/*.py', 'mcomix/library/*.py'):
        found.extend(sorted(glob.glob(os.path.join(constants.BASE_PATH, pattern))))
    return found


def _table_keys(tree):
    """The keys of the two tables in preferences.py that name every
    preference: the TypedDict describing them and the defaults.

    They are what the test asks about, so a name that appears only there
    is a name nothing uses.
    """
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(id(key))
    return keys


def _named_in_the_source():
    """Every string the source of MComix holds, bar the two tables."""
    named = {}
    for path in _sources():
        tree = ast.parse(open(path).read())
        skip = _table_keys(tree) if os.path.basename(path) == 'preferences.py' else set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in skip):
                named.setdefault(node.value, []).append(
                    '%s:%d' % (os.path.relpath(path, constants.BASE_PATH), node.lineno))
    return named


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

    def test_moves_aside_a_file_that_holds_no_preferences(self) -> None:
        """JSON of another shape - a list, a string, a number - stopped
        MComix with AttributeError before it had a window."""
        for text in ('[1]', '"abc"', '42'):
            with self.subTest(text=text):
                self._write(text)
                preferences.read_preferences_file()
                self.assertFalse(os.path.exists(self.path))
                with open(self.broken) as broken:
                    self.assertEqual(text, broken.read())

    def test_a_value_of_the_wrong_type_is_not_taken_in(self) -> None:
        """Typed in by hand, it was taken in as it was, to reach code
        that could do nothing with it."""
        default = prefs['lens size']
        for value in ('big', None, 1.5, True):
            with self.subTest(value=value):
                self._write(json.dumps({'lens size': value,
                                        'lens magnification': 3}))
                preferences.read_preferences_file()
                self.assertEqual(default, prefs['lens size'])
                # The rest of the file is read all the same; a whole
                # number is a float's value, as JSON writes one.
                self.assertEqual(3, prefs['lens magnification'])

    def test_a_colour_of_the_wrong_length_is_not_taken_in(self) -> None:
        default = list(prefs['bg colour'])
        self._write(json.dumps({'config format version':
                                preferences.CONFIG_FORMAT_VERSION,
                                'bg colour': [1.0]}))
        preferences.read_preferences_file()
        self.assertEqual(default, prefs['bg colour'])

    def test_every_default_is_of_the_type_it_is_declared_to_be(self) -> None:
        """A default that did not pass would be written out, and the
        next start would refuse it."""
        for key, value in preferences._DEFAULTS.items():
            with self.subTest(key=key):
                self.assertTrue(preferences._fits(value, key))

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

    def test_the_misspelt_delete_answer_is_renamed(self) -> None:
        """Up to format version 2 the prompt that deletes the opened
        file stored its answer under "delete-opend-file"; a file holding
        that name would be asked again for good."""
        self._write({'stored dialog choices': {'delete-opend-file': -5}})
        preferences.read_preferences_file()
        self.assertEqual(prefs['stored dialog choices'],
                         {'delete-opened-file': -5})

    def test_the_rename_reaches_a_file_that_is_already_at_version_1(self) -> None:
        """Format version 1 is this branch's own and never was released,
        but files at it exist all the same - anyone running from this
        branch has one - so the rename is a step of its own rather than
        an addition to the step before it."""
        self._write({preferences._FORMAT_VERSION_KEY: 1,
                     'stored dialog choices': {'delete-opend-file': -5}})
        preferences.read_preferences_file()
        self.assertEqual(prefs['stored dialog choices'],
                         {'delete-opened-file': -5})

    def test_a_version_that_is_not_a_number_is_taken_as_the_oldest(self) -> None:
        """The version comes out of the file like everything else in it,
        so it can be anything a hand edit or a half-written file left
        there.  Comparing that against the current version raised
        TypeError, which nothing on the way up caught: MComix would not
        start."""
        self._write({_FORMAT_VERSION_KEY: '1',
                     'bg colour': self.OLD_DEFAULT})
        preferences.read_preferences_file()
        self.assertEqual(len(prefs['bg colour']), 4)
        self.assertAlmostEqual(prefs['bg colour'][0], 5000 / 65535)

    def test_a_colour_an_older_mcomix_wrote_back_unchanged_is_kept(self) -> None:
        """MComix 3.2 reads a file this one has migrated, drops the
        format version it does not know, and writes the RGBA components
        back as they were.  Taken for 16-bit ones on the way up again,
        they were divided a second time, and the background turned
        black.  A 16-bit component was always a whole number."""
        self._write({'bg colour': [0.5, 0.25, 0.125, 1.0],
                     'thumb bg colour': [1.0, 0.0, 0.5, 1.0]})
        preferences.read_preferences_file()
        self.assertEqual(prefs['bg colour'], [0.5, 0.25, 0.125, 1.0])
        self.assertEqual(prefs['thumb bg colour'], [1.0, 0.0, 0.5, 1.0])

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

    def test_a_second_write_does_not_put_back_what_the_first_wrote(self) -> None:
        """What this instance has changed is measured against the file as
        it was read, and the baseline stayed there after a write.  So
        every later write carried every change this instance had ever
        made, and put each back over whatever another window had set
        since - a lens size changed an hour ago undid one changed a
        minute ago."""
        prefs['lens size'] = 222
        preferences.write_preferences_file()

        # Another window changes the same preference afterwards.
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            elsewhere = json.load(config_file)
        elsewhere['lens size'] = 333
        with open(constants.PREFERENCE_PATH, 'w') as config_file:
            json.dump(elsewhere, config_file)

        # This one changes something else, and writes again.
        prefs['thumbnail size'] = 120
        preferences.write_preferences_file()
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            stored = json.load(config_file)
        self.assertEqual(stored['thumbnail size'], 120)
        self.assertEqual(stored['lens size'], 333)

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


class ByNameTest(MComixTest):

    """Reading and writing a preference by a name worked out at run time.

    The preferences dialog and the menu's toggles are built over the
    names they are handed, which is the one thing the mapping's type
    cannot check: nothing tells the checker that a name in a variable is
    one of the ninety-seven there are.  These two are where that is
    checked instead.
    """

    def test_a_preference_can_be_read_by_name(self) -> None:
        self.assertEqual(prefs['thumbnail size'],
                         preferences.by_name('thumbnail size'))

    def test_a_preference_can_be_set_by_name(self) -> None:
        preferences.set_by_name('thumbnail size', 111)
        self.assertEqual(111, prefs['thumbnail size'])

    def test_reading_one_that_does_not_exist_is_an_error(self) -> None:
        self.assertRaises(KeyError, preferences.by_name, 'no such preference')

    def test_setting_one_that_does_not_exist_is_an_error(self) -> None:
        # A dict would take the new key and keep it, so a misspelled
        # name in the dialog would read as a setting that does nothing.
        self.assertRaises(KeyError, preferences.set_by_name,
                          'no such preference', 1)
        self.assertNotIn('no such preference', prefs)


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


class EveryPreferenceIsUsedTest(MComixTest):

    """A preference nothing reads is a control that does nothing.

    That has happened here: a pair of radio buttons was given a
    preference each, and the one the first button was given was read by
    nothing at all, so whatever it was set to went out with the wash.
    Both directions are checked - every preference is named somewhere,
    and every name a control is given is a preference.
    """

    #: Where a control is handed the name of the preference it stands
    #: for, and which of its arguments that name is.  Nothing else can
    #: check these: they are strings at run time, where a mistake in
    #: prefs['...'] is an error the type checker reports.
    _CONTROLS = (
        ('_create_pref_check_button', 1),
        ('_create_binary_pref_radio_buttons', 3),
        ('_create_color_button', 0),
        ('_create_pref_spinner', 0),
        ('_update_toggle_preference', 0),
        ('_should_toggle_be_visible', 0),
        ('by_name', 0),
        ('set_by_name', 0),
    )

    def test_every_preference_is_named_somewhere(self):
        named = _named_in_the_source()
        unused = sorted(key for key in preferences._DEFAULTS if key not in named)
        self.assertEqual([], unused,
                         'preferences that nothing outside the tables names')

    def test_a_control_is_never_given_a_name_that_is_not_a_preference(self):
        wanted = dict(self._CONTROLS)
        found = {}
        for path in _sources():
            tree = ast.parse(open(path).read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
                if name not in wanted:
                    continue
                index = wanted[name]
                if len(node.args) <= index:
                    continue
                argument = node.args[index]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.setdefault(argument.value, []).append(
                        '%s:%d' % (os.path.relpath(path, constants.BASE_PATH),
                                   node.lineno))
        self.assertTrue(found, 'no control named a preference; have they been renamed?')
        for key, where in sorted(found.items()):
            self.assertIn(key, preferences._DEFAULTS,
                          '%s is named at %s and is not a preference'
                          % (key, ', '.join(where)))

# vim: expandtab:sw=4:ts=4
