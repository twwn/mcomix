"""The version the Windows builds stamp on what they build.

MComix is numbered by year and month, as 26.10, and both WiX and the
version resource of the executable want three numbers.  The scripts
under win32/ only ever run on Windows, at release time, so a version
they cannot read would first be found there; these tests run the part
that reads it here.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import types
import unittest.mock

from . import MComixTest

WIN32 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), 'win32')
sys.path.insert(0, WIN32)
try:
    import build_msi
    import build_pyinstaller
finally:
    sys.path.remove(WIN32)


class VersionTripletTest(MComixTest):

    def test_a_year_and_a_month_get_a_third_number(self):
        self.assertEqual((26, 10, 0), build_msi.version_triplet('26.10'))

    def test_three_numbers_are_kept(self):
        self.assertEqual((26, 10, 1), build_msi.version_triplet('26.10.1'))
        self.assertEqual((4, 0, 1), build_msi.version_triplet('4.0.1'))

    def test_a_suffix_is_left_out(self):
        self.assertEqual((26, 10, 0),
                         build_msi.version_triplet('26.10-dev0'))

    def test_no_number_at_all_is_an_error(self):
        with self.assertRaises(ValueError):
            build_msi.version_triplet('unknown')

    def test_wix_is_given_three_numbers(self):
        with unittest.mock.patch.object(build_msi, 'VERSION', '26.10'):
            self.assertEqual('26.10.0', build_msi.normalize_mcomix_version())


class VersionFileTest(MComixTest):

    """The version resource PyInstaller embeds in MComix.exe."""

    def test_a_year_and_a_month_are_written_as_four_numbers(self):
        os.mkdir(os.path.join(self.tmp_dir, 'win32'))
        shutil.copy(os.path.join(WIN32, 'version_file.template'),
                    os.path.join(self.tmp_dir, 'win32'))
        cwd = os.getcwd()
        os.chdir(self.tmp_dir)
        self.addCleanup(os.chdir, cwd)

        with unittest.mock.patch.object(build_pyinstaller.constants,
                                        'VERSION', '26.10'), \
                unittest.mock.patch('builtins.print'):
            build_pyinstaller.prepare_version_file()

        with open(os.path.join('win32', 'version_file.txt')) as fp:
            written = fp.read()
        self.assertIn('filevers=(26, 10, 0, 0)', written)
        self.assertIn('prodvers=(26, 10, 0, 0)', written)


class SpecDataTest(MComixTest):

    """What win32/mcomix.spec hands PyInstaller."""

    #: What Analysis answers with, as far as the spec reads it: a data
    #: file is (name in the bundle, source, kind).
    COLLECTED = [
        ('share/icons/Adwaita/symbolic/actions/go-next-symbolic.svg',
         '/ucrt64/share/icons/Adwaita/symbolic/actions/go-next-symbolic.svg',
         'DATA'),
        ('share/icons/Adwaita/cursors/default', '/ucrt64/share/icons/'
         'Adwaita/cursors/default', 'DATA'),
    ]

    def _run_spec(self):
        """Run the spec as PyInstaller does - from the top of the checkout,
        with its names defined - and answer with what it handed them."""
        found = {'EXE': []}

        def analysis(*args, **kwargs):
            found['Analysis'] = kwargs
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[],
                                         datas=list(self.COLLECTED))

        def exe(*args, **kwargs):
            found['EXE'].append(kwargs)
            return kwargs['name']

        def collect(*args, **kwargs):
            found['COLLECT'] = args, kwargs

        names = {'Analysis': analysis, 'PYZ': unittest.mock.Mock(),
                 'EXE': exe, 'COLLECT': collect}
        cwd = os.getcwd()
        os.chdir(os.path.dirname(WIN32))
        self.addCleanup(os.chdir, cwd)
        with open(os.path.join(WIN32, 'mcomix.spec')) as fp:
            exec(fp.read(), names)
        return found

    def test_every_image_is_packed(self):
        top = os.path.dirname(WIN32)
        packed = {os.path.normpath(os.path.join(WIN32, source))
                  for source, _ in self._run_spec()['Analysis']['datas']}
        images = {os.path.join(dirpath, filename)
                  for dirpath, _, filenames
                  in os.walk(os.path.join(top, 'mcomix', 'images'))
                  for filename in filenames
                  if filename.endswith(('.png', '.svg'))}
        self.assertEqual(set(), images - packed)

    def test_the_gtk_hooks_are_told_this_is_gtk_4(self):
        """Left to itself, PyInstaller's GTK hook looks for GTK 3, finds
        none, and collects neither the icon theme nor GTK's translations:
        the 26.09 zip had no share/icons and no gtk40.mo."""
        gi = self._run_spec()['Analysis']['hooksconfig']['gi']
        self.assertEqual('4.0', gi['module-versions']['Gtk'])
        self.assertIn('Adwaita', gi['icons'])

    def test_translations_are_collected_for_mcomix_languages_alone(self):
        messages = os.path.join(os.path.dirname(WIN32), 'mcomix', 'messages')
        catalogues = sorted(name for name in os.listdir(messages)
                            if os.path.isdir(os.path.join(messages, name)))
        self.assertGreater(len(catalogues), 20)
        gi = self._run_spec()['Analysis']['hooksconfig']['gi']
        self.assertEqual(catalogues, gi['languages'])

    def test_both_executables_are_built_in_one_run(self):
        """And share the code, which each carried a copy of inside it
        when the build ran PyInstaller once for each."""
        found = self._run_spec()
        self.assertTrue(found['Analysis']['noarchive'])
        self.assertEqual({'MComix': False, 'MComix.Console': True},
                         {exe['name']: exe['console'] for exe in found['EXE']})
        args, kwargs = found['COLLECT']
        self.assertEqual(['MComix', 'MComix.Console'], list(args[:2]))
        self.assertEqual('MComix', kwargs['name'])


class ChocolateyPackageTest(MComixTest):

    """What win32/build_msi.py leaves beside chocolateyinstall.ps1, and
    the installer the script then downloads."""

    def test_the_release_is_recorded_as_it_is_named(self):
        path = pathlib.Path(self.tmp_dir) / 'release.txt'
        with unittest.mock.patch.object(build_msi, 'RELEASE_PATH', path):
            build_msi.write_release('26.09')
        self.assertEqual('26.09\n', path.read_text())

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is not installed')
    def test_the_script_downloads_the_release_not_the_package_version(self):
        """Chocolatey gives the package's version back as a number, 26.9.0
        for 26.09; the release and its installer are named 26.09."""
        tools = pathlib.Path(self.tmp_dir)
        shutil.copy(pathlib.Path(__file__).parent.parent / 'win32' / 'tools'
                    / 'chocolateyinstall.ps1', tools)
        (tools / 'checksum.sha256').write_text('abc\n')
        (tools / 'release.txt').write_text('26.09\n')
        (tools / 'run.ps1').write_text(
            'function Install-ChocolateyPackage {'
            ' param([Parameter(ValueFromRemainingArguments)]$a) }\n'
            "$env:ChocolateyPackageName = 'mcomix-gtk'\n"
            "$env:ChocolateyPackageVersion = '26.9.0'\n"
            '. "$PSScriptRoot/chocolateyinstall.ps1"\n'
            '$packageArgs.url64bit\n')
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-File', str(tools / 'run.ps1')],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            'https://github.com/twwn/mcomix/releases/download/26.09/'
            'mcomix-win64-26.09.msi', result.stdout.strip())

# vim: expandtab:sw=4:ts=4
