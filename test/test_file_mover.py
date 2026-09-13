""" Tests for moving the opened file, or its archive, to another folder. """

import errno
import os
import types
import unittest.mock

from . import MComixTest

from mcomix import file_mover


class FileMoverTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.source = os.path.join(self.tmp_dir, 'source')
        self.target = os.path.join(self.tmp_dir, 'target')
        os.makedirs(self.source)
        os.makedirs(self.target)
        self.book = os.path.join(self.source, 'book.cbz')
        with open(self.book, 'wb') as handle:
            handle.write(b'x' * 1024)

    def test_the_file_is_moved_and_where_it_went_reported(self):
        moved = file_mover.move_file(self.book, self.target)

        self.assertEqual(moved, os.path.join(self.target, 'book.cbz'))
        self.assertTrue(os.path.isfile(moved))
        self.assertFalse(os.path.exists(self.book))

    def test_a_name_that_is_taken_is_not_overwritten(self):
        """A move is not a way to replace a file.

        shutil.move() replaces one without a word, so the name is asked
        about first - and nothing has moved when the answer is no.
        """
        taken = os.path.join(self.target, 'book.cbz')
        with open(taken, 'wb') as handle:
            handle.write(b'something else')

        with self.assertRaises(FileExistsError):
            file_mover.move_file(self.book, self.target)

        self.assertTrue(os.path.isfile(self.book))
        with open(taken, 'rb') as handle:
            self.assertEqual(handle.read(), b'something else')

    def test_a_file_and_the_directory_beside_it_share_a_file_system(self):
        self.assertTrue(file_mover.same_file_system(self.book, self.target))

    def test_no_room_is_asked_for_within_one_file_system(self):
        """A rename writes nothing, so a full disk is no obstacle."""
        with unittest.mock.patch('shutil.disk_usage') as usage:
            file_mover.check_room_for(self.book, self.target)

        usage.assert_not_called()

    def test_a_move_across_file_systems_that_would_not_fit(self):
        with unittest.mock.patch.object(file_mover, 'same_file_system',
                                        return_value=False), \
                unittest.mock.patch('shutil.disk_usage',
                                    return_value=types.SimpleNamespace(free=1023)):
            with self.assertRaises(OSError) as raised:
                file_mover.move_file(self.book, self.target)

        self.assertEqual(raised.exception.errno, errno.ENOSPC)
        # Refused before a byte of it was copied.
        self.assertTrue(os.path.isfile(self.book))
        self.assertEqual(os.listdir(self.target), [])

    def test_a_move_across_file_systems_that_fits(self):
        with unittest.mock.patch.object(file_mover, 'same_file_system',
                                        return_value=False), \
                unittest.mock.patch('shutil.disk_usage',
                                    return_value=types.SimpleNamespace(free=1024)):
            moved = file_mover.move_file(self.book, self.target)

        self.assertTrue(os.path.isfile(moved))

# vim: expandtab:sw=4:ts=4
