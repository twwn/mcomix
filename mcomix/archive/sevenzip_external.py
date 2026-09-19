""" 7z archive extractor. """

import functools
import re
import os
import subprocess
import tempfile
from collections.abc import Iterable, Iterator

from mcomix import process
from mcomix import log
from mcomix.archive import archive_base
from mcomix.i18n import _


class SevenZipArchive(archive_base.ExternalExecutableArchive):
    """ 7z file extractor using the 7z executable. """

    #: Which part of a listing the parser is in: the block describing the
    #: archive, the entries between the two rows of dashes, and whatever
    #: 7z prints after them.
    STATE_HEADER, STATE_LISTING, STATE_FOOTER = 1, 2, 3

    class EncryptedHeader(Exception):
        """The listing itself is encrypted, so it needs a password.

        Raised out of the parser to abandon a listing that never reached
        the entries, and caught by iter_contents(), which starts again
        with the password the reader is asked for.
        """

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        self._is_solid = False
        self._is_encrypted = False
        self._contents: list[tuple[str, int]] = []
        #: Indicates which part of the file listing has been read.
        self._state = self.STATE_HEADER
        #: Current path while listing contents.
        self._path = ''
        #: The entry read but not yet handed over, and whether the
        #: attributes seen for it say it is a directory.
        self._pending: str | None = None
        self._pending_is_directory = False

    def _get_executable(self) -> str | None:
        return SevenZipArchive._find_7z_executable()

    def _get_password_argument(self) -> str:
        """The -p switch to pass 7z.

        Every invocation carries one, encrypted archive or not: without
        it, 7z meeting an archive it does want a password for stops to
        read one from a terminal that is not there, and nothing ever
        comes back.  A bare "-p" says the password is empty.
        """
        if self._is_encrypted:
            return '-p' + self._get_password()
        else:
            return '-p'

    def _get_list_arguments(self) -> list[str]:
        """The command that lists the archive.

        "-slt" asks for the technical listing, which gives each entry
        several "Key = value" lines rather than a row of columns a long
        name would run over, and "-sccUTF-8" fixes the encoding of that
        output rather than leaving it to the console's code page.
        """
        args = [self._executable, 'l', '-slt', '-sccUTF-8']
        args.append(self._get_password_argument())
        args.extend(('--', self.archive))
        return args

    def _get_extract_arguments(self, list_file: str | None = None) -> list[str]:
        """The command that writes the archive's files to standard output.

        "-so" is what sends them there instead of to disk.  <list_file>
        names a file holding the entries to extract, which is how a name
        reaches 7z without the shell or 7z itself reading it as a switch
        or a wildcard.
        """
        args = [self._executable, 'x', '-so', '-sccUTF-8']
        if list_file is not None:
            args.append('-i@' + list_file)
        args.append(self._get_password_argument())
        args.extend(('--', self.archive))
        return args

    def _parse_list_output_line(self, line: str) -> str | None:
        """Read one line of 7z's listing, and return a name or None.

        The listing is asked for with -slt, so an entry is several
        "Key = value" lines rather than a row of columns; the name comes
        back on the "Path = " line and the size on the "Size = " line
        after it.  A run of dashes separates the header from the entries
        and the entries from the footer, which is what the parser's
        three states are.

        A name is held back until the next entry begins, because what
        says whether it is a directory - the "Attributes = " line, which
        starts with D for one - comes after it.  A directory is not a
        member anything can extract, so it is never returned.
        """

        if line.startswith('----------'):
            if self._state == self.STATE_HEADER:
                # First delimiter reached, start reading from next line.
                self._state = self.STATE_LISTING
            elif self._state == self.STATE_LISTING:
                # Last delimiter read, stop reading from now on.
                self._state = self.STATE_FOOTER

            return None

        if self._state == self.STATE_HEADER:
            if re.match(r'^error:.+?can\s?not open encrypted archive\. wrong password\?$', line,
                        re.IGNORECASE):
                self._is_encrypted = True
                raise self.EncryptedHeader()
            if line == 'Solid = +':
                self._is_solid = True

        if self._state == self.STATE_LISTING:
            if line.startswith('Path = '):
                finished = self._flush_pending_entry()
                self._path = self._pending = line[7:]
                self._pending_is_directory = False
                return finished
            if line.startswith('Attributes = '):
                # One letter per attribute, D first for a directory.  An
                # entry with no attributes line at all is taken for a
                # file: not every format 7z reads records any.
                self._pending_is_directory = line[13:].startswith('D')
            if line.startswith('Size = '):
                filesize = int(line[7:])
                if filesize > 0:
                    self._contents.append((self._path, filesize))
            elif line == 'Encrypted = +':
                self._is_encrypted = True

        return None

    def _flush_pending_entry(self) -> str | None:
        """The entry just read, unless it was a directory."""
        pending, self._pending = self._pending, None
        return None if self._pending_is_directory else pending

    def is_solid(self) -> bool:
        """Whether the archive was packed as one stream.

        Only known once it has been listed; the header says so.
        """
        return self._is_solid

    def iter_contents(self) -> Iterator[str]:
        """Yield the name of every file in the archive.

        An archive with an encrypted header cannot be listed at all
        without the password, and there is no way to know that before
        trying: the first attempt is made without one, and the parser
        raises EncryptedHeader when 7z answers that it cannot open the
        archive, which starts the second and last attempt.
        """
        if not self._get_executable():
            return

        for retry_count in range(2):
            self._state = self.STATE_HEADER
            self._path = ''
            self._pending = None
            self._pending_is_directory = False
            proc = subprocess.run(self._get_list_arguments(),
                                  stdout=subprocess.PIPE, stderr=process.STDOUT, encoding='utf-8')
            try:
                for line in proc.stdout.splitlines():
                    filename = self._parse_list_output_line(line.rstrip(os.linesep))
                    if filename is not None:
                        yield filename
                pending = self._flush_pending_entry()
                if pending is not None:
                    yield pending
            except self.EncryptedHeader:
                if retry_count == 0:
                    continue
            break

        self.filenames_initialized = True

    def extract(self, filename: str, destination_dir: str) -> None:
        """ Extract <filename> from the archive to <destination_dir>.

        The name goes to 7z in a file of its own rather than on the
        command line, which is what -i@ takes; a name is written and the
        file removed again around the one run that reads it.
        """
        assert isinstance(filename, str) and \
               isinstance(destination_dir, str)

        if not self._get_executable():
            return

        if not self.filenames_initialized:
            self.list_contents()

        tmplistfile = tempfile.NamedTemporaryFile(prefix='mcomix.7z.', delete=False)
        try:
            desired_filename = self._original_filename(filename).encode('utf-8')
            tmplistfile.write(desired_filename + os.linesep.encode('utf-8'))
            tmplistfile.close()

            output = self._create_file(os.path.join(destination_dir, filename))
            try:
                proc = subprocess.run(
                    self._get_extract_arguments(list_file=tmplistfile.name),
                    stdout=output, stderr=subprocess.PIPE,
                    creationflags=process.CREATIONFLAGS)

                if proc.stderr:
                    log.error(_("Extraction of %(archivefile)s might have failed: %(error)s"),
                              {'archivefile': filename, 'error': proc.stderr.decode('utf-8')})
            finally:
                output.close()
        finally:
            os.unlink(tmplistfile.name)

    def iter_extract(self, entries: Iterable[str], destination_dir: str) -> Iterator[str]:
        """Extract <entries> to <destination_dir>, yielding as each lands.

        One 7z run prints the whole archive to a pipe, in the order the
        listing gave, and the sizes recorded while listing say where
        each file ends.  That is what makes this worth having over the
        inherited one file at a time: a solid archive is unpacked once
        rather than once per file.  Unwanted files are still read, since
        the only way past a file in the stream is through it.
        """
        if not self._get_executable():
            return

        if not self.filenames_initialized:
            self.list_contents()

        proc = process.popen(self._get_extract_arguments())
        assert proc.stdout is not None
        try:
            wanted = set(entries)
            for filename, filesize in self._contents:
                data = proc.stdout.read(filesize)
                if filename not in wanted:
                    continue
                new = self._create_file(os.path.join(destination_dir, filename))
                new.write(data)
                new.close()
                yield filename
                wanted.remove(filename)
                if not wanted:
                    break

        finally:
            proc.stdout.close()
            proc.wait()

    @staticmethod
    @functools.cache
    def _find_7z_executable() -> str | None:
        """ Tries to start 7z, and returns either '7z' if
        it was started successfully or None otherwise. """
        return process.find_executable(('7z',))

    @staticmethod
    def is_available() -> bool:
        return bool(SevenZipArchive._find_7z_executable())


class TarArchive(SevenZipArchive):

    """A tarball inside a compressed file, unpacked one layer at a time.

    7z sees a .tar.xz as one compressed member, and for xz its technical
    listing does not name that member at all.  So the name is made up -
    "archive.tar", which MComix recognises as an archive - and the
    tarball it stands for is opened by the tar handler afterwards, the
    same way any archive inside an archive is.
    """

    def __init__(self, archive: str) -> None:
        super().__init__(archive)
        self._is_solid = True
        self._is_encrypted = False

    def _get_extract_arguments(self, list_file: str | None = None) -> list[str]:
        # Note: we ignore the list_file argument, which
        # contains our made up archive member name.
        return super()._get_extract_arguments()

    def iter_contents(self) -> Iterator[str]:
        """Yield the one made-up name this archive holds."""
        if not self._get_executable():
            return
        self._state = self.STATE_HEADER
        self._path = 'archive.tar'
        proc = subprocess.run(self._get_list_arguments(),
                              stdout=subprocess.PIPE, stderr=process.STDOUT,
                              encoding='utf-8')
        for line in proc.stdout.splitlines():
            self._parse_list_output_line(line.rstrip(os.linesep))
        if self._contents:
            # The archive should not contain more than 1 member.
            assert len(self._contents) == 1
            yield self._unicode_filename(self._path)
        self.filenames_initialized = True

# vim: expandtab:sw=4:ts=4
