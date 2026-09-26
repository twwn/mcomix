"""What the program does before it has a window to say it in."""

import io
import os
import re
import tomllib
import unittest.mock

import gi
# PIL.Image compares PIL.__version__ with its extension's version when it
# is first imported, so it has to be in before the tests patch that.
import PIL.Image

from . import MComixTest, get_testfile_path

from mcomix import run
from mcomix.preferences import prefs

PYPROJECT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(run.__file__))), 'pyproject.toml')


class RequiredPillowTest(MComixTest):

    """run.py let MComix start with Pillow 9.1.0 while pyproject.toml
    required 10.1.0, so a distribution packaging MComix outside pip could
    ship a Pillow no test had been run against."""

    @unittest.skipUnless(os.path.isfile(PYPROJECT),
                         'not running from a source tree')
    def test_pyproject_declares_the_same_minimum(self):
        with open(PYPROJECT, 'rb') as fp:
            dependencies = tomllib.load(fp)['project']['dependencies']
        declared = [match.group(1) for match in
                    (re.fullmatch(r'Pillow\s*>=\s*(\S+)', dependency)
                     for dependency in dependencies) if match]
        self.assertEqual([run.PIL_VERSION_REQUIRED], declared)

    def test_an_older_pillow_exits_with_a_message(self):
        with unittest.mock.patch.object(PIL, '__version__', '10.0.1'), \
                self.assertRaises(SystemExit) as caught:
            run.setup_dependencies()
        self.assertEqual(1, caught.exception.code)

    def test_the_required_pillow_starts(self):
        with unittest.mock.patch.object(PIL, '__version__',
                                        run.PIL_VERSION_REQUIRED):
            run.setup_dependencies()


class DependencyCheckTest(MComixTest):

    """setup_dependencies() reports a missing dependency rather than
    letting it out as a traceback."""

    def _fail_with(self, error):
        with unittest.mock.patch.object(gi, 'require_version',
                                        side_effect=error):
            with self.assertRaises(SystemExit) as caught:
                run.setup_dependencies()
        return caught.exception

    def test_an_unavailable_namespace_exits_with_a_message(self):
        # This is what gi.require_version() raises, and the only thing it
        # documents raising.
        exit = self._fail_with(
            ValueError('Namespace Gtk not available for version 4.0'))
        self.assertEqual(1, exit.code)

    def test_a_namespace_already_loaded_elsewhere_exits_too(self):
        exit = self._fail_with(
            ValueError('Namespace Gtk is already loaded with version 3.0'))
        self.assertEqual(1, exit.code)


class ArgumentTest(MComixTest):

    """The command line, which is also how MComix asks another MComix to
    open something: a middle click on a bookmark starts one with the
    bookmark's file and its page."""

    def test_a_book_is_opened_at_its_first_page_by_default(self):
        opts, args = run.parse_arguments(['/books/one.cbz'])
        self.assertEqual(args, ['/books/one.cbz'])
        self.assertEqual(opts.page, 0)

    def test_a_page_can_be_named(self):
        opts, args = run.parse_arguments(['--page', '7', '/books/one.cbz'])
        self.assertEqual(args, ['/books/one.cbz'])
        self.assertEqual(opts.page, 7)

    def test_the_file_of_the_page_can_be_named(self):
        """What a bookmark in an archive hands a second MComix, beside
        the page: the name within the archive of the page's file."""
        opts, args = run.parse_arguments(
            ['--page', '7', '--page-member', 'pages/07.jpg',
             '/books/one.cbz'])
        self.assertEqual(args, ['/books/one.cbz'])
        self.assertEqual(opts.page_member, 'pages/07.jpg')

    def test_the_file_of_the_page_is_not_in_the_help(self):
        """It is for MComix to hand another MComix, not for a reader to
        type."""
        with unittest.mock.patch('sys.stdout', new_callable=io.StringIO) \
                as printed, self.assertRaises(SystemExit):
            run.parse_arguments(['--help'])
        self.assertNotIn('page-member', printed.getvalue())

    def test_a_log_file_can_be_named(self):
        """The one way to read the log of MComix.exe, which has no
        console; -o was accepted and ignored."""
        opts, args = run.parse_arguments(['-o', 'mcomix.log', '/books/one.cbz'])
        self.assertEqual(args, ['/books/one.cbz'])
        self.assertEqual(opts.output, 'mcomix.log')
        with unittest.mock.patch('sys.stdout', new_callable=io.StringIO) \
                as printed, self.assertRaises(SystemExit):
            run.parse_arguments(['--help'])
        self.assertIn('-o FILE', printed.getvalue())

    def _open(self, argv):
        opts, args = run.parse_arguments(argv)
        return run.what_to_open(opts, args)

    def test_the_last_file_is_opened_at_the_file_of_its_page(self):
        """What 9c4095ef keeps for "auto load last file" reaches the
        window: the page's file as well as its number."""
        book = get_testfile_path('archives', '01-ZIP-Normal.zip')
        prefs['auto load last file'] = True
        prefs['path to last file'] = book
        prefs['page of last file'] = 2
        prefs['member of last file'] = 'images/02-JPG-RGB.jpg'
        self.assertEqual((book, 2, 'images/02-JPG-RGB.jpg'), self._open([]))

    def test_a_last_file_kept_by_an_older_mcomix_has_no_file_of_its_page(self):
        book = get_testfile_path('archives', '01-ZIP-Normal.zip')
        prefs['auto load last file'] = True
        prefs['path to last file'] = book
        prefs['page of last file'] = 2
        self.assertEqual((book, 2, None), self._open([]))

    def test_a_book_named_on_the_command_line_wins(self):
        """The last file's page and its file are about the last file,
        not about the book that was named."""
        prefs['auto load last file'] = True
        prefs['path to last file'] = get_testfile_path(
            'archives', '01-ZIP-Normal.zip')
        prefs['page of last file'] = 2
        prefs['member of last file'] = 'images/02-JPG-RGB.jpg'
        self.assertEqual(('/books/one.cbz', 0, None),
                         self._open(['/books/one.cbz']))

    def test_a_last_file_that_is_gone_is_not_opened(self):
        prefs['auto load last file'] = True
        prefs['path to last file'] = '/books/gone.cbz'
        prefs['member of last file'] = 'pages/02.jpg'
        self.assertEqual((None, 0, None), self._open([]))

    def test_a_page_that_is_not_a_number_is_refused(self):
        with self.assertRaises(SystemExit):
            run.parse_arguments(['--page', 'seven', '/books/one.cbz'])



class MakeDirectoriesTest(MComixTest):

    def test_directories_another_mcomix_has_just_made_are_taken_as_made(self):
        """MComix runs one process per window, and two started at once
        on a new account both found the directories missing; the one
        that made them second died of FileExistsError."""
        from mcomix import constants
        for directory in (constants.DATA_DIR, constants.CONFIG_DIR):
            os.makedirs(directory, exist_ok=True)
        # What the second process saw: missing when it looked, there by
        # the time it made them.
        with unittest.mock.patch('os.path.exists', return_value=False):
            run.make_directories()
        self.assertTrue(os.path.isdir(constants.DATA_DIR))
        self.assertTrue(os.path.isdir(constants.CONFIG_DIR))

    def test_they_are_made_for_the_user_alone(self):
        from mcomix import constants
        run.make_directories()
        for directory in (constants.DATA_DIR, constants.CONFIG_DIR):
            self.assertEqual(0o700, os.stat(directory).st_mode & 0o777)

# vim: expandtab:sw=4:ts=4
