Maintenance
===========

This page describes the tasks involved in releasing and distributing MComix.

Translation files
-----------------

Whenever a translatable string is added or changed, regenerate the translation template `mcomix/messages/mcomix.pot`, merge it into every catalogue in `mcomix/messages/*/LC_MESSAGES/mcomix.po`, and compile each catalogue into the `mcomix.mo` beside it. The compiled files are kept in Git, and `test/test_messages.py` fails until all three agree with the source. Run this from MComix' root directory; it needs GNU gettext.

```bash
#!/bin/sh
VERSION=$(grep VERSION mcomix/constants.py | sed -e "s/VERSION = //" -e "s/'//g")
MAINTAINER="https://github.com/twwn/mcomix/issues"

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
2. Set `VERSION` in `mcomix/constants.py` to the release's year and month, such as `26.10` for October 2026.
3. Regenerate the translation files as above. The template's header carries the version.
4. Add the release to `share/metainfo/mcomix.metainfo.xml`.
5. Commit, with a message naming the version, such as "MComix 26.10", and create an [annotated tag](https://git-scm.com/book/en/v2/Git-Basics-Tagging) for it: `git tag -a 26.10 -m "Version 26.10"`.

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

The Chocolatey package does not carry MComix: it downloads the MSI installer from the GitHub release and checks it against the checksum in `win32/tools/checksum.sha256`. So publish the release first, and pack the checksum file written by the build of that same installer. The file is deliberately not kept in Git, since it describes one build of one version. With the [Chocolatey CLI](https://chocolatey.org/install), in MComix' root directory:

```bash
choco pack win32/mcomix.nuspec --version <version> --out dist
choco push dist/mcomix-gtk.<version>.nupkg --source https://push.chocolatey.org/
```

`choco pack` may write a version such as 26.10 with a third number, as `mcomix-gtk.26.10.0.nupkg`; push the file it names. The package is `mcomix-gtk`, since `mcomix` on chocolatey.org is the original MComix 3. Pushing needs an API key from the Chocolatey account the nuspec names as its owner, set once with `choco apikey`. Packages are moderated, so the new version appears some time after it is pushed.

Uploading a new release
-----------------------

On GitHub, draft a release from the tag the release commit carries, name it `MComix <version>`, and give it the release's section of `ChangeLog.md` as its notes. Attach `mcomix-<version>.tar.gz`, `mcomix-win64-<version>.zip` and `mcomix-win64-<version>.msi` to it; the Chocolatey package downloads the MSI from exactly that release, under the file name the build gives it.

After a release
---------------

Open a milestone for the next release in the issue tracker and close the one just released, so that an issue can say which version the bug occurs in, or was fixed in.
