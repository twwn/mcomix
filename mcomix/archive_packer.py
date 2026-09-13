"""archive_packer.py - Archive creation class."""

import os
import zipfile
import threading
from collections.abc import Iterator, Sequence

from mcomix import log
from mcomix.i18n import _


class Packer:

    """Packer is a threaded class for packing files into ZIP archives.

    It would be straight-forward to add support for more archive types,
    but basically all other types are less well fitted for this particular
    task than ZIP archives are (yes, really).
    """

    def __init__(self, image_files: Sequence[str], other_files: Sequence[str],
                 archive_path: str, base_name: str) -> None:
        """Setup a Packer object to create a ZIP archive at <archive_path>.
        All files pointed to by paths in the sequences <image_files> and
        <other_files> will be included in the archive when packed.

        The files in <image_files> will be renamed on the form
        "NN - <base_name>.ext", so that the lexical ordering of their
        filenames match that of their order in the list.

        The files in <other_files> will be included as they are,
        assuming their filenames does not clash with other filenames in
        the archive. All files are placed in the archive root.
        """
        self._image_files = image_files
        self._other_files = other_files
        self._archive_path = archive_path
        self._base_name = base_name
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

    def _files_to_pack(self) -> "Iterator[tuple[str, str, int]]":
        """Every file to write, as (path, name in the archive, method).

        The pages come first, numbered so that their names sort the way
        they were given; a file that came with them keeps its own name
        unless one of the pages has already taken it.  A page is stored
        rather than deflated, being a compressed image already.
        """
        digits = len(str(len(self._image_files)))
        taken = set()

        for number, path in enumerate(self._image_files, start=1):
            extension = os.path.splitext(path)[1]
            name = f'{number:0{digits}d} - {self._base_name}{extension}'
            taken.add(name)
            yield path, name, zipfile.ZIP_STORED

        for path in self._other_files:
            name = os.path.basename(path)
            while name in taken:
                name = '_%s' % name
            taken.add(name)
            yield path, name, zipfile.ZIP_DEFLATED

    def _thread_pack(self) -> None:
        try:
            archive = zipfile.ZipFile(self._archive_path, 'w')
        except Exception:
            log.error(_('! Could not create archive at path "%s"'),
                      self._archive_path)
            return

        with archive:
            for path, name, compression in self._files_to_pack():
                try:
                    archive.write(path, name, compression)
                except Exception:
                    log.error(_('! Could not add file %(sourcefile)s '
                                'to archive %(archivefile)s, aborting...'),
                              {"sourcefile": path,
                               "archivefile": self._archive_path})
                    break
            else:
                self._packing_successful = True

        if not self._packing_successful:
            # Half an archive is worse than none: the caller renames
            # whatever is there over the file being edited.
            try:
                os.remove(self._archive_path)
            except OSError:
                pass

# vim: expandtab:sw=4:ts=4
