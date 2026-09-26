"""The "Open with" command line, and what it puts in place of each
variable.

The command is typed by the reader, so what it says is theirs to
expand; the file names that go into it are not, and a name holding
what looks like an environment variable is a name like any other.
"""

import ntpath
import os
import time
from unittest import mock

from . import MComixTest

from mcomix import openwith


class _StubImageHandler:

    def __init__(self, filename, path):
        self._filename = filename
        self._path = path

    def get_current_page(self):
        return 1

    def get_page_filename(self):
        return self._filename

    def get_path_to_page(self):
        return self._path


class _StubFileHandler:

    file_loaded = True
    archive_type = None

    def get_path_to_base(self):
        return None

    def get_base_filename(self):
        return ''


class _StubWindow:

    """Enough of a window for a command line to be parsed against."""

    def __init__(self, filename, path):
        self.filehandler = _StubFileHandler()
        self.imagehandler = _StubImageHandler(filename, path)


class OpenWithCommandTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.environ['MCOMIX_TEST_VARIABLE'] = 'expanded'
        self.addCleanup(os.environ.pop, 'MCOMIX_TEST_VARIABLE', None)

    def _parse(self, command, filename='page.jpg', path='/books/page.jpg'):
        return openwith.OpenWithCommand(
            'test', command, '', False).parse(_StubWindow(filename, path))

    def test_a_variable_is_replaced_by_what_it_stands_for(self):
        self.assertEqual(['viewer', 'page.jpg'], self._parse('viewer %f'))

    def test_an_environment_variable_in_the_command_is_expanded(self):
        """What the reader types is theirs, so $VARIABLE in the command
        line means what the shell would make of it."""
        self.assertEqual(['viewer', 'expanded'],
                         self._parse('viewer $MCOMIX_TEST_VARIABLE'))

    def test_a_file_name_that_reads_as_a_variable_is_left_alone(self):
        """A page called "$MCOMIX_TEST_VARIABLE.jpg" is a page with an
        awkward name, not a request to read the environment."""
        self.assertEqual(['viewer', '$MCOMIX_TEST_VARIABLE.jpg'],
                         self._parse('viewer %f',
                                     filename='$MCOMIX_TEST_VARIABLE.jpg'))

    def test_a_doubled_per_cent_sign_stands_for_one(self):
        self.assertEqual(['viewer', '50%'], self._parse('viewer 50%%'))

    def test_a_doubled_per_cent_sign_is_not_read_as_a_variable_either(self):
        """On win32 the environment's own variables are written between
        per cent signs, so an expansion has to be kept away from them."""
        self.assertEqual(['viewer', '%MCOMIX_TEST_VARIABLE%'],
                         self._parse('viewer %%MCOMIX_TEST_VARIABLE%%'))

    def test_the_win32_way_of_writing_a_variable_does_not_eat_it_either(self):
        """This machine need not be win32 for that rule to be checked:
        ntpath.expandvars is the function that runs there."""
        with mock.patch.object(os.path, 'expandvars', ntpath.expandvars):
            self.assertEqual(['viewer', '%MCOMIX_TEST_VARIABLE%'],
                             self._parse('viewer %%MCOMIX_TEST_VARIABLE%%'))
            self.assertEqual(['viewer', '$MCOMIX_TEST_VARIABLE.jpg'],
                             self._parse('viewer %f',
                                         filename='$MCOMIX_TEST_VARIABLE.jpg'))

    def test_a_quoted_argument_keeps_its_spaces(self):
        self.assertEqual(['viewer', 'two words'],
                         self._parse('viewer "two words"'))

    def test_an_incomplete_escape_is_refused(self):
        with self.assertRaises(openwith.OpenWithException):
            self._parse('viewer %')

    def test_an_incomplete_quote_is_refused(self):
        with self.assertRaises(openwith.OpenWithException):
            self._parse('viewer "one')

    def test_a_slash_variable_is_the_path_separator(self):
        self.assertEqual(['viewer', os.path.sep], self._parse('viewer %/'))

    def test_a_variable_the_manual_does_not_list_is_refused(self):
        with self.assertRaisesRegex(openwith.OpenWithException,
                                    'Invalid escape sequence: %x'):
            self._parse('viewer %x')

    def test_an_empty_command_line_is_refused(self):
        with self.assertRaisesRegex(openwith.OpenWithException,
                                    'Command line is empty'):
            self._parse('   ')

    def test_a_working_directory_of_two_arguments_is_not_valid(self):
        """An unquoted space splits the directory into two arguments,
        which is not a directory, even where the first half is one."""
        command = openwith.OpenWithCommand(
            'test', 'viewer', self.tmp_dir + ' more', False)
        self.assertFalse(command.is_valid_workdir(
            _StubWindow('page.jpg', '/books/page.jpg')))
        quoted = openwith.OpenWithCommand(
            'test', 'viewer', '"%s"' % self.tmp_dir, False)
        self.assertTrue(quoted.is_valid_workdir(
            _StubWindow('page.jpg', '/books/page.jpg')))

# vim: expandtab:sw=4:ts=4


class _Osd:

    def __init__(self):
        self.shown = []

    def show(self, text):
        self.shown.append(text)


class ExecuteTest(MComixTest):

    """Running a command: where it runs, and what the reader is told
    when it will not."""

    def setUp(self):
        super().setUp()
        self.window = _StubWindow('page.jpg', '/books/page.jpg')
        self.window.osd = _Osd()
        patcher = mock.patch.object(openwith.process, 'popen')
        self.popen = patcher.start()
        self.addCleanup(patcher.stop)

    def _command(self, command, cwd='', disabled_for_archives=False):
        return openwith.OpenWithCommand('Viewer', command, cwd,
                                        disabled_for_archives)

    def test_a_command_runs_with_the_page_and_its_directory(self):
        self._command('viewer %f', cwd=self.tmp_dir).execute(self.window)
        self.popen.assert_called_once_with(
            ['viewer', 'page.jpg'], stdout=openwith.process.NULL,
            workdir=self.tmp_dir)
        self.assertEqual([], self.window.osd.shown)

    def test_a_directory_that_is_not_there_is_not_run_in(self):
        self._command('viewer', cwd='/no/such/directory').execute(self.window)
        self.assertIsNone(self.popen.call_args.kwargs['workdir'])

    def test_a_command_kept_from_archives_says_so_over_one(self):
        self.window.filehandler.archive_type = 1
        self._command('viewer', disabled_for_archives=True).execute(
            self.window)
        self.popen.assert_not_called()
        self.assertEqual(["'Viewer' is disabled for archives."],
                         self.window.osd.shown)

    def test_a_command_that_cannot_start_says_why(self):
        self.popen.side_effect = FileNotFoundError(2, 'No such file')
        self._command('no-such-viewer').execute(self.window)
        self.assertEqual(1, len(self.window.osd.shown))
        self.assertIn('Could not run command Viewer', self.window.osd.shown[0])
        self.assertIn('No such file', self.window.osd.shown[0])


class _StubArchiveHandler(_StubFileHandler):

    archive_type = 'zip'

    def __init__(self, path):
        self._path = path

    def get_path_to_base(self):
        return self._path

    def get_base_filename(self):
        return os.path.basename(self._path)


class DocumentedVariablesTest(MComixTest):

    """Every variable the manual lists, with the manual's own examples
    (docs/External_Commands.md)."""

    def _expand(self, variable, window):
        return openwith.OpenWithCommand(
            'test', 'viewer %' + variable, '', False).parse(window)[1]

    def test_for_an_image_file(self):
        window = _StubWindow('cats.jpg', '/home/user/Downloads/cats.jpg')
        for variable, expected in (('F', '/home/user/Downloads/cats.jpg'),
                                   ('f', 'cats.jpg'),
                                   ('D', '/home/user/Downloads'),
                                   ('d', 'Downloads'),
                                   ('B', '/home/user/Downloads'),
                                   ('b', 'Downloads'),
                                   ('S', '/home/user'),
                                   ('s', 'user')):
            with self.subTest(variable=variable):
                self.assertEqual(expected, self._expand(variable, window))

    def test_for_an_archive(self):
        window = _StubWindow('cats.jpg', '/tmp/extracted/cats.jpg')
        window.filehandler = _StubArchiveHandler('/home/user/comic-2012.zip')
        for variable, expected in (('A', '/home/user/comic-2012.zip'),
                                   ('a', 'comic-2012.zip'),
                                   ('C', '/home/user'),
                                   ('c', 'user'),
                                   ('B', '/home/user/comic-2012.zip'),
                                   ('b', 'comic-2012.zip'),
                                   ('S', '/home/user'),
                                   ('s', 'user')):
            with self.subTest(variable=variable):
                self.assertEqual(expected, self._expand(variable, window))

    def test_archive_variables_are_refused_for_an_image_file(self):
        window = _StubWindow('cats.jpg', '/home/user/Downloads/cats.jpg')
        for variable in 'AaCc':
            with self.subTest(variable=variable):
                with self.assertRaises(openwith.OpenWithException):
                    self._expand(variable, window)


class _StubOSD:

    def __init__(self):
        self.shown = []

    def show(self, text):
        self.shown.append(text)


class WorkingDirectoryTest(MComixTest):

    def test_the_command_runs_in_its_directory_and_mcomix_stays_put(self):
        """The working directory was set by changing MComix' own, for
        every thread in it, and changing it back afterwards."""
        workdir = os.path.join(self.tmp_dir, 'work')
        os.makedirs(workdir)
        written = os.path.join(self.tmp_dir, 'where')
        window = _StubWindow('page.jpg', '/books/page.jpg')
        window.osd = _StubOSD()
        command = openwith.OpenWithCommand(
            'where', 'sh -c "pwd > %s"' % written, workdir, False)
        with mock.patch('os.chdir', side_effect=AssertionError('chdir')):
            command.execute(window)
        self.assertEqual([], window.osd.shown)
        deadline = time.monotonic() + 5
        while not (os.path.exists(written) and os.path.getsize(written)) \
                and time.monotonic() < deadline:
            time.sleep(0.01)
        with open(written) as where:
            self.assertEqual(os.path.realpath(workdir),
                             os.path.realpath(where.read().strip()))
