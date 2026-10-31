#!/usr/bin/env python3
import datetime
import json
import os
import pathlib
import re
import shutil
import string
import subprocess
import sys
import typing
import uuid
import zipfile

# Patch import path to be able to import the mcomix module
sys.path.append(str(pathlib.Path(__file__).parent.parent))

from mcomix import constants

# The installer's builder beside this file, which reads the version the
# same way for WiX.
import build_msi

""" Wrapper for pyinstaller, to compensate some shortcomings of the build process.

This file should be run from MComix' root directory, in order to avoid
having to play around with relative path names.

    Build instructions:

    0. To begin with, follow the installation instructions of PyGObject
       on Windows. At the time of this writing, using MSYS2 is recommended.

    1. Using the MSYS2 UCRT64 shell, install:

           pacman -Sy \
               mingw-w64-ucrt-x86_64-gtk4 \
               mingw-w64-ucrt-x86_64-adwaita-icon-theme \
               mingw-w64-ucrt-x86_64-jxrlib \
               mingw-w64-ucrt-x86_64-libadwaita \
               mingw-w64-ucrt-x86_64-libjxl \
               mingw-w64-ucrt-x86_64-python \
               mingw-w64-ucrt-x86_64-python-gobject \
               mingw-w64-ucrt-x86_64-python-pillow \
               mingw-w64-ucrt-x86_64-python-pip \
               mingw-w64-ucrt-x86_64-python-pymupdf \
               mingw-w64-ucrt-x86_64-pyinstaller

       UCRT64, not MINGW64: MSYS2 builds PyMuPDF for UCRT64 and CLANG64
       only.  libadwaita is the only one of these MComix runs without:
       it is what reads the colour names a GTK4 theme states, and the
       build that ships without it follows only what plain GTK4 can be
       told.  libjxl is the loader for the JPEG XL files the open dialog
       offers to filter for, and adwaita-icon-theme holds the icons the
       toolbar and menus name.  jxrlib's JxrDecApp shows the pictures
       a KFX book keeps in JPEG XR.  pyinstaller is MSYS2's own build of
       PyInstaller, which pip would otherwise have to build for this
       Python.

       docs/releasing.md and .github/workflows/release.yml list the
       same packages, and a test holds the three lists to each other.

    2. Make sure the pyinstaller executable is on PATH; the package
       above puts it there.

    3. 'win32/build_pyinstaller.py' will create the folder 'dist/MComix'
       and copy relevant libraries.

    4. This script will copy images, translations and documentation
       into the created distribution folder.
"""


def clear_distdir(distdir: str) -> None:
    """ Removes files from <distdir>. """
    if not os.path.isdir(distdir):
        return

    files = [os.path.join(distdir, file)
             for file in os.listdir(distdir)]

    print('Cleaning %s...' % distdir)
    for file in files:
        if os.path.isfile(file):
            os.unlink(file)
        elif os.path.isdir(file):
            shutil.rmtree(file)


def prepare_version_file() -> None:
    """ Fills out version information for embedding in the final executable. """
    print("Creating version file with current MComix version")
    with open('win32/version_file.template') as fp:
        tmpl = string.Template(fp.read())

    try:
        major, minor, patch = build_msi.version_triplet(constants.VERSION)
    except ValueError as error:
        print('Could not determine current version:', error, file=sys.stderr)
        sys.exit(1)

    version_file_contents = tmpl.substitute(major=major, minor=minor,
                                            patch=patch)
    with open('win32/version_file.txt', 'w') as out:
        out.write(version_file_contents)


def run_pyinstaller() -> int:
    """Build dist/MComix, with both executables the spec names, in one
    run of the PyInstaller of the Python running this."""
    print('Executing pyinstaller...')
    args = [sys.executable, '-m', 'PyInstaller', 'win32/mcomix.spec',
            '--noconfirm']
    return subprocess.run(args).returncode


def win32_newline(source: str, dest: str) -> None:
    """ Converts Unix newlines to Windows newlines. """
    from_fp = open(source, "r", encoding='utf-8')

    dest_dir = os.path.split(dest)[0]
    if not os.path.isdir(dest_dir):
        os.makedirs(dest_dir)
    to_fp = open(dest, "w", encoding='utf-8')

    for line in from_fp:
        to_fp.write(line.rstrip())
        to_fp.write("\n")

    from_fp.close()
    to_fp.close()


#: The files of MSYS2's jxrlib the bundle carries: the decoder and the
#: libraries it is linked against.
JXRLIB_FILES = ('JxrDecApp.exe', 'libjxrglue.dll', 'libjpegxr.dll')


def copy_other_files() -> None:
    """ Copy other relevant files into dist directory. """
    print("Copying misc files into dist directory...")
    win32_newline('ChangeLog.md', 'dist/MComix/ChangeLog.md')
    win32_newline('README.md', 'dist/MComix/README.md')
    win32_newline('COPYING', 'dist/MComix/licenses/mcomix/COPYING.txt')

    if os.path.isdir('../mcomix-other/unrar'):
        shutil.copy('../mcomix-other/unrar/UnRAR64.dll', 'dist/MComix/UnRAR64.dll')
        win32_newline('../mcomix-other/unrar/license.txt', 'dist/MComix/licenses/unrar/license.txt')

    if os.path.isdir('../mcomix-other/7z'):
        shutil.copy('../mcomix-other/7z/7z.exe', 'dist/MComix/7z.exe')
        shutil.copy('../mcomix-other/7z/7z.dll', 'dist/MComix/7z.dll')
        win32_newline('../mcomix-other/7z/License.txt', 'dist/MComix/licenses/7z/License.txt')

    # JxrDecApp beside MComix.exe, where MComix looks for programs, with
    # the two DLLs of jxrlib's it loads from its own folder.  MSYS2's
    # package carries no licence, so jxrlib's is kept beside this file.
    msys2_bin = os.path.join(sys.prefix, 'bin')
    if os.path.isfile(os.path.join(msys2_bin, 'JxrDecApp.exe')):
        for name in JXRLIB_FILES:
            shutil.copy(os.path.join(msys2_bin, name), os.path.join('dist/MComix', name))
        win32_newline('win32/jxrlib-license.txt', 'dist/MComix/licenses/jxrlib/LICENSE.txt')

    # Where MSYS2's packages keep their licences: beside the Python
    # running this, whichever MSYS2 environment it is.
    licenses_basedir = os.path.join(sys.prefix, 'share', 'licenses')
    for entry in bundled_licences(pathlib.Path('dist/MComix/_internal'),
                                  pathlib.Path(sys.prefix)):
        path = os.path.join(licenses_basedir, entry)
        if os.path.isdir(path):
            shutil.copytree(path, os.path.join('dist/MComix/licenses', entry))


#: The licences to ship where there is no package database to tell whose
#: files the bundle carries: those of the libraries MComix itself uses.
_KNOWN_LICENCES = ('cairo', 'fontconfig', 'freetype', 'gdk-pixbuf2', 'glib2',
                   'gtk4', 'libadwaita', 'mupdf', 'pango', 'python',
                   'python-cairo', 'python-gobject', 'python-Pillow',
                   'python-pymupdf')


def _desc_fields(text: str) -> dict[str, list[str]]:
    """The fields of a package's desc file in MSYS2's package database:
    %NAME%, %VERSION%, %URL%, %LICENSE% and the rest, each the lines up
    to the blank one after it."""
    fields: dict[str, list[str]] = {}
    key = None
    for line in text.splitlines():
        if len(line) > 2 and line.startswith('%') and line.endswith('%'):
            key = line[1:-1]
            fields[key] = []
        elif not line:
            key = None
        elif key is not None:
            fields[key].append(line)
    return fields


class _Package(typing.NamedTuple):
    """An MSYS2 package, as its entry in the package database has it."""

    fields: dict[str, list[str]]
    #: Its folders under <prefix>/share/licenses.
    licences: frozenset[str]


def bundled_packages(bundle: pathlib.Path,
                     prefix: pathlib.Path) -> "dict[str, _Package] | None":
    """The MSYS2 packages whose files <bundle> carries, by name; None
    where there is no package database.

    MSYS2 keeps a package database, as pacman does anywhere, one level up
    from the environment's prefix: var/lib/pacman/local/<package>/files
    lists every file a package installed, its licence folder among them
    - share/licenses/gtk4 for gtk4, share/licenses/python3.14 for python.
    A file of the bundle is known by its name, and only a name one package
    alone installs counts.
    """
    local = prefix.parent / 'var' / 'lib' / 'pacman' / 'local'
    if not local.is_dir():
        return None
    owners: dict[str, str | None] = {}
    packages: dict[str, _Package] = {}
    for package in local.iterdir():
        try:
            desc = (package / 'desc').read_text(encoding='utf-8')
            files = (package / 'files').read_text(encoding='utf-8')
        except OSError:
            continue
        fields = _desc_fields(desc)
        name = (fields.get('NAME') or [''])[0]
        licences = set()
        listed = files.split('%FILES%\n', 1)[-1].split('\n\n', 1)[0]
        for path in listed.splitlines():
            parts = path.split('/')
            if parts[:3] == [prefix.name, 'share', 'licenses'] and len(parts) > 4:
                licences.add(parts[3])
            if path and not path.endswith('/'):
                key = parts[-1].lower()
                # A name two packages install says nothing of either.
                owners[key] = name if owners.get(key, name) == name else None
        packages[name] = _Package(fields, frozenset(licences))
    found = {owner for path in bundle.rglob('*') if path.is_file()
             for owner in [owners.get(path.name.lower())] if owner}
    return {name: packages[name] for name in sorted(found)}


def bundled_licences(bundle: pathlib.Path, prefix: pathlib.Path) -> list[str]:
    """The licence folders, under <prefix>/share/licenses, of the MSYS2
    packages whose files <bundle> carries (bundled_packages()).  Without
    the package database, the licences of the libraries MComix itself
    uses."""
    packages = bundled_packages(bundle, prefix)
    if packages is None:
        return list(_KNOWN_LICENCES)
    return sorted(set().union(*(package.licences
                                for package in packages.values())))


def spdx_licence(entries: list[str]) -> str:
    """An SPDX licence expression of a package's %LICENSE% lines.

    MSYS2 writes nearly every licence as "spdx:<expression>"; the few
    written otherwise ("custom", "GPL", "BSD") become LicenseRef-<name>,
    which the document then lists among the licences it found but could
    not name.
    """
    terms = []
    for entry in entries:
        if entry.startswith('spdx:'):
            term = entry[len('spdx:'):].strip()
        else:
            term = 'LicenseRef-' + (re.sub(r'[^A-Za-z0-9.-]+', '-', entry).strip('-')
                                    or 'unknown')
        if term:
            terms.append('(%s)' % term if ' ' in term and len(entries) > 1
                         else term)
    return ' AND '.join(terms) or 'NOASSERTION'


def _spdx_id(name: str) -> str:
    return 'SPDXRef-Package-' + re.sub(r'[^A-Za-z0-9.-]+', '-', name)


def write_sbom(path: pathlib.Path, bundle: pathlib.Path, prefix: pathlib.Path,
               version: str, others: list[tuple[str, str, str, str]]) -> None:
    """Write to <path> an SPDX 2.3 document of what the Windows bundle
    carries: MComix <version>, the MSYS2 packages whose files are in
    <bundle> (bundled_packages()), and <others>, each (name, version,
    licence expression, URL), the programs fetched from elsewhere.
    Without MSYS2's package database the document names MComix and the
    others alone.
    """
    def package(name: str, version: str, licence: str, url: str,
                supplier: str) -> dict[str, object]:
        entry: dict[str, object] = {
            'name': name,
            'SPDXID': _spdx_id(name),
            'downloadLocation': url or 'NOASSERTION',
            'filesAnalyzed': False,
            'licenseConcluded': 'NOASSERTION',
            'licenseDeclared': licence or 'NOASSERTION',
            'copyrightText': 'NOASSERTION',
            'supplier': supplier,
        }
        if version:
            entry['versionInfo'] = version
        return entry

    packages = [package('MComix', version, 'GPL-2.0-or-later',
                        'https://github.com/twwn/mcomix', 'Organization: The MComix Team')]
    for name, msys2 in (bundled_packages(bundle, prefix) or {}).items():
        fields = msys2.fields
        packages.append(package(name, (fields.get('VERSION') or [''])[0],
                                spdx_licence(fields.get('LICENSE', [])),
                                (fields.get('URL') or [''])[0],
                                'Organization: MSYS2'))
    for name, other_version, licence, url in others:
        packages.append(package(name, other_version, licence, url, 'NOASSERTION'))

    references = sorted({ref for entry in packages
                         for ref in re.findall(r'LicenseRef-[A-Za-z0-9.-]+',
                                               str(entry['licenseDeclared']))})
    document = {
        'spdxVersion': 'SPDX-2.3',
        'dataLicense': 'CC0-1.0',
        'SPDXID': 'SPDXRef-DOCUMENT',
        'name': f'mcomix-win64-{version}',
        'documentNamespace': f'https://github.com/twwn/mcomix/spdx/mcomix-win64-{version}-{uuid.uuid4()}',
        'creationInfo': {
            'created': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'creators': ['Tool: win32/build_pyinstaller.py'],
        },
        'packages': packages,
        'relationships': [{'spdxElementId': 'SPDXRef-DOCUMENT',
                           'relationshipType': 'DESCRIBES',
                           'relatedSpdxElement': packages[0]['SPDXID']}]
        + [{'spdxElementId': packages[0]['SPDXID'],
            'relationshipType': 'CONTAINS',
            'relatedSpdxElement': entry['SPDXID']} for entry in packages[1:]],
    }
    if references:
        document['hasExtractedLicensingInfos'] = [
            {'licenseId': reference,
             'name': reference[len('LicenseRef-'):],
             'extractedText': 'A licence its package does not name by an SPDX '
                              'identifier; its text is in licenses/ in the bundle.'}
            for reference in references]
    path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')


def _fetched_programs() -> list[tuple[str, str, str, str]]:
    """UnRAR.dll and 7-Zip, which release.yml fetches and names in
    UNRAR_VERSION ("7.23") and SEVENZIP_VERSION (7-Zip's banner)."""
    programs = []
    if os.path.isfile('dist/MComix/UnRAR64.dll'):
        programs.append(('UnRAR.dll', os.environ.get('UNRAR_VERSION', ''),
                         'LicenseRef-UnRAR', 'https://www.rarlab.com/rar_add.htm'))
    if os.path.isfile('dist/MComix/7z.exe'):
        banner = re.search(r'7-Zip(?: \(\w\))? ([\d.]+)',
                           os.environ.get('SEVENZIP_VERSION', ''))
        programs.append(('7-Zip', banner.group(1) if banner else '',
                         'LGPL-2.1-or-later AND BSD-3-Clause AND LicenseRef-unRAR-restriction',
                         'https://www.7-zip.org/'))
    return programs


def create_release_archive() -> None:
    """ Packs the contents of the release directory. """
    print("Creating ZIP archive...")
    with zipfile.ZipFile(f'dist/mcomix-win64-{constants.VERSION}.zip', 'w', compression=zipfile.ZIP_DEFLATED) as zip:
        basedir = pathlib.Path('dist/MComix/')
        for dirpath, dirnames, filenames in os.walk('dist/MComix/'):
            currentdir = pathlib.Path(dirpath)
            for filename in filenames:
                full_file_path = currentdir / filename
                zip.write(full_file_path, full_file_path.relative_to(basedir))


if __name__ == '__main__':
    prepare_version_file()

    # dist/MComix, with MComix.exe, from the spec.
    clear_distdir('dist/MComix/')
    if run_pyinstaller() != 0:
        sys.exit(1)

    os.unlink('win32/version_file.txt')

    copy_other_files()
    create_release_archive()
    # Beside the zip and the installer, not in them: the release carries
    # it, and attests it as the SBOM of both.
    write_sbom(pathlib.Path(f'dist/sbom-win64-{constants.VERSION}.spdx.json'),
               pathlib.Path('dist/MComix'), pathlib.Path(sys.prefix),
               constants.VERSION, _fetched_programs())

# vim: expandtab:sw=4:ts=4
