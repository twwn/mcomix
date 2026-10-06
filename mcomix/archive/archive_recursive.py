""" Class for transparently handling an archive containing sub-archives. """

from mcomix.archive import archive_base
from mcomix import archive_tools
from mcomix import log

import os
from collections.abc import Iterable, Iterator

#: How many archives deep a listing follows an archive within an archive.
#: Listing extracts every sub-archive it finds, so an archive that holds a
#: copy of itself - which a well made one can - would otherwise be followed
#: until the disk it is written to fills up.
MAX_NESTING_DEPTH = 10


class RecursiveArchive(archive_base.BaseArchive):

    """An archive and the archives inside it, as one flat listing.

    Every entry is named by the path it takes through the nesting - the
    name of the archive it was found in, then the name inside that - so
    a caller that only ever sees these names needs to know nothing about
    where the nesting ends.  Sub-archives are extracted to
    <destination_dir> as they are found, since an archive has to be a
    file on disk before a handler can open it.
    """

    def __init__(self, archive: archive_base.BaseArchive, destination_dir: str) -> None:
        super().__init__(archive.archive)
        self._main_archive = archive
        self._destination_dir = destination_dir
        self._archive_list: list[archive_base.BaseArchive] = []
        # Map entry name to its archive+name.
        self._entry_mapping: dict[str, tuple[archive_base.BaseArchive, str]] = {}
        # Map archive to its root.
        self._archive_root: dict[archive_base.BaseArchive, str | None] = {}
        self._contents_listed = False
        self._contents: list[str] = []
        # Assume concurrent extractions are not supported.
        self.support_concurrent_extractions = False

    def _iter_contents(self, archive: archive_base.BaseArchive,
                       root: str | None = None, depth: int = 0) -> Iterator[str]:
        """Yield every entry of <archive> and of the archives within it.

        <root> is the name this archive is reached under, which every
        name it holds is prefixed with, and <depth> is how many archives
        deep it already is.

        The entries of one archive are listed before any of its
        sub-archives are opened, because extracting from an archive
        while its own listing is still being read is what several of the
        handlers cannot do.
        """
        self._archive_list.append(archive)
        self._archive_root[archive] = root
        sub_archive_list: list[str] = []
        for f in archive.iter_contents():
            if archive_tools.is_archive_file(f):
                if depth < MAX_NESTING_DEPTH:
                    # We found a sub-archive, don't try to extract it now, as we
                    # must finish listing the containing archive contents before
                    # any extraction can be done.
                    sub_archive_list.append(f)
                    continue
                # Too deep to follow: the entry is still listed, as any
                # other one that holds no image would be.
                log.warning('Not opening %s: more than %u archives deep',
                            f, MAX_NESTING_DEPTH)
            name = f
            if root is not None:
                name = os.path.join(root, name)
            self._entry_mapping[name] = (archive, f)
            yield name
        for f in sub_archive_list:
            # Extract sub-archive.
            destination_dir = self._destination_dir
            if root is not None:
                destination_dir = os.path.join(destination_dir, root)
            archive.extract(f, destination_dir)
            sub_archive_ext = os.path.splitext(f)[1].lower()[1:]
            sub_archive_path = os.path.join(
                self._destination_dir, 'sub-archives',
                '%04u.%s' % (len(self._archive_list), sub_archive_ext))
            self._create_directory(os.path.dirname(sub_archive_path))
            os.rename(os.path.join(destination_dir, f), sub_archive_path)
            # And open it and list its contents.
            sub_archive = archive_tools.get_archive_handler(sub_archive_path)
            if sub_archive is None:
                log.warning('Non-supported archive format: %s',
                            os.path.basename(sub_archive_path))
                continue
            sub_root = f
            if root is not None:
                sub_root = os.path.join(root, sub_root)
            for name in self._iter_contents(sub_archive, sub_root, depth + 1):
                yield name

    def _check_concurrent_extraction_support(self) -> None:
        """Settle whether extractions may run side by side.

        Only once every archive in the nesting is known, and only if all
        of them allow it: the answer for the whole is the answer of the
        least capable part.
        """
        supported = True
        # We need all archives to support concurrent extractions.
        for archive in self._archive_list:
            if not archive.support_concurrent_extractions:
                supported = False
                break
        self.support_concurrent_extractions = supported
        # What a thread costs is what the costliest part's threads do.
        self.extraction_thread_memory = max(
            (archive.extraction_thread_memory
             for archive in self._archive_list), default=0)

    def member_date(self, name: str) -> float | None:
        """The date the archive that holds <name> records for it."""
        entry = self._entry_mapping.get(name)
        if entry is None:
            return None
        archive, inner = entry
        return archive.member_date(inner)

    def iter_contents(self) -> Iterator[str]:
        """Yield every entry, listing the nesting on the first call."""
        if self._contents_listed:
            for f in self._contents:
                yield f
            return
        self._contents = []
        for f in self._iter_contents(self._main_archive):
            self._contents.append(f)
            yield f
        self._contents_listed = True
        # We can now check if concurrent extractions are really supported.
        self._check_concurrent_extraction_support()

    def list_contents(self) -> list[str]:
        """Every entry, from the listing already taken if there is one."""
        if self._contents_listed:
            return self._contents
        return list(self.iter_contents())

    def extract(self, filename: str, destination_dir: str) -> None:
        """Extract <filename> from whichever archive holds it.

        The listing is what says which one that is, so a caller that
        extracts without listing first is listed for.
        """
        if not self._contents_listed:
            self.list_contents()
        archive, name = self._entry_mapping[filename]
        root = self._archive_root[archive]
        if root is not None:
            destination_dir = os.path.join(destination_dir, root)
        log.debug('extracting from %s to %s: %s',
                  archive.archive, destination_dir, filename)
        archive.extract(name, destination_dir)

    def iter_extract(self, entries: Iterable[str], destination_dir: str) -> Iterator[str]:
        """Extract <entries>, one archive at a time, yielding as they land.

        The inherited version would extract them one file at a time,
        which costs a solid archive a pass over itself for every entry
        asked of it.  Grouping the entries by the archive they came from
        and handing each group to that archive's own iter_extract() is
        one pass per archive instead.
        """
        if not self._contents_listed:
            self.list_contents()
        wanted = set(entries)
        for archive in self._archive_list:
            archive_wanted: dict[str, str] = {}
            for name in wanted:
                name_archive, name_archive_name = self._entry_mapping[name]
                if name_archive == archive:
                    archive_wanted[name_archive_name] = name
            if not archive_wanted:
                continue
            root = self._archive_root[archive]
            archive_destination_dir = destination_dir
            if root is not None:
                archive_destination_dir = os.path.join(destination_dir, root)
            wanted_names = list(archive_wanted)
            log.debug('extracting from %s to %s: %s',
                      archive.archive, archive_destination_dir,
                      ' '.join(wanted_names))
            for f in archive.iter_extract(wanted_names, archive_destination_dir):
                yield archive_wanted[f]
            wanted -= set(archive_wanted.values())
            if not wanted:
                break

    def is_solid(self) -> bool:
        """Whether any archive in the nesting is solid.

        One solid archive anywhere makes the whole thing worth
        extracting in one pass, since that archive would otherwise be
        walked once per entry.
        """
        if not self._contents_listed:
            self.list_contents()
        for archive in self._archive_list:
            if archive.is_solid():
                return True
        return False

    def close(self) -> None:
        """Close every archive in the nesting."""
        archives = list(self._archive_list)
        # The main archive only joins the list once listing has started, so
        # closing an archive that was opened but never listed needs this.
        if self._main_archive not in archives:
            archives.append(self._main_archive)
        for archive in archives:
            archive.close()
