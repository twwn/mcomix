""" Logging module for MComix. Provides a logger 'mcomix' with a few
pre-configured settings. Functions in this module are redirected to
this default logger. """

import sys
import logging
import threading
import types
from logging import DEBUG, INFO, WARNING, ERROR


__all__ = [
    'debug', 'info', 'warning', 'error',
    'DEBUG', 'INFO', 'WARNING', 'ERROR',
    'getLevel', 'setLevel', 'log_to_file', 'log_uncaught_exceptions',
]


class _Formatter(logging.Formatter):

    """A formatter whose lines any UTF-8 stream can write.

    A name on disk that is not UTF-8 reaches Python with lone
    surrogates, and standard output encodes strictly: a line naming
    such a file raised in the handler, which printed a "--- Logging
    error ---" traceback in place of the line.  Those characters are
    written as their escapes instead.
    """

    def format(self, record: logging.LogRecord) -> str:
        return super().format(record).encode(
            'utf-8', 'backslashreplace').decode('utf-8')


# Set up default logger.
__logger = logging.getLogger('mcomix')
__logger.setLevel(WARNING)
__formatter = _Formatter(
    '%(asctime)s [%(threadName)s] %(levelname)s: %(message)s', '%H:%M:%S')
# A build without a console - MComix.exe on Windows - has no standard
# output at all, and a handler writing to none fails on every line.
if not __logger.handlers and sys.stdout is not None:
    __handler = logging.StreamHandler(sys.stdout)
    __handler.setFormatter(__formatter)
    __logger.handlers = [__handler]


def getLevel() -> int:
    return __logger.level


def log_to_file(path: str) -> None:
    """Write the log to <path> as well, from the start of the file.

    The one way to read the log of a build that has no console, whose
    standard output goes nowhere.
    """
    handler = logging.FileHandler(path, mode='w', encoding='utf-8')
    handler.setFormatter(__formatter)
    __logger.addHandler(handler)


def log_uncaught_exceptions() -> None:
    """Log an exception nothing caught, with its traceback, in any thread.

    Python writes those to standard error, which a build without a
    console does not have either; logged, they reach the log file.  An
    exception in a GTK callback is one of these: PyGObject hands it to
    sys.excepthook and carries on.
    """
    def in_main_thread(kind: type[BaseException], value: BaseException,
                       traceback: types.TracebackType | None) -> None:
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, traceback)
            return
        __logger.error('Uncaught exception', exc_info=(kind, value, traceback))

    def in_other_thread(args: threading.ExceptHookArgs) -> None:
        # As threading's own hook, which says nothing of SystemExit.
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else '?'
        __logger.error('Uncaught exception in thread %s', name,
                       exc_info=args.exc_value)

    sys.excepthook = in_main_thread
    threading.excepthook = in_other_thread


# The following functions direct all input to __logger.
debug = __logger.debug
info = __logger.info
warning = __logger.warning
error = __logger.error
setLevel = __logger.setLevel


# vim: expandtab:sw=4:ts=4
