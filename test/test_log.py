"""The log MComix writes to its standard output."""

import io
import logging
import os
import sys
import tempfile
import threading
import unittest

# Imported for what it does: it sets the 'mcomix' logger's handler up.
import mcomix.log  # noqa: F401


class LogTest(unittest.TestCase):

    def test_a_path_that_is_not_utf_8_is_written_as_escapes(self):
        """A name on disk that is not UTF-8 reaches Python with lone
        surrogates, and standard output encodes strictly: every line
        naming such a path came out as a "--- Logging error ---"
        traceback in place of the line."""
        stream = io.TextIOWrapper(io.BytesIO(), encoding='utf-8',
                                  errors='strict', write_through=True)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            logging.getLogger('mcomix').handlers[0].formatter)
        record = logging.LogRecord('mcomix', logging.WARNING, __file__, 1,
                                   'extracting from %s', ('B\udcfccher.cbz',),
                                   None)
        handler.handle(record)
        written = stream.buffer.getvalue().decode('utf-8')
        self.assertIn('B\\udcfccher.cbz', written)


# vim: expandtab:sw=4:ts=4


class LogFileTest(unittest.TestCase):

    """-o FILE, the log a build without a console - MComix.exe on
    Windows - is read by; and what nothing caught, which Python writes
    to a standard error such a build does not have."""

    def setUp(self):
        self.logger = logging.getLogger('mcomix')
        self.handlers = list(self.logger.handlers)
        self.addCleanup(setattr, self.logger, 'handlers', self.handlers)
        self.addCleanup(self.logger.setLevel, self.logger.level)
        self.logger.setLevel(logging.DEBUG)
        fd, self.path = tempfile.mkstemp(suffix='.log')
        os.close(fd)
        self.addCleanup(os.unlink, self.path)
        self.addCleanup(self._close_file_handlers)

    def _close_file_handlers(self):
        for handler in self.logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.close()

    def _written(self):
        for handler in self.logger.handlers:
            handler.flush()
        with open(self.path, encoding='utf-8') as fp:
            return fp.read()

    def test_the_log_goes_to_the_file_as_well(self):
        with open(self.path, 'w') as fp:
            fp.write('the log of the time before\n')
        mcomix.log.log_to_file(self.path)
        mcomix.log.debug('Page %d is available', 1)
        written = self._written()
        self.assertNotIn('the time before', written)
        self.assertRegex(written, r'DEBUG: Page 1 is available')

    def test_what_nothing_caught_is_logged_with_its_traceback(self):
        self.addCleanup(setattr, sys, 'excepthook', sys.excepthook)
        self.addCleanup(setattr, threading, 'excepthook', threading.excepthook)
        mcomix.log.log_to_file(self.path)
        mcomix.log.log_uncaught_exceptions()
        try:
            raise TypeError("Couldn't find foreign struct converter")
        except TypeError as error:
            sys.excepthook(type(error), error, error.__traceback__)
        try:
            raise ValueError('in a worker')
        except ValueError as error:
            thread = threading.Thread(name='extract')
            threading.excepthook(threading.ExceptHookArgs(
                (type(error), error, error.__traceback__, thread)))
        written = self._written()
        self.assertIn('ERROR: Uncaught exception\nTraceback', written)
        self.assertIn("TypeError: Couldn't find foreign struct converter",
                      written)
        self.assertIn('Uncaught exception in thread extract\nTraceback',
                      written)
        self.assertIn('ValueError: in a worker', written)
