""" Tests for moving the opened file, or its archive, to another folder. """

import errno
import os
import shutil
import types
import unittest.mock

from . import MComixTest, get_testfile_path

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

    def _volume_set(self):
        """The three volumes of Multivolume.rar in the source folder."""
        volumes = []
        for part in (1, 2, 3):
            volume = os.path.join(self.source, 'Set.part%d.rar' % part)
            shutil.copy(get_testfile_path(
                'archives', 'Multivolume.part%d.rar' % part), volume)
            volumes.append(volume)
        return volumes

    def test_a_rar_set_moves_whole(self):
        """Its first volume is the book; the rest, left behind, were
        listed nowhere, and the book that moved was cut short."""
        volumes = self._volume_set()
        moved = file_mover.move_book(volumes[0], self.target)
        self.assertEqual(os.path.join(self.target, 'Set.part1.rar'), moved)
        self.assertEqual(['Set.part1.rar', 'Set.part2.rar', 'Set.part3.rar'],
                         sorted(os.listdir(self.target)))
        self.assertEqual(['book.cbz'], os.listdir(self.source))

    def test_a_rar_set_with_a_volume_s_name_taken_does_not_move(self):
        volumes = self._volume_set()
        with open(os.path.join(self.target, 'Set.part3.rar'), 'wb') as taken:
            taken.write(b'something else')
        with unittest.mock.patch.object(
                file_mover, 'move_file', wraps=file_mover.move_file) as moving, \
                self.assertRaises(FileExistsError):
            file_mover.move_book(volumes[0], self.target)
        moving.assert_not_called()
        self.assertTrue(all(os.path.isfile(volume) for volume in volumes))
        self.assertEqual(['Set.part3.rar'], os.listdir(self.target))

    def test_a_rar_set_that_would_not_fit_does_not_move(self):
        volumes = self._volume_set()
        # Room for each volume, not for all of them.
        free = max(os.path.getsize(volume) for volume in volumes)
        with unittest.mock.patch.object(file_mover, 'same_file_system',
                                        return_value=False), \
                unittest.mock.patch('shutil.disk_usage',
                                    return_value=types.SimpleNamespace(free=free)):
            with self.assertRaises(OSError) as raised:
                file_mover.move_book(volumes[0], self.target)
        self.assertEqual(raised.exception.errno, errno.ENOSPC)
        self.assertTrue(all(os.path.isfile(volume) for volume in volumes))
        self.assertEqual([], os.listdir(self.target))

    def test_a_volume_that_fails_takes_the_ones_moved_back(self):
        volumes = self._volume_set()
        move_file = file_mover.move_file

        def failing(path, directory):
            if path == volumes[2]:
                raise OSError(errno.EIO, os.strerror(errno.EIO), path)
            return move_file(path, directory)

        with unittest.mock.patch.object(file_mover, 'move_file', failing), \
                self.assertRaises(OSError):
            file_mover.move_book(volumes[0], self.target)
        self.assertTrue(all(os.path.isfile(volume) for volume in volumes))
        self.assertEqual([], os.listdir(self.target))

    def test_a_book_in_one_file_moves_as_before(self):
        self.assertEqual(os.path.join(self.target, 'book.cbz'),
                         file_mover.move_book(self.book, self.target))

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
