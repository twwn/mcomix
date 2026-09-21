Maintenance
===========

This page describes the tasks involved in releasing and distributing MComix.

Translation files
-----------------

Whenever a translatable string is added or changed, regenerate the translation template `mcomix/messages/mcomix.pot`, merge it into every catalogue in `mcomix/messages/*/LC_MESSAGES/mcomix.po`, and compile each catalogue into the `mcomix.mo` beside it. The compiled files are kept in Git, and `test/test_messages.py` fails until all three agree with the source. Run this from MComix' root directory; it needs GNU gettext.

```bash
#!/bin/sh
VERSION=$(grep VERSION mcomix/constants.py | sed -e "s/VERSION = //" -e "s/'//g")
MAINTAINER="https://sourceforge.net/projects/mcomix"

xgettext -LPython -omcomix.pot -pmcomix/messages/ -cTRANSLATORS \
	--from-code=utf-8 --package-name=MComix --package-version=${VERSION} \
	--msgid-bugs-address=${MAINTAINER} \
	mcomix/*.py mcomix/archive/*.py mcomix/library/*.py

for pofile in mcomix/messages/*/LC_MESSAGES/*.po
do
	# msgmerge marks the old translation of a changed string fuzzy, and
	# msgfmt leaves fuzzy entries out, so nothing uncertain is shipped.
	msgmerge -U --backup=none ${pofile} mcomix/messages/mcomix.pot
	msgfmt ${pofile} -o ${pofile%.*}.mo
done
```

Preparing a new release
-----------------------

1. Give the release its section in `ChangeLog.md`, with a `## Release date:` line below the heading.
2. Remove the `-dev0` suffix from `VERSION` in `mcomix/constants.py`.
3. Regenerate the translation files as above. The template's header carries the version.
4. Add the release to `share/metainfo/mcomix.metainfo.xml`.
5. Commit, with a message naming the version, such as "MComix 4.0.0", and create an [annotated tag](https://git-scm.com/book/en/v2/Git-Basics-Tagging) for it: `git tag -a 4.0.0 -m "Version 4.0.0"`.

Building the source archive
---------------------------

With a development environment set up as on the [Installation](Installation.md) page, build `dist/mcomix-<version>.tar.gz`:

```bash
python3 -m build -s
```

Do not build it on Windows, to avoid files in the archive having executable permission bits set.

Building the Windows packages
-----------------------------

The Windows packages are built in [MSYS2](https://www.msys2.org/), with these packages, updated with `pacman -Syuu` before each release: `mingw-w64-x86_64-gtk4`, `mingw-w64-x86_64-libadwaita`, `mingw-w64-x86_64-libjxl`, `mingw-w64-x86_64-python`, `mingw-w64-x86_64-python-gobject`, `mingw-w64-x86_64-python-pillow`, `mingw-w64-x86_64-python-pip` and `mingw-w64-x86_64-python-pymupdf`. `win32/build_pyinstaller.py` names the same list. The development dependencies install PyInstaller; update it with `pip-review --auto --local`.

The packages carry these archive programs, which the build copies from `../mcomix-other`, beside MComix' root directory. A directory that is not there is left out of the package.

Directory | Files | From
----------|-------|-----
`7z` | `7z.exe`, `7z.dll`, `License.txt` | [7-Zip](https://www.7-zip.org/download.html)
`mutool` | `mutool.exe`, `COPYING.txt` | [MuPDF](https://mupdf.com/releases?product=MuPDF)
`unrar` | `UnRAR64.dll`, `license.txt` | [RARLAB](https://www.rarlab.com/rar_add.htm)

In a MINGW64 shell in MComix' root directory, build `dist/MComix` and `dist/mcomix-win64-<version>.zip`:

```bash
python win32/build_pyinstaller.py
```

Then, in a regular Windows console with the [WiX Toolset](https://wixtoolset.org/docs/wix3/) version 3 on the `PATH`, build `dist/mcomix-win64-<version>.msi`. This also writes the installer's SHA-256 to `win32/tools/checksum.sha256`, and prints it.

```bash
python win32/build_msi.py
```

Building the Chocolatey package
-------------------------------

The Chocolatey package does not carry MComix: it downloads the MSI installer from SourceForge and checks it against the checksum in `win32/tools/checksum.sha256`. So upload the installer first, and pack the checksum file written by the build of that same installer. The file is deliberately not kept in Git, since it describes one build of one version. With the [Chocolatey CLI](https://chocolatey.org/install), in MComix' root directory:

```bash
choco pack win32/mcomix.nuspec --version <version> --out dist
choco push dist/mcomix.<version>.nupkg --source https://push.chocolatey.org/
```

Pushing needs an API key from a Chocolatey account with rights to the `mcomix` package, set once with `choco apikey`. Packages are moderated, so the new version appears some time after it is pushed.

Uploading a new release
-----------------------

In the list of files on MComix' SourceForge project page, create a folder named `MComix-<version>`, which is where the Chocolatey package downloads from, and upload `mcomix-<version>.tar.gz`, `mcomix-win64-<version>.zip` and `mcomix-win64-<version>.msi` into it. With the (i) button beside each file, make the MSI installer the default download for Windows, and the source archive the default for everything else. If the web form times out on the Windows packages, upload them with scp, following SourceForge's [SCP upload manual](https://sourceforge.net/p/forge/documentation/SCP/).

Then post a news entry with the release's section of `ChangeLog.md`.

After a release
---------------

Raise `VERSION` in `mcomix/constants.py` and append `-dev0`, so that anyone running MComix from Git can tell it is not a release.

On SourceForge, start a milestone for the new version in the "Bugs" and "Support Requests" trackers, and close the old ones. The "Git" milestone always stays open. A milestone lets a bug report say which version the bug occurs in, or was fixed in.
