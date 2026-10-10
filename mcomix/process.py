"""process.py - Process spawning module."""

import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import IO

from mcomix import i18n


NULL = subprocess.DEVNULL
PIPE = subprocess.PIPE
STDOUT = subprocess.STDOUT

# What subprocess accepts for a standard stream: one of the constants
# above, an open file, or None to inherit the caller's stream.
type Redirect = int | IO[bytes] | None


#: What every program MComix runs is started with: on Windows,
#: CREATE_NO_WINDOW, so that a console program such as unrar or 7z does
#: not open a console window of its own; nothing elsewhere.
CREATIONFLAGS = 0x08000000 if sys.platform == 'win32' else 0


# Cannot spawn processes with PythonW/Win32 unless stdin
# and stderr are redirected to a pipe/devnull as well.
def call(args: Sequence[str | bytes], stdin: Redirect = NULL,
         stdout: Redirect = NULL, stderr: Redirect = NULL,
         workdir: str | None = None,
         env: Mapping[str, str] | None = None) -> bool:
    """Run <args> and say whether it succeeded.

    <workdir> is the directory it runs in, which is what an archiver
    that names its entries after the files it is given needs: the names
    are then the ones under that directory.  <env> is its environment,
    MComix' own where none is given.
    """
    return subprocess.call(args, stdin=stdin, stdout=stdout,
                           stderr=stderr, cwd=workdir, env=env,
                           creationflags=CREATIONFLAGS) == 0


def popen(args: Sequence[str | bytes], stdin: Redirect = NULL,
          stdout: Redirect = PIPE, stderr: Redirect = NULL,
          workdir: str | None = None,
          env: Mapping[str, str] | None = None) -> subprocess.Popen[bytes]:
    """Start <args>, in <workdir> and with <env> if they are given."""
    return subprocess.Popen(args, stdin=stdin,
                            stdout=stdout, stderr=stderr, cwd=workdir,
                            env=env, creationflags=CREATIONFLAGS)


def find_executable(candidates: Iterable[str], workdir: str | None = None,
                    is_valid_candidate: Callable[[str], bool] | None = None) -> str | None:
    """ Find executable in path.

    Return an absolute path to a valid executable or None.

    <workdir> default to the current working directory if not set.

    <is_valid_candidate> is an optional function that must return True
    if the path passed in argument is a valid candidate (to check for
    version number, symlinks to an unsupported variant, etc...).

    If a candidate has a directory component,
    it will be checked relative to <workdir>.

    On Windows:

    - '.exe' will be appended to each candidate if not already

    - MComix executable directory is prepended to the path on Windows
      (to support embedded tools/executables in the distribution).

    - <workdir> will be inserted first in the path.

    On Unix:

    - a valid candidate must have execution right

    """
    if workdir is None:
        workdir = os.getcwd()
    workdir = os.path.abspath(workdir)

    # os.defpath where PATH is not set at all, as shutil.which() does:
    # MComix started from a service or a bare environment stopped with
    # KeyError the first time it looked for 7z or unrar.
    search_path = os.environ.get('PATH', os.defpath).split(os.pathsep)
    if sys.platform == 'win32':
        search_path.insert(0, workdir)
        search_path.insert(0, _exe_dir)

    def is_valid_exe(exe: str) -> bool:
        return os.path.isfile(exe) and os.access(exe, os.R_OK | os.X_OK)

    if is_valid_candidate is None:
        is_valid = is_valid_exe
    else:
        def is_valid(exe: str) -> bool:
            return is_valid_exe(exe) and is_valid_candidate(exe)

    for name in candidates:

        # On Windows, must end with '.exe'
        if sys.platform == 'win32':
            if not name.endswith('.exe'):
                name = name + '.exe'

        # Absolute path?
        if os.path.isabs(name):
            if is_valid(name):
                return name

        # Does candidate have a directory component?
        elif os.path.dirname(name):
            # Yes, check relative to working directory.
            path = os.path.normpath(os.path.join(workdir, name))
            if is_valid(path):
                return path

        # Look in search path.
        else:
            for directory in search_path:
                path = os.path.abspath(os.path.join(directory, name))
                if is_valid(path):
                    return path

    return None


if sys.platform == 'win32':

    _exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

    def Win32Popen(cmd: Sequence[str], workdir: str | None = None) -> int:
        """Start <cmd> on its own, in <workdir> if one is given, and
        return its process id.

        What sets this apart from popen() is that the program is looked
        up with find_executable() - MComix' own directory first, then
        the working directory, then PATH, with '.exe' added - and
        started with the console window it asks for and none of MComix'
        handles, where popen() hides the console and redirects the
        standard streams.
        """
        import ctypes

        # Declare common data types
        DWORD = ctypes.c_uint
        WORD = ctypes.c_ushort
        LPTSTR = ctypes.c_wchar_p
        LPBYTE = ctypes.POINTER(ctypes.c_ubyte)
        HANDLE = ctypes.c_void_p

        class StartupInfo(ctypes.Structure):
            _fields_ = [("cb", DWORD),
                        ("lpReserved", LPTSTR),
                        ("lpDesktop", LPTSTR),
                        ("lpTitle", LPTSTR),
                        ("dwX", DWORD),
                        ("dwY", DWORD),
                        ("dwXSize", DWORD),
                        ("dwYSize", DWORD),
                        ("dwXCountChars", DWORD),
                        ("dwYCountChars", DWORD),
                        ("dwFillAttribute", DWORD),
                        ("dwFlags", DWORD),
                        ("wShowWindow", WORD),
                        ("cbReserved2", WORD),
                        ("lpReserved2", LPBYTE),
                        ("hStdInput", HANDLE),
                        ("hStdOutput", HANDLE),
                        ("hStdError", HANDLE)]

        class ProcessInformation(ctypes.Structure):
            _fields_ = [("hProcess", HANDLE),
                        ("hThread", HANDLE),
                        ("dwProcessId", DWORD),
                        ("dwThreadId", DWORD)]

        LPSTRARTUPINFO = ctypes.POINTER(StartupInfo)
        LPROCESS_INFORMATION = ctypes.POINTER(ProcessInformation)
        ctypes.windll.kernel32.CreateProcessW.argtypes = [LPTSTR, LPTSTR,
                                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool, DWORD,
                                                          ctypes.c_void_p, LPTSTR, LPSTRARTUPINFO, LPROCESS_INFORMATION]
        ctypes.windll.kernel32.CreateProcessW.restype = ctypes.c_bool

        # Convert list of arguments into a single string
        cmdline = subprocess.list2cmdline(cmd)
        buffer = ctypes.create_unicode_buffer(cmdline)

        # Resolve executable path.
        exe = find_executable((cmd[0],), workdir=workdir)

        # Some required structures for the method call...
        startupinfo = StartupInfo()
        ctypes.memset(ctypes.addressof(startupinfo), 0, ctypes.sizeof(startupinfo))
        startupinfo.cb = ctypes.sizeof(startupinfo)
        processinfo = ProcessInformation()

        # Spawn new process
        success = ctypes.windll.kernel32.CreateProcessW(exe, buffer,
                                                        None, None, False, 0, None, workdir, ctypes.byref(startupinfo),
                                                        ctypes.byref(processinfo))

        if success:
            ctypes.windll.kernel32.CloseHandle(processinfo.hProcess)
            ctypes.windll.kernel32.CloseHandle(processinfo.hThread)
            return int(processinfo.dwProcessId)
        else:
            raise ctypes.WinError(ctypes.GetLastError(),
                                  i18n.to_unicode(ctypes.FormatError()))


def mcomix_command() -> list[str]:
    """How to start another MComix, given how this one was started.

    A frozen build is one executable and takes its arguments directly.
    Everything else is the interpreter running either a script or a
    package: sys.argv[0] names the script an installed entry point or
    mcomixstarter.py was reached by, but names mcomix/__main__.py once
    "python -m mcomix" is what started the program - and running that
    file as a script fails, its relative imports having no package to
    resolve against.
    """
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    spec = getattr(sys.modules['__main__'], '__spec__', None)
    if spec is not None and spec.parent:
        return [sys.executable, '-m', spec.parent]
    return [sys.executable, os.path.abspath(sys.argv[0])]


def launch_mcomix(path: "str | None" = None, page: int = 0,
                  member: "str | None" = None) -> None:
    """Open <path> in an MComix of its own, at <page> if one is given.

    <member> is the name within the archive at <path> of the file of that
    page, which the new program finds the page by where the archive
    still has it, wherever its sort order has put it.

    The new program is passed the file the way the command line would
    pass it, so a file that has gone missing is reported by the reader
    that was asked to show it, as it would be from a shell.  With no
    path it starts as a launcher would start it, on whatever the
    preferences say to open; a page without a file to find it in is
    nothing to pass on.
    """
    # A window of its own is what was asked for, whatever "single
    # instance" would do with a file opened from outside.
    command = mcomix_command() + ['--new-window']
    if path is not None:
        if page:
            command += ['--page', str(page)]
        if member is not None:
            command += ['--page-member', member]
        command.append(path)
    # It runs on its own from here; on Unix the SIGCHLD handler
    # installed in run.py collects it once it exits.
    if sys.platform == 'win32':
        Win32Popen(command)
    else:
        popen(command, stdout=NULL)


# vim: expandtab:sw=4:ts=4
