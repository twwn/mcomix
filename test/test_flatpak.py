"""The Flatpak manifest, and the Flathub copy written from it.

flatpak-builder is not run here: a build takes minutes and fetches the
runtime.  What is checked is what the manifest relies on in the tree,
which a change elsewhere could break without anyone building it.
"""

import os
import re
import subprocess
import sys
import tempfile
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
import keep_manifest_format  # noqa: E402
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

    def test_its_pymupdf_comes_without_the_layout_analysis(self):
        """PyMuPDF 2.0 requires onnxruntime, numpy, networkx and the rest
        of its layout analysis, which pip, given only the wheel, could
        not find; the module imports none of them."""
        module = re.search(r'(?ms)^  - name: python3-PyMuPDF\n.*?^    sources:',
                           _manifest()).group(0)
        self.assertIn('--no-deps', module)

    def test_its_unrar_is_a_release_not_a_beta(self):
        """The checker reads rar_add.htm, which links RARLAB's newest
        source, a beta as often as not: unrarsrc-7.3.1, which the
        manifest had, was RAR 7.30 beta 1.  A beta stops the build."""
        module = re.search(r'(?ms)^  - name: unrar\n.*?^    sources:',
                           _manifest()).group(0)
        build = re.search(r'(?ms)^    build-commands:\n(.*)', module).group(1)
        self.assertTrue(build.lstrip().startswith(
            '''- test "$(sed -n 's/^#define RARVER_BETA *//p' version.hpp)" = 0'''),
            build)

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


class KeepManifestFormatTest(MComixTest):
    """What flatpak-updates.yml does to the checker's manifest."""

    # A source and a command of the manifest, and the same two as ruamel.yaml
    # writes them in flatpak-external-data-checker's settings.
    OLD = (
        "      - make -C Bundles/Alone2 -j ${FLATPAK_BUILDER_N_JOBS} -f ../../cmpl_gcc.mak\n"
        "        CFLAGS_WARN_WALL=\"-Wall -Wextra\"\n"
        "    sources:\n"
        "      # The checker's comment stays.\n"
        "      - type: git\n"
        "        tag: '1.4.4'\n"
        "        commit: ddda911\n"
        "        url-query: '.urls[] | select(.filename | test(\"-x86_64\\\\.whl$\")) | .url'\n"
        "        url: https://files.pythonhosted.org/packages/33/fd/8762f7ee3e4e4be6d1d846cffb4916dd9bb02b2f800d3603718a0efe494c/a-1.whl\n")
    REWRITTEN = (
        "      - make -C Bundles/Alone2 -j ${FLATPAK_BUILDER_N_JOBS} -f \n"
        "        ../../cmpl_gcc.mak CFLAGS_WARN_WALL=\"-Wall -Wextra\"\n"
        "    sources:\n"
        "      # The checker's comment stays.\n"
        "      - type: git\n"
        "        tag: 1.4.4\n"
        "        commit: ddda911\n"
        "        url-query: .urls[] | select(.filename | \n"
        "          test(\"-x86_64\\\\.whl$\")) | .url\n"
        "        url: \n"
        "          https://files.pythonhosted.org/packages/33/fd/8762f7ee3e4e4be6d1d846cffb4916dd9bb02b2f800d3603718a0efe494c/a-1.whl\n")

    def test_a_rewrite_with_no_new_value_leaves_nothing(self):
        self.assertEqual(
            self.OLD, keep_manifest_format.keep_format(self.OLD, self.REWRITTEN))

    def test_a_new_value_is_all_that_changes(self):
        kept = keep_manifest_format.keep_format(
            self.OLD, self.REWRITTEN.replace('ddda911', 'abc1234'))
        self.assertEqual(self.OLD.replace('ddda911', 'abc1234'), kept)

    def test_a_new_value_stays_in_its_quotes(self):
        kept = keep_manifest_format.keep_format(
            self.OLD, self.REWRITTEN.replace('tag: 1.4.4', 'tag: 1.4.5'))
        self.assertEqual(self.OLD.replace("'1.4.4'", "'1.4.5'"), kept)

    def test_a_new_value_where_the_checker_kept_the_quotes(self):
        kept = keep_manifest_format.keep_format(
            "tag: '26.05'\n", "tag: '26.06'\n")
        self.assertEqual("tag: '26.06'\n", kept)

    def test_more_than_new_values_stays_as_the_checker_wrote_it(self):
        rewritten = self.REWRITTEN + '        size: 1234\n'
        self.assertEqual(
            rewritten, keep_manifest_format.keep_format(self.OLD, rewritten))

    def test_the_manifest_comes_through_a_rewrite_unchanged(self):
        text = _manifest()
        rewritten = re.sub(r'(?m)^( *)url: ', r'\1url: \n\1  ', text)
        rewritten = rewritten.replace(" --prefix=", "\n  --prefix=")
        rewritten = rewritten.replace("tag: '1.4.4'", 'tag: 1.4.4')
        self.assertNotEqual(text, rewritten)
        self.assertEqual(
            text, keep_manifest_format.keep_format(text, rewritten))

    def test_the_script_overwrites_what_the_checker_wrote(self):
        with tempfile.TemporaryDirectory() as folder:
            old = os.path.join(folder, 'old.yml')
            new = os.path.join(folder, 'new.yml')
            for path, text in ((old, self.OLD), (new, self.REWRITTEN)):
                with open(path, 'w', encoding='utf-8', newline='\n') as written:
                    written.write(text)
            subprocess.run(
                [sys.executable,
                 os.path.join(ROOT, 'flatpak', 'keep_manifest_format.py'),
                 old, new],
                check=True)
            with open(new, encoding='utf-8') as written:
                self.assertEqual(self.OLD, written.read())


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
