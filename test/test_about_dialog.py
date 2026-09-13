"""The About dialog's sentence on what MComix reads."""

import ast
import gettext
import os
import unittest
from unittest import mock

from mcomix import about_dialog
from mcomix import archive_tools
from mcomix import constants

MESSAGES_PATH = os.path.join(constants.BASE_PATH, 'mcomix', 'messages')

#: How the sentence writes a format that get_supported_formats() names
#: otherwise.
SPELLINGS = {'Tar': 'tar', 'MobiPocket': 'AZW3'}


def description():
    """The sentence in about_dialog.py that lists the formats."""
    with open(about_dialog.__file__, encoding='utf-8') as fp:
        tree = ast.parse(fp.read())
    found = [node.args[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and getattr(node.func, 'id', None) == '_'
             and node.args and isinstance(node.args[0], ast.Constant)
             and node.args[0].value.startswith('It reads ')]
    assert len(found) == 1, found
    return found[0]


def formats():
    """Every format MComix reads, whether or not its handler is installed
    where the test runs."""
    available = dict.fromkeys(('rar_available', 'szip_available',
                               'lha_available', 'pdf_available',
                               'mobi_available'), lambda: True)
    with mock.patch.multiple(archive_tools, **available):
        return [SPELLINGS.get(name, name)
                for name in archive_tools.get_supported_formats()]


class FormatsTest(unittest.TestCase):

    """The dialog said MComix reads "ZIP, RAR and tar archives", leaving out
    7z, LHA, PDF and AZW3, which it had read for years."""

    def test_the_sentence_names_every_format(self):
        self.assertIn('AZW3', formats())
        missing = [name for name in formats() if name not in description()]
        self.assertEqual([], missing)

    def test_every_translation_names_every_format(self):
        languages = sorted(
            language for language in os.listdir(MESSAGES_PATH)
            if os.path.isdir(os.path.join(MESSAGES_PATH, language)))
        self.assertEqual(24, len(languages))
        for language in languages:
            with self.subTest(language=language):
                text = gettext.translation(
                    'mcomix', MESSAGES_PATH,
                    languages=[language]).gettext(description())
                # An untranslated sentence would name them all in English.
                self.assertNotEqual(description(), text)
                self.assertEqual([], [name for name in formats()
                                      if name.lower() not in text.lower()])

# vim: expandtab:sw=4:ts=4
