""" Tests for the freedesktop.org thumbnail store. """

import os
import shutil
import unittest.mock
import zipfile
from hashlib import md5

import PIL.Image
import PIL.PngImagePlugin
from gi.repository import Gio

from . import MComixTest, get_testfile_path, wait_for

from mcomix import image_tools
from mcomix.archive import password as archive_password
from mcomix import thumbnail_tools
from mcomix.preferences import prefs


class ThumbnailFailureTest(MComixTest):

    """A file named like a picture that will not decode as one.

    Whether a file is a picture is decided by its name, so a damaged
    page goes all the way to the decoder before anything finds out.
    """

    def setUp(self):
        super().setUp()
        self._thumbnailer = thumbnail_tools.Thumbnailer(store_on_disk=False,
                                                        size=(128, 128))
        self._source = os.path.join(self.tmp_dir, 'damaged.png')
        with open(self._source, 'wb') as damaged:
            damaged.write(b'not a picture at all')

    def test_a_thumbnail_that_cannot_be_made_is_none(self):
        """What thumbnail() says it answers when creation fails; the
        archive editor and the library both test for None."""
        self.assertIsNone(self._thumbnailer.thumbnail(self._source))

    def test_a_threaded_one_still_says_it_has_finished(self):
        """The file chooser's preview waits on thumbnail_finished, and
        the thread used to die before sending it, leaving the preview
        showing the picture selected before."""
        finished = []
        self._thumbnailer.thumbnail_finished += \
            lambda path, pixbuf: finished.append((path, pixbuf))
        self.assertIsNone(self._thumbnailer.thumbnail(self._source,
                                                      threaded=True))
        self.assertTrue(wait_for(lambda: finished, seconds=10),
                        'the thread never said it had finished')
        self.assertEqual(finished, [(self._source, None)])


class ThumbnailNameTest(MComixTest):

    """The name a thumbnail is stored under.

    The freedesktop specification names it after a hash of the file's
    URI, which every application works out the same way; a file has one
    thumbnail whatever path a caller happens to hold it by."""

    def setUp(self):
        super().setUp()
        self._thumbnailer = thumbnail_tools.Thumbnailer(
            dst_dir=os.path.join(self.tmp_dir, 'thumbnails'), size=(128, 128))

    def test_a_relative_path_names_the_same_thumbnail_as_an_absolute_one(self):
        """A relative path made a URI of its own, so the same file was
        thumbnailed again under a name nothing else would look for."""
        absolute = get_testfile_path('images', 'red.png')
        directory, name = os.path.split(absolute)
        saved = os.getcwd()
        os.chdir(directory)
        try:
            self.assertEqual(self._thumbnailer._path_to_thumbpath(absolute),
                             self._thumbnailer._path_to_thumbpath(name))
            self.assertEqual(
                self._thumbnailer._path_to_thumbpath(absolute),
                self._thumbnailer._path_to_thumbpath(
                    os.path.join('.', name)))
        finally:
            os.chdir(saved)

    def test_the_name_is_the_one_every_other_program_works_out(self):
        """The URI was built by urllib's pathname2url(), which escapes
        the brackets, commas and plus signs GLib - and so GNOME's and
        KDE's thumbnailers - leave as they are, and from Python 3.14 on
        gives an absolute path an empty authority of its own, so that
        every URI began "file://///".  No thumbnail MComix stored was
        found by anything else, nor one anything else stored by
        MComix."""
        for name in ('Batman (2016) #1.cbz', 'w\u00e4hle, 1+1=2.png'):
            source = os.path.join(self.tmp_dir, name)
            uri = Gio.File.new_for_path(source).get_uri()
            self.assertEqual(
                md5(uri.encode('utf-8')).hexdigest() + '.png',
                os.path.basename(self._thumbnailer._path_to_thumbpath(source)))

    def test_the_uri_stored_with_it_is_the_file_s(self):
        source = os.path.join(self.tmp_dir, 'red (1).png')
        shutil.copy(get_testfile_path('images', 'red.png'), source)
        thumbnailer = thumbnail_tools.Thumbnailer(
            dst_dir=self._thumbnailer.dst_dir, store_on_disk=True,
            size=(128, 128))
        thumbnailer.thumbnail(source)
        with PIL.Image.open(thumbnailer._path_to_thumbpath(source)) as stored:
            self.assertEqual(Gio.File.new_for_path(source).get_uri(),
                             stored.info['Thumb::URI'])


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

    def test_a_thumbnail_is_written_under_another_name_and_moved_in(self):
        """The store is read by every program on the desktop while
        MComix writes to it, so the specification asks for a thumbnail
        to be written to a temporary file in the same directory and
        renamed into place; it was written in place, where another
        reader could meet half of it, and made private only afterwards."""
        from gi.repository import GdkPixbuf
        savev = GdkPixbuf.Pixbuf.savev
        written = []

        def save(pixbuf, path, *args):
            written.append((path, oct(os.stat(path).st_mode & 0o777)
                            if os.path.exists(path) else None))
            return savev(pixbuf, path, *args)

        with unittest.mock.patch.object(GdkPixbuf.Pixbuf, 'savev', save):
            self._thumbnailer.thumbnail(self._source)
        final = self._thumbnailer._path_to_thumbpath(self._source)
        self.assertEqual(1, len(written))
        path, mode = written[0]
        self.assertNotEqual(final, path, 'it was written in place')
        self.assertEqual(os.path.dirname(final), os.path.dirname(path))
        self.assertEqual('0o600', mode,
                         'what was being written could be read by others')
        self.assertFalse(os.path.exists(path), 'the temporary file stayed')
        self.assertEqual(0o600, os.stat(final).st_mode & 0o777)

    def test_a_thumbnail_that_cannot_be_stored_is_still_made(self):
        """A store that refuses the file - full, or read-only - costs
        the next start the work again, and nothing else: the thumbnail
        is shown, and the half-written file does not stay behind."""
        refused = OSError(28, 'No space left on device')
        with unittest.mock.patch.object(thumbnail_tools.os, 'replace',
                                        side_effect=refused):
            pixbuf = self._thumbnailer.thumbnail(self._source)
        self.assertIsNotNone(pixbuf)
        final = self._thumbnailer._path_to_thumbpath(self._source)
        self.assertEqual([], os.listdir(os.path.dirname(final)))

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
        application works out.  _file_uri() percent-encodes anything
        outside ASCII, which is what makes the encoding immaterial - this
        asserts that rather than assuming it."""
        source = os.path.join(self.tmp_dir, 'w\u00e4hle.png')
        uri = self._thumbnailer._path_to_thumbpath(source)
        self.assertTrue(
            os.path.basename(uri).removesuffix('.png').isascii())
        self.assertTrue(
            thumbnail_tools._file_uri(source).isascii(),
            'the URI carried a character the hash would have to encode')

# vim: expandtab:sw=4:ts=4


class ArchiveCoverOrientationTest(MComixTest):

    """The thumbnail of an archive is of its cover, and is turned the
    way that picture is shown - the Exif orientation of a file inside
    the archive, which nothing can read off the archive's path.

    The picture is 210 pixels wide and 297 high, and its Exif data turns
    it a quarter, so it is shown wider than it is high.
    """

    def setUp(self):
        super().setUp()
        self._archive = os.path.join(self.tmp_dir, 'turned.cbz')
        with zipfile.ZipFile(self._archive, 'w') as archive:
            archive.write(get_testfile_path(
                'images', 'landscape-exif-270-rotation.jpg'), '01.jpg')
        self._store = os.path.join(self.tmp_dir, 'thumbnails')

    def _shown(self):
        thumbnailer = thumbnail_tools.Thumbnailer(
            dst_dir=self._store, store_on_disk=True, archive_support=True,
            size=(128, 128))
        pixbuf = thumbnailer.thumbnail(self._archive)
        self.assertIsNotNone(pixbuf)
        return image_tools.turned_as_shown(pixbuf, self._archive)

    def test_a_new_thumbnail_is_turned_as_its_cover_is(self):
        prefs['auto rotate from exif'] = True
        shown = self._shown()
        self.assertGreater(shown.get_width(), shown.get_height())

    def test_one_from_the_store_is_turned_as_well(self):
        """What is stored is upright, as other programs reading the
        store expect; what the cover's orientation was is stored with
        it."""
        prefs['auto rotate from exif'] = True
        self._shown()
        with PIL.Image.open(thumbnail_tools.Thumbnailer(
                dst_dir=self._store)._path_to_thumbpath(self._archive)) as stored:
            self.assertGreater(stored.size[0], stored.size[1])
        shown = self._shown()
        self.assertGreater(shown.get_width(), shown.get_height())

    def test_one_from_the_store_is_turned_back_where_exif_is_not_followed(self):
        prefs['auto rotate from exif'] = True
        self._shown()
        prefs['auto rotate from exif'] = False
        shown = self._shown()
        self.assertLess(shown.get_width(), shown.get_height())

    def test_it_is_left_as_it_is_where_exif_is_not_followed(self):
        prefs['auto rotate from exif'] = False
        shown = self._shown()
        self.assertLess(shown.get_width(), shown.get_height())

    def test_the_store_is_told_it_is_the_archive_s(self):
        """The URI, size and type written with it were those of the
        cover, extracted to a temporary file, so other programs, which
        check the URI, took it for a thumbnail of that file."""
        self._shown()
        with PIL.Image.open(thumbnail_tools.Thumbnailer(
                dst_dir=self._store)._path_to_thumbpath(self._archive)) as stored:
            self.assertEqual(Gio.File.new_for_path(self._archive).get_uri(),
                             stored.info['Thumb::URI'])
            self.assertEqual(str(os.stat(self._archive).st_size),
                             stored.info['Thumb::Size'])
            self.assertEqual('application/vnd.comicbook+zip',
                             stored.info['Thumb::Mimetype'])
            self.assertEqual(('210', '297'),
                             (stored.info['Thumb::Image::Width'],
                              stored.info['Thumb::Image::Height']))

    def test_a_stored_cover_that_says_nothing_of_it_is_made_again(self):
        """A store only MComix writes to - the library's covers - holds
        thumbnails made before the orientation was kept; they are made
        again, or those covers would stay unturned for good."""
        prefs['auto rotate from exif'] = True
        self._shown()
        path = thumbnail_tools.Thumbnailer(
            dst_dir=self._store)._path_to_thumbpath(self._archive)
        with PIL.Image.open(path) as stored:
            info = PIL.PngImagePlugin.PngInfo()
            for key, value in stored.info.items():
                if isinstance(value, str) and 'MComix::' not in key:
                    info.add_text(key, value)
            stored.load()
            stored.save(path, 'PNG', pnginfo=info)
        thumbnailer = thumbnail_tools.Thumbnailer(
            dst_dir=self._store, store_on_disk=True, archive_support=True,
            size=(128, 128), cover_orientation_required=True)
        shown = image_tools.turned_as_shown(
            thumbnailer.thumbnail(self._archive), self._archive)
        self.assertGreater(shown.get_width(), shown.get_height())
        with PIL.Image.open(path) as stored:
            self.assertIn('X-MComix::Orientation', stored.info)


class EncryptedArchiveThumbnailTest(MComixTest):

    """A thumbnail of an encrypted archive is made without asking for
    its password, and shows a lock.

    The library draws a cover for every book it holds, again whenever
    it draws them, and the file chooser previews whatever is selected:
    each of those asked for the password of an encrypted book, one
    dialog after another.
    """

    def setUp(self):
        super().setUp()
        self.asked = []

        def ask(archive, on_password):
            self.asked.append(archive)
            on_password(None)

        patcher = unittest.mock.patch.object(
            archive_password, 'ask_for_password', ask)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _thumbnail(self, name, size=128):
        return thumbnail_tools.Thumbnailer(
            dst_dir=os.path.join(self.tmp_dir, 'thumbnails'),
            store_on_disk=True, archive_support=True,
            size=(size, size)).thumbnail(get_testfile_path('archives', name))

    def test_no_password_is_asked_for(self):
        for name in ('Encrypted.zip', 'Encrypted.rar', 'Encrypted.7z',
                     'EncryptedHeader.rar', 'EncryptedHeader.7z'):
            with self.subTest(name):
                self._thumbnail(name)
        self.assertEqual([], self.asked)

    def test_the_thumbnail_is_a_lock(self):
        for name in ('Encrypted.zip', 'Encrypted.rar', 'Encrypted.7z'):
            with self.subTest(name):
                self.assertIs(image_tools.locked_image_icon(128),
                              self._thumbnail(name))

    def test_the_lock_is_drawn_at_the_size_of_the_thumbnail(self):
        """It was drawn at 64 pixels whatever the size, and the library,
        whose covers are made at 500, scaled it up into a blur."""
        lock = self._thumbnail('Encrypted.zip', size=500)
        self.assertEqual((500, 500), (lock.get_width(), lock.get_height()))

    def test_the_lock_is_not_stored(self):
        """It stands for a thumbnail that could not be made; the store
        is for thumbnails."""
        self._thumbnail('Encrypted.zip')
        self.assertFalse(os.path.exists(os.path.join(self.tmp_dir,
                                                     'thumbnails')))


class ForeignThumbnailOrientationTest(MComixTest):

    """A thumbnail another program put in the shared store is not turned
    again.

    GNOME's and KDE's thumbnailers store a picture turned upright by its
    Exif orientation already; MComix stores it as it is in the file, and
    turns it when it draws it.  Turning one of theirs by the picture's
    Exif turned it past upright.
    """

    def setUp(self):
        super().setUp()
        prefs['auto rotate from exif'] = True
        self._store = os.path.join(self.tmp_dir, 'thumbnails')
        self._source = os.path.join(self.tmp_dir, 'turned.jpg')
        # 210 wide and 297 high in the file, shown the other way round.
        shutil.copy(get_testfile_path(
            'images', 'landscape-exif-270-rotation.jpg'), self._source)
        self._thumbnailer = thumbnail_tools.Thumbnailer(
            dst_dir=self._store, store_on_disk=True, size=(128, 128))

    def _stored(self, software, size=(128, 91)):
        """Put a thumbnail of the source of <size> in the store, as
        <software> writes one; upright unless <size> says otherwise."""
        path = self._thumbnailer._path_to_thumbpath(self._source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        info = PIL.PngImagePlugin.PngInfo()
        info.add_text('Thumb::MTime', str(int(os.stat(self._source).st_mtime)))
        info.add_text('Software', software)
        PIL.Image.new('RGB', size).save(path, 'PNG', pnginfo=info)

    def _shown(self):
        pixbuf = self._thumbnailer.thumbnail(self._source)
        return image_tools.turned_as_shown(pixbuf, self._source)

    def test_one_another_program_wrote_is_left_as_it_is(self):
        self._stored('GNOME::ThumbnailFactory')
        shown = self._shown()
        self.assertEqual((128, 91), (shown.get_width(), shown.get_height()))

    def test_one_an_older_mcomix_wrote_is_turned(self):
        """An older MComix stored the picture as it is in the file."""
        self._stored('MComix 3.1.0', size=(91, 128))
        shown = self._shown()
        self.assertEqual((128, 91), (shown.get_width(), shown.get_height()))

    def test_mcomix_stores_its_own_upright(self):
        """As GNOME's and KDE's thumbnailers do, and as a file manager
        reading the store shows them: stored as the picture is in the
        file, a turned photograph lay on its side there."""
        path = self._thumbnailer._path_to_thumbpath(self._source)
        self._shown()
        with PIL.Image.open(path) as stored:
            self.assertGreater(stored.size[0], stored.size[1])
        shown = self._shown()
        self.assertGreater(shown.get_width(), shown.get_height())

    def test_an_upright_one_is_turned_back_where_exif_is_not_followed(self):
        self._stored('GNOME::ThumbnailFactory')
        prefs['auto rotate from exif'] = False
        shown = self._shown()
        self.assertEqual((91, 128), (shown.get_width(), shown.get_height()))

    def test_a_small_turned_picture_s_thumbnail_is_reused(self):
        """A picture smaller than the box is stored at its own size, and
        stored upright a quarter-turned one is that size the other way
        round; compared with its size as in the file, the thumbnail
        looked stale and was made again on every look."""
        small = os.path.join(self.tmp_dir, 'small.jpg')
        exif = PIL.Image.Exif()
        exif[274] = 6
        PIL.Image.new('RGB', (60, 90)).save(small, exif=exif)
        self._thumbnailer.thumbnail(small)
        with unittest.mock.patch.object(
                self._thumbnailer, '_create_thumbnail',
                wraps=self._thumbnailer._create_thumbnail) as made:
            pixbuf = self._thumbnailer.thumbnail(small)
        self.assertFalse(made.called, 'the stored thumbnail was not reused')
        self.assertEqual((90, 60), (pixbuf.get_width(), pixbuf.get_height()))
