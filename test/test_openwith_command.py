"""The "Open with" command line, and what it puts in place of each
variable.

The command is typed by the reader, so what it says is theirs to
expand; the file names that go into it are not, and a name holding
what looks like an environment variable is a name like any other.
"""

import ntpath
import os
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

# vim: expandtab:sw=4:ts=4


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
    (wiki/content/External_Commands.md)."""

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
