""" Tests for the freedesktop.org thumbnail store. """

import os
from urllib.request import pathname2url

import PIL.Image
import PIL.PngImagePlugin

from . import MComixTest, get_testfile_path

from mcomix import portability
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

    def _write_thumbnail(self, size=(128, 96), source=None, **text):
        """Put a thumbnail for <source> in the store, of <size> and
        carrying the tEXt chunks named in <text>."""
        source = source or self._source
        path = self._thumbnailer._path_to_thumbpath(source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        info = PIL.PngImagePlugin.PngInfo()
        for key, value in text.items():
            info.add_text(key.replace('__', '::'), value)
        PIL.Image.new('RGB', size).save(path, 'PNG', pnginfo=info)
        return path

    def _small_source(self, size=(90, 110)):
        """An image smaller than the thumbnail size in both directions,
        with a thumbnail of it already in the store."""
        source = os.path.join(self.tmp_dir, 'small.png')
        PIL.Image.new('RGB', size).save(source)
        self._write_thumbnail(
            size=size, source=source,
            Thumb__MTime=str(int(os.stat(source).st_mtime)),
            Thumb__Image__Width=str(size[0]),
            Thumb__Image__Height=str(size[1]))
        return source

    def test_a_thumbnail_of_the_same_age_is_reused(self):
        mtime = str(int(os.stat(self._source).st_mtime))
        self._write_thumbnail(Thumb__MTime=mtime)
        self.assertIsNotNone(
            self._thumbnailer._stored_thumbnail(self._source))

    def test_a_thumbnail_of_another_age_is_not_reused(self):
        self._write_thumbnail(Thumb__MTime='1')
        self.assertIsNone(
            self._thumbnailer._stored_thumbnail(self._source))

    def test_a_thumbnail_that_names_no_time_is_not_reused(self):
        # It used to raise KeyError out of thumbnail(), which is reached
        # for every cover the library draws.
        self._write_thumbnail(Software='something else')
        self.assertIsNone(
            self._thumbnailer._stored_thumbnail(self._source))

    def test_a_thumbnail_whose_time_is_not_a_number_is_not_reused(self):
        self._write_thumbnail(Thumb__MTime='the day before yesterday')
        self.assertIsNone(
            self._thumbnailer._stored_thumbnail(self._source))

    def test_a_thumbnail_of_a_picture_smaller_than_the_box_is_reused(self):
        """Nothing is scaled up, so a cover smaller than the thumbnail size
        is stored at its own size.  Comparing that against the box made
        every such thumbnail look stale, and one was written again on every
        single look - a cache that only cost writes."""
        source = self._small_source()
        self.assertIsNotNone(self._thumbnailer._stored_thumbnail(source))

    def test_a_thumbnail_made_for_another_size_is_not_reused(self):
        source = self._small_source()
        self._thumbnailer.width = self._thumbnailer.height = 64
        self.assertIsNone(self._thumbnailer._stored_thumbnail(source),
                          'a thumbnail larger than the box was reused')

    def test_a_small_thumbnail_that_names_no_dimensions_is_not_reused(self):
        """Without them there is no telling a picture that was smaller than
        the box from a thumbnail made for a smaller box."""
        source = os.path.join(self.tmp_dir, 'small.png')
        PIL.Image.new('RGB', (90, 110)).save(source)
        self._write_thumbnail(
            size=(90, 110), source=source,
            Thumb__MTime=str(int(os.stat(source).st_mtime)))
        self.assertIsNone(self._thumbnailer._stored_thumbnail(source))

    def test_a_thumbnail_of_a_source_that_is_gone_is_kept(self):
        """It is the only thing left that describes the file."""
        source = self._small_source()
        os.remove(source)
        self.assertIsNotNone(self._thumbnailer._stored_thumbnail(source))

    def test_the_thumbnail_that_comes_back_is_the_one_on_disk(self):
        """It is decoded out of the file the checks were made on, so the
        picture and the checks have to agree about which file that was."""
        mtime = str(int(os.stat(self._source).st_mtime))
        self._write_thumbnail(size=(128, 96), Thumb__MTime=mtime)
        pixbuf = self._thumbnailer._stored_thumbnail(self._source)
        self.assertIsNotNone(pixbuf)
        self.assertEqual((128, 96),
                         (pixbuf.get_width(), pixbuf.get_height()))

    def test_a_thumbnail_that_cannot_be_decoded_is_made_again(self):
        """Its header is whole, so every check passes and the decode is
        what fails.  gdk-pixbuf, which used to do the decoding, hands back
        as much of a half-written PNG as it managed to read, so the
        library drew a cover that was part grey and kept drawing it until
        the source file changed."""
        mtime = str(int(os.stat(self._source).st_mtime))
        path = self._write_thumbnail(Thumb__MTime=mtime)
        with open(path, 'rb') as fp:
            whole = fp.read()
        with open(path, 'wb') as fp:
            fp.write(whole[:len(whole) // 2])
        self.assertIsNone(self._thumbnailer._stored_thumbnail(self._source))
        self.assertIsNotNone(self._thumbnailer.thumbnail(self._source),
                             'no new thumbnail was made for the broken one')

    def test_the_name_does_not_depend_on_the_machine_s_encoding(self):
        """The store is shared, so the name has to be the one every other
        application works out.  pathname2url() percent-encodes anything
        outside ASCII, which is what makes the encoding immaterial - this
        asserts that rather than assuming it."""
        source = os.path.join(self.tmp_dir, 'w\u00e4hle.png')
        uri = self._thumbnailer._path_to_thumbpath(source)
        self.assertTrue(
            os.path.basename(uri).removesuffix('.png').isascii())
        self.assertTrue(
            (portability.uri_prefix() + pathname2url(source)).isascii(),
            'the URI carried a character the hash would have to encode')

# vim: expandtab:sw=4:ts=4
