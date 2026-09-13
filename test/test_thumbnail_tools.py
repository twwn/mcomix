""" Tests for the freedesktop.org thumbnail store. """

import os

import PIL.Image
import PIL.PngImagePlugin

from . import MComixTest, get_testfile_path

from mcomix import thumbnail_tools


class ThumbnailReuseTest(MComixTest):

    """Whether a thumbnail already on disk can stand in for a new one.

    The store is shared with every other application on the desktop, so
    what is found there was not necessarily written by MComix.
    """

    def setUp(self):
        super().setUp()
        self._store = os.path.join(self.tmp_dir, 'thumbnails')
        self._thumbnailer = thumbnail_tools.Thumbnailer(dst_dir=self._store,
                                                        store_on_disk=True,
                                                        size=(128, 128))
        self._source = get_testfile_path('images', 'red.png')

    def _write_thumbnail(self, **text):
        """Put a thumbnail for the source image in the store, carrying
        the tEXt chunks named in <text>."""
        path = self._thumbnailer._path_to_thumbpath(self._source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        info = PIL.PngImagePlugin.PngInfo()
        for key, value in text.items():
            info.add_text(key.replace('__', '::'), value)
        PIL.Image.new('RGB', (128, 96)).save(path, 'PNG', pnginfo=info)
        return path

    def test_a_thumbnail_of_the_same_age_is_reused(self):
        mtime = str(int(os.stat(self._source).st_mtime))
        self._write_thumbnail(Thumb__MTime=mtime)
        self.assertTrue(self._thumbnailer._thumbnail_exists(self._source))

    def test_a_thumbnail_of_another_age_is_not_reused(self):
        self._write_thumbnail(Thumb__MTime='1')
        self.assertFalse(self._thumbnailer._thumbnail_exists(self._source))

    def test_a_thumbnail_that_names_no_time_is_not_reused(self):
        # It used to raise KeyError out of thumbnail(), which is reached
        # for every cover the library draws.
        self._write_thumbnail(Software='something else')
        self.assertFalse(self._thumbnailer._thumbnail_exists(self._source))

    def test_a_thumbnail_whose_time_is_not_a_number_is_not_reused(self):
        self._write_thumbnail(Thumb__MTime='the day before yesterday')
        self.assertFalse(self._thumbnailer._thumbnail_exists(self._source))

# vim: expandtab:sw=4:ts=4
