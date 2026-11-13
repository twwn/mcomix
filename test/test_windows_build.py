"""The version the Windows builds stamp on what they build.

MComix is numbered by year and month, as 26.10, and both WiX and the
version resource of the executable want three numbers.  The scripts
under win32/ only ever run on Windows, at release time, so a version
they cannot read would first be found there; these tests run the part
that reads it here.
"""

import ast
import contextlib
import hashlib
import io
import os
import pathlib
import shutil
import subprocess
import sys
import types
import unittest.mock
from importlib import metadata

from mcomix.archive import pdf_multi

from . import MComixTest

WIN32 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), 'win32')
sys.path.insert(0, WIN32)
try:
    import build_msi
    import build_pyinstaller
    import check_imports
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

        with open(os.path.join('win32', 'version_file.txt'),
                  encoding='utf-8') as fp:
            written = fp.read()
        self.assertIn('filevers=(26, 10, 0, 0)', written)
        self.assertIn('prodvers=(26, 10, 0, 0)', written)

    def test_the_name_windows_shows_for_the_process_is_mcomix(self):
        """Task Manager names a process by its FileDescription: a
        sentence there stood in its list where MComix should."""
        with open(os.path.join(WIN32, 'version_file.template'),
                  encoding='utf-8') as fp:
            template = fp.read()
        self.assertIn("StringStruct('FileDescription', 'MComix')", template)


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

    #: The distributions whose metadata PyInstaller finds, by the folder
    #: it is in; MSYS2 has PyMuPDF under this name alone.
    INSTALLED = {'pymupdf-lite': 'pymupdf_lite-2.0.dist-info'}

    def _run_spec(self):
        """Run the spec as PyInstaller does - from the top of the checkout,
        with its names defined - and answer with what it handed them."""
        found = {'EXE': [], 'copy_metadata': []}

        def copy_metadata(name):
            found['copy_metadata'].append(name)
            if name not in self.INSTALLED:
                raise metadata.PackageNotFoundError(name)
            folder = self.INSTALLED[name]
            return [('/ucrt64/lib/python3.14/site-packages/' + folder, folder)]

        # PyInstaller itself, which only a machine that builds has.
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.copy_metadata = copy_metadata
        modules = unittest.mock.patch.dict(sys.modules, {
            'PyInstaller': types.ModuleType('PyInstaller'),
            'PyInstaller.utils': types.ModuleType('PyInstaller.utils'),
            'PyInstaller.utils.hooks': hooks})
        modules.start()
        self.addCleanup(modules.stop)

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
        with open(os.path.join(WIN32, 'mcomix.spec'), encoding='utf-8') as fp:
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

    def test_pymupdf_is_packed_with_the_record_of_its_version(self):
        """Without it pdf_multi.installed_version() has to import
        PyMuPDF to learn its version, and the bundle loaded libmupdf.dll
        and its bindings, 67 MB, at every start."""
        found = self._run_spec()
        self.assertEqual(list(pdf_multi.PYMUPDF_DISTRIBUTIONS),
                         found['copy_metadata'])
        self.assertIn(('/ucrt64/lib/python3.14/site-packages/'
                       'pymupdf_lite-2.0.dist-info',
                       'pymupdf_lite-2.0.dist-info'),
                      found['Analysis']['datas'])

    def test_a_build_without_pymupdf_packs_no_record_of_it(self):
        with unittest.mock.patch.object(self, 'INSTALLED', {}):
            datas = self._run_spec()['Analysis']['datas']
        self.assertEqual([], [name for _, name in datas
                              if name.endswith('.dist-info')])

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

    def test_the_cairo_glue_pygobject_imports_itself_is_packed(self):
        hidden = self._run_spec()['Analysis']['hiddenimports']
        self.assertIn('cairo', hidden)
        self.assertIn('gi._gi_cairo', hidden)

    def test_openssl_is_left_out(self):
        """PyGObject imports asyncio, asyncio imports ssl where it can,
        and hashlib prefers _hashlib: packed, they loaded libssl and
        libcrypto at every start, 6 MB for Windows to scan."""
        excluded = self._run_spec()['Analysis']['excludes']
        self.assertLessEqual({'ssl', '_ssl', '_hashlib'}, set(excluded))

    def test_mcomix_loads_without_openssl(self):
        """What the bundle has without them: every module the start
        imports, and the md5 thumbnails are named by."""
        home = os.path.join(self.tmp_dir, 'no-openssl')
        env = dict(os.environ, HOME=home, PYTHONPATH=os.path.dirname(WIN32))
        for name in ('CONFIG', 'DATA', 'CACHE', 'STATE'):
            env['XDG_%s_HOME' % name] = os.path.join(home, name.lower())
        script = (
            "import sys\n"
            "for name in ('ssl', '_ssl', '_hashlib'):\n"
            "    sys.modules[name] = None\n"
            "import gi\n"
            "gi.require_version('Gtk', '4.0')\n"
            "gi.require_version('Gdk', '4.0')\n"
            "import asyncio\n"
            "from mcomix import archive_tools, image_tools, main, run\n"
            "from mcomix import thumbnail_tools\n"
            "print(thumbnail_tools.md5(b'mcomix').hexdigest())\n")
        done = subprocess.run([sys.executable, '-c', script], env=env,
                              cwd=self.tmp_dir, capture_output=True,
                              text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(hashlib.md5(b'mcomix').hexdigest() + '\n',
                         done.stdout)

    def test_mcomix_exe_is_the_one_executable(self):
        """Without a console, as the desktop starts it; -W debug -o FILE
        is what its log is read by, where a second, console build each
        carried its own 5.7 MB copy of the code."""
        found = self._run_spec()
        self.assertEqual([('MComix', False)],
                         [(exe['name'], exe['console']) for exe in found['EXE']])
        args, kwargs = found['COLLECT']
        self.assertEqual('MComix', args[0])
        self.assertEqual('MComix', kwargs['name'])

    def test_the_program_glib_starts_the_session_bus_with_is_packed(self):
        """Without gdbus.exe beside libgio-2.0-0.dll, GLib could start no
        session bus, and a second MComix found none running to hand its
        files to."""
        found = []

        def which(name):
            found.append(name)
            return 'C:/msys64/ucrt64/bin/gdbus.exe'

        with unittest.mock.patch.object(sys, 'platform', 'win32'), \
                unittest.mock.patch.object(shutil, 'which', which):
            binaries = self._run_spec()['Analysis']['binaries']
        self.assertEqual(['gdbus.exe'], found)
        self.assertEqual([('C:/msys64/ucrt64/bin/gdbus.exe', '.')], binaries)

    def test_elsewhere_the_spec_packs_no_program_of_its_own(self):
        with unittest.mock.patch.object(sys, 'platform', 'linux'):
            self.assertEqual([], self._run_spec()['Analysis']['binaries'])

    def test_the_icon_theme_goes_without_its_cursors(self):
        args, _ = self._run_spec()['COLLECT']
        collected = [entry[0] for part in args[2:] for entry in part]
        self.assertEqual(
            ['share/icons/Adwaita/symbolic/actions/go-next-symbolic.svg'],
            collected)


class BundledLicencesTest(MComixTest):

    """Whose licences the Windows packages carry: every MSYS2 package
    whose files are in the bundle, found in MSYS2's package database."""

    def _package(self, root, name, files):
        entry = root / 'var' / 'lib' / 'pacman' / 'local' / (name + '-1.0-1')
        entry.mkdir(parents=True)
        (entry / 'desc').write_text('%NAME%\n' + name + '\n\n%VERSION%\n1.0-1\n')
        (entry / 'files').write_text('%FILES%\nucrt64/\nucrt64/bin/\n'
                                     + ''.join(f + '\n' for f in files)
                                     + '\n%BACKUP%\n')

    def test_the_packages_the_bundle_takes_files_from(self):
        root = pathlib.Path(self.tmp_dir) / 'msys64'
        prefix = root / 'ucrt64'
        self._package(root, 'mingw-w64-ucrt-x86_64-gtk4',
                      ['ucrt64/bin/libgtk-4-1.dll', 'ucrt64/share/doc/README',
                       'ucrt64/share/licenses/gtk4/COPYING'])
        # Its licence folder is not called after the package.
        self._package(root, 'mingw-w64-ucrt-x86_64-python',
                      ['ucrt64/bin/libpython3.14.dll',
                       'ucrt64/lib/python3.14/lib-dynload/_ssl.pyd',
                       'ucrt64/share/doc/README',
                       'ucrt64/share/licenses/python3.14/LICENSE'])
        self._package(root, 'mingw-w64-ucrt-x86_64-sqlite3',
                      ['ucrt64/bin/libsqlite3-0.dll',
                       'ucrt64/share/licenses/sqlite3/LICENSE'])
        bundle = pathlib.Path(self.tmp_dir) / 'MComix' / '_internal'
        for name in ('libgtk-4-1.dll', 'python3.14/lib-dynload/_ssl.pyd',
                     'README', 'mcomix/images/mcomix.png'):
            (bundle / name).parent.mkdir(parents=True, exist_ok=True)
            (bundle / name).write_text('')
        # README is both packages', so it names neither; sqlite3 has no
        # file in the bundle.
        self.assertEqual(['gtk4', 'python3.14'],
                         build_pyinstaller.bundled_licences(bundle, prefix))

    def test_without_a_package_database_the_known_ones(self):
        bundle = pathlib.Path(self.tmp_dir) / 'MComix' / '_internal'
        bundle.mkdir(parents=True)
        licences = build_pyinstaller.bundled_licences(
            bundle, pathlib.Path(self.tmp_dir) / 'nowhere')
        self.assertIn('gtk4', licences)
        self.assertIn('python-pymupdf', licences)


class SbomTest(MComixTest):

    """The SPDX document the release carries of the Windows bundle: the
    MSYS2 packages whose files it holds, as for their licences, and the
    programs fetched from elsewhere."""

    def _database(self):
        root = pathlib.Path(self.tmp_dir) / 'msys64'
        for name, version, licences, files in (
                ('mingw-w64-ucrt-x86_64-gtk4', '4.24.1-1',
                 ['spdx:LGPL-2.1-or-later'], ['ucrt64/bin/libgtk-4-1.dll']),
                ('mingw-w64-ucrt-x86_64-jxrlib', '1.1-4', ['custom'],
                 ['ucrt64/bin/libjpegxr.dll']),
                ('mingw-w64-ucrt-x86_64-sqlite3', '3.50.0-1', ['spdx:blessing'],
                 ['ucrt64/bin/libsqlite3-0.dll'])):
            entry = root / 'var' / 'lib' / 'pacman' / 'local' / ('%s-%s' % (name, version))
            entry.mkdir(parents=True)
            (entry / 'desc').write_text(
                '%%NAME%%\n%s\n\n%%VERSION%%\n%s\n\n%%URL%%\nhttps://example.org/%s\n\n'
                '%%LICENSE%%\n%s\n\n%%ARCH%%\nany\n' % (name, version, name, '\n'.join(licences)))
            (entry / 'files').write_text('%FILES%\n' + ''.join(f + '\n' for f in files) + '\n')
        bundle = pathlib.Path(self.tmp_dir) / 'MComix'
        (bundle / '_internal').mkdir(parents=True)
        (bundle / '_internal' / 'libgtk-4-1.dll').write_text('')
        # Beside MComix.exe, where JxrDecApp loads it from.
        (bundle / 'libjpegxr.dll').write_text('')
        return bundle, root / 'ucrt64'

    def _document(self, bundle, prefix, others=()):
        import json
        path = pathlib.Path(self.tmp_dir) / 'sbom.spdx.json'
        build_pyinstaller.write_sbom(path, bundle, prefix, '26.11', list(others))
        return json.loads(path.read_text(encoding='utf-8'))

    def test_it_names_mcomix_and_the_packages_in_the_bundle(self):
        bundle, prefix = self._database()
        document = self._document(bundle, prefix, [
            ('UnRAR.dll', '7.23', 'LicenseRef-UnRAR', 'https://www.rarlab.com/rar_add.htm')])
        self.assertEqual('SPDX-2.3', document['spdxVersion'])
        packages = {entry['name']: entry for entry in document['packages']}
        # sqlite3 has no file in the bundle.
        self.assertEqual(['MComix', 'mingw-w64-ucrt-x86_64-gtk4',
                          'mingw-w64-ucrt-x86_64-jxrlib', 'UnRAR.dll'],
                         [entry['name'] for entry in document['packages']])
        self.assertEqual('26.11', packages['MComix']['versionInfo'])
        self.assertEqual('GPL-2.0-or-later', packages['MComix']['licenseDeclared'])
        gtk = packages['mingw-w64-ucrt-x86_64-gtk4']
        self.assertEqual('4.24.1-1', gtk['versionInfo'])
        self.assertEqual('LGPL-2.1-or-later', gtk['licenseDeclared'])
        self.assertEqual('https://example.org/mingw-w64-ucrt-x86_64-gtk4',
                         gtk['downloadLocation'])
        self.assertEqual('Organization: MSYS2', gtk['supplier'])
        self.assertEqual('7.23', packages['UnRAR.dll']['versionInfo'])

    def test_mcomix_contains_each_package(self):
        bundle, prefix = self._database()
        document = self._document(bundle, prefix)
        ids = [entry['SPDXID'] for entry in document['packages']]
        self.assertEqual(len(ids), len(set(ids)))
        for spdx_id in ids:
            self.assertRegex(spdx_id, r'^SPDXRef-[A-Za-z0-9.-]+$')
        relationships = {(rel['spdxElementId'], rel['relationshipType'],
                          rel['relatedSpdxElement'])
                         for rel in document['relationships']}
        self.assertIn(('SPDXRef-DOCUMENT', 'DESCRIBES', ids[0]), relationships)
        for spdx_id in ids[1:]:
            self.assertIn((ids[0], 'CONTAINS', spdx_id), relationships)

    def test_a_licence_without_an_spdx_identifier_is_listed(self):
        """A LicenseRef the document uses has to be defined in it."""
        bundle, prefix = self._database()
        document = self._document(bundle, prefix)
        packages = {entry['name']: entry for entry in document['packages']}
        self.assertEqual('LicenseRef-custom',
                         packages['mingw-w64-ucrt-x86_64-jxrlib']['licenseDeclared'])
        self.assertEqual(['LicenseRef-custom'],
                         [info['licenseId'] for info in
                          document['hasExtractedLicensingInfos']])

    def test_without_a_package_database_mcomix_and_the_others(self):
        bundle = pathlib.Path(self.tmp_dir) / 'MComix'
        bundle.mkdir()
        document = self._document(bundle, pathlib.Path(self.tmp_dir) / 'nowhere',
                                  [('7-Zip', '26.05', 'LGPL-2.1-or-later', '')])
        self.assertEqual(['MComix', '7-Zip'],
                         [entry['name'] for entry in document['packages']])
        self.assertEqual('NOASSERTION', document['packages'][1]['downloadLocation'])

    def test_licence_expressions(self):
        self.assertEqual('MIT', build_pyinstaller.spdx_licence(['spdx:MIT']))
        self.assertEqual('(MIT OR Apache-2.0) AND BSD-3-Clause',
                         build_pyinstaller.spdx_licence(
                             ['spdx:MIT OR Apache-2.0', 'spdx:BSD-3-Clause']))
        self.assertEqual('MIT OR Apache-2.0',
                         build_pyinstaller.spdx_licence(['spdx:MIT OR Apache-2.0']))
        self.assertEqual('LicenseRef-GPL2 AND LicenseRef-custom-foo',
                         build_pyinstaller.spdx_licence(['GPL2', 'custom:foo']))
        self.assertEqual('NOASSERTION', build_pyinstaller.spdx_licence([]))

    def test_the_fetched_programs_are_named_with_their_versions(self):
        bundle = pathlib.Path(self.tmp_dir) / 'dist' / 'MComix'
        bundle.mkdir(parents=True)
        for name in ('UnRAR64.dll', '7z.exe'):
            (bundle / name).write_text('')
        environment = {'UNRAR_VERSION': '7.23',
                       'SEVENZIP_VERSION': '7-Zip 26.05 (x64) : Copyright (c) '
                                           '1999-2026 Igor Pavlov : 2026-10-21'}
        cwd = os.getcwd()
        with unittest.mock.patch.dict(os.environ, environment):
            # The bundle is found where the build leaves it, under dist/.
            os.chdir(self.tmp_dir)
            try:
                programs = build_pyinstaller._fetched_programs()
            finally:
                os.chdir(cwd)
        self.assertEqual([('UnRAR.dll', '7.23'), ('7-Zip', '26.05')],
                         [(name, version) for name, version, _l, _u in programs])


class OtherFilesTest(MComixTest):

    """What the build adds to dist/MComix beside what PyInstaller froze."""

    def test_jxrlib_s_decoder_goes_beside_mcomix_exe(self):
        """MComix looks for programs in its own folder, and Windows for
        the DLLs a program loads in the program's: the decoder and its
        two libraries go there, with jxrlib's licence."""
        checkout = pathlib.Path(self.tmp_dir) / 'checkout'
        for name in ('ChangeLog.md', 'README.md', 'COPYING',
                     'win32/jxrlib-license.txt'):
            (checkout / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(os.path.join(os.path.dirname(WIN32), name),
                        checkout / name)
        prefix = pathlib.Path(self.tmp_dir) / 'msys64' / 'ucrt64'
        (prefix / 'bin').mkdir(parents=True)
        for name in build_pyinstaller.JXRLIB_FILES + ('JxrEncApp.exe',):
            (prefix / 'bin' / name).write_bytes(name.encode())
        (checkout / 'dist' / 'MComix' / '_internal').mkdir(parents=True)
        cwd = os.getcwd()
        os.chdir(checkout)
        try:
            with unittest.mock.patch.object(sys, 'prefix', str(prefix)):
                build_pyinstaller.copy_other_files()
        finally:
            os.chdir(cwd)
        bundle = checkout / 'dist' / 'MComix'
        self.assertEqual(
            ['JxrDecApp.exe', 'libjpegxr.dll', 'libjxrglue.dll'],
            sorted(path.name for path in bundle.iterdir()
                   if path.name.startswith(('Jxr', 'libj'))))
        self.assertEqual(b'libjxrglue.dll',
                         (bundle / 'libjxrglue.dll').read_bytes())
        self.assertIn('Copyright © Microsoft Corp.', (
            bundle / 'licenses' / 'jxrlib' / 'LICENSE.txt').read_text(
                encoding='utf-8'))

    def test_without_jxrlib_the_bundle_goes_without(self):
        checkout = pathlib.Path(self.tmp_dir) / 'checkout'
        for name in ('ChangeLog.md', 'README.md', 'COPYING'):
            (checkout / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(os.path.join(os.path.dirname(WIN32), name),
                        checkout / name)
        (checkout / 'dist' / 'MComix').mkdir(parents=True)
        cwd = os.getcwd()
        os.chdir(checkout)
        try:
            with unittest.mock.patch.object(
                    sys, 'prefix', str(pathlib.Path(self.tmp_dir) / 'none')):
                build_pyinstaller.copy_other_files()
        finally:
            os.chdir(cwd)
        self.assertFalse((checkout / 'dist' / 'MComix'
                          / 'JxrDecApp.exe').exists())
        self.assertFalse((checkout / 'dist' / 'MComix' / 'licenses'
                          / 'jxrlib').exists())


class CheckImportsTest(MComixTest):

    """win32/check_imports.py, which fails the release build on a DLL
    that a file of the bundle imports and nothing provides."""

    def test_the_bundle_api_sets_and_windows_provide(self):
        importers = {'libtiff-6.dll': {'_internal/libgtk-4-1.dll'},
                     'KERNEL32.dll': {'MComix.exe'},
                     'api-ms-win-crt-heap-l1-1-0.dll': {'MComix.exe'},
                     'ext-ms-win-ntuser-window-l1-1-0.dll': {'x.dll'}}
        self.assertEqual([], check_imports.unresolved(
            {'libtiff-6.dll'}, importers,
            check_imports.system_dlls(['Kernel32.dll'])))

    def test_names_compare_without_case(self):
        self.assertEqual([], check_imports.unresolved(
            {'libjxl.dll'}, {'LibJXL.DLL': {'loaders/jxl.dll'}}, set()))

    def test_a_dll_only_a_loader_imports_is_missed(self):
        """What a smoke run that opens a PDF never loads."""
        importers = {'libjxl_threads.dll': {
            '_internal/lib/gdk-pixbuf/loaders/libpixbufloader-jxl.dll'}}
        self.assertEqual(['libjxl_threads.dll'], check_imports.unresolved(
            {'libjxl.dll'}, importers, set()))

    def test_the_visual_c_runtimes_are_not_windows_own(self):
        """A runner has them in System32, a fresh Windows does not."""
        system = check_imports.system_dlls([
            'vcruntime140.dll', 'VCRUNTIME140_1.dll', 'msvcp140.dll',
            'msvcr120.dll', 'concrt140.dll', 'vcomp140.dll',
            'mfc140u.dll', 'd3dx9_43.dll', 'ucrtbased.dll',
            'msvcrt.dll', 'mfcore.dll', 'mfplat.dll', 'ucrtbase.dll',
            'd3d11.dll', 'user32.dll'])
        self.assertEqual({'msvcrt.dll', 'mfcore.dll', 'mfplat.dll',
                          'ucrtbase.dll', 'd3d11.dll', 'user32.dll'},
                         system)

    def _main(self, provided, importers):
        system = pathlib.Path(self.tmp_dir) / 'System32'
        system.mkdir()
        (system / 'KERNEL32.dll').write_bytes(b'')
        output = io.StringIO()
        with unittest.mock.patch.object(
                check_imports, 'read_imports',
                return_value=(provided, importers)), \
                contextlib.redirect_stdout(output):
            status = check_imports.main(['dist/MComix', str(system)])
        return status, output.getvalue()

    def test_a_complete_bundle_passes(self):
        status, output = self._main(
            {'mcomix.exe'}, {'kernel32.dll': {'MComix.exe'}})
        self.assertEqual(0, status)
        self.assertNotIn('::error::', output)

    def test_a_missing_dll_fails_the_build_naming_its_importers(self):
        status, output = self._main(
            {'mcomix.exe'},
            {'kernel32.dll': {'MComix.exe'},
             'librsvg-2-2.dll': {'b/pixbufloader_svg.dll', 'a/other.dll'}})
        self.assertEqual(1, status)
        self.assertIn('::error::librsvg-2-2.dll is imported by '
                      'a/other.dll, b/pixbufloader_svg.dll', output)
        self.assertNotIn('kernel32', output.split('\n', 1)[1])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows has PE files')
    def test_a_real_bundle_s_imports_are_read(self):
        """Python's own executable and DLL, copied into a folder of
        their own, as the build would bundle them."""
        try:
            import pefile  # noqa: F401
        except ImportError:
            self.skipTest('pefile is not installed')
        bundle = pathlib.Path(self.tmp_dir) / 'bundle'
        (bundle / '_internal').mkdir(parents=True)
        python_dll = next(pathlib.Path(sys.executable).parent.glob(
            'libpython3.*.dll'))
        shutil.copy(sys.executable, bundle / 'python.exe')
        system = check_imports.system_dlls(os.listdir(
            os.path.join(os.environ['SystemRoot'], 'System32')))
        name = python_dll.name.lower()
        provided, importers = check_imports.read_imports(str(bundle))
        self.assertEqual({'python.exe'}, provided)
        self.assertEqual({'python.exe'}, importers[name])
        self.assertIn('kernel32.dll', importers)
        self.assertIn(name, check_imports.unresolved(
            provided, importers, system))
        shutil.copy(python_dll, bundle / '_internal' / python_dll.name)
        provided, importers = check_imports.read_imports(str(bundle))
        self.assertIn(os.path.join('_internal', python_dll.name),
                      importers['kernel32.dll'])
        self.assertNotIn(name, check_imports.unresolved(
            provided, importers, system))
        self.assertNotIn('kernel32.dll', check_imports.unresolved(
            provided, importers, system))


class FrozenEntryTest(MComixTest):

    """mcomixstarter.py, the script the Windows build freezes."""

    def test_it_lets_a_worker_process_be_one(self):
        """The PDF workers are MComix started again; without
        freeze_support() they were a second MComix, which refused their
        arguments ("unrecognized arguments: -B -S -I -c", in a frozen
        build on Linux), and no PDF opened."""
        path = os.path.join(os.path.dirname(WIN32), 'mcomixstarter.py')
        with open(path, encoding='utf-8') as fp:
            tree = ast.parse(fp.read())
        guard = next(node for node in tree.body
                     if isinstance(node, ast.If)
                     and ast.unparse(node.test) == "__name__ == '__main__'")
        calls = [ast.unparse(statement.value) for statement in guard.body
                 if isinstance(statement, ast.Expr)]
        self.assertEqual(['multiprocessing.freeze_support()', 'main()'],
                         calls)


#: The namespace of WiX 3's source files.
_WIX = '{http://schemas.microsoft.com/wix/2006/wi}'


class InstallerTest(MComixTest):

    """The MSI: what win32/msi/mcomix.wxs and the fragment
    win32/build_msi.py writes beside it say, read here since WiX itself
    runs only on Windows."""

    def _product(self):
        from xml.etree import ElementTree
        tree = ElementTree.parse(os.path.join(WIN32, 'msi', 'mcomix.wxs'))
        return tree.getroot().find(_WIX + 'Product')

    def _file_types(self):
        """The registry values of the file types component, as (key,
        name, value) - name None for a key's default value."""
        from xml.etree import ElementTree
        fragment = ElementTree.fromstring(
            '<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">%s</Wix>'
            % '\n'.join(build_msi.generate_file_types_component()))
        component = fragment.find('.//%sComponent' % _WIX)
        self.assertEqual('FileTypes.c', component.get('Id'))
        values = component.findall(_WIX + 'RegistryValue')
        for value in values:
            # HKLM for an installation for everyone, HKCU otherwise.
            self.assertEqual('HKMU', value.get('Root'))
        return component, [(value.get('Key'), value.get('Name'),
                            value.get('Value')) for value in values]

    def test_each_build_is_a_product_found_by_its_upgrade_code(self):
        """With one product code for every version, the next version's
        installer refused to run over the last one ("Another version of
        this product is already installed"), and Chocolatey and winget
        could not update it."""
        product = self._product()
        self.assertEqual('*', product.get('Id'))
        self.assertEqual('A6486632-9E26-428B-8AA3-40B183C35892',
                         product.get('UpgradeCode'))
        upgrade = product.find(_WIX + 'MajorUpgrade')
        self.assertIsNotNone(upgrade)
        # A release replaced under its tag is built as the same version.
        self.assertEqual('yes', upgrade.get('AllowSameVersionUpgrades'))
        self.assertTrue(upgrade.get('DowngradeErrorMessage'))

    def test_the_cabinet_is_packed_with_lzx(self):
        """WiX packs with MSZIP unless told, and the 26.11.1 installer
        came to 98.9 MB, as large as the zip."""
        media = self._product().find(_WIX + 'Media')
        self.assertEqual('yes', media.get('EmbedCab'))
        self.assertEqual('high', media.get('CompressionLevel'))

    def test_the_file_types_are_installed_with_mcomix(self):
        references = {ref.get('Id') for ref in
                      self._product().iter(_WIX + 'ComponentRef')}
        self.assertIn('FileTypes.c', references)
        component, _values = self._file_types()
        # The GUID of a component under HKMU cannot be generated, and
        # has to stay the same from one release to the next.
        self.assertEqual(build_msi.FILE_TYPES_GUID, component.get('Guid'))
        self.assertRegex(component.get('Guid'),
                         r'^[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}$')

    def test_the_file_types_are_books_mcomix_opens(self):
        from mcomix import constants
        extensions = set()
        for formats in (constants.ZIP_FORMATS, constants.RAR_FORMATS,
                        constants.TAR_FORMATS, constants.SZIP_FORMATS,
                        constants.PDF_FORMATS, constants.DJVU_FORMATS,
                        constants.MOBI_FORMATS, constants.KFX_FORMATS,
                        constants.EPUB_FORMATS):
            extensions.update(formats[1])
        self.assertEqual(set(), set(build_msi.FILE_TYPES) - extensions)
        # Archives in general are not offered, as on Linux.
        for extension in ('zip', 'rar', '7z', 'tar'):
            self.assertNotIn(extension, build_msi.FILE_TYPES)

    def test_mcomix_is_offered_for_each_type_and_takes_none_over(self):
        _component, values = self._file_types()
        capabilities = 'Software\\MComix\\Capabilities'
        for extension in build_msi.FILE_TYPES:
            with self.subTest(extension=extension):
                self.assertIn(('Software\\Classes\\.%s\\OpenWithProgids'
                               % extension, build_msi.PROG_ID, 'MComix'),
                              values)
                self.assertIn((capabilities + '\\FileAssociations',
                               '.' + extension, build_msi.PROG_ID), values)
                # The extension's default value is what opens it on a
                # double-click; it is never written.
                self.assertNotIn('Software\\Classes\\.' + extension,
                                 [key for key, _name, _value in values])
        self.assertIn(('Software\\RegisteredApplications', 'MComix',
                       capabilities), values)

    def test_the_book_type_opens_mcomix_exe_on_the_file(self):
        _component, values = self._file_types()
        command = 'Software\\Classes\\%s\\shell\\open\\command' % (
            build_msi.PROG_ID)
        self.assertIn((command, None, '"[#MComix_exe.f]" "%1"'), values)

    def test_mcomix_exe_has_the_file_id_the_installer_names(self):
        root = pathlib.PurePath('dist/MComix')
        self.assertEqual('MComix_exe.f', build_msi.generate_id_from_string(
            root / 'MComix.exe', root, build_msi.IdType.File))
        shortcut = self._product().find('.//%sShortcut' % _WIX)
        self.assertEqual('[!MComix_exe.f]', shortcut.get('Target'))


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


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is not installed')
class FetchUnrarTest(MComixTest):

    """win32/fetch_unrar.ps1, which the release workflow fetches the
    bundled UnRAR.dll with and the Windows tests the one they load: the
    newest release RARLAB has, never the beta its page links to."""

    def _fetch(self, linked, present):
        """Run the script against a page linking <linked>, with the
        installers <present> there to download, and 7-Zip played by a
        script that writes the two files it is asked for."""
        work = pathlib.Path(self.tmp_dir)
        (work / '7z.ps1').write_text(
            "$to = ($args | Where-Object { $_ -like '-o*' }).Substring(2)\n"
            "Set-Content (Join-Path $to 'UnRAR64.dll') 'dll'\n"
            "Set-Content (Join-Path $to 'license.txt') 'license'\n")
        script = pathlib.Path(__file__).parent.parent / 'win32' / 'fetch_unrar.ps1'
        (work / 'run.ps1').write_text(
            "$fakePage = '<a href=\"rar/%s\">UnRAR.dll</a>'\n"
            "$fakePresent = @(%s)\n"
            "function Invoke-WebRequest {\n"
            "  param([Parameter(Position = 0)] [string] $Uri, [string] $OutFile)\n"
            "  if ($Uri.EndsWith('rar_add.htm')) { return [pscustomobject]@{ Content = $fakePage } }\n"
            "  if ($fakePresent -notcontains $Uri) { throw \"404 $Uri\" }\n"
            "  Set-Content -Path $OutFile -Value 'installer'\n"
            "}\n"
            "& '%s' -Destination '%s' -SevenZip '%s'\n"
            % (linked,
               ', '.join("'https://www.rarlab.com/rar/%s'" % name
                         for name in present),
               script, work / 'unrar', work / '7z.ps1'))
        return subprocess.run(
            ['pwsh', '-NoProfile', '-File', str(work / 'run.ps1')],
            capture_output=True, text=True, timeout=60)

    def test_below_a_beta_the_newest_release_is_fetched(self):
        result = self._fetch('unrardll-724b1.exe', ['unrardll-722.exe'])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('7.22', result.stdout.strip())
        unrar = pathlib.Path(self.tmp_dir) / 'unrar'
        self.assertEqual(['UnRAR64.dll', 'license.txt'],
                         sorted(path.name for path in unrar.iterdir()))

    def test_a_release_linked_is_the_one_fetched(self):
        result = self._fetch('unrardll-723.exe', ['unrardll-723.exe',
                                                  'unrardll-722.exe'])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('7.23', result.stdout.strip())

    def test_no_release_to_fetch_fails(self):
        result = self._fetch('unrardll-724b1.exe', [])
        self.assertNotEqual(0, result.returncode)
        self.assertIn('No released UnRAR.dll', result.stderr + result.stdout)


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is not installed')
class FetchSevenZipTest(MComixTest):

    """win32/fetch_7zip.ps1, which the release workflow fetches the
    bundled 7-Zip with: the newest release on GitHub, checked against the
    SHA-256 GitHub gives, not the runner's, which can be a release
    behind."""

    INSTALLER = b'installer'
    # Whatever GitHub calls its latest release; nothing in the script
    # knows a version.
    TAG = '31.07'
    X64 = '7z3107-x64.exe'

    def _fetch(self, assets, digest=None):
        """Run the script against a latest release TAG with the assets
        named <assets>, each carrying <digest> (the installer's own where
        None), and 7-Zip played by a script that writes the three files
        it is asked for."""
        work = pathlib.Path(self.tmp_dir)
        if digest is None:
            digest = 'sha256:' + hashlib.sha256(self.INSTALLER).hexdigest()
        (work / '7z.ps1').write_text(
            "$to = ($args | Where-Object { $_ -like '-o*' }).Substring(2)\n"
            "foreach ($name in '7z.exe', '7z.dll', 'License.txt') {\n"
            "  Set-Content (Join-Path $to $name) $name\n"
            "}\n")
        script = pathlib.Path(__file__).parent.parent / 'win32' / 'fetch_7zip.ps1'
        (work / 'run.ps1').write_text(
            "$fakeAssets = @(%s)\n"
            "function Invoke-RestMethod {\n"
            "  param([Parameter(Position = 0)] [string] $Uri, $Headers)\n"
            "  if (-not $Uri.EndsWith('/repos/ip7z/7zip/releases/latest')) { throw \"404 $Uri\" }\n"
            "  [pscustomobject]@{ tag_name = '%s'; assets = $fakeAssets }\n"
            "}\n"
            "function Invoke-WebRequest {\n"
            "  param([Parameter(Position = 0)] [string] $Uri, [string] $OutFile)\n"
            "  if ($Uri -ne 'https://github.com/ip7z/7zip/releases/download/%s/%s') { throw \"404 $Uri\" }\n"
            "  [IO.File]::WriteAllText($OutFile, '%s')\n"
            "}\n"
            "& '%s' -Destination '%s' -SevenZip '%s' -Token ''\n"
            % (', '.join(
                "[pscustomobject]@{ name = '%s'; digest = '%s'; "
                "browser_download_url = 'https://github.com/ip7z/7zip/"
                "releases/download/%s/%s' }" % (name, digest, self.TAG, name)
                for name in assets),
               self.TAG, self.TAG, self.X64,
               self.INSTALLER.decode(), script, work / '7z', work / '7z.ps1'))
        return subprocess.run(
            ['pwsh', '-NoProfile', '-File', str(work / 'run.ps1')],
            capture_output=True, text=True, timeout=60)

    def test_the_x64_installer_of_the_latest_release_is_unpacked(self):
        result = self._fetch(['7z3107.exe', self.X64,
                              '7z3107-x64.msi', '7z3107-arm64.exe'])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.TAG, result.stdout.strip())
        self.assertEqual(['7z.dll', '7z.exe', 'License.txt'],
                         sorted(path.name for path in
                                (pathlib.Path(self.tmp_dir) / '7z').iterdir()))

    def test_an_installer_not_as_github_hashed_it_is_refused(self):
        result = self._fetch([self.X64], 'sha256:' + '0' * 64)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('GitHub gives', result.stderr + result.stdout)
        self.assertFalse((pathlib.Path(self.tmp_dir) / '7z').exists())

    def test_an_installer_without_a_digest_is_refused(self):
        result = self._fetch([self.X64], '')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('no SHA-256', result.stderr + result.stdout)

    def test_a_release_without_an_x64_installer_fails(self):
        result = self._fetch(['7z3107.exe', '7z3107-arm64.exe'])
        self.assertNotEqual(0, result.returncode)
        self.assertIn('no single x64 installer', result.stderr + result.stdout)

# vim: expandtab:sw=4:ts=4
