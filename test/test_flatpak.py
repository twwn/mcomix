"""The Flatpak manifest, and the Flathub copy written from it.

flatpak-builder is not run here: a build takes minutes and fetches the
runtime.  What is checked is what the manifest relies on in the tree,
which a change elsewhere could break without anyone building it.
"""

import os
import re
import subprocess
import sys
import unittest.mock

from . import MComixTest

from mcomix import run
from mcomix.archive import pdf_multi
from mcomix.version_tools import Version

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, 'flatpak', 'io.github.twwn.mcomix.yml')
SCRIPT = os.path.join(ROOT, 'flatpak', 'flathub_manifest.py')
COMMIT = '0123456789abcdef0123456789abcdef01234567'

sys.path.insert(0, os.path.dirname(SCRIPT))
import flathub_manifest  # noqa: E402
sys.path.pop(0)


def _manifest():
    with open(MANIFEST, encoding='utf-8') as manifest:
        return manifest.read()


class ManifestTest(MComixTest):

    def test_the_id_is_the_fork_s_and_the_files_are_renamed_to_it(self):
        text = _manifest()
        self.assertIn('app-id: io.github.twwn.mcomix\n', text)
        self.assertIn('rename-icon: mcomix\n', text)
        self.assertIn('rename-desktop-file: mcomix.desktop\n', text)
        # Renaming the AppStream file would list net.sourceforge.mcomix,
        # the original MComix, as an id this one provides.
        self.assertNotRegex(text, r'(?m)^rename-appdata-file:')

    def test_the_files_it_renames_are_where_it_takes_them_from(self):
        share = os.path.join(ROOT, 'share')
        for path in ('applications/mcomix.desktop',
                     'icons/hicolor/scalable/apps/mcomix.svg',
                     'mime/packages/mcomix.xml'):
            self.assertTrue(os.path.isfile(os.path.join(share, path)), path)

    def test_the_appstream_id_and_launchable_it_rewrites_are_there(self):
        """The build rewrites both with sed, which finds nothing to
        rewrite, silently, once the file says them another way."""
        with open(os.path.join(ROOT, 'share', 'metainfo',
                               'mcomix.metainfo.xml'),
                  encoding='utf-8') as metainfo:
            text = metainfo.read()
        self.assertEqual(1, text.count('<id>net.sourceforge.mcomix</id>'))
        self.assertEqual(1, text.count('>mcomix.desktop</launchable>'))
        manifest = _manifest()
        self.assertIn('s|<id>net.sourceforge.mcomix</id>|', manifest)
        self.assertIn('s|>mcomix.desktop</launchable>|', manifest)

    def test_its_pymupdf_is_one_the_native_pdf_reader_takes(self):
        versions = set(re.findall(r'/pymupdf-([\d.]+)-', _manifest()))
        self.assertEqual(1, len(versions), versions)
        self.assertGreaterEqual(Version(versions.pop()),
                                Version(pdf_multi.PYMUPDF_VERSION_REQUIRED))

    def test_every_downloaded_source_carries_a_checksum(self):
        sources = re.findall(r'^      - type: (?:file|archive)\n((?:        .*\n)+)',
                             _manifest(), re.MULTILINE)
        # unrar, djvulibre, pybind11, Pillow, chardet, PyMuPDF twice.
        self.assertEqual(7, len(sources))
        for source in sources:
            self.assertRegex(source, r'(?m)^        sha256: [0-9a-f]{64}$')


class FlathubManifestTest(MComixTest):

    def test_mcomix_is_fetched_from_the_tag_and_nothing_else_changes(self):
        original = _manifest()
        released = flathub_manifest.flathub_manifest(original, '26.10', COMMIT)
        local = original.index('      - type: dir\n')
        self.assertEqual(original[:local], released[:local])
        self.assertEqual(
            "      - type: git\n"
            "        url: https://github.com/twwn/mcomix.git\n"
            "        tag: '26.10'\n"
            "        commit: %s\n" % COMMIT,
            ''.join(released[local:].splitlines(True)[:4]))
        self.assertNotIn('type: dir', released)

    def test_a_second_release_of_a_month_is_a_tag_as_well(self):
        released = flathub_manifest.flathub_manifest(_manifest(), '26.10.1',
                                                     COMMIT)
        self.assertIn("tag: '26.10.1'\n", released)

    def test_what_is_not_a_release_is_refused(self):
        for tag, commit in (('main', COMMIT), ('v26.10', COMMIT),
                            ('26.10', 'abc123')):
            with self.subTest(tag=tag, commit=commit):
                with self.assertRaises(ValueError):
                    flathub_manifest.flathub_manifest(_manifest(), tag,
                                                      commit)

    def test_the_script_writes_it(self):
        written = subprocess.run(
            [sys.executable, SCRIPT, '26.10', COMMIT], check=True,
            capture_output=True, encoding='utf-8').stdout
        self.assertEqual(
            flathub_manifest.flathub_manifest(_manifest(), '26.10', COMMIT),
            written)


class ProgramNameTest(MComixTest):

    """The window class a desktop matches the window to its launcher
    by: the launcher is mcomix.desktop installed, and named after the
    app id in the Flatpak."""

    def test_installed_it_is_mcomix(self):
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop('FLATPAK_ID', None)
            self.assertEqual('MComix', run.program_name())

    def test_in_the_flatpak_it_is_the_app_id(self):
        with unittest.mock.patch.dict(os.environ,
                                      FLATPAK_ID='io.github.twwn.mcomix'):
            self.assertEqual('io.github.twwn.mcomix', run.program_name())

# vim: expandtab:sw=4:ts=4
