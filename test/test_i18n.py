"""Which language the interface is in, and which way it is laid out."""

import glob
import locale
import os
import re
import unittest.mock

from gi.repository import Gtk

from . import MComixTest

from mcomix import constants, i18n, portability, run
from mcomix.preferences import prefs


MESSAGES_PATH = os.path.join(constants.BASE_PATH, 'mcomix', 'messages')

#: Languages written right to left, by primary subtag. The ones MComix
#: has no catalogue for belong here as well: the list is here to
#: recognise a catalogue that turns up later, not to describe the ones
#: that ship today.
RTL_LANGUAGES = frozenset((
    'ar',    # Arabic
    'arc',   # Aramaic
    'ckb',   # Central Kurdish
    'dv',    # Divehi
    'fa',    # Persian
    'he',    # Hebrew
    'ks',    # Kashmiri
    'nqo',   # N'Ko
    'ps',    # Pashto
    'sd',    # Sindhi
    'syr',   # Syriac
    'ug',    # Uyghur
    'ur',    # Urdu
    'yi',    # Yiddish
))

#: Script subtags written right to left, for the languages that are
#: written in more than one script: pa_Arab reads right to left where
#: pa does not.
RTL_SCRIPTS = frozenset(('Adlm', 'Arab', 'Hebr', 'Nkoo', 'Syrc', 'Thaa'))


class LanguageTest(MComixTest):

    """install_gettext() resolves a language from one of three sources."""

    def setUp(self):
        super().setUp()
        self._saved = (i18n._language, i18n._translation,
                       os.environ.get('LANGUAGE'))
        self._saved_locale = portability.get_default_locale

    def tearDown(self):
        portability.get_default_locale = self._saved_locale
        i18n._language, i18n._translation, language = self._saved
        if language is None:
            os.environ.pop('LANGUAGE', None)
        else:
            os.environ['LANGUAGE'] = language
        super().tearDown()

    def test_forced_language_wins(self):
        i18n.install_gettext('he')
        self.assertEqual('he', i18n.get_language())

    def test_preference_is_used_when_set(self):
        prefs['language'] = 'fa'
        i18n.install_gettext()
        self.assertEqual('fa', i18n.get_language())

    def test_locale_is_used_when_the_preference_is_auto(self):
        prefs['language'] = 'auto'
        portability.get_default_locale = lambda: 'he_IL'
        i18n.install_gettext()
        self.assertEqual('he_IL', i18n.get_language())

    def test_the_search_loop_does_not_overwrite_the_language(self):
        # install_gettext() reuses the name while looking for a catalogue,
        # and 'he_IL' has none: the loop runs to its end on 'he'.
        prefs['language'] = 'auto'
        portability.get_default_locale = lambda: 'he_IL'
        i18n.install_gettext()
        self.assertEqual('he_IL', i18n.get_language())

    def test_a_locale_the_system_lacks_does_not_stop_startup(self):
        # The environment routinely names a locale that was never
        # generated; setlocale() answers that with locale.Error.
        prefs['language'] = 'auto'
        portability.get_default_locale = lambda: 'fr_FR'
        with unittest.mock.patch.object(
                locale, 'setlocale',
                side_effect=locale.Error('unsupported locale setting')):
            i18n.install_gettext()
        # The C locale only decides formatting, so the language survives.
        self.assertEqual('fr_FR', i18n.get_language())

    def test_rtl_languages(self):
        for language in ('he', 'fa', 'he_IL', 'fa_IR', 'he.UTF-8', 'he@quot'):
            i18n._language = language
            self.assertTrue(i18n.is_rtl_language(), language)

    def test_ltr_languages(self):
        for language in ('C', 'en', 'en_US', 'de', 'ja', 'zh_TW', 'hebrew'):
            i18n._language = language
            self.assertFalse(i18n.is_rtl_language(), language)


class LayoutDirectionTest(MComixTest):

    """The interface is laid out the way its language reads."""

    def setUp(self):
        super().setUp()
        self._saved_direction = Gtk.Widget.get_default_direction()
        self._saved_language = i18n._language

    def tearDown(self):
        Gtk.Widget.set_default_direction(self._saved_direction)
        i18n._language = self._saved_language
        super().tearDown()

    def test_a_right_to_left_language_turns_the_interface_around(self):
        Gtk.Widget.set_default_direction(Gtk.TextDirection.LTR)
        i18n._language = 'he'
        run.apply_layout_direction()
        self.assertEqual(Gtk.TextDirection.RTL,
                         Gtk.Widget.get_default_direction())

    def test_a_left_to_right_language_leaves_it_alone(self):
        Gtk.Widget.set_default_direction(Gtk.TextDirection.LTR)
        i18n._language = 'de'
        run.apply_layout_direction()
        self.assertEqual(Gtk.TextDirection.LTR,
                         Gtk.Widget.get_default_direction())


class CatalogueDirectionTest(MComixTest):

    """i18n._RTL_LANGUAGES names the catalogues that read right to left.

    That set is written out by hand, pango_language_get_direction()
    having no introspection binding, so nothing in the program tells it
    about a catalogue added afterwards. A translation into Arabic would
    be laid out left to right without a word about it anywhere, and
    only a reader of that language would ever see it."""

    def _catalogue_languages(self):
        """The languages mcomix/messages holds a catalogue for."""
        return set(
            os.path.basename(os.path.dirname(os.path.dirname(path)))
            for path in glob.glob(os.path.join(
                MESSAGES_PATH, '*', 'LC_MESSAGES', 'mcomix.po')))

    def test_every_right_to_left_catalogue_is_named(self):
        overlooked = set()
        for language in self._catalogue_languages():
            subtags = re.split(r'[-_.@]', language)
            script_reads_rtl = not RTL_SCRIPTS.isdisjoint(subtags[1:])
            if subtags[0] in RTL_LANGUAGES or script_reads_rtl:
                if subtags[0] not in i18n._RTL_LANGUAGES:
                    overlooked.add(language)
        self.assertEqual(set(), overlooked,
                         'catalogues in a language that reads right to '
                         'left which i18n._RTL_LANGUAGES leaves out, so '
                         'the interface stays laid out left to right')

    def test_nothing_is_named_without_a_catalogue(self):
        # A language nobody has translated MComix into is never the
        # interface language, so naming it here would say nothing; a
        # name that has lost its catalogue, or was misspelt, says
        # something false about what the set covers.
        catalogues = set(re.split(r'[-_.@]', language)[0]
                         for language in self._catalogue_languages())
        self.assertEqual(set(), i18n._RTL_LANGUAGES - catalogues,
                         'languages i18n._RTL_LANGUAGES names that '
                         'mcomix/messages has no catalogue for')


# vim: expandtab:sw=4:ts=4
