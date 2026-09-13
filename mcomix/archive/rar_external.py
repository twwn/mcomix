""" RAR archive extractor. """

import functools
import os
import sys
import subprocess
from collections.abc import Iterable, Iterator

from mcomix import log
from mcomix import process
from mcomix.archive import archive_base


class RarArchive(archive_base.ExternalExecutableArchive):
    """ RAR file extractor using the unrar/rar executable. """

    #: Which part of a listing the parser is in: the block describing
    #: the archive, then the entries themselves.
    STATE_HEADER, STATE_LISTING = 1, 2

    class EncryptedHeader(Exception):
        """The listing itself is encrypted, so it needs a password.

        Raised out of the parser to abandon a listing that has only
        produced a header, and caught by iter_contents(), which starts
        again with the password the reader is asked for.
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

    def _get_executable(self) -> str | None:
        return self._find_unrar_executable()

    def _get_password_argument(self) -> str:
        """The -p switch to pass unrar.

        Every invocation carries one, encrypted archive or not: without
        it, unrar meeting an archive it does want a password for stops
        to read one from a terminal that is not there, and nothing ever
        comes back.  "-p-" says explicitly that there is none.
        """
        if not self._is_encrypted:
            return '-p-'
        password = self._get_password()
        if not password:
            return '-p-'
        return '-p' + password

    def _get_list_arguments(self) -> list[str]:
        """The command that lists the archive.

        "vt" is the verbose technical listing, which names each entry on
        a line of its own rather than in columns that a long name would
        run over.
        """
        args = [self._executable, 'vt']
        args.append(self._get_password_argument())
        args.extend(('--', self.archive))
        return args

    def _get_extract_arguments(self) -> list[str]:
        """The command that writes the archive's files to standard output.

        "p" prints rather than unpacking to disk, "-inul" silences the
        progress lines that would otherwise be mixed into that output,
        and "-@" stops unrar from reading a file list from its input.
        """
        args = [self._executable, 'p', '-inul', '-@']
        args.append(self._get_password_argument())
        args.extend(('--', self.archive))
        return args

    def _parse_list_output_line(self, line: str) -> str | None:
        """Take one line of the listing, returning a name if it named one.

        The technical listing gives each entry several lines - Name,
        Size, Flags - so a name is returned as it is read and the lines
        under it are recorded against it.  Only entries with a size are
        kept for iter_extract(): a directory has none, and nothing is
        printed for it later.
        """
        if self._state == self.STATE_HEADER:
            if line.startswith('Details: '):
                flags = line[9:].split(', ')
                if 'solid' in flags:
                    self._is_solid = True
                if 'encrypted headers' in flags:
                    if not self._is_encrypted:
                        # Trigger a restart of the enclosing
                        # iter_contents loop with a password.
                        self._is_encrypted = True
                        raise self.EncryptedHeader()
                self._state = self.STATE_LISTING
                return None
        if self._state == self.STATE_LISTING:
            line = line.lstrip()
            if line.startswith('Name: '):
                self._path = line[6:]
                return self._path
            if line.startswith('Size: '):
                filesize = int(line[6:])
                if filesize > 0:
                    self._contents.append((self._path, filesize))
            if line.startswith('Flags: '):
                flags = line[7:].split()
                if 'solid' in flags:
                    self._is_solid = True
                if 'encrypted' in flags:
                    self._is_encrypted = True
        return None

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
        raises EncryptedHeader if the header says it needs one, which
        starts the second and last attempt.
        """
        if not self._get_executable():
            return

        for retry_count in range(2):
            self._state = self.STATE_HEADER
            self._path = ''
            proc = subprocess.run(
                self._get_list_arguments(), stdout=process.PIPE, stderr=process.STDOUT,
                encoding="utf-8",
                creationflags=process._get_creationflags())
            try:
                for line in proc.stdout.splitlines():
                    filename = self._parse_list_output_line(line.rstrip(os.linesep))
                    if filename is not None:
                        yield self._unicode_filename(filename)
            except self.EncryptedHeader:
                if retry_count == 0:
                    continue
            break

        self.filenames_initialized = True

    def extract(self, filename: str, destination_dir: str) -> None:
        """ Extract <filename> from the archive to <destination_dir>. """
        assert isinstance(filename, str) \
            and isinstance(destination_dir, str)

        if not self._get_executable():
            return

        if not self.filenames_initialized:
            self.list_contents()

        desired_filename = self._original_filename(filename)
        cmd = self._get_extract_arguments() + [desired_filename]
        output = self._create_file(os.path.join(destination_dir, filename))
        try:
            process.call(cmd, stdout=output)
        finally:
            output.close()

    def iter_extract(self, entries: Iterable[str], destination_dir: str) -> Iterator[str]:
        """Extract <entries> to <destination_dir>, yielding as each lands.

        One unrar run prints the whole archive to a pipe, in the order
        the listing gave, and the sizes recorded while listing say where
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
            wanted = {self._original_filename(unicode_name): unicode_name
                      for unicode_name in entries}

            for filename, filesize in self._contents:
                data = proc.stdout.read(filesize)
                if filename not in wanted:
                    continue
                unicode_name = wanted.get(filename, None)
                if unicode_name is None:
                    continue
                new = self._create_file(os.path.join(destination_dir, unicode_name))
                new.write(data)
                new.close()
                yield unicode_name
                del wanted[filename]
                if not wanted:
                    break

        finally:
            proc.stdout.close()
            proc.wait()

    @staticmethod
    @functools.cache
    def _find_unrar_executable() -> str | None:
        """ Tries to start rar/unrar, and returns either 'rar' or 'unrar' if
        one of them was started successfully.
        Returns None if neither could be started. """
        if sys.platform == 'win32':
            def is_not_unrar_free(exe: str) -> bool:
                return True
        else:
            def is_not_unrar_free(exe: str) -> bool:
                real_exe = exe
                while os.path.islink(real_exe):
                    real_exe = os.readlink(real_exe)
                if real_exe.endswith(os.path.sep + 'unrar-free'):
                    log.warning('RAR executable %s is unrar-free, ignoring', exe)
                    return False
                return True
        return process.find_executable(('unrar-nonfree', 'unrar', 'rar'),
                                       is_valid_candidate=is_not_unrar_free)

    @staticmethod
    def is_available() -> bool:
        return bool(RarArchive._find_unrar_executable())

# vim: expandtab:sw=4:ts=4
