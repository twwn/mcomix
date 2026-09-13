"""process.py - Process spawning module."""

import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import IO

from mcomix import i18n


NULL = subprocess.DEVNULL
PIPE = subprocess.PIPE
STDOUT = subprocess.STDOUT

# What subprocess accepts for a standard stream: one of the constants
# above, an open file, or None to inherit the caller's stream.
type Redirect = int | IO[bytes] | None


def _get_creationflags() -> int:
    if sys.platform == 'win32':
        # Do not create a console window.
        return 0x08000000
    else:
        return 0

# Cannot spawn processes with PythonW/Win32 unless stdin
# and stderr are redirected to a pipe/devnull as well.
def call(args: Sequence[str | bytes], stdin: Redirect = NULL,
         stdout: Redirect = NULL, stderr: Redirect = NULL) -> bool:
    return 0 == subprocess.call(args, stdin=stdin,
                                stdout=stdout, stderr=stderr,
                                creationflags=_get_creationflags())


def popen(args: Sequence[str | bytes], stdin: Redirect = NULL,
          stdout: Redirect = PIPE, stderr: Redirect = NULL) -> subprocess.Popen[bytes]:
    return subprocess.Popen(args, stdin=stdin,
                            stdout=stdout, stderr=stderr,
                            creationflags=_get_creationflags())


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

    search_path = os.environ['PATH'].split(os.pathsep)
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

    def Win32Popen(cmd: Sequence[str]) -> int:
        """ Spawns a new process on Win32. cmd is a list of parameters.
        This method's sole purpose is calling CreateProcessW, not
        CreateProcessA as it is done by subprocess.Popen. """
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
        exe = find_executable((cmd[0],))

        # Some required structures for the method call...
        startupinfo = StartupInfo()
        ctypes.memset(ctypes.addressof(startupinfo), 0, ctypes.sizeof(startupinfo))
        startupinfo.cb = ctypes.sizeof(startupinfo)
        processinfo = ProcessInformation()

        # Spawn new process
        success = ctypes.windll.kernel32.CreateProcessW(exe, buffer,
                None, None, False, 0, None, None, ctypes.byref(startupinfo),
                ctypes.byref(processinfo))

        if success:
            ctypes.windll.kernel32.CloseHandle(processinfo.hProcess)
            ctypes.windll.kernel32.CloseHandle(processinfo.hThread)
            return int(processinfo.dwProcessId)
        else:
            raise ctypes.WinError(ctypes.GetLastError(),
                    i18n.to_unicode(ctypes.FormatError()))


# vim: expandtab:sw=4:ts=4
