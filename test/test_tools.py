import itertools
import os
import shutil
import sys
import tempfile
import unittest

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
