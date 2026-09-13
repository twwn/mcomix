#!/usr/bin/env python3
import os
import pathlib
import re
import shutil
import string
import subprocess
import sys
import zipfile

# Patch import path to be able to import the mcomix module
sys.path.append(str(pathlib.Path(__file__).parent.parent))

from mcomix import constants

""" Wrapper for pyinstaller, to compensate some shortcomings of the build process.

This file should be run from MComix' root directory, in order to avoid
having to play around with relative path names.

    Build instructions:

    0. To begin with, follow the installation instructions of PyGObject
       on Windows. At the time of this writing, using MSYS2 is recommended.

    1. Using the MSYS2 mingw64 shell, install:

           pacman -Sy \
               mingw-w64-x86_64-gtk4 \
               mingw-w64-x86_64-libadwaita \
               mingw-w64-x86_64-python \
               mingw-w64-x86_64-python-gobject \
               mingw-w64-x86_64-python-pillow \
               mingw-w64-x86_64-python-pymupdf \
               mingw-w64-x86_64-libjxl

       libadwaita is the only one of these MComix runs without: it is
       what reads the colour names a GTK4 theme states, and the build
       that ships without it follows only what plain GTK4 can be told.

    2. In the same shell, install pyinstaller with pip:

           python3 -m pip install --user pyinstaller

       Make sure that the installed pyinstaller executable is on PATH.
       You may wish to use a virtual environment:

           python3 -m venv venv --system-site-packages
           . ./venv/bin/activate
           python3 -m pip install pyinstaller

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

    version_match = re.search(r"^(\d+)\.(\d+).(\d+)", constants.VERSION)
    if not version_match:
        print('Could not determine current version', file=sys.stderr)
        sys.exit(1)

    version_file_contents = tmpl.substitute(major=version_match.group(1),
                                            minor=version_match.group(2),
                                            patch=version_match.group(3))
    with open('win32/version_file.txt', 'w') as out:
        out.write(version_file_contents)


def run_pyinstaller(attach_console: bool) -> int:
    """ Runs setup.py py2exe. """
    print('Executing pyinstaller...')
    args = ['pyinstaller', 'win32/mcomix.spec', '--noconfirm']

    # The spec file takes this environment setting to determine if a console should be attached
    environ = os.environ.copy()
    environ["PYINSTALLER_CONSOLE"] = "1" if attach_console else "0"

    proc_result = subprocess.run(args, shell=True, env=environ)

    return proc_result.returncode


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

    if os.path.isdir('../mcomix-other/mutool'):
        shutil.copy('../mcomix-other/mutool/mutool.exe', 'dist/MComix/mutool.exe')
        win32_newline('../mcomix-other/mutool/COPYING.txt', 'dist/MComix/licenses/mupdf/COPYING.txt')

    licenses_basedir = '/mingw64/share/licenses'
    components = ('cairo', 'fontconfig', 'freetype', 'gdk-pixbuf2', 'glib2', 'gtk4',
                  'libadwaita', 'pango', 'python-cairo', 'python-Pillow')
    if os.path.isdir(licenses_basedir):
        for entry in components:
            path = os.path.join(licenses_basedir, entry)
            if os.path.isdir(path):
                shutil.copytree(path, os.path.join('dist/MComix/licenses', entry))


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

    # First, a console application is created with default arguments from the spec
    clear_distdir('dist/MComix/')
    success = run_pyinstaller(attach_console=True) == 0
    if not success:
        sys.exit(1)

    shutil.move('dist/MComix/MComix.exe', 'dist/MComix.Console.exe')

    # Create version without console
    clear_distdir('dist/MComix/')
    success = run_pyinstaller(attach_console=False) == 0
    if not success:
        sys.exit(1)

    os.unlink('win32/version_file.txt')

    shutil.move('dist/MComix.Console.exe', 'dist/MComix/')
    copy_other_files()
    create_release_archive()

# vim: expandtab:sw=4:ts=4
