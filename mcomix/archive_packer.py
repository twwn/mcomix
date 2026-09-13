"""archive_packer.py - Archive creation class."""

import errno
import os
import shutil
import tarfile
import tempfile
import zipfile
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence

from mcomix import comicinfo
from mcomix import constants
from mcomix import log
from mcomix import process
from mcomix.i18n import _


def check_room_for(files: "Iterable[str]", archive_path: str) -> None:
    """Raise ENOSPC if <files> will not fit beside <archive_path>.

    The new archive is written under a temporary name in the directory
    the old one is in and renamed over it at the end, so all of it has
    to fit there at once: an archive being replaced does not give its
    room up until it has been.  Writing until the disk fills up and
    unwinding from there works - the packer stops and its half-written
    archive is removed - but only after minutes of writing, and with the
    disk full in the meantime.

    What the entries take once they are deflated is not known before
    they are written, so what they take now stands in for it.  For the
    pictures a book is made of that is within a per cent; a page in a
    format that is not compressed already, a BMP say, comes out about
    30% smaller, so a save is refused with that much room to spare.
    """
    needed = sum(os.path.getsize(path) for path in files)
    free = shutil.disk_usage(os.path.dirname(archive_path) or '.').free
    if needed > free:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), archive_path)


def _add_comic_info(image_files: Sequence[str],
                    carried_files: "dict[str, str]",
                    directory: str) -> "str | None":
    """Put the ComicInfo.xml an archive of <image_files> wants into
    <carried_files>, and answer with the path it was written to.

    None where there is nothing to write, which is the usual case for a
    book saved with its pages untouched: the file it already carries
    still counts them, and is carried on as it is.

    <carried_files> is changed in place, and the file that was there is
    replaced rather than added beside: both would go into the archive
    under the one name, and only one of them can.  That name is the one
    the archive had it under, so that a book whose metadata sat
    somewhere other than the root keeps it there.

    The temporary file goes beside the archive, where the archive's own
    temporary file goes, and the caller removes it.
    """
    was_carried = comicinfo.carried(carried_files)
    existing = None
    if was_carried is not None:
        try:
            with open(was_carried[0], 'rb') as fp:
                existing = fp.read()
        except OSError:
            # Carried but unreadable, which is not the same as absent:
            # a file whose contents cannot be read is one to write again.
            existing = b''
    document = comicinfo.for_pages(image_files, existing)
    if document is None:
        return None
    fd, path = tempfile.mkstemp(suffix='.%s' % comicinfo.NAME,
                                prefix='tmp.', dir=directory)
    with os.fdopen(fd, 'wb') as fp:
        fp.write(document)
    if was_carried is None:
        carried_files[path] = comicinfo.NAME
    else:
        del carried_files[was_carried[0]]
        carried_files[path] = was_carried[1]
    return path


def write_archive(archive_path: str, image_files: Sequence[str],
                  comment_files: Sequence[str],
                  carried_files: "Mapping[str, str] | None" = None,
                  archive_type: int = constants.ZIP,
                  permissions_from: "str | None" = None) -> None:
    """Write an archive of those files at <archive_path>.

    Whatever is at that path already is replaced, and only once the new
    archive is whole: it is written under a temporary name in the same
    directory and renamed over the old one, which is also why the room
    for it is asked for first.  <permissions_from>, where it names a
    file that is there, is the file the new archive takes its mode from,
    so that replacing an archive does not change who may read it.

    A ComicInfo.xml goes in as well, so that what MComix writes is a
    comic archive to every other reader and not merely a ZIP of
    pictures.  See mcomix.comicinfo for what goes in it.

    Raises OSError if anything on the way fails, having left nothing
    behind: everything here writes to the directory the archive is in -
    the temporary file, the rename, the permissions - and any of it can.
    """
    carried_files = dict(carried_files or {})
    comment_files = list(comment_files)
    # The default comment extensions take in .xml, so a book's
    # ComicInfo.xml usually comes as a comment.  Left there it would be
    # packed under that name before the rewrite, which the packer then
    # skips as a name already taken, and a book that lost a page would
    # keep a count that still names it.  So it is carried instead, under
    # the name a comment is packed under.
    if comicinfo.carried(carried_files) is None:
        comment = comicinfo.carried(
            {path: os.path.basename(path) for path in comment_files})
        if comment is not None:
            comment_files.remove(comment[0])
            carried_files[comment[0]] = comment[1]
    tmp_path = None
    comic_info_path = None
    written = False
    try:
        comic_info_path = _add_comic_info(image_files, carried_files,
                                          os.path.dirname(archive_path))
        check_room_for(list(image_files) + list(comment_files)
                       + list(carried_files), archive_path)
        fd, tmp_path = tempfile.mkstemp(
            suffix='.%s' % os.path.basename(archive_path),
            prefix='tmp.', dir=os.path.dirname(archive_path))
        # Close the open handle; the writing is the packer's.
        os.close(fd)

        packer = Packer(image_files, comment_files, tmp_path,
                        os.path.splitext(os.path.basename(archive_path))[0],
                        carried_files=carried_files,
                        archive_type=archive_type)
        packer.pack()
        if not packer.wait():
            raise OSError('the archive could not be packed')

        if permissions_from is not None and os.path.exists(permissions_from):
            mode = os.stat(permissions_from).st_mode
        else:
            mode = os.stat(tmp_path).st_mode

        # Removed first: a rename over a file that is there fails on
        # Win32.
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        os.rename(tmp_path, archive_path)
        os.chmod(archive_path, mode)
        written = True
    finally:
        # A half-written archive under a temporary name is of no use to
        # anyone, and the packer only removes its own on a write error.
        # The ComicInfo.xml goes either way: it has been packed by then,
        # or the archive it was written for was never finished.
        for leftover in (tmp_path if not written else None, comic_info_path):
            if leftover is None or not os.path.exists(leftover):
                continue
            try:
                os.unlink(leftover)
            except OSError as error:
                log.error(_('! Could not remove %(file)s: %(error)s'),
                          {'file': leftover, 'error': error})


class _Writer:

    """One archive being written, whatever format it is in.

    MComix reads a dozen archive formats and writes three, which is
    what the ones it reads with an external program can be asked to
    make: a ZIP, a tar, and a 7z where 7-Zip is installed.  A RAR is
    read with unrar, which cannot create one; a PDF, a MOBI and an LHA
    are not formats a book of pages is written back into.
    """

    def __init__(self, archive_path: str) -> None:
        self._archive_path = archive_path

    def add(self, path: str, name: str) -> None:
        """Write the file at <path> into the archive as <name>."""
        raise NotImplementedError

    def close(self) -> None:
        """Finish the archive."""
        raise NotImplementedError

    def clean_up(self) -> None:
        """Drop whatever was left over, finished or not."""


class _ZipWriter(_Writer):

    """A ZIP, which is what a CBZ is.

    Everything is deflated, pages included.  Storing them was meant to
    save the time of compressing a compressed image again, but it also
    means the archive can only come out larger than the one it was made
    from: over twenty 1000x1400 JPEG pages the stored copy was 3,265,642
    bytes against the deflated 3,242,804 and the 3,242,684 of the
    archive they came out of, so removing a page or two from a long book
    still left a bigger file than before.  Deflating them costs 54ms
    against 1.4ms for those twenty pages, on a save that reads and
    writes the whole book anyway; pages that are not compressed already,
    BMP and uncompressed TIFF, come out 30% smaller.
    """

    def __init__(self, archive_path: str) -> None:
        super().__init__(archive_path)
        self._zip = zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED)

    def add(self, path: str, name: str) -> None:
        self._zip.write(path, name)

    def close(self) -> None:
        self._zip.close()

    def clean_up(self) -> None:
        self._zip.close()


class _TarWriter(_Writer):

    """A tar, compressed however the archive it was made from was.

    tarfile writes gzip, bzip2 and xz itself, so this needs nothing
    installed; the mode is the one the source archive's own extension
    asks for, since a .cbt that came back gzipped would no longer be
    the file it was.
    """

    def __init__(self, archive_path: str, mode: str = 'w') -> None:
        super().__init__(archive_path)
        self._tar = tarfile.open(archive_path, mode)  # type: ignore[call-overload]  # the mode is one of the write modes, which tarfile types as literals

    def add(self, path: str, name: str) -> None:
        # recursive=False: every entry is named one at a time, and a
        # directory among them would otherwise bring its whole tree.
        self._tar.add(path, name, recursive=False)

    def close(self) -> None:
        self._tar.close()

    def clean_up(self) -> None:
        self._tar.close()


class _StagedWriter(_Writer):

    """An archive written by a program that names entries after files.

    Neither 7z nor rar takes a name to write a file under: each names an
    entry after the file it was given.  So the entries are laid out
    under a directory of their own first, and that directory is what the
    program is pointed at.  They are linked there where the file system
    allows it, which costs nothing; a copy is what is left when it does
    not.
    """

    #: The program, and what to give it besides the archive and the
    #: directory.  Named by the classes below.
    PROGRAM = ''
    SWITCHES: tuple[str, ...] = ()

    def __init__(self, archive_path: str) -> None:
        super().__init__(archive_path)
        self._staging = tempfile.mkdtemp(
            prefix='mcomix-pack.', dir=os.path.dirname(archive_path))

    def add(self, path: str, name: str) -> None:
        staged = os.path.join(self._staging, name)
        os.makedirs(os.path.dirname(staged), exist_ok=True)
        try:
            os.link(path, staged)
        except OSError:
            shutil.copyfile(path, staged)

    def _executable(self) -> "str | None":
        raise NotImplementedError

    def close(self) -> None:
        executable = self._executable()
        if executable is None:
            raise OSError('%s is not installed' % self.PROGRAM)
        try:
            # Both programs add to an archive that is already there
            # rather than replacing it, and refuse a file that is not
            # one - which the empty file a caller makes to hold the name
            # is.
            if os.path.exists(self._archive_path):
                os.unlink(self._archive_path)
            if not process.call([executable, 'a', *self.SWITCHES, '--',
                                 self._archive_path, '.'],
                                workdir=self._staging):
                raise OSError('%s would not write %s'
                              % (self.PROGRAM, self._archive_path))
        finally:
            self.clean_up()

    def clean_up(self) -> None:
        shutil.rmtree(self._staging, ignore_errors=True)


class _SevenZipWriter(_StagedWriter):

    """A 7z, written by the 7z program, which recurses of itself."""

    PROGRAM = '7z'
    SWITCHES = ('-t7z', '-y')

    def _executable(self) -> "str | None":
        return szip_executable()


class _RarWriter(_StagedWriter):

    """A RAR, written by the rar program.

    -r, because rar takes a directory without descending into it
    otherwise, and a book whose pages are in one would come out empty.
    """

    PROGRAM = 'rar'
    SWITCHES = ('-r', '-y')

    def _executable(self) -> "str | None":
        return rar_executable()


def szip_executable() -> "str | None":
    """The 7z program, or None where it is not installed."""
    return process.find_executable(('7z',))


def rar_executable() -> "str | None":
    """The program that writes a RAR, or None where there is none.

    Not the one that reads them: unrar, which is what MComix extracts a
    RAR with and what a distribution ships, only ever reads.  Making one
    needs the rar program itself, which is not free software and is
    installed by hand where it is installed at all - so this is None on
    most machines, and a RAR is saved as a CBZ there.
    """
    return process.find_executable(('rar',))


#: How a tar is written back, by the extension it carries.  tarfile
#: reads an xz tar as any other, so its type says only "a tar"; writing
#: one back uncompressed under the name it had would leave a file that
#: is not what it says it is.
_TAR_MODES = {'.gz': 'w:gz', '.tgz': 'w:gz',
              '.bz2': 'w:bz2', '.tbz': 'w:bz2', '.tbz2': 'w:bz2',
              '.xz': 'w:xz', '.txz': 'w:xz', '.lzma': 'w:xz'}


def _tar_mode(archive_path: str) -> str:
    """Which of tarfile's write modes <archive_path> asks for."""
    return _TAR_MODES.get(os.path.splitext(archive_path)[1].lower(), 'w')


def can_write(archive_type: "int | None") -> bool:
    """Whether a book read as <archive_type> can be written back as one.

    ZIP and tar are written by the standard library and are always
    there.  A 7z needs the 7z program and a RAR needs rar, neither of
    which MComix installs - and unrar, which is what a RAR is read
    with, only ever reads - so those two are offered only on a machine
    that has them.
    """
    if archive_type in (constants.ZIP, constants.ZIP_EXTERNAL,
                        constants.TAR, constants.GZIP, constants.BZIP2):
        return True
    if archive_type == constants.SEVENZIP:
        return szip_executable() is not None
    if archive_type == constants.RAR:
        return rar_executable() is not None
    return False


def make_writer(archive_path: str, archive_type: int) -> _Writer:
    """The writer that makes an <archive_type> archive at <archive_path>."""
    if archive_type == constants.SEVENZIP:
        return _SevenZipWriter(archive_path)
    if archive_type == constants.RAR:
        return _RarWriter(archive_path)
    if archive_type in (constants.TAR, constants.GZIP, constants.BZIP2):
        return _TarWriter(archive_path, _tar_mode(archive_path))
    return _ZipWriter(archive_path)


class Packer:

    """One archive being written, on a thread of its own.

    pack() starts the writing and returns; wait() blocks until it is done
    and says whether it worked.  write_archive() is the caller, and it
    waits, so the thread is not left running - it is deliberately not a
    daemon, since a half-written archive is worse than a slow exit.

    Which formats can be written is make_writer()'s business rather than
    this class': ZIP, tar, and 7z or RAR where those programs are
    installed.
    """

    def __init__(self, image_files: Sequence[str], other_files: Sequence[str],
                 archive_path: str, base_name: str,
                 carried_files: "Mapping[str, str] | None" = None,
                 archive_type: int = constants.ZIP) -> None:
        """Setup a Packer object to create an archive at <archive_path>.
        All files pointed to by paths in the sequences <image_files> and
        <other_files> will be included in the archive when packed.

        The files in <image_files> will be renamed on the form
        "NN - <base_name>.ext", so that the lexical ordering of their
        filenames match that of their order in the list.

        The files in <other_files> will be included as they are,
        assuming their filenames does not clash with other filenames in
        the archive, and are placed in the archive root.

        <carried_files> maps a path to the name it is written under, and
        is how the archive being edited hands over what it held besides
        its pages: a name there keeps whatever directory it was in, the
        point of carrying a file being that the archive still holds what
        it held.

        <archive_type> is which format to write, out of the three
        can_write() answers for; anything else is a ZIP.
        """
        self._image_files = image_files
        self._other_files = other_files
        self._carried_files = carried_files or {}
        self._archive_path = archive_path
        self._base_name = base_name
        self._archive_type = archive_type
        self._pack_thread: threading.Thread | None = None
        self._packing_successful = False

    def pack(self) -> None:
        """Pack all the files in the file lists into the archive."""
        self._pack_thread = threading.Thread(target=self._thread_pack)
        self._pack_thread.name += '-pack'
        self._pack_thread.daemon = False
        self._pack_thread.start()

    def wait(self) -> bool:
        """Block until the packer thread has finished. Return True if the
        packer finished its work successfully.
        """
        if self._pack_thread is not None:
            self._pack_thread.join()

        return self._packing_successful

    def _files_to_pack(self) -> "Iterator[tuple[str, str]]":
        """Every file to write, as (path, the name it is written under).

        The pages come first, numbered so that their names sort the way
        they were given; a file that came with them keeps its own name
        unless one of the pages has already taken it.
        """
        digits = len(str(len(self._image_files)))
        taken = set()

        for number, path in enumerate(self._image_files, start=1):
            extension = os.path.splitext(path)[1]
            name = f'{number:0{digits}d} - {self._base_name}{extension}'
            taken.add(name)
            yield path, name

        for path in self._other_files:
            name = os.path.basename(path)
            while name in taken:
                name = '_%s' % name
            taken.add(name)
            yield path, name

        for path, name in self._carried_files.items():
            if name in taken:
                # The editor is showing that file under a name of its
                # own, and has already written it out.
                continue
            taken.add(name)
            yield path, name

    def _thread_pack(self) -> None:
        try:
            archive = make_writer(self._archive_path, self._archive_type)
        except Exception:
            log.error(_('! Could not create archive at path "%s"'),
                      self._archive_path)
            return

        try:
            for path, name in self._files_to_pack():
                try:
                    archive.add(path, name)
                except Exception:
                    log.error(_('! Could not add file %(sourcefile)s '
                                'to archive %(archivefile)s, aborting...'),
                              {"sourcefile": path,
                               "archivefile": self._archive_path})
                    break
            else:
                archive.close()
                self._packing_successful = True
        except Exception:
            log.error(_('! Could not create archive at path "%s"'),
                      self._archive_path)
        finally:
            if not self._packing_successful:
                archive.clean_up()

        if not self._packing_successful:
            # Half an archive is worse than none: the caller renames
            # whatever is there over the file being edited.
            try:
                os.remove(self._archive_path)
            except OSError:
                pass

# vim: expandtab:sw=4:ts=4
