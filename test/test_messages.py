# -*- coding: utf-8 -*-

"""The translation template against the strings the source actually marks.

A msgid that never reaches mcomix.pot cannot be translated, in any
language, however complete a catalogue looks; one that lingers after its
string is gone wastes a translator's attention. Both drift in silently,
because nothing about a stale template shows up when the program runs.
"""

import gettext
import glob
import os
import shutil
import subprocess
import unittest

from . import MComixTest

from mcomix import constants


MESSAGES_PATH = os.path.join(constants.BASE_PATH, 'mcomix', 'messages')
TEMPLATE_PATH = os.path.join(MESSAGES_PATH, 'mcomix.pot')


def read_msgids(path):
    """The set of msgids <path> defines, ignoring obsolete entries and
    the header, whose msgid is empty."""
    msgids, parts, reading = set(), [], False
    with open(path, encoding='utf-8') as catalogue:
        for line in catalogue:
            line = line.rstrip('\n')
            if line.startswith('msgid '):
                reading, parts = True, [line[len('msgid '):]]
            elif reading and line.startswith('"'):
                parts.append(line)
            elif reading:
                msgids.add(''.join(part[1:-1] for part in parts))
                reading = False
    if reading:
        msgids.add(''.join(part[1:-1] for part in parts))
    msgids.discard('')
    return msgids


def read_catalogue(path):
    """What a compiled catalogue translates, without its header."""
    with open(path, 'rb') as catalogue:
        translations = dict(gettext.GNUTranslations(catalogue)._catalog)
    translations.pop('', None)
    return translations


@unittest.skipIf(shutil.which('xgettext') is None, 'xgettext is not installed')
class TemplateTest(MComixTest):

    """mcomix.pot names every string the source marks for translation."""

    def _extract(self):
        """The msgids xgettext finds in the source right now. The file set
        is the one wiki/content/Maintenance.md documents.

        The header is kept, though read_msgids() drops it again: it is
        where xgettext states the encoding it wrote, and asked to omit
        it xgettext writes ASCII instead and drops what will not fit -
        a msgid of "Rotate 90° CW" comes back as "Rotate 90 CW".
        """
        extracted = os.path.join(self.tmp_dir, 'extracted.pot')
        sources = []
        for pattern in ('mcomix/*.py', 'mcomix/archive/*.py',
                        'mcomix/library/*.py'):
            sources.extend(sorted(glob.glob(
                os.path.join(constants.BASE_PATH, pattern))))
        self.assertTrue(sources, 'no sources to extract from')
        subprocess.run(
            ['xgettext', '-LPython', '-o', extracted, '--from-code=utf-8']
            + sources,
            check=True, capture_output=True)
        return read_msgids(extracted)

    def test_the_template_holds_every_marked_string(self):
        missing = self._extract() - read_msgids(TEMPLATE_PATH)
        self.assertEqual(set(), missing,
                         'strings the source marks that mcomix.pot lacks; '
                         'regenerate it as wiki/content/Maintenance.md says')

    def test_the_template_holds_nothing_the_source_dropped(self):
        stale = read_msgids(TEMPLATE_PATH) - self._extract()
        self.assertEqual(set(), stale,
                         'strings in mcomix.pot the source no longer marks; '
                         'regenerate it as wiki/content/Maintenance.md says')

    @unittest.skipIf(shutil.which('msgfmt') is None, 'msgfmt is not installed')
    def test_every_catalogue_is_compiled(self):
        """The .mo beside each .po says what the .po says.

        gettext reads the .mo and nothing reads the .po, so a
        translation that was never compiled is not a translation: it is
        a file saying what the program would have said if anyone had
        run msgfmt. The header is left out of the comparison, being
        stamped with the time it was compiled at."""
        for path in sorted(glob.glob(
                os.path.join(MESSAGES_PATH, '*', 'LC_MESSAGES', 'mcomix.po'))):
            name = os.path.relpath(path, constants.BASE_PATH)
            compiled = path[:-len('.po')] + '.mo'
            self.assertTrue(os.path.isfile(compiled),
                            '%s was never compiled' % name)
            fresh = os.path.join(self.tmp_dir, 'fresh.mo')
            subprocess.run(['msgfmt', path, '-o', fresh],
                           check=True, capture_output=True)
            self.assertEqual(read_catalogue(fresh), read_catalogue(compiled),
                             '%s is out of step with its catalogue; compile '
                             'it as wiki/content/Maintenance.md says' % name)

    def test_every_catalogue_covers_the_template(self):
        template = read_msgids(TEMPLATE_PATH)
        for path in sorted(glob.glob(
                os.path.join(MESSAGES_PATH, '*', 'LC_MESSAGES', 'mcomix.po'))):
            missing = template - read_msgids(path)
            self.assertEqual(set(), missing,
                             '%s is behind the template; msgmerge it'
                             % os.path.relpath(path, constants.BASE_PATH))


# vim: expandtab:sw=4:ts=4
