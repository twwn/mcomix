""" Glue around libunrar.so/unrar.dll to extract RAR files without having to
resort to calling rar/unrar manually. """

import functools
import sys
import os
import ctypes
import ctypes.util
from collections.abc import Iterator

from mcomix import constants
from mcomix.archive import archive_base
from mcomix import log

if sys.platform == 'win32':
    UNRARCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_uint,
                                       ctypes.c_longlong, ctypes.c_longlong, ctypes.c_longlong)
else:
    UNRARCALLBACK = ctypes.CFUNCTYPE(ctypes.c_longlong, ctypes.c_uint,
                                     ctypes.c_longlong, ctypes.c_longlong, ctypes.c_longlong)


class RarArchive(archive_base.BaseArchive):
    """ Wrapper class for libunrar. All string values passed to this class must be unicode objects.
    In turn, all values returned are also unicode. """

    # Nope! Not a good idea...
    support_concurrent_extractions = False

    class _OpenMode:
        """ Rar open mode """
        RAR_OM_LIST = 0
        RAR_OM_EXTRACT = 1

    class _ProcessingMode:
        """ Rar file processing mode """
        RAR_SKIP = 0
        RAR_EXTRACT = 2

    class _CallbackMessage:
        """ Messages passed to the unrar callback function """
        UCM_CHANGEVOLUME = 0
        UCM_PROCESSDATA = 1
        UCM_NEEDPASSWORD = 2
        UCM_CHANGEVOLUMEW = 3
        UCM_NEEDPASSWORDW = 4
        UCM_PROCESSDATAW = 5

    class _VolumeMode:
        """ Reason a UCM_CHANGEVOLUME message was sent """
        # The next volume is missing, and unrar is asking for it. Answering
        # anything but -1 makes it retry the very same volume, forever.
        RAR_VOL_ASK = 0
        # The next volume is about to be opened, this is just a notification.
        RAR_VOL_NOTIFY = 1

    class _ErrorCode:
        """ Rar error codes """
        ERAR_END_ARCHIVE = 10
        ERAR_NO_MEMORY = 11
        ERAR_BAD_DATA = 12
        ERAR_BAD_ARCHIVE = 13
        ERAR_UNKNOWN_FORMAT = 14
        ERAR_EOPEN = 15
        ERAR_ECREATE = 16
        ERAR_ECLOSE = 17
        ERAR_EREAD = 18
        ERAR_EWRITE = 19
        ERAR_SMALL_BUF = 20
        ERAR_UNKNOWN = 21
        ERAR_MISSING_PASSWORD = 22

    class _RAROpenArchiveDataEx(ctypes.Structure):
        """ Archive header structure. Used by DLL calls. """
        _pack_ = 1
        # unrar.dll is built with MSVC; ctypes used its layout by default
        # for packed structures, but wants that spelled out from 3.14 on.
        _layout_ = 'ms'
        _fields_ = [("ArcName", ctypes.c_char_p),
                    ("ArcNameW", ctypes.c_wchar_p),
                    ("OpenMode", ctypes.c_uint),
                    ("OpenResult", ctypes.c_uint),
                    ("CmtBuf", ctypes.c_char_p),
                    ("CmtBufSize", ctypes.c_uint),
                    ("CmtSize", ctypes.c_uint),
                    ("CmtState", ctypes.c_uint),
                    ("Flags", ctypes.c_uint),
                    ("Callback", UNRARCALLBACK),
                    ("UserData", ctypes.c_long),
                    ("Reserved", ctypes.c_uint * 28)]

    class _RARHeaderDataEx(ctypes.Structure):
        """ Archive file structure. Used by DLL calls. """
        _pack_ = 1
        # unrar.dll is built with MSVC; ctypes used its layout by default
        # for packed structures, but wants that spelled out from 3.14 on.
        _layout_ = 'ms'
        _fields_ = [("ArcName", ctypes.c_char * 1024),
                    ("ArcNameW", ctypes.c_wchar * 1024),
                    ("FileName", ctypes.c_char * 1024),
                    ("FileNameW", ctypes.c_wchar * 1024),
                    ("Flags", ctypes.c_uint),
                    ("PackSize", ctypes.c_uint),
                    ("PackSizeHigh", ctypes.c_uint),
                    ("UnpSize", ctypes.c_uint),
                    ("UnpSizeHigh", ctypes.c_uint),
                    ("HostOS", ctypes.c_uint),
                    ("FileCRC", ctypes.c_uint),
                    ("FileTime", ctypes.c_uint),
                    ("UnpVer", ctypes.c_uint),
                    ("Method", ctypes.c_uint),
                    ("FileAttr", ctypes.c_uint),
                    ("CmtBuf", ctypes.c_char_p),
                    ("CmtBufSize", ctypes.c_uint),
                    ("CmtSize", ctypes.c_uint),
                    ("CmtState", ctypes.c_uint),
                    ("Reserved", ctypes.c_uint * 1024)]

    @staticmethod
    def is_available() -> bool:
        """ Returns True if unrar.dll can be found, False otherwise. """
        return bool(_get_unrar_dll())

    def __init__(self, archive: str) -> None:
        """ Initialize Unrar.dll. """
        super().__init__(archive)
        unrar = _get_unrar_dll()
        if unrar is None:
            raise UnrarException('libunrar could not be loaded.')
        self._unrar = unrar
        self._handle: int | None = None
        self._callback_function: ctypes._FuncPointer | None = None
        self._is_solid = False
        # Information about the current file will be stored in this structure
        self._headerdata = RarArchive._RARHeaderDataEx()
        self._current_filename: str | None = None

        # Set up function prototypes.
        # Mandatory since pointers get truncated on x64 otherwise!
        self._unrar.RAROpenArchiveEx.restype = ctypes.c_void_p
        self._unrar.RAROpenArchiveEx.argtypes = \
            [ctypes.POINTER(RarArchive._RAROpenArchiveDataEx)]
        self._unrar.RARCloseArchive.restype = ctypes.c_int
        self._unrar.RARCloseArchive.argtypes = \
            [ctypes.c_void_p]
        self._unrar.RARReadHeaderEx.restype = ctypes.c_int
        self._unrar.RARReadHeaderEx.argtypes = \
            [ctypes.c_void_p, ctypes.POINTER(RarArchive._RARHeaderDataEx)]
        self._unrar.RARProcessFileW.restype = ctypes.c_int
        self._unrar.RARProcessFileW.argtypes = \
            [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_wchar_p]
        self._unrar.RARSetCallback.argtypes = \
            [ctypes.c_void_p, UNRARCALLBACK, ctypes.c_long]

    def is_solid(self) -> bool:
        """Whether the archive was packed as one stream.

        Only known once it has been listed; each entry's header says so,
        and one solid entry makes the archive solid.
        """
        return self._is_solid

    def iter_contents(self) -> Iterator[str]:
        """ List archive contents. """
        self._close()
        self._open()
        try:
            while True:
                filename = self._read_header()
                if self._headerdata.Flags & 0x10:
                    self._is_solid = True
                if self._header_is_directory():
                    # Not a member anything can extract; skip past it.
                    self._process()
                    continue
                yield filename
                # Skip to the next entry if we're still on the same name
                # (extract may have been called by iter_extract).
                if filename == self._current_filename:
                    self._process()
        except UnrarException as exc:
            log.error('Error while listing contents: %s', str(exc))
        except EOFError:
            # End of archive reached.
            pass
        finally:
            self._close()

    #: The unrar HostOS values whose file attributes are DOS attributes
    #: rather than a Unix mode: MS-DOS, OS/2 and Win32.
    _DOS_HOSTS = (0, 1, 2)

    def _header_is_directory(self) -> bool:
        """Whether the header just read describes a directory.

        The header flags do not say so portably - the bits that stand
        for a directory in RAR 3 are dictionary-size bits in the older
        formats, and the archives MComix meets carry both - but the file
        attributes do, once it is known which system wrote them.  A
        directory packed under Windows carries FILE_ATTRIBUTE_DIRECTORY
        and one packed under Unix carries S_IFDIR in its mode; anything
        else is taken for a file, so an attribute word that means
        neither costs a listing nothing.
        """
        attributes = self._headerdata.FileAttr
        if self._headerdata.HostOS in self._DOS_HOSTS:
            return bool(attributes & 0x10)
        return bool(attributes & 0xF000 == 0x4000)

    def extract(self, filename: str, destination_dir: str) -> None:
        """ Extract <filename> from the archive to <destination_dir>. """
        if not self._handle:
            self._open()
        looped = False
        while True:
            # Check if the current entry matches the requested file.
            if self._current_filename is not None:
                if (self._current_filename == filename):
                    # It's the entry we're looking for, extract it.
                    dest = ctypes.c_wchar_p(os.path.join(destination_dir, filename))
                    self._process(dest)
                    break
                # Not the right entry, skip it.
                self._process()
            try:
                self._read_header()
            except EOFError:
                # Archive end was reached, this might be due to out-of-order
                # extraction while the handle was still open.  Close the
                # archive and jump back to archive start and try to extract
                # file again.  Do this only once; if the file isn't found after
                # a second full pass, it probably doesn't even exist in the
                # archive.
                if looped:
                    break
                looped = True
                self._open()
        # After the method returns, the RAR handler is still open and pointing
        # to the next archive file. This will improve extraction speed for sequential file reads.
        # After all files have been extracted, close() should be called to free the handler resources.

    def close(self) -> None:
        """ Close the archive handle """
        self._close()

    def _open(self) -> None:
        """ Open rar handle for extraction. """
        self._callback_function = UNRARCALLBACK(self._unrar_callback)
        archivedata = RarArchive._RAROpenArchiveDataEx(ArcNameW=self.archive,
                                                       OpenMode=RarArchive._OpenMode.RAR_OM_EXTRACT,
                                                       Callback=self._callback_function,
                                                       UserData=0)

        handle = self._unrar.RAROpenArchiveEx(ctypes.byref(archivedata))
        if not handle:
            errormessage = UnrarException.get_error_message(archivedata.OpenResult)
            raise UnrarException("Couldn't open archive: %s" % errormessage)
        self._unrar.RARSetCallback(handle, self._callback_function, 0)
        self._handle = handle

    def _check_errorcode(self, errorcode: int) -> None:
        """Turn a libunrar return code into an exception, or into nothing.

        The end of the archive is a code like any other to libunrar, and
        comes back here as EOFError, which the loops that read entries
        expect.  Anything else closes the archive before raising, since
        the handle is not to be used after a failure.
        """
        if errorcode == 0:
            return
        self._close()
        exc: Exception
        if RarArchive._ErrorCode.ERAR_END_ARCHIVE == errorcode:
            # End of archive reached.
            exc = EOFError()
        else:
            errormessage = UnrarException.get_error_message(errorcode)
            exc = UnrarException(errormessage)
        raise exc

    def _read_header(self) -> str:
        """ Read the next entry's header, and return the name it names. """
        self._current_filename = None
        errorcode = self._unrar.RARReadHeaderEx(self._handle, ctypes.byref(self._headerdata))
        self._check_errorcode(errorcode)
        self._current_filename = str(self._headerdata.FileNameW)
        return self._current_filename

    def _process(self, dest: ctypes.c_wchar_p | None = None) -> None:
        """ Process current entry: extract or skip it. """
        if dest is None:
            mode = RarArchive._ProcessingMode.RAR_SKIP
        else:
            mode = RarArchive._ProcessingMode.RAR_EXTRACT
        errorcode = self._unrar.RARProcessFileW(self._handle, mode, None, dest)
        self._current_filename = None
        self._check_errorcode(errorcode)

    def _close(self) -> None:
        """ Close the rar handle previously obtained by open. """
        if self._handle is None:
            return
        errorcode = self._unrar.RARCloseArchive(self._handle)
        if errorcode != 0:
            errormessage = UnrarException.get_error_message(errorcode)
            raise UnrarException("Couldn't close archive: %s" % errormessage)
        self._handle = None

    def _unrar_callback(self, msg: int, userdata: int, param1: int, param2: int) -> int:
        """ Called by the unrar library for missing passwords and volumes. """
        if msg == RarArchive._CallbackMessage.UCM_NEEDPASSWORD:
            password = self._get_password()
            if not password:
                # Abort extraction
                return -1
            byte_buffer = ctypes.create_string_buffer(password.encode('utf-8'))
            copy_size = min(param2, len(byte_buffer))
            ctypes.memmove(param1, byte_buffer, copy_size)
            return 1
        elif msg == RarArchive._CallbackMessage.UCM_NEEDPASSWORDW:
            password = self._get_password()
            if not password:
                # Abort extraction
                return -1
            # param2 is the size of unrar's buffer in characters, and its
            # wchar_t is 4 bytes wide everywhere but on Windows, so let
            # ctypes pick the native encoding and terminator instead of
            # assuming UTF-16.
            wchar_buffer = ctypes.create_unicode_buffer(password)
            copy_size = min(param2, len(wchar_buffer)) * ctypes.sizeof(ctypes.c_wchar)
            ctypes.memmove(param1, wchar_buffer, copy_size)
            return 1
        elif msg in (RarArchive._CallbackMessage.UCM_CHANGEVOLUME,
                     RarArchive._CallbackMessage.UCM_CHANGEVOLUMEW):
            if param2 == RarArchive._VolumeMode.RAR_VOL_ASK:
                # A volume of the set is missing. We have no way of supplying
                # it, and continuing would just make unrar retry the same
                # volume in an endless loop, so give up on the rest of the
                # archive; whatever came before is still extractable.
                log.warning('Missing volume for archive "%s", ignoring the rest of the set',
                            self.archive)
                return -1
            # RAR_VOL_NOTIFY: the next volume was found, carry on.
            return 0
        else:
            # Continue operation
            return 0


class UnrarException(Exception):
    """ Exception class for RarArchive. """

    _exceptions = {
        RarArchive._ErrorCode.ERAR_END_ARCHIVE: "End of archive",
        RarArchive._ErrorCode.ERAR_NO_MEMORY: " Not enough memory to initialize data structures",
        RarArchive._ErrorCode.ERAR_BAD_DATA: "Bad data, CRC mismatch",
        RarArchive._ErrorCode.ERAR_BAD_ARCHIVE: "Volume is not valid RAR archive",
        RarArchive._ErrorCode.ERAR_UNKNOWN_FORMAT: "Unknown archive format",
        RarArchive._ErrorCode.ERAR_EOPEN: "Volume open error",
        RarArchive._ErrorCode.ERAR_ECREATE: "File create error",
        RarArchive._ErrorCode.ERAR_ECLOSE: "File close error",
        RarArchive._ErrorCode.ERAR_EREAD: "Read error",
        RarArchive._ErrorCode.ERAR_EWRITE: "Write error",
        RarArchive._ErrorCode.ERAR_SMALL_BUF: "Buffer too small",
        RarArchive._ErrorCode.ERAR_UNKNOWN: "Unknown error",
        RarArchive._ErrorCode.ERAR_MISSING_PASSWORD: "Password missing"
    }

    @staticmethod
    def get_error_message(errorcode: int) -> str:
        """What libunrar's <errorcode> means, in English.

        These go into exception messages and into the log rather than in
        front of the reader, so they are not translated.
        """
        return UnrarException._exceptions.get(errorcode, "Unknown error")


@functools.cache
def _get_unrar_dll() -> ctypes.CDLL | None:
    """ Tries to load libunrar and will return a handle of it.
    Returns None if an error occured or the library couldn't be found. """

    # Load UnRAR64.dll on win32
    if sys.platform == 'win32':
        UNRAR_DLL = "UnRAR64.dll"
        # In PATH first, then MComix' root directory, then the current one.
        # find_library answers None when it finds nothing, which is not
        # a candidate.
        candidates = tuple(name for name in
                           (ctypes.util.find_library(UNRAR_DLL),
                            os.path.join(constants.BASE_PATH, UNRAR_DLL),
                            UNRAR_DLL) if name)
        loader = ctypes.windll
    # Load libunrar.so on UNIX
    else:
        # find_library on UNIX uses various mechanisms to determine the path
        # of a library, so one could assume the library is not installed
        # when find_library fails
        candidates = (ctypes.util.find_library("unrar") or '/usr/lib64/libunrar.so',
                      os.path.join(os.getcwd(), "libunrar.so"))
        loader = ctypes.cdll

    for candidate in candidates:
        try:
            return loader.LoadLibrary(candidate)
        except OSError:
            pass

    return None

# vim: expandtab:sw=4:ts=4
