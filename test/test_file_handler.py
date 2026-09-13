# -*- coding: utf-8 -*-

""" Walking from one directory to the next, and back again. """

import os
import shutil

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main


class DirectoryWalkTest(MComixTest):

    """ The next/previous directory commands, over directories that hold
    an archive, images, or nothing worth opening. """

    def setUp(self):
        super(DirectoryWalkTest, self).setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        self.root = os.path.join(self.tmp_dir, 'books')
        for name in ('a', 'b', 'c'):
            os.makedirs(os.path.join(self.root, name))
        icons.load_icons()
        self.window = main.MainWindow()
        main.set_main_window(self.window)
        self.handler = self.window.filehandler
        pump()

    def tearDown(self):
        # Only terminate_program() stops the worker threads, and a GTK4
        # toplevel that is never destroyed goes on taking part in the
        # display's layout.
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super(DirectoryWalkTest, self).tearDown()

    def _put_archive(self, directory):
        """ Copies the test archive into <directory>, and returns its path. """
        path = os.path.join(self.root, directory, '01-ZIP-Normal.zip')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'), path)
        return path

    def _put_image(self, directory):
        """ Copies a test image into <directory>, and returns its path. """
        path = os.path.join(self.root, directory, '01-JPG-Indexed.jpg')
        shutil.copy(get_testfile_path('images', '01-JPG-Indexed.jpg'), path)
        return path

    def _open(self, path):
        self.handler.open_file(path)
        self.assertTrue(wait_for(lambda: self.handler.file_loaded and
                                 self.window.imagehandler.get_number_of_pages() > 0),
                        "'%s' never finished opening" % path)

    def _opened_file(self):
        """ The file the handler currently has open. """
        pump()
        wait_for(lambda: not self.handler.file_loading, seconds=3)
        return self.handler._current_file

    def test_walking_back_out_of_an_empty_directory_reopens_the_archive(self):
        """ A directory with nothing to open leaves no archive open, and
        the walk used to take that to mean it was looking for images from
        then on - so coming back found none of the archives it left. """
        archive = self._put_archive('a')
        self._open(archive)
        self.handler.open_next_directory()
        self.assertEqual(os.path.join(self.root, 'b'), self._opened_file())
        self.handler.open_previous_directory()
        self.assertEqual(archive, self._opened_file())

    def test_walking_on_past_an_empty_directory_finds_the_next_archive(self):
        archive = self._put_archive('a')
        last = self._put_archive('c')
        self._open(archive)
        self.handler.open_next_directory()
        self.handler.open_next_directory()
        self.assertEqual(last, self._opened_file())

    def test_walking_on_past_an_empty_directory_finds_the_next_images(self):
        image = self._put_image('a')
        last = self._put_image('c')
        self._open(image)
        self.handler.open_next_directory()
        self.handler.open_next_directory()
        self.assertEqual(last, self._opened_file())

    def test_opening_a_directory_of_images_leaves_the_archives_behind(self):
        """ Opening a directory by hand, rather than walking into it,
        starts a walk over the images in it. """
        self._open(self._put_archive('a'))
        self._put_image('b')
        image = self._put_image('c')
        self._open(os.path.join(self.root, 'b'))
        self.handler.open_next_directory()
        self.assertEqual(image, self._opened_file())
