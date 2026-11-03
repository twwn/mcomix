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

    def test_a_file_held_open_for_a_moment_is_moved_once(self):
        """Windows refuses to rename or remove a file something is
        reading, as the thumbnail bar reads a loose page.  shutil.move()
        took a refused rename for a move across file systems: it copied
        the book, failed to remove the original, and left it in both."""
        held = PermissionError(13, 'The process cannot access the file '
                               'because it is being used by another process')
        held.winerror = 32
        rename, unlink = os.rename, os.unlink
        refusals = {'rename': [held], 'unlink': [held]}

        def refused_once(name, real):
            def call(*args, **kwargs):
                if refusals[name]:
                    raise refusals[name].pop()
                return real(*args, **kwargs)
            return call

        with unittest.mock.patch('os.rename', refused_once('rename', rename)), \
                unittest.mock.patch('os.unlink', refused_once('unlink', unlink)):
            moved = file_mover.move_file(self.book, self.target)

        self.assertTrue(os.path.isfile(moved))
        self.assertEqual(os.listdir(self.source), [])

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

    def _move_across_with(self, name, stand_in):
        """Move the book as across file systems, with <stand_in> for the
        function called <name>."""
        crossing = OSError(errno.EXDEV, os.strerror(errno.EXDEV))
        with unittest.mock.patch.object(file_mover, 'same_file_system',
                                        return_value=False), \
                unittest.mock.patch('shutil.disk_usage',
                                    return_value=types.SimpleNamespace(free=4096)), \
                unittest.mock.patch('os.rename', side_effect=crossing), \
                unittest.mock.patch(name, stand_in), \
                self.assertRaises(OSError):
            file_mover.move_file(self.book, self.target)

    def test_an_original_that_will_not_go_leaves_no_copy(self):
        """A folder that can be read and not written to, on another file
        system: the copy stayed behind, and a second try was told its
        name was taken."""
        unlink = os.unlink

        def refused(path, **kwargs):
            if path == self.book:
                raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
            unlink(path, **kwargs)

        self._move_across_with('os.unlink', refused)
        self.assertTrue(os.path.isfile(self.book))
        self.assertEqual([], os.listdir(self.target))

    def test_a_copy_that_fails_leaves_no_part_of_it(self):
        def half_written(source, destination, **kwargs):
            with open(destination, 'wb') as handle:
                handle.write(b'x')
            raise OSError(errno.EIO, os.strerror(errno.EIO), destination)

        # Windows copies with an API of its own, so the whole move stands in.
        self._move_across_with('shutil.move', half_written)
        self.assertTrue(os.path.isfile(self.book))
        self.assertEqual([], os.listdir(self.target))

# vim: expandtab:sw=4:ts=4
