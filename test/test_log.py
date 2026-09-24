"""The log MComix writes to its standard output."""

import io
import logging
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
