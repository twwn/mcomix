import os
import shutil
import tempfile
import unittest

from mcomix import tools


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
