# -*- mode: python ; coding: utf-8 -*-


import glob
import os
import shutil
import sys


def list_files(basedir, *patterns):
    """ Locates all files in <basedir> that match one of <patterns>. """

    all_files = []
    for dirpath, _, _ in os.walk(basedir):

        for pattern in patterns:
            cur_pattern = os.path.join(dirpath, pattern)
            all_files.extend([os.path.normpath(path)
                              for path in glob.glob(cur_pattern)])

    return all_files


added_files = [(os.path.join('..', path),
                os.path.split(path)[0])
               for path in list_files('mcomix/messages', '*.mo')]
added_files.extend([(os.path.join('..', path),
                     os.path.split(path)[0])
                    for path in list_files('mcomix/images', '*.png', '*.svg')])

# The languages MComix speaks: the translations of GTK, GLib and
# libadwaita are collected for these alone, as MComix' own are.
languages = sorted(name for name in os.listdir('mcomix/messages')
                   if os.path.isdir(os.path.join('mcomix/messages', name)))

# GLib starts the session bus an MComix finds the one already running
# by ("Open files in the window that is already open") with gdbus.exe,
# which it looks for beside libgio-2.0-0.dll.  PyInstaller collects the
# DLL and not the program, and without it every MComix found itself
# alone.  The destination is the folder the DLLs go to.
binaries = []
if sys.platform == 'win32':
    gdbus = shutil.which('gdbus.exe')
    if gdbus is not None:
        binaries.append((gdbus, '.'))

a = Analysis(['../mcomixstarter.py'],
             pathex=[],
             binaries=binaries,
             datas=added_files,
             # PyGObject imports these itself, when a cairo context
             # crosses into Python - as the on-screen display draws with
             # one - so PyInstaller cannot see them; left out, the
             # display raised "Couldn't find foreign struct converter
             # for 'cairo.Context'" and drew nothing.
             hiddenimports=['cairo', 'gi._gi_cairo'],
             hookspath=[],
             # PyInstaller's GTK hook freezes GTK 3 unless it is told
             # which GTK this is, and with no GTK 3 installed it collected
             # nothing at all: no icon theme, so the toolbar's Adwaita
             # icons were missing, no GTK translations, so the file
             # chooser was English in every language, and no Windows
             # font configuration.
             hooksconfig={
                 'gi': {
                     'module-versions': {'Gtk': '4.0', 'Gdk': '4.0'},
                     'icons': ['Adwaita', 'hicolor'],
                     'themes': [],
                     'languages': languages,
                 },
             },
             runtime_hooks=[],
             # Nothing in MComix speaks TLS or needs OpenSSL's hashes, but
             # PyGObject imports asyncio, which imports ssl if it can, and
             # hashlib prefers _hashlib: left in, every start loaded
             # libcrypto and libssl, 6 MB that Windows' antivirus and
             # Smart App Control check before the window can show.
             # Without them asyncio leaves TLS out and hashlib uses its
             # own md5, which is all the thumbnails need.
             excludes=['ssl', '_ssl', '_hashlib'],
             # The code in an archive inside the executable: as .pyc files
             # beside it, it takes some 8 MB more unpacked, in 1,800 files.
             noarchive=False)

# The icon theme's X11 cursors: GTK on Windows draws the system's.
a.datas = [entry for entry in a.datas
           if not entry[0].replace('\\', '/').startswith(
               'share/icons/Adwaita/cursors/')]

pyz = PYZ(a.pure)


# MComix.exe, without a console: "-W debug -o FILE" writes the log that
# MComix.Console.exe, dropped for the 5.7 MB its copy of the code took,
# was there to show.
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='MComix',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=False,
          console=False,
          disable_windowed_traceback=False,
          target_arch=None,
          version='version_file.txt',
          codesign_identity=None,
          entitlements_file=None,
          icon='../mcomix/images/mcomix.ico')

coll = COLLECT(exe,
               a.binaries,
               a.datas,
               strip=False,
               upx=False,
               name='MComix')
