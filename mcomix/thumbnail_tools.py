"""thumbnail_tools.py - The thumbnails of pages, books and archives.

Most of the freedesktop.org thumbnail specification: a thumbnail is a
PNG named after a hash of the source file's URI, kept in the directory
of the thumbnail cache for its size ("normal" for 128 pixels, "large"
for 256, and so on), with the URI it was made from and
that file's size and modification time written into its tEXt chunks, so
that one left behind by an edited file can be told from a current one.

A Thumbnailer can be pointed at a directory of its own instead, which is
what the library does for its covers, and can be told to make a
thumbnail without storing it at all.  A directory nothing but MComix
reads can hold WebP instead of PNG, with the same keys in its XMP.

For such a directory of its own it also keeps, for whoever asks, the
thumbnail as it was last drawn: scaled to the size shown, as the bytes
of its pixels, in a directory beside it or one the caller names.  See
Thumbnailer.sized().
"""

import functools
import io
import os
import re
import tempfile
import threading
import PIL.Image as Image
from collections.abc import Callable, Iterable, Mapping, Sequence
from hashlib import md5
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr
from gi.repository import GdkPixbuf, Gio, GLib

from mcomix.preferences import prefs
from mcomix import constants
from mcomix import archive_tools
from mcomix import tools
from mcomix import image_tools
from mcomix import portability
from mcomix.archive import password as archive_password
from mcomix import callback
from mcomix import log
from mcomix.i18n import _


#: The tEXt key the Exif orientation of an archive's cover is stored
#: under, beside the thumbnail made of it.  Not one of the spec's own
#: Thumb:: keys, which other programs read.
_ORIENTATION_KEY = 'tEXt::X-MComix::Orientation'


#: The tEXt key that says a thumbnail MComix stored is upright - turned
#: by its picture's Exif orientation - which one an older MComix stored
#: is not.
_UPRIGHT_KEY = 'tEXt::X-MComix::Upright'

#: The attribute of a thumbnail read from the store, or just written to
#: it, that says which stored file it is: that file's modification time
#: in nanoseconds and its size, and its source's modification time as
#: the file records it.  Thumbnailer.keep_sized() writes them down.
_STORED = 'mcomix_stored_as'

#: The first line of a file Thumbnailer.keep_sized() writes.
_SIZED_MAGIC = b'MComix sized thumbnail 1\n'

#: The folders of the store every program shares, each with the size
#: its thumbnails fit in, as the specification names them.  MComix
#: stored every size in "normal", whose thumbnails are no larger than
#: 128: its file chooser's previews were 256 on a screen of twice the
#: scale, which every other program found there in place of its own.
_SHARED_FOLDERS = ((128, 'normal'), (256, 'large'),
                   (512, 'x-large'), (1024, 'xx-large'))

#: The quality a thumbnail is stored at as WebP.  A cover 500 pixels
#: high takes 44 kB where PNG takes 198, and decodes in 1.9 ms against
#: PNG's 2.2 (the medians of nine covers); what WebP loses is colour at
#: sharp edges, which drawing the cover smaller than that hides.
_WEBP_QUALITY = 90

#: The namespace of the keys a thumbnail stored as WebP carries in its
#: XMP: those a PNG one carries in its tEXt chunks, "Thumb::URI" there
#: written "Thumb.URI" here.  Only MComix reads them.  A name, not a
#: link: nothing is to be found under it.
_XMP_NAMESPACE = 'urn:x-mcomix:thumbnail:1:'

_RDF_NAMESPACE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'


def _xmp_of(tEXt_data: Mapping[str, str]) -> bytes:
    """The XMP that carries <tEXt_data>, the tEXt chunks a PNG
    thumbnail would be written with, in a WebP one."""
    attributes = ''.join(
        ' mcomix:%s=%s' % (key.removeprefix('tEXt::').replace('::', '.'),
                           quoteattr(value))
        for key, value in tEXt_data.items())
    return ('<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            '<rdf:RDF xmlns:rdf="%s">'
            '<rdf:Description rdf:about="" xmlns:mcomix="%s"%s/>'
            '</rdf:RDF></x:xmpmeta>'
            % (_RDF_NAMESPACE, _XMP_NAMESPACE, attributes)).encode('utf-8')


def _info_of_xmp(xmp: object) -> "dict[str | tuple[int, int], object]":
    """The keys _xmp_of() wrote into <xmp>, as PIL reads those of a PNG
    out of its tEXt chunks; none from anything else."""
    if isinstance(xmp, str):
        xmp = xmp.encode('utf-8')
    if not isinstance(xmp, bytes):
        return {}
    try:
        root = ElementTree.fromstring(xmp)
    except ElementTree.ParseError:
        return {}
    ours = '{%s}' % _XMP_NAMESPACE
    return {name[len(ours):].replace('.', '::'): value
            for description in root.iter('{%s}Description' % _RDF_NAMESPACE)
            for name, value in description.attrib.items()
            if name.startswith(ours)}


@functools.cache
def _webp_keeps_xmp() -> bool:
    """Whether Pillow writes WebP here and keeps XMP in it.  A thumbnail
    stored without its keys says nothing of what it was made of, and
    would be made again every time it is looked for."""
    written = io.BytesIO()
    try:
        Image.new('RGB', (1, 1)).save(written, 'WEBP', xmp=b'<x/>')
        with Image.open(io.BytesIO(written.getvalue())) as image:
            return image.info.get('xmp') == b'<x/>'
    except (KeyError, OSError, ValueError):
        return False

#: A file name that says the picture is not the book's cover: "credit"
#: anywhere in it, or "banner" however its letters are spaced out.
_NOT_A_COVER = re.compile(r'credit|' + r'[\W_]*'.join('banner'), re.I)


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

    def __init__(self, dst_dir: str | None = None,
                 store_on_disk: bool | None = None,
                 size: tuple[int, int] | None = None,
                 force_recreation: bool = False,
                 archive_support: bool = False,
                 cover_orientation_required: bool = False,
                 cover: str | None = None,
                 stored_as: str = 'png',
                 larger_is_current: bool = False,
                 sized_dir: str | None = None) -> None:
        """
        <dst_dir> set the thumbnailer's storage directory.  None is the
        store every program shares, in the specification's folder for
        the size: "normal" up to 128 pixels, then "large" (256),
        "x-large" (512) and "xx-large" (1024).  A thumbnail is made and
        stored there at the folder's size, which is what other programs
        look for in it, and answered fitted in <size>.

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

        <cover> names the picture an archive's thumbnail is made of, as
        FileHandler.page_member() names a page, where the reader chose
        one; the archive's cover is guessed where it is None, or names
        a picture the archive no longer holds.

        <stored_as> is what thumbnails are stored as: 'png', which the
        specification asks of the store every program shares, or
        'webp', a fifth of the size, for a store only MComix reads, such
        as the library's.  Such a store reads the PNG thumbnails an
        older MComix stored there, and puts a WebP one in the place of
        each; it stays PNG where Pillow cannot write WebP with XMP.

        If <larger_is_current> is True, a stored thumbnail larger than
        <size> is used as it is, for a caller that scales whatever it
        is given: the library's covers are stored as large as the
        screen they were last drawn on wants them, and one stored for a
        screen of twice the scale is not made again on the next.

        <sized_dir> is where keep_sized() keeps what it is given, which
        is beside <dst_dir> where it is None: the library keeps it in
        the cache, as it is made again wherever it is missing.
        """
        if stored_as == 'webp' and _webp_keeps_xmp():
            self._extensions: tuple[str, ...] = ('.webp', '.png')
        else:
            self._extensions = ('.png',)
        self._dst_dir = dst_dir
        self._sized_dir = sized_dir
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
        self.cover = cover
        self.larger_is_current = larger_is_current

    @property
    def _shared(self) -> bool:
        """Whether this stores in the store every program shares."""
        return self._dst_dir is None

    def _shared_folder(self) -> tuple[int, str]:
        """The size and the name of the shared store's folder for the
        size asked for: the smallest that holds it, else the largest."""
        asked = max(self.width, self.height)
        return next((folder for folder in _SHARED_FOLDERS
                     if asked <= folder[0]), _SHARED_FOLDERS[-1])

    @property
    def dst_dir(self) -> str:
        """The directory thumbnails are stored in."""
        if self._dst_dir is not None:
            return self._dst_dir
        # Beside "normal", wherever that has been put.
        return os.path.join(os.path.dirname(constants.THUMBNAIL_PATH),
                            self._shared_folder()[1])

    @property
    def _stored_box(self) -> int:
        """The size a stored thumbnail fits in."""
        if self._shared:
            return self._shared_folder()[0]
        return max(self.width, self.height)

    def _made_at(self) -> tuple[int, int]:
        """The box a thumbnail is made in: the size it is stored at,
        where it is going to be stored; the size asked for otherwise."""
        if self._shared and self.store_on_disk:
            return self._stored_box, self._stored_box
        return self.width, self.height

    def _as_asked(self, pixbuf: "GdkPixbuf.Pixbuf | None"
                  ) -> "GdkPixbuf.Pixbuf | None":
        """<pixbuf>, made or stored at the size of a folder of the shared
        store, fitted in the size asked for, with what was noted on it:
        the orientation of its picture, and whether it is upright."""
        if (pixbuf is None or not self._shared
                or (pixbuf.get_width() <= self.width
                    and pixbuf.get_height() <= self.height)):
            return pixbuf
        fitted = image_tools.fit_in_rectangle(pixbuf, self.width, self.height)
        for noted in ('orientation', image_tools.UPRIGHT):
            if hasattr(pixbuf, noted):
                setattr(fitted, noted, getattr(pixbuf, noted))
        return fitted

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

        pixbuf = self._as_asked(self._stored_thumbnail(filepath))
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
        """ Deletes the thumbnail for <filepath> (if it exists), and
        what keep_sized() kept of it. """
        for thumbpath in self._stored_paths(filepath):
            if not os.path.isfile(thumbpath):
                continue
            try:
                os.remove(thumbpath)
            except OSError as error:
                log.error(_("! Could not remove file \"%s\""), thumbpath)
                log.error(error)
        # After the thumbnail, never before: keep_sized() looks for the
        # thumbnail once it has written, and takes away what it wrote
        # where this has been.
        try:
            os.remove(self._path_to_sizedpath(filepath))
        except OSError:
            pass

    def follow(self, old_path: str, new_path: str) -> None:
        """Keep the thumbnail stored for <old_path> for <new_path>, where
        the file has been moved to.

        A thumbnail is stored under a name made of its file's path, so
        one left where it was is never looked at again and never
        removed, and the file is thumbnailed a second time where it is
        now - for a book, by opening the archive.  The modification time
        is what tells a stored thumbnail from a stale one, and a move
        keeps it."""
        moved = False
        for stored, new in zip(self._stored_paths(old_path),
                               self._stored_paths(new_path)):
            if not os.path.isfile(stored):
                continue
            try:
                portability.rename_once_closed(os.replace, stored, new)
            except OSError as error:
                log.error(_('! Could not move %(file)s to %(directory)s: %(error)s'),
                          {'file': stored, 'directory': self.dst_dir,
                           'error': error})
                return
            moved = True
        if not moved:
            return
        # What keep_sized() kept goes with it: it says which thumbnail
        # it was made of by that file's time and size, which a move
        # keeps.  One that will not move is made again.
        sized = self._path_to_sizedpath(old_path)
        try:
            portability.rename_once_closed(
                os.replace, sized, self._path_to_sizedpath(new_path))
        except OSError:
            try:
                os.remove(sized)
            except OSError:
                pass

    def sized(self, filepath: str,
              made_for: Sequence[int]) -> "GdkPixbuf.Pixbuf | None":
        """The picture keep_sized() kept for <filepath> and <made_for>,
        or None where there is none to use.

        A stored thumbnail is as large as the largest size it is ever
        shown at, and showing it smaller means decoding all of it and
        scaling it down: 4.7 ms for a library cover of 333x500 pixels
        drawn 83x125, of every cover in view each time the program
        starts.  What was drawn is therefore kept beside the thumbnails,
        not as a picture file but as the bytes of its pixels under a line
        of numbers, which takes a fraction of that to read back.

        It is used while the thumbnail it was made of is the one stored
        - by that file's time and size - while the source has the
        modification time that thumbnail records, or is gone, as a
        stored thumbnail is used, and while <made_for> is what it was
        kept under: the size drawn, and whatever else the caller's
        drawing depends on.
        """
        if self.force_recreation:
            return None
        try:
            with open(self._path_to_sizedpath(filepath), 'rb') as file:
                if file.readline() != _SIZED_MAGIC:
                    return None
                numbers = [int(number) for number in file.readline().split()]
                pixels = file.read()
        except (OSError, ValueError):
            return None
        if len(numbers) < 8 or numbers[8:] != list(made_for):
            return None
        (width, height, rowstride, has_alpha,
         stored_mtime, stored_size, source_mtime, length) = numbers[:8]
        row = width * (4 if has_alpha else 3)
        if (width < 1 or height < 1 or rowstride < row
                or length != len(pixels)
                or length < (height - 1) * rowstride + row):
            # Broken off partway through being written, or not written
            # by keep_sized() at all.
            return None
        if self._stored_identity(filepath) != (stored_mtime, stored_size):
            return None
        try:
            if source_mtime != int(os.stat(filepath).st_mtime):
                return None
        except OSError:
            # A source that is no longer there: see _source_is_unchanged().
            pass
        return GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB,
            bool(has_alpha), 8, width, height, rowstride)

    def keep_sized(self, filepath: str, pixbuf: "GdkPixbuf.Pixbuf",
                   made_for: Sequence[int],
                   made_of: "GdkPixbuf.Pixbuf") -> None:
        """Keep <pixbuf>, which the caller drew from the thumbnail
        <made_of> that thumbnail() answered for <filepath>, for sized()
        to answer with for the same <made_for>.

        Nothing is kept of a thumbnail that is not stored: there is
        nothing to tell what was kept by once the source changes.  Nor
        of one drawn with more than a quarter of the stored one's
        pixels, and whatever was kept for <filepath> before goes: such
        a copy weighs several times the stored picture, and spares
        decoding fewer than four times its own pixels.  A library
        cover 500 pixels high, the Huge size, is 489 kB of them against
        41 kB of WebP that decodes in 1.9 ms; 1000 high, on a screen of
        twice the scale, 2 MB against 127 kB and 6 ms.  Drawn 125 high
        from 500, the default size, they are 31 kB and spare decoding
        and scaling down sixteen times as many.
        """
        stored = getattr(made_of, _STORED, None)
        if stored is None:
            return
        if (4 * pixbuf.get_width() * pixbuf.get_height()
                > made_of.get_width() * made_of.get_height()):
            try:
                os.remove(self._path_to_sizedpath(filepath))
            except OSError:
                pass
            return
        pixels = pixbuf.read_pixel_bytes().get_data()
        numbers = (pixbuf.get_width(), pixbuf.get_height(),
                   pixbuf.get_rowstride(), int(pixbuf.get_has_alpha()),
                   *stored, len(pixels), *made_for)
        path = self._path_to_sizedpath(filepath)
        temporary = None
        try:
            directory = os.path.dirname(path)
            os.makedirs(directory, 0o700, exist_ok=True)
            handle, temporary = tempfile.mkstemp(
                dir=directory, prefix=os.path.basename(path) + '.',
                suffix='.tmp')
            # Not synced to the disk: one cut short by a crash does not
            # have the length it says, and is made again.
            with os.fdopen(handle, 'wb') as file:
                file.write(_SIZED_MAGIC)
                file.write(' '.join(map(str, numbers)).encode('ascii'))
                file.write(b'\n')
                file.write(pixels)
            portability.rename_once_closed(os.replace, temporary, path)
            temporary = None
            if self._stored_identity(filepath) != stored[:2]:
                # The thumbnail went, or another took its place, while
                # this was drawn from it.  delete() removes the thumbnail
                # first, so one of the two always sees the other's work.
                os.remove(path)
        except OSError as error:
            log.debug('Could not keep the thumbnail of "%s" as drawn: %s',
                      filepath, error)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def _stored_identity(self, filepath: str) -> tuple[int, int] | None:
        """The modification time, in nanoseconds, and the size of the
        thumbnail stored for <filepath>, which tell it from the one a
        changed source or another choice of cover puts in its place;
        None where none is stored."""
        for thumbpath in self._stored_paths(filepath):
            try:
                stat = os.stat(thumbpath)
            except OSError:
                continue
            return stat.st_mtime_ns, stat.st_size
        return None

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
                cleanup.append(lambda: tools.remove_tree(tmpdir))
                archive = archive_tools.get_recursive_archive_handler(filepath,
                                                                      tmpdir,
                                                                      type=mime)
                if archive is None:
                    return None, None
                cleanup.append(archive.close)
                files = archive.list_contents()
                wanted = self._chosen_cover(files) or self._guess_cover(files)
                if wanted is None:
                    return None, None

                archive.extract(wanted, tmpdir)

                image_path = os.path.join(tmpdir, wanted)
                if not os.path.isfile(image_path):
                    return None, None

                pixbuf = _upright(image_tools.load_pixbuf_size(
                    image_path, *self._made_at()))
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
                filepath, *self._made_at()))
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
        asked = self._as_asked(pixbuf)
        self.thumbnail_finished(filepath, asked)

        if pixbuf and self.store_on_disk and tEXt_data is not None:
            thumbpath = self._path_to_thumbpath(filepath)
            if self._save_thumbnail(pixbuf, thumbpath, tEXt_data):
                self._remove_older(filepath)

        return asked

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
                        tEXt_data: dict[str, str]) -> bool:
        """ Saves <pixbuf> as <thumbpath>, with additional metadata
        from <tEXt_data>. If <thumbpath> already exists, it is overwritten.
        As WebP where <thumbpath> says so, the metadata in its XMP; and
        whether it was stored.

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
            if thumbpath.endswith('.webp'):
                image_tools.pixbuf_to_pil(pixbuf).save(
                    temporary, 'WEBP', quality=_WEBP_QUALITY, method=4,
                    xmp=_xmp_of(tEXt_data))
            else:
                pixbuf.savev(temporary, 'png',
                             list(tEXt_data), list(tEXt_data.values()))
            # Of the file written here, before it is renamed: another
            # thread or program may put its own in that place right after.
            stat = os.stat(temporary)
            portability.rename_once_closed(os.replace, temporary, thumbpath)
            temporary = None
            setattr(pixbuf, _STORED, (
                stat.st_mtime_ns, stat.st_size,
                int(tEXt_data['tEXt::Thumb::MTime'])))
            return True

        except Exception as ex:
            log.warning(_('! Could not save thumbnail "%(thumbpath)s": %(error)s'),
                        {'thumbpath': thumbpath, 'error': ex})
            return False
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
        for thumbpath in self._stored_paths(filepath):
            if os.path.isfile(thumbpath):
                break
        else:
            return None

        try:
            with open(thumbpath, 'rb') as file, Image.open(file) as img:
                info = (_info_of_xmp(img.info.get('xmp'))
                        if img.format == 'WEBP' else img.info)
                if not (self._source_is_unchanged(filepath, info)
                        and self._is_current_size(img.size, info)):
                    return None
                orientation = info.get(_ORIENTATION_KEY[len('tEXt::'):])
                if (self.cover_orientation_required
                        and not isinstance(orientation, str)
                        and not image_tools.is_image_file(filepath)):
                    # A cover whose orientation nobody wrote down, which
                    # is made again to find it out.
                    return None
                pixbuf = image_tools.pil_to_pixbuf(img, keep_orientation=True)
                if isinstance(orientation, str):
                    setattr(pixbuf, 'orientation', orientation)
                software = info.get('Software')
                if (info.get(_UPRIGHT_KEY[len('tEXt::'):]) == '1'
                        or not (isinstance(software, str)
                                and software.startswith('MComix'))):
                    # MComix' own are stored upright, as GNOME's and
                    # KDE's thumbnailers store theirs; one an older
                    # MComix stored is as the picture is in the file.
                    setattr(pixbuf, image_tools.UPRIGHT, True)
                stat = os.fstat(file.fileno())
                setattr(pixbuf, _STORED, (
                    stat.st_mtime_ns, stat.st_size,
                    int(float(str(info['Thumb::MTime'])))))
        except OSError:
            # Not an image, not readable, or broken off partway through
            # being written: there is nothing to reuse, and one that
            # cannot be decoded is one to make again rather than one to
            # raise over.
            return None
        stored_as = self._path_to_thumbpath(filepath)
        if thumbpath != stored_as and self._save_thumbnail(
                pixbuf, stored_as,
                {'tEXt::' + key: value for key, value in info.items()
                 if isinstance(key, str) and isinstance(value, str)}):
            # A PNG an older MComix stored, in a store that is WebP now,
            # which becomes WebP once it is read.
            self._remove_older(filepath)
        return pixbuf

    def _remove_older(self, filepath: str) -> None:
        """Take away the PNG an older MComix stored for <filepath> in a
        store that is WebP now, once a WebP one is in its place: nothing
        looks at it while that one is there."""
        for older in self._stored_paths(filepath)[1:]:
            try:
                os.remove(older)
            except OSError:
                pass

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
        box = self._stored_box
        if max(stored) == box or (self.larger_is_current
                                  and max(stored) > box):
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
                and max(source) <= box)

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
        return os.path.join(self.dst_dir, md5hash + self._extensions[0])

    def _stored_paths(self, filepath: str) -> list[str]:
        """Where a thumbnail of <filepath> may be stored: under the name
        _path_to_thumbpath() gives it, then, in a store that is WebP, as
        the PNG an older MComix stored."""
        base = os.path.splitext(self._path_to_thumbpath(filepath))[0]
        return [base + extension for extension in self._extensions]

    def _path_to_sizedpath(self, filepath: str) -> str:
        """Return the path of what keep_sized() keeps for <filepath>: in
        <sized_dir>, or a directory beside <dst_dir>, which holds picture
        files only, under the name the thumbnail has there."""
        name = os.path.basename(self._path_to_thumbpath(filepath))
        directory = (self._sized_dir
                     or self.dst_dir.rstrip('/' + os.sep) + '_sized')
        return os.path.join(directory, os.path.splitext(name)[0])

    def _chosen_cover(self, files: Iterable[str]) -> str | None:
        """The filename within <files> that is the picture the reader
        chose as the cover, or None where none was chosen or the one
        chosen is not among them."""
        if self.cover is None:
            return None
        return next((name for name in files
                     if os.path.normpath(name).replace(os.sep, '/')
                     == self.cover and image_tools.is_image_file(name)),
                    None)

    def _guess_cover(self, files: Iterable[str]) -> str | None:
        """Return the filename within <files> that is the most likely to be the
        cover of an archive using some simple heuristics.
        """
        images = [name for name in files
                  if not archive_tools.is_finder_file(name)
                  and image_tools.is_image_file(name)]
        # And the pages a scan is given by whoever passed it on, which
        # sort before the cover: the credits, and the banner upstream
        # feature request 65 names, also written "banne r" and
        # "ban_ner".  Not where that leaves nothing: a book whose every
        # page is called so has a cover all the same.
        images = [name for name in images
                  if not _NOT_A_COVER.search(os.path.split(name)[1])] or images

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
