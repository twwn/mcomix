"""thumbnail_tools.py - The thumbnails of pages, books and archives.

Most of the freedesktop.org thumbnail specification: a thumbnail is a
PNG named after a hash of the source file's URI, kept in the "normal"
directory of the thumbnail cache, with the URI it was made from and
that file's size and modification time written into its tEXt chunks, so
that one left behind by an edited file can be told from a current one.

A Thumbnailer can be pointed at a directory of its own instead, which is
what the library does for its covers, and can be told to make a
thumbnail without storing it at all.
"""

import os
import re
import shutil
import tempfile
import threading
import PIL.Image as Image
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING
from hashlib import md5
from gi.repository import Gio, GLib

from mcomix.preferences import prefs
from mcomix import constants
from mcomix import archive_tools
from mcomix import tools
from mcomix import image_tools
from mcomix.archive import password as archive_password
from mcomix import callback
from mcomix import log
from mcomix.i18n import _

if TYPE_CHECKING:
    from gi.repository import GdkPixbuf


#: The tEXt key the Exif orientation of an archive's cover is stored
#: under, beside the thumbnail made of it.  Not one of the spec's own
#: Thumb:: keys, which other programs read.
_ORIENTATION_KEY = 'tEXt::X-MComix::Orientation'


#: The tEXt key that says a thumbnail MComix stored is upright - turned
#: by its picture's Exif orientation - which one an older MComix stored
#: is not.
_UPRIGHT_KEY = 'tEXt::X-MComix::Upright'


def _upright(pixbuf: "GdkPixbuf.Pixbuf") -> "GdkPixbuf.Pixbuf":
    """<pixbuf>, just loaded, turned by the Exif orientation the loader
    found, as GNOME's and KDE's thumbnailers store a thumbnail and as
    every program reading the shared store expects one.  The orientation
    stays with it, which is what turns it back where MComix is told not
    to follow Exif; and it is marked upright."""
    orientation = _orientation_of(pixbuf)
    turned = image_tools.rotate_pixbuf(
        pixbuf, image_tools.get_implied_rotation(pixbuf))
    if orientation is not None:
        setattr(turned, 'orientation', orientation)
    setattr(turned, image_tools.UPRIGHT, True)
    return turned


def _orientation_of(pixbuf: "GdkPixbuf.Pixbuf") -> str | None:
    """The Exif orientation the loader found for <pixbuf>, if any."""
    orientation = getattr(pixbuf, 'orientation', None) \
        or pixbuf.get_option('orientation')
    return str(orientation) if orientation is not None else None


def _file_uri(filepath: str) -> str:
    """The URI of the file at <filepath>.

    Absolute, whatever the caller held the file by: the specification
    names a thumbnail after the URI, so a relative path would file the
    same page under a name no other application - and no other working
    directory - would look for.  GLib's, because the name has to be
    the one GNOME's and KDE's thumbnailers work out: urllib's
    pathname2url() escapes brackets, commas and plus signs they leave
    alone, and from Python 3.14 on begins an absolute path with "///".
    """
    return GLib.filename_to_uri(
        os.path.abspath(os.path.normpath(filepath)), None)


class Thumbnailer:
    """ The Thumbnailer class is responsible for managing MComix
    internal thumbnail creation. Depending on its settings,
    it either stores thumbnails on disk and retrieves them later,
    or simply creates new thumbnails each time it is called. """

    def __init__(self, dst_dir: str = constants.THUMBNAIL_PATH,
                 store_on_disk: bool | None = None,
                 size: tuple[int, int] | None = None,
                 force_recreation: bool = False,
                 archive_support: bool = False,
                 cover_orientation_required: bool = False) -> None:
        """
        <dst_dir> set the thumbnailer's storage directory.

        If <store_on_disk> on disk is True, it changes the thumbnailer's
        behaviour to store files on disk, or just create new thumbnails each
        time it was called when set to False. Defaults to the 'create
        thumbnails' preference if not set.

        The dimensions for the created thumbnails is set by <size>, a (width,
        height) tupple. Defaults to the 'thumbnail size' preference if not set.

        If <force_recreation> is True, thumbnails stored on disk
        will always be re-created instead of being re-used.

        If <archive_support> is True, support for archive thumbnail creation
        (based on cover detection) is enabled. Otherwise, only image files are
        supported.

        If <cover_orientation_required> is True, the stored thumbnail of
        an archive is made again where it does not say how its cover was
        turned: a store only MComix writes to, such as the library's,
        then comes to say so for every cover.
        """
        self.dst_dir = dst_dir
        if store_on_disk is None:
            self.store_on_disk = prefs['create thumbnails']
        else:
            self.store_on_disk = store_on_disk
        if size is None:
            self.width = self.height = prefs['thumbnail size']
            self.default_sizes = True
        else:
            self.width, self.height = size
            self.default_sizes = False
        self.force_recreation = force_recreation
        self.archive_support = archive_support
        self.cover_orientation_required = cover_orientation_required

    def thumbnail(self, filepath: str, threaded: bool = False) -> "GdkPixbuf.Pixbuf | None":
        """ Returns a thumbnail pixbuf for <filepath>, transparently handling
        both normal image files and archives. If a thumbnail file already exists,
        it is re-used. Otherwise, a new thumbnail is created from <filepath>.

        Returns None if thumbnail creation failed, or if the thumbnail creation
        is run asynchrounosly. """

        # Update width and height from preferences if they haven't been set explicitly
        if self.default_sizes:
            self.width = prefs['thumbnail size']
            self.height = prefs['thumbnail size']

        pixbuf = self._stored_thumbnail(filepath)
        if pixbuf is not None:
            self.thumbnail_finished(filepath, pixbuf)
            return pixbuf

        if threaded:
            thread = threading.Thread(target=self._create_thumbnail, args=(filepath,))
            thread.name += '-thumbnailer'
            thread.daemon = True
            thread.start()
            return None
        return self._create_thumbnail(filepath)

    @callback.Callback
    def thumbnail_finished(self, filepath: str,
                           pixbuf: "GdkPixbuf.Pixbuf | None") -> None:
        """ Called every time a thumbnail has been completed.
        <filepath> is the file that was used as source, <pixbuf> is the
        resulting thumbnail. """

        pass

    def delete(self, filepath: str) -> None:
        """ Deletes the thumbnail for <filepath> (if it exists) """
        thumbpath = self._path_to_thumbpath(filepath)
        if os.path.isfile(thumbpath):
            try:
                os.remove(thumbpath)
            except OSError as error:
                log.error(_("! Could not remove file \"%s\""), thumbpath)
                log.error(error)

    def _create_thumbnail_pixbuf(self, filepath: str) \
            -> "tuple[GdkPixbuf.Pixbuf | None, dict[str, str] | None]":
        """ Creates a thumbnail pixbuf from <filepath>, and returns it as a
        tuple along with a file metadata dictionary: (pixbuf, tEXt_data) """

        if self.archive_support:
            mime = archive_tools.archive_mime_type(filepath)
        else:
            mime = None
        if mime is not None:
            cleanup: list[Callable[[], object]] = []
            try:
                tmpdir = tempfile.mkdtemp(prefix='mcomix_archive_thumb.')
                cleanup.append(lambda: shutil.rmtree(tmpdir, True))
                archive = archive_tools.get_recursive_archive_handler(filepath,
                                                                      tmpdir,
                                                                      type=mime)
                if archive is None:
                    return None, None
                cleanup.append(archive.close)
                files = archive.list_contents()
                wanted = self._guess_cover(files)
                if wanted is None:
                    return None, None

                archive.extract(wanted, tmpdir)

                image_path = os.path.join(tmpdir, wanted)
                if not os.path.isfile(image_path):
                    return None, None

                pixbuf = _upright(image_tools.load_pixbuf_size(
                    image_path, self.width, self.height))
                tEXt_data: dict[str, str] | None
                if self.store_on_disk:
                    tEXt_data = self._get_text_data(filepath, image_path)
                    # The cover's Exif orientation is kept beside the
                    # thumbnail, since the cover is not to be had again
                    # without opening the archive, and a thumbnail shown
                    # with 'auto rotate from exif' off is turned back by
                    # it.  1 is Exif's own "as stored", written rather
                    # than left out so that a thumbnail made before this
                    # was kept can be told from one of an upright cover.
                    tEXt_data[_ORIENTATION_KEY] = _orientation_of(pixbuf) or '1'
                else:
                    tEXt_data = None

                return pixbuf, tEXt_data
            finally:
                for fn in reversed(cleanup):
                    fn()

        elif image_tools.is_image_file(filepath):
            pixbuf = _upright(image_tools.load_pixbuf_size(
                filepath, self.width, self.height))
            if self.store_on_disk:
                tEXt_data = self._get_text_data(filepath)
            else:
                tEXt_data = None

            return pixbuf, tEXt_data
        else:
            return None, None

    def _create_thumbnail(self, filepath: str) -> "GdkPixbuf.Pixbuf | None":
        """ Creates the thumbnail pixbuf for <filepath>, and saves the pixbuf
        to disk if necessary. Returns the created pixbuf, or None, if creation failed. """

        # A thumbnail is made on the reader's behalf, not at their
        # asking - the library draws a cover for every book, the file
        # chooser previews whatever is selected - so an encrypted
        # archive is not asked the password of.  It is shown locked.
        with archive_password.never_asked() as withheld:
            try:
                pixbuf, tEXt_data = self._create_thumbnail_pixbuf(filepath)
            except Exception as error:
                # Whether a file is a picture is decided by its name, so a
                # damaged one is only found out here.  That is a thumbnail
                # that failed, which is what None says; raising instead left
                # a threaded caller waiting for a finish that never came.
                log.debug('Could not make a thumbnail of "%s": %s',
                          filepath, error)
                pixbuf, tEXt_data = None, None
        if pixbuf is None and withheld.wanted:
            # Not stored: it is not a thumbnail of the archive.
            pixbuf, tEXt_data = image_tools.locked_image_icon(
                min(self.width, self.height)), None
        self.thumbnail_finished(filepath, pixbuf)

        if pixbuf and self.store_on_disk and tEXt_data is not None:
            thumbpath = self._path_to_thumbpath(filepath)
            self._save_thumbnail(pixbuf, thumbpath, tEXt_data)

        return pixbuf

    def _get_text_data(self, filepath: str,
                       picture: str | None = None) -> dict[str, str]:
        """The tEXt chunks for a thumbnail of <filepath>.

        <picture> is what the thumbnail was made from, where that is not
        <filepath> itself - an archive's cover, extracted - and only its
        dimensions are written.  The URI, the size and the time are the
        archive's: they were the extracted cover's, so that other
        programs, which check the URI, took the thumbnail for one of a
        temporary file and made their own over it.  The type is GIO's
        guess from the name, as theirs is; Python's mimetypes reads the
        system's mime.types files, and one of them calls .cbz a RAR
        comic.
        """
        content_type, _uncertain = Gio.content_type_guess(filepath, None)
        mime = Gio.content_type_get_mime_type(content_type) or 'unknown/mime'
        uri = _file_uri(filepath)
        stat = os.stat(filepath)
        # MTime could be floating point number, so convert to long first to have a fixed point number
        mtime = str(int(stat.st_mtime))
        size = str(stat.st_size)
        width, height = image_tools.get_image_size(picture or filepath)
        return {
            'tEXt::Thumb::URI':           uri,
            'tEXt::Thumb::MTime':         mtime,
            'tEXt::Thumb::Size':          size,
            'tEXt::Thumb::Mimetype':      mime,
            'tEXt::Thumb::Image::Width':  str(width),
            'tEXt::Thumb::Image::Height': str(height),
            'tEXt::Software':             'MComix %s' % constants.VERSION,
            _UPRIGHT_KEY:                 '1',
        }

    def _save_thumbnail(self, pixbuf: "GdkPixbuf.Pixbuf", thumbpath: str,
                        tEXt_data: dict[str, str]) -> None:
        """ Saves <pixbuf> as <thumbpath>, with additional metadata
        from <tEXt_data>. If <thumbpath> already exists, it is overwritten.

        Written to a temporary file in the same directory, private from
        the start, and renamed into place, as the thumbnail specification
        asks: the store is read by every program on the desktop, and one
        of them may look while this is being written.  The directory is
        made without asking first whether it is there, since another
        thread or program may be making it too. """

        temporary = None
        try:
            directory = os.path.dirname(thumbpath)
            os.makedirs(directory, 0o700, exist_ok=True)
            handle, temporary = tempfile.mkstemp(
                dir=directory, prefix=os.path.basename(thumbpath) + '.',
                suffix='.tmp')
            os.close(handle)
            pixbuf.savev(temporary, 'png',
                         list(tEXt_data), list(tEXt_data.values()))
            os.replace(temporary, thumbpath)
            temporary = None

        except Exception as ex:
            log.warning(_('! Could not save thumbnail "%(thumbpath)s": %(error)s'),
                        {'thumbpath': thumbpath, 'error': ex})
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def _stored_thumbnail(self, filepath: str) -> "GdkPixbuf.Pixbuf | None":
        """The thumbnail already on disk for <filepath>, if it can be used.

        None where there is none, where the source has been modified
        since it was made, where it was made for a different thumbnail
        size, where it cannot be decoded, or where <force_recreation>
        asks for a new one regardless.

        The picture is made out of the same PIL image the checks read, so
        that a thumbnail which is going to be used is opened once rather
        than twice.  Loading it a second time through
        image_tools.load_pixbuf() was almost all of what a cover cost:
        0.39ms against the 0.17ms the one open takes.
        """

        if self.force_recreation:
            return None
        thumbpath = self._path_to_thumbpath(filepath)
        if not os.path.isfile(thumbpath):
            return None

        try:
            with Image.open(thumbpath) as img:
                if not (self._source_is_unchanged(filepath, img.info)
                        and self._is_current_size(img.size, img.info)):
                    return None
                orientation = img.info.get(_ORIENTATION_KEY[len('tEXt::'):])
                if (self.cover_orientation_required
                        and not isinstance(orientation, str)
                        and not image_tools.is_image_file(filepath)):
                    # A cover whose orientation nobody wrote down, which
                    # is made again to find it out.
                    return None
                pixbuf = image_tools.pil_to_pixbuf(img, keep_orientation=True)
                if isinstance(orientation, str):
                    setattr(pixbuf, 'orientation', orientation)
                software = img.info.get('Software')
                if (img.info.get(_UPRIGHT_KEY[len('tEXt::'):]) == '1'
                        or not (isinstance(software, str)
                                and software.startswith('MComix'))):
                    # MComix' own are stored upright, as GNOME's and
                    # KDE's thumbnailers store theirs; one an older
                    # MComix stored is as the picture is in the file.
                    setattr(pixbuf, image_tools.UPRIGHT, True)
                return pixbuf
        except OSError:
            # Not an image, not readable, or broken off partway through
            # being written: there is nothing to reuse, and one that
            # cannot be decoded is one to make again rather than one to
            # raise over.
            return None

    def _source_is_unchanged(
            self, filepath: str,
            info: "Mapping[str | tuple[int, int], object]") -> bool:
        """Whether a thumbnail holding <info> still describes <filepath>."""
        # A thumbnail written by something other than MComix need not
        # carry the modification time, and one that does need not have
        # written a number: either way there is nothing to compare
        # against, so the thumbnail is made afresh.
        try:
            stored_mtime = int(float(str(info['Thumb::MTime'])))
        except (KeyError, TypeError, ValueError):
            return False
        if not os.path.isfile(filepath):
            # A source that is no longer there cannot be compared
            # against, and its thumbnail is the only thing left that
            # describes it, so it is kept rather than thrown away.
            return True
        # int, because st_mtime is a float and the stored one is not.
        return stored_mtime == int(os.stat(filepath).st_mtime)

    def _is_current_size(self, stored: tuple[int, int],
                         info: "Mapping[str | tuple[int, int], object]"
                         ) -> bool:
        """Whether a thumbnail of <stored> size was made for this size.

        load_pixbuf_size() scales a picture to fit inside the box and
        never scales it up, so a cover smaller than the box is stored at
        its own size.  Comparing that against the box made every such
        thumbnail look stale and written again on every single look, which
        for a library of small covers is a cache that only costs writes.
        The source's own dimensions are in the tEXt chunks this writes, so
        the size to expect is the box or the source, whichever is smaller.
        """
        if max(stored) == max(self.width, self.height):
            return True
        try:
            source = (int(str(info['Thumb::Image::Width'])),
                      int(str(info['Thumb::Image::Height'])))
        except (KeyError, TypeError, ValueError):
            # Written by something that does not record them, so there is
            # no way to tell a small source from a stale thumbnail.
            return False
        # Stored upright, a small picture turned a quarter by its Exif
        # orientation is its own size the other way round.
        return (stored in (source, source[::-1])
                and max(source) <= max(self.width, self.height))

    def _path_to_thumbpath(self, filepath: str) -> str:
        """Return the path of the thumbnail for <filepath> in <dst_dir>.

        The name is a hash of the file's URI, which is what the
        freedesktop specification asks for, so the URI is built here and
        _uri_to_thumbpath() turns it into the name.
        """
        return self._uri_to_thumbpath(_file_uri(filepath))

    def _uri_to_thumbpath(self, uri: str) -> str:
        """Return the path of the thumbnail for <uri> under <dst_dir>.

        UTF-8 because the specification says so, and because the name has
        to be the one every other application works out for the same file.
        Nothing turns on the choice today - _file_uri() percent-encodes
        anything outside ASCII, so the URI is ASCII whatever the file is
        called - but the encoding the machine happens to prefer is no part
        of the answer.
        """
        md5hash = md5(uri.encode('utf-8')).hexdigest()
        return os.path.join(self.dst_dir, md5hash + '.png')

    def _guess_cover(self, files: Iterable[str]) -> str | None:
        """Return the filename within <files> that is the most likely to be the
        cover of an archive using some simple heuristics.
        """
        # Ignore MacOSX meta files, and credit files if possible.
        named = (filename for filename in files
                 if '__MACOSX' not in os.path.normpath(filename).split(os.sep)
                 and 'credit' not in os.path.split(filename)[1].lower())

        images = [name for name in named if image_tools.is_image_file(name)]

        tools.alphanumeric_sort(images)

        front_re = re.compile('(cover|front)', re.I)
        candidates = list(filter(front_re.search, images))
        candidates = [c for c in candidates if 'back' not in c.lower()]

        if candidates:
            return candidates[0]

        if images:
            return images[0]

        return None

# vim: expandtab:sw=4:ts=4
