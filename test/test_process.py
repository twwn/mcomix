
import importlib.machinery
import os
import stat
import sys
import tempfile
import types
import unittest.mock

from . import MComixTest

from mcomix import process


def _create_file(path, rights='r'):
    mode = 0
    for r, m in (
        ('r', stat.S_IRUSR),
        ('w', stat.S_IWUSR),
        ('x', stat.S_IXUSR),
    ):
        if r in rights:
            mode |= m
    dir = os.path.dirname(path)
    if not os.path.exists(dir):
        os.makedirs(dir)
    open(path, 'w+b').close()
    os.chmod(path, mode)


def _create_tree(root, entries):
    for name, rights in entries:
        full_path = os.path.join(root, name)
        _create_file(full_path, rights)


class ProcessTest(MComixTest):

    @unittest.skipIf(sys.platform == 'win32', 'os.defpath holds no sh there')
    def test_with_no_path_set_the_default_one_is_searched(self):
        environ = {name: value for name, value in os.environ.items()
                   if name != 'PATH'}
        with unittest.mock.patch.dict(os.environ, environ, clear=True):
            found = process.find_executable(('sh',))
        self.assertIsNotNone(found)
        self.assertIn(os.path.dirname(found), os.defpath.split(os.pathsep))

    def test_find_executable(self):
        cleanup = []
        try:
            root_dir = tempfile.mkdtemp(prefix='path.')

            if 'win32' == sys.platform:
                orig_exe_dir = process._exe_dir
                cleanup.append(lambda: setattr(process, '_exe_dir', orig_exe_dir))
                process._exe_dir = 'dir4'
                tree = (
                    ('bin1.exe', 'rx'),
                    ('bin3.exe', 'rx'),
                    ('dir1/bin1.exe', 'rx'),
                    ('dir1/bin2', 'rx'),
                    ('dir2/bin1.exe', 'rx'),
                    ('dir3/bin2.exe', 'rx'),
                    ('dir3/bin4.exe', 'rx'),
                    ('dir3/dir/bin2.exe', 'rx'),
                    ('dir4/bin4.exe', 'rx'),
                    ('dir4/bin5.exe', 'rx'),
                )
                tests = (
                    # Absolute path, unchanged.
                    ([sys.executable], None, sys.executable),
                    # Same without .exe extension.
                    ([sys.executable[:-4]], None, sys.executable),
                    # Must still be valid, though...
                    (['C:/invalid/invalid'], None, None),
                    # bin1 in workdir should be picked up.
                    (['bin1.exe'], None, 'bin1.exe'),
                    (['bad', 'bin1.exe'], None, 'bin1.exe'),
                    # Same without .exe extension.
                    (['bin1'], None, 'bin1.exe'),
                    # bin2 in dir1 or bin2 @ind dir3 should not be picked up.
                    (['bin2'], None, 'dir3/bin2.exe'),
                    # Candidate with a directory component.
                    (['./bin3'], None, 'bin3.exe'),
                    # And a custom working directory.
                    (['dir/bin2'], 'dir3', 'dir3/dir/bin2.exe'),
                    # Check main executable directory is searched too.
                    # (with higher priority than PATH)
                    (['bin4'], None, 'dir4/bin4.exe'),
                    # And work directory.
                    (['bin4'], 'dir3', 'dir4/bin4.exe'),
                )
            else:
                tree = (
                    ('bin1', 'rx'),
                    ('bin3', 'rx'),
                    ('dir1/bin1', 'rx'),
                    ('dir1/bin2', 'r '),
                    ('dir2/bin1', 'rx'),
                    ('dir2/bin2', '  '),
                    ('dir3/bin1', 'rx'),
                    ('dir3/bin2', 'rx'),
                    ('dir3/bin3', 'r '),
                    ('dir3/bin4', 'rx'),
                    ('dir3/dir/bin2', 'rx'),
                    ('dir3/dir/bin3', 'rw '),
                )
                tests = (
                    # Absolute path, unchanged.
                    (['/bin/true'], None, '/bin/true'),
                    # Must still be valid, though...
                    (['/invalid/invalid'], None, None),
                    # bin1 in workdir should not be picked up.
                    (['bin1'], None, 'dir1/bin1'),
                    # Check all candidates.
                    (['bad', 'bin1'], None, 'dir1/bin1'),
                    # bin2 in dir1 should not be picked up (not executable).
                    (['bin2'], None, 'dir3/bin2'),
                    # Same with bin3.
                    (['bin3'], None, None),
                    # Candidate with a directory component.
                    (['./bin3'], None, 'bin3'),
                    # And a custom working directory.
                    (['dir/bin2'], 'dir3', 'dir3/dir/bin2'),
                    # But must still be valid...
                    (['dir/bin3'], 'dir3', None),
                )

            _create_tree(root_dir, tree)

            root_dir = os.path.abspath(root_dir)

            orig_path = os.environ['PATH']
            cleanup.append(lambda: os.environ.__setitem__('PATH', orig_path))
            os.environ['PATH'] = os.pathsep.join('dir1 dir2 dir3'.split())

            orig_cwd = os.getcwd()
            cleanup.append(lambda: os.chdir(orig_cwd))
            os.chdir(root_dir)

            for candidates, workdir, expected in tests:
                if expected is not None:
                    if not os.path.isabs(expected):
                        expected = os.path.join(root_dir, expected)
                    expected = os.path.normpath(expected)
                result = process.find_executable(candidates, workdir=workdir)
                msg = (
                    'find_executable(%s, workdir=%s) failed; '
                    'returned %s instead of %s' % (
                        candidates, workdir,
                        result, expected,
                    )
                )
                self.assertEqual(result, expected, msg=msg)

        finally:
            for fn in reversed(cleanup):
                fn()

    @unittest.skipIf(sys.platform == 'win32', 'file names are UTF-16 there, '
                     'with no bytes to escape')
    def test_an_argument_the_locale_cannot_encode(self):
        """ Paths read from the filesystem carry undecodable bytes as
        surrogate escapes, and those must reach the spawned process
        unchanged rather than raising while the argument vector is built. """
        name = 'a\udcffb'
        with tempfile.TemporaryDirectory(prefix='surrogate.') as tmp_dir:
            path = os.path.join(tmp_dir, name)
            proc = process.popen(('/bin/cp', '/dev/null', path))
            proc.stdout.close()
            self.assertEqual(0, proc.wait())
            self.assertEqual([name], os.listdir(tmp_dir))


class LaunchTest(MComixTest):

    """Starting another MComix, which is what a middle click on a recent
    file or a bookmark does."""

    def setUp(self):
        super().setUp()
        self.spawned = []
        patch = unittest.mock.patch.object(
            process, 'popen',
            side_effect=lambda command, **kwargs: self.spawned.append(
                list(command)))
        patch.start()
        self.addCleanup(patch.stop)

    def _as_main(self, name):
        """Pretend the program was started as the module <name>."""
        main = types.ModuleType('__main__')
        main.__spec__ = importlib.machinery.ModuleSpec(
            name, None, is_package=False)
        return unittest.mock.patch.dict(sys.modules, {'__main__': main})

    def test_a_module_run_is_started_the_same_way(self):
        """sys.argv[0] names mcomix/__main__.py after "python -m mcomix",
        and running that file as a script fails: its relative imports
        have no package to resolve against."""
        with self._as_main('mcomix.__main__'):
            self.assertEqual(process.mcomix_command(),
                             [sys.executable, '-m', 'mcomix'])

    def test_a_script_is_started_by_its_path(self):
        main = types.ModuleType('__main__')
        main.__spec__ = None
        with unittest.mock.patch.dict(sys.modules, {'__main__': main}), \
                unittest.mock.patch.object(sys, 'argv', ['bin/mcomix']):
            self.assertEqual(process.mcomix_command(),
                             [sys.executable, os.path.abspath('bin/mcomix')])

    def test_a_frozen_build_is_its_own_executable(self):
        with unittest.mock.patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(process.mcomix_command(), [sys.executable])

    @unittest.skipIf(sys.platform == 'win32', 'Win32Popen is used there')
    def test_the_file_is_the_last_argument(self):
        with self._as_main('mcomix.__main__'):
            process.launch_mcomix('/books/one.cbz')
        self.assertEqual(self.spawned,
                         [[sys.executable, '-m', 'mcomix', '/books/one.cbz']])

    @unittest.skipIf(sys.platform == 'win32', 'Win32Popen is used there')
    def test_a_page_is_passed_on(self):
        """A bookmark is a file and a page, so opening one elsewhere has
        to name the page as well."""
        with self._as_main('mcomix.__main__'):
            process.launch_mcomix('/books/one.cbz', 7)
        self.assertEqual(self.spawned, [[sys.executable, '-m', 'mcomix',
                                         '--page', '7', '/books/one.cbz']])

    @unittest.skipIf(sys.platform == 'win32', 'Win32Popen is used there')
    def test_the_file_of_the_page_is_passed_on(self):
        """A bookmark in an archive also names the file of its page,
        which finds the page wherever the archive's sort order has put
        it; the new program is told it too."""
        with self._as_main('mcomix.__main__'):
            process.launch_mcomix('/books/one.cbz', 7, 'pages/07.jpg')
        self.assertEqual(self.spawned, [[
            sys.executable, '-m', 'mcomix', '--page', '7',
            '--page-member', 'pages/07.jpg', '/books/one.cbz']])

    @unittest.skipIf(sys.platform == 'win32', 'Win32Popen is used there')
    def test_no_file_starts_it_as_a_launcher_would(self):
        """Restarting with nothing open passes nothing on, and leaves
        the new program to read the preferences for what to open."""
        with self._as_main('mcomix.__main__'):
            process.launch_mcomix(None, 3)
        self.assertEqual(self.spawned, [[sys.executable, '-m', 'mcomix']])

    @unittest.skipIf(sys.platform == 'win32', 'Win32Popen is used there')
    def test_no_page_means_no_page_argument(self):
        """0 is what a recent file is opened with, and it leaves the
        choice to the file handler: the first page, or the last one
        read."""
        with self._as_main('mcomix.__main__'):
            process.launch_mcomix('/books/one.cbz', 0)
        self.assertNotIn('--page', self.spawned[0])
