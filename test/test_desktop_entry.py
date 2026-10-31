""" The desktop entry, which file managers read to start MComix. """

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from gi.repository import Gio

_ENTRY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'share', 'applications', 'mcomix.desktop')


def _desktop_app_info(path):
    """The entry at <path>, as GIO reads it to launch it."""
    import gi
    try:
        gi.require_version('GioUnix', '2.0')
        from gi.repository import GioUnix
    except (ImportError, ValueError):
        return Gio.DesktopAppInfo.new_from_filename(path)
    return GioUnix.DesktopAppInfo.new_from_filename(path)


@unittest.skipIf(sys.platform == 'win32', 'desktop entries are for Unix desktops')
class DesktopEntryTest(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)

    def test_several_files_open_in_one_mcomix(self):
        """The entry said %f, which tells a file manager that MComix
        takes one file at a time, so opening five books from one
        selection started five MComix, each reading its own book with
        the rest of its folder.  MComix takes several files, and reads
        just those, one after the other, as it does with a drop or a
        choice of several in its own file chooser."""
        launches = os.path.join(self.tmp_dir, 'launches')
        script = os.path.join(self.tmp_dir, 'mcomix')
        with open(script, 'w') as handle:
            handle.write('#!/bin/sh\necho "$#" >> "%s"\n' % launches)
        os.chmod(script, stat.S_IRWXU)
        with open(_ENTRY) as entry:
            text = entry.read()
        self.assertIn('\nExec=mcomix ', text)
        probe = os.path.join(self.tmp_dir, 'probe.desktop')
        with open(probe, 'w') as entry:
            entry.write(text.replace('\nExec=mcomix ', '\nExec=%s ' % script))
        books = []
        for name in ('one.cbz', 'two.cbz'):
            books.append(os.path.join(self.tmp_dir, name))
            open(books[-1], 'wb').close()

        _desktop_app_info(probe).launch(
            [Gio.File.new_for_path(book) for book in books], None)

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not os.path.exists(launches):
            time.sleep(0.05)
        # Long enough for a second launch, had there been one, to write.
        time.sleep(0.3)
        with open(launches) as handle:
            self.assertEqual(['2'], handle.read().split())


_METAINFO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'share', 'metainfo', 'mcomix.metainfo.xml')


class ValidatorsTest(unittest.TestCase):

    """The entry and the AppStream metainfo, as the desktops' own
    checkers read them: desktop-file-validate (desktop-file-utils) and
    appstreamcli (appstream), which distributions and Flathub run on
    what they ship.  Neither ran anywhere before."""

    def _run(self, *command):
        result = subprocess.run(command, capture_output=True, text=True,
                                env=dict(os.environ, LC_ALL='C'), timeout=60)
        return result.returncode, (result.stdout + result.stderr).strip()

    @unittest.skipUnless(shutil.which('desktop-file-validate'),
                         'desktop-file-utils is not installed')
    def test_the_desktop_entry_validates(self):
        self.assertEqual((0, ''), self._run('desktop-file-validate', _ENTRY))

    @unittest.skipUnless(shutil.which('appstreamcli'),
                         'appstream is not installed')
    def test_the_metainfo_validates(self):
        code, output = self._run('appstreamcli', 'validate', '--no-net',
                                 _METAINFO)
        self.assertEqual(0, code, output)

    @unittest.skipUnless(shutil.which('appstreamcli'),
                         'appstream is not installed')
    def test_the_metainfo_the_flatpak_installs_validates(self):
        """The manifest rewrites the component id and the launchable;
        the copy it installs is validated as it is written."""
        with open(_METAINFO, encoding='utf-8') as fp:
            text = fp.read()
        flatpak_id = 'io.github.twwn.mcomix'
        text = text.replace('<id>net.sourceforge.mcomix</id>',
                            '<id>%s</id>' % flatpak_id)
        text = text.replace('>mcomix.desktop</launchable>',
                            '>%s.desktop</launchable>' % flatpak_id)
        path = os.path.join(tempfile.mkdtemp(), flatpak_id + '.metainfo.xml')
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write(text)
        code, output = self._run('appstreamcli', 'validate', '--no-net', path)
        self.assertEqual(0, code, output)


_MESSAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'mcomix', 'messages')


def _languages():
    """The languages MComix has a catalogue for."""
    return sorted(name for name in os.listdir(_MESSAGES)
                  if os.path.isfile(os.path.join(_MESSAGES, name, 'LC_MESSAGES',
                                                 'mcomix.po')))


class TranslatedEntriesTest(unittest.TestCase):

    """What file managers, menus and software centres show of MComix,
    in each language MComix speaks.  The entry had its generic name in
    four languages and its comment in seven, the metainfo its summary
    and description in English alone, of 24 catalogues."""

    def setUp(self):
        with open(_ENTRY, encoding='utf-8') as fp:
            self.entry = fp.read()
        with open(_METAINFO, encoding='utf-8') as fp:
            self.metainfo = fp.read()

    def test_there_are_catalogues_to_compare_with(self):
        self.assertGreater(len(_languages()), 20)

    def test_the_entry_speaks_each_language(self):
        for language in _languages():
            with self.subTest(language=language):
                for key in ('GenericName', 'Comment', 'Keywords'):
                    self.assertRegex(self.entry, r'(?m)^%s\[%s\]=\S'
                                     % (key, re.escape(language)))

    def test_the_metainfo_speaks_each_language(self):
        from xml.etree import ElementTree
        root = ElementTree.fromstring(self.metainfo)
        lang = '{http://www.w3.org/XML/1998/namespace}lang'
        summaries = {element.get(lang) for element in root.findall('summary')}
        paragraphs = [element.get(lang)
                      for element in root.find('description').findall('p')]
        english = paragraphs.count(None)
        self.assertGreater(english, 0)
        for language in _languages():
            with self.subTest(language=language):
                self.assertIn(language, summaries)
                self.assertEqual(english, paragraphs.count(language))

    def test_the_entry_offers_mcomix_for_each_kind_of_book(self):
        """For every type MComix reads as a book; ZIP, RAR, 7z and tar
        archives in general are left out, most of them being no book."""
        from mcomix import constants
        listed = set(re.search(r'(?m)^MimeType=(.*)$', self.entry).group(1)
                     .strip(';').split(';'))
        archives = {'application/x-zip', 'application/zip',
                    'application/x-zip-compressed', 'application/x-rar',
                    'application/x-7z-compressed', 'application/x-tar',
                    'application/x-gzip', 'application/x-bzip2'}
        for name in dir(constants):
            if name.endswith('_FORMATS'):
                with self.subTest(formats=name):
                    self.assertEqual(set(), set(getattr(constants, name)[0])
                                     - listed - archives)
        self.assertEqual(set(), archives & listed)

    def test_each_calver_release_links_its_page(self):
        """A software centre shows what changed in a release from its
        details link."""
        from xml.etree import ElementTree
        root = ElementTree.fromstring(self.metainfo)
        releases = root.find('releases').findall('release')
        calver = [release for release in releases
                  if re.fullmatch(r'\d\d\.\d\d(\.\d+)?', release.get('version'))]
        self.assertTrue(calver)
        for release in calver:
            with self.subTest(version=release.get('version')):
                url = release.find('url')
                self.assertEqual('details', url.get('type'))
                self.assertEqual('https://github.com/twwn/mcomix/releases/tag/'
                                 + release.get('version'), url.text)

# vim: expandtab:sw=4:ts=4
