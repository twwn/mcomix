import itertools
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

from mcomix import tools


class TestCompileRotations(unittest.TestCase):

    """The one rotation a series of them amounts to."""

    def test_rotations_that_fit_in_a_turn_are_added_up(self) -> None:
        self.assertEqual(tools.compile_rotations(90, 180), 270)
        self.assertEqual(tools.compile_rotations(0, 90), 90)
        self.assertEqual(tools.compile_rotations(90), 90)
        self.assertEqual(tools.compile_rotations(), 0)

    def test_a_full_turn_and_more_comes_back_into_range(self) -> None:
        """Each rotation was brought into range on its way in, but the
        running total was not, so anything adding up to a full turn or
        more came out as an angle no other caller accepts: four turns of
        90 degrees left the preference at 360, and 270 with 180 gave 450
        where angle_to_gdkpixbuf_rotation() raises."""
        self.assertEqual(tools.compile_rotations(270, 90), 0)
        self.assertEqual(tools.compile_rotations(270, 180), 90)
        self.assertEqual(tools.compile_rotations(270, 270), 180)
        self.assertEqual(tools.compile_rotations(180, 180), 0)
        self.assertEqual(tools.compile_rotations(90, 90, 90, 90), 0)

    def test_turning_ninety_degrees_four_times_comes_back_to_where_it_began(self) -> None:
        rotation = 0
        for _turn in range(4):
            rotation = tools.compile_rotations(rotation, 90)
        self.assertEqual(rotation, 0)

    def test_every_answer_is_one_a_rotation_can_be_asked_for(self) -> None:
        for first in (0, 90, 180, 270):
            for second in (0, 90, 180, 270):
                self.assertIn(tools.compile_rotations(first, second),
                              (0, 90, 180, 270))


class TestAxisMaps(unittest.TestCase):

    """remap_axes() and the order that undoes it."""

    def test_the_inverse_undoes_the_remapping(self) -> None:
        """MComix only ever swaps two axes, and a swap is its own
        inverse, so this went unnoticed: inverse_axis_map() returned the
        order it was given rather than the one that reverses it."""
        for order in ((0, 1), (1, 0), (0, 2, 1), (1, 2, 0), (2, 0, 1),
                      (3, 0, 1, 2)):
            vector = list('abcd'[:len(order)])
            remapped = tools.remap_axes(vector, order)
            self.assertEqual(
                tools.remap_axes(remapped, tools.inverse_axis_map(order)),
                vector, 'order %r did not come back' % (order,))

    def test_the_inverse_of_a_swap_is_the_swap(self) -> None:
        self.assertEqual(tools.inverse_axis_map((0, 1)), [0, 1])
        self.assertEqual(tools.inverse_axis_map((1, 0)), [1, 0])


class TestAlphanumericSort(unittest.TestCase):
    def test_numbers_are_ordered_naturally(self) -> None:
        lst = ['10.jpg', '2.jpg']
        tools.alphanumeric_sort(lst)
        self.assertListEqual(lst, ['2.jpg', '10.jpg'])

    def test_sort_with_mixed_number_and_string_files(self) -> None:
        lst = ['text_2.jpg', '2_text.jpg']
        tools.alphanumeric_sort(lst)
        self.assertListEqual(lst, ['2_text.jpg', 'text_2.jpg'])

    def test_sort_creates_strict_order(self) -> None:
        lst = ['Comic 001-01.jpg', 'Comic 001-00.jpg', 'zCover.jpg', 'Comic 001-03.jpg']
        tools.alphanumeric_sort(lst)
        self.assertListEqual(lst, ['Comic 001-00.jpg', 'Comic 001-01.jpg', 'Comic 001-03.jpg', 'zCover.jpg'])


    def test_a_digit_that_is_not_a_number_is_sorted_as_text(self) -> None:
        """str.isdigit() is true of the superscripts and the circled
        numbers, which int() refuses: a page named "m\u00b2" made the sort
        raise ValueError, and the book could not be listed at all."""
        lst = ['page 1\u00b23.jpg', '10.jpg', '2.jpg']
        tools.alphanumeric_sort(lst)
        self.assertListEqual(lst, ['2.jpg', '10.jpg', 'page 1\u00b23.jpg'])


    def test_the_order_does_not_depend_on_the_order_listed(self) -> None:
        """Names that differ only in case or in leading zeros compared
        equal, and the sort kept them in whatever order the directory
        or the archive listed them: all 24 orders of these four came
        out as 24 different sorts."""
        names = ['Page1.jpg', 'page1.jpg', 'page01.jpg', 'PAGE001.jpg']
        sorts = set()
        for listed in itertools.permutations(names):
            lst = list(listed)
            tools.alphanumeric_sort(lst)
            sorts.add(tuple(lst))
        self.assertEqual(1, len(sorts), sorts)

    def test_numbers_still_come_before_the_case_of_a_name(self) -> None:
        lst = ['page10.jpg', 'Page2.jpg', 'page2.jpg']
        tools.alphanumeric_sort(lst)
        self.assertListEqual(lst, ['Page2.jpg', 'page2.jpg', 'page10.jpg'])

class TestAtomicWrite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp_dir, 'preferences.conf')

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir)

    def test_old_content_is_readable_until_write_finished(self) -> None:
        # Several instances quitting at once (e.g. by "pkill mcomix") used to
        # truncate each other's config files, leaving the next started
        # instance with an unparsable file and thus default settings.
        with open(self.path, 'w') as file:
            file.write('old')

        with tools.atomic_write(self.path) as file:
            file.write('new')
            with open(self.path, 'r') as concurrent_reader:
                self.assertEqual(concurrent_reader.read(), 'old')

        with open(self.path, 'r') as file:
            self.assertEqual(file.read(), 'new')
        self.assertListEqual(os.listdir(self.tmp_dir), ['preferences.conf'])

    def test_failed_write_keeps_old_content(self) -> None:
        with open(self.path, 'wb') as file:
            file.write(b'old')

        with self.assertRaises(RuntimeError):
            with tools.atomic_write(self.path, binary=True) as file:
                file.write(b'new')
                raise RuntimeError('write failed')

        with open(self.path, 'rb') as file:
            self.assertEqual(file.read(), b'old')
        self.assertListEqual(os.listdir(self.tmp_dir), ['preferences.conf'])

    @unittest.skipIf(sys.platform == 'win32', 'symbolic links need privileges')
    def test_a_linked_file_stays_linked(self) -> None:
        """Settings kept elsewhere and linked into place, as dotfile
        managers do: the new file was renamed over the link, so the
        link was gone and what it pointed at never changed again."""
        kept = os.path.join(self.tmp_dir, 'dotfiles')
        os.makedirs(kept)
        target = os.path.join(kept, 'preferences.conf')
        with open(target, 'w') as file:
            file.write('old')
        os.symlink(target, self.path)

        with tools.atomic_write(self.path) as file:
            file.write('new')

        self.assertTrue(os.path.islink(self.path))
        with open(target, 'r') as file:
            self.assertEqual(file.read(), 'new')
        self.assertListEqual(os.listdir(kept), ['preferences.conf'])


@unittest.skipIf(sys.platform == 'win32', 'the XDG directories are for Unix')
class TestXdgDirectories(unittest.TestCase):

    """Where the settings, the library and the thumbnails go.

    The base directory specification says a variable that is empty, or
    that names a relative path, is to be ignored in favour of the
    default.  An empty one was taken as it was: $XDG_CONFIG_HOME set to
    nothing put MComix' settings in a directory called mcomix under
    whatever directory it was started from."""

    CASES = (
        (tools.get_config_directory, 'XDG_CONFIG_HOME', ('.config', 'mcomix')),
        (tools.get_data_directory, 'XDG_DATA_HOME', ('.local/share', 'mcomix')),
        (tools.get_thumbnail_directory, 'XDG_CACHE_HOME',
         ('.cache', 'thumbnails', 'normal')),
    )

    def _with(self, variable, value, function):
        saved = os.environ.get(variable)
        os.environ[variable] = value
        try:
            return function()
        finally:
            if saved is None:
                del os.environ[variable]
            else:
                os.environ[variable] = saved

    def test_an_empty_or_relative_variable_is_ignored(self):
        home = os.path.expanduser('~')
        for function, variable, default in self.CASES:
            for value in ('', 'relative/dir'):
                with self.subTest(variable=variable, value=value):
                    self.assertEqual(os.path.join(home, *default),
                                     self._with(variable, value, function))

    def test_an_absolute_variable_is_used(self):
        for function, variable, default in self.CASES:
            with self.subTest(variable=variable):
                self.assertEqual(
                    os.path.join('/somewhere', *default[1:]),
                    self._with(variable, '/somewhere', function))


class TestWindowsDirectories(unittest.TestCase):

    """Where the settings, the library and the thumbnails go on Windows,
    checked here with ntpath's expandvars, which is what os.path is
    there: posixpath's leaves %APPDATA% as it is."""

    def test_everything_goes_into_mcomix_under_appdata(self):
        import ntpath
        from unittest import mock
        roaming = '/Users/reader/AppData/Roaming'
        with mock.patch.object(sys, 'platform', 'win32'), \
                mock.patch.object(os.path, 'expandvars', ntpath.expandvars), \
                mock.patch.dict(os.environ, {'APPDATA': roaming}):
            self.assertEqual(os.path.join(roaming, 'MComix'),
                             tools.get_config_directory())
            self.assertEqual(os.path.join(roaming, 'MComix'),
                             tools.get_data_directory())
            self.assertEqual(
                os.path.join(roaming, 'MComix', '.thumbnails', 'normal'),
                tools.get_thumbnail_directory())
            # The profile itself, where the choosers open: the MComix
            # folder in it is where the settings were before %APPDATA%,
            # and is moved away at the first start.
            self.assertEqual(os.path.expanduser('~'),
                             tools.get_home_directory())


class TestThreadCount(unittest.TestCase):

    """The automatic setting of the two thread preferences."""

    def _available(self, count):
        """Patch whichever call thread_count() asks for the processors
        this process may run on, so that it answers <count>."""
        if sys.version_info >= (3, 13):
            return unittest.mock.patch.object(
                os, 'process_cpu_count', return_value=count)
        return unittest.mock.patch.object(
            os, 'sched_getaffinity', return_value=set(range(count)),
            create=True)

    def test_a_chosen_number_is_kept(self):
        for chosen in (1, 3, 16):
            with self.subTest(chosen=chosen), self._available(24):
                self.assertEqual(chosen, tools.thread_count(chosen))

    def test_zero_is_one_thread_for_each_processor(self):
        for available in (1, 2, 8, 24):
            with self.subTest(available=available), \
                    self._available(available):
                self.assertEqual(available, tools.thread_count(0))

    def test_zero_follows_the_processors_however_many(self):
        with self._available(256):
            self.assertEqual(256, tools.thread_count(0))

    def test_zero_is_one_thread_where_the_count_is_unknown(self):
        if sys.version_info < (3, 13):
            self.skipTest('os.process_cpu_count() is new in Python 3.13')
        with self._available(None):
            self.assertEqual(1, tools.thread_count(0))

    def _memory(self, gigabytes):
        return unittest.mock.patch.object(
            tools, 'physical_memory',
            return_value=None if gigabytes is None else gigabytes * 2**30)

    def test_threads_that_cost_memory_take_a_sixteenth_of_it(self):
        """A thread with a process of its own, as the PDF reader's
        have, cost 3 GB for one book when there was one per
        processor."""
        for gigabytes, expected in ((8, 4), (16, 8), (64, 24)):
            with self.subTest(gigabytes=gigabytes), self._available(24), \
                    self._memory(gigabytes):
                self.assertEqual(expected, tools.thread_count(0, 128 * 2**20))

    def test_threads_that_cost_more_than_the_share_still_get_one(self):
        with self._available(24), self._memory(1):
            self.assertEqual(1, tools.thread_count(0, 2**30))

    def test_threads_that_cost_nothing_follow_the_processors_alone(self):
        with self._available(24), self._memory(1):
            self.assertEqual(24, tools.thread_count(0))

    def test_an_unknown_memory_leaves_the_processors(self):
        with self._available(24), self._memory(None):
            self.assertEqual(24, tools.thread_count(0, 128 * 2**20))

    def test_a_chosen_number_is_kept_whatever_each_thread_costs(self):
        with self._available(24), self._memory(1):
            self.assertEqual(20, tools.thread_count(20, 2**30))


class TestPhysicalMemory(unittest.TestCase):

    @unittest.skipIf(sys.platform == 'win32', 'the POSIX call')
    def test_this_machine_says_how_much_it_has(self):
        memory = tools.physical_memory()
        self.assertIsNotNone(memory)
        self.assertGreater(memory, 2**20)

    def test_an_unanswered_question_is_no_answer(self):
        with unittest.mock.patch.object(os, 'sysconf', return_value=-1, create=True):
            if sys.platform != 'win32':
                self.assertIsNone(tools.physical_memory())

    def _windows(self, answer, total):
        """Ask as Windows is asked, with GlobalMemoryStatusEx answering
        <answer> and filling in <total> bytes."""
        def global_memory_status(pointer):
            pointer._obj.ullTotalPhys = total
            return answer
        windll = unittest.mock.Mock()
        windll.kernel32.GlobalMemoryStatusEx.side_effect = global_memory_status
        with unittest.mock.patch.object(sys, 'platform', 'win32'), \
                unittest.mock.patch('ctypes.windll', windll, create=True):
            return tools.physical_memory()

    def test_windows_is_asked_for_its_memory_status(self):
        self.assertEqual(16 * 2**30, self._windows(1, 16 * 2**30))

    def test_a_windows_call_that_fails_is_no_answer(self):
        self.assertIsNone(self._windows(0, 16 * 2**30))


class TestNumberOfDigits(unittest.TestCase):

    def test_zero_has_one_digit(self):
        """log10 of it would raise."""
        self.assertEqual(1, tools.number_of_digits(0))
        self.assertEqual(3, tools.number_of_digits(-120))
