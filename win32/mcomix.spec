# -*- mode: python ; coding: utf-8 -*-


import glob
import os


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

a = Analysis(['../mcomixstarter.py'],
             pathex=[],
             binaries=[],
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
             excludes=[],
             # The code stays in an archive inside each executable, 5.9 MB
             # twice over.  Kept as .pyc files beside them instead, it is
             # stored once and zips 5 MB smaller, but takes some 8 MB more
             # unpacked, in 1,800 files where there were two.
             noarchive=False)

# The icon theme's X11 cursors: GTK on Windows draws the system's.
a.datas = [entry for entry in a.datas
           if not entry[0].replace('\\', '/').startswith(
               'share/icons/Adwaita/cursors/')]

pyz = PYZ(a.pure)


def executable(name, console):
    """One of the two executables, which share everything else."""
    return EXE(pyz,
               a.scripts,
               [],
               exclude_binaries=True,
               name=name,
               debug=False,
               bootloader_ignore_signals=False,
               strip=False,
               upx=False,
               console=console,
               disable_windowed_traceback=False,
               target_arch=None,
               version='version_file.txt',
               codesign_identity=None,
               entitlements_file=None,
               icon='../mcomix/images/mcomix.ico')


# MComix.exe for the desktop, and MComix.Console.exe, which opens a
# console for what MComix logs, for when something goes wrong.
coll = COLLECT(executable('MComix', console=False),
               executable('MComix.Console', console=True),
               a.binaries,
               a.datas,
               strip=False,
               upx=False,
               name='MComix')
