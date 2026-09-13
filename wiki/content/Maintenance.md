Maintenance
===========

This page contains information on how to various maintenance tasks related to MComix building and distribution.

Translation files
-----------------

Whenever a new translatable string is added to one of the source files, or an existing string is edited, the translation template (found in `mcomix/messages/mcomix.pot`) should be updated. At the same time, it is convenient to also update all regular translation files (in `mcomix/messages/*/LC_MESSAGES/mcomix.po`) from the template.

For this task, the following code can be put in a shell script to be executed from MComix' root directory. The gettext package is required.

~~~~~~
#!/bin/sh
VERSION=$(grep VERSION mcomix/constants.py | sed -e "s/VERSION = //" -e "s/'//g")
MAINTAINER="NAME@HO.ST"

xgettext -LPython -omcomix.pot -pmcomix/messages/ -cTRANSLATORS \
	--from-code=utf-8 --package-name=MComix --package-version=${VERSION} \
	--msgid-bugs-address=${MAINTAINER} \
	mcomix/*.py mcomix/archive/*.py mcomix/library/*.py

for pofile in mcomix/messages/*/LC_MESSAGES/*.po
do
	# Merge message files with master template, no fuzzy matching (-N)
	msgmerge -U --backup=none ${pofile} mcomix/messages/mcomix.pot
	# Compile translation, add "-f" to include fuzzy strings
	#msgfmt ${pofile} -o ${pofile%.*}.mo
done
~~~~~~

The last, commented out line also automatically compiles a new .mo file from the original .po file, which isn't really necessary unless the translation has been updated.


Preparing a new release
-----------------------

The following steps should be performed prior to releasing a new version.

1. Make sure the `ChangeLog.md` is up-to-date. Add a "Release Date" line below the line indicating the current version.
2. Edit `mcomix/constants.py` and make sure the `VERSION` constant is correct and final. Remove the `-dev0` suffix if required.
3. Update the translation template as outlined above if required.
4. Commit changes to Git with a message indicating that the current commit marks a new version, for example "MComix 1.3.0".
5. Create an [annotated tag](https://git-scm.com/book/en/v2/Git-Basics-Tagging) with the version number, for example "1.3.0", using the command `git tag -a 1.3.0 -m "Version 1.3.0"`


Compiling the distribution files
--------------------------------

The source distribution files can be created from any system with Python installed. When following the steps to set up a development environment on [Installation], the `build` module can be used to create the source package.

~~~~~~
:::bash
python3 -m build -s
~~~~~~

This will create `mcomix-version.tar.gz` in the `dist` subfolder, ready for uploading. Note that the command should not be run on a Windows machine, to avoid files in the archive having executable permission bits set. Building the Windows packages is a bit more difficult and requires:

1. A MSYS2 installation with the following packages: `mingw-w64-x86_64-python3-pillow`, `mingw-w64-x86_64-gtk4`, `mingw-w64-x86_64-python3`, `mingw-w64-x86_64-python3-gobject`, `mingw-w64-x86_64-python3-pip`, `mingw-w64-x86_64-python-ujson`, `mingw-w64-x86_64-mypy`, `mingw-w64-x86_64-python-pymupdf`, `mingw-w64-x86_64-libjxl`.
2. Make sure to update to the latest version of these packages before starting the release with `pacman -Syuu`.
3. The Python 3 package `pyinstaller` is automatically installed when development dependencies have been installed, but it shoulld be updated to the latest version with `pip-review --auto --local`
4. The installer script expects optional archive extractors in the directory `../mcomix-other`,  relative to MComix' root directory.  At this time, those are:
4.1. `../mcomix-other/7z/7z.exe`, `../mcomix-other/7z/License.txt` (from [7-zip](https://www.7-zip.org/download.html))
4.2. `../mcomix-other/mutool/COPYING.txt`, `../mcomix-other/mutool/mutool.exe` (from [mupdf](https://mupdf.com/releases/index.html))
4.3. `../mcomix-other/unrar/license.txt`, `../mcomix-other/unrar/UnRAR64.dll` (from [WinRar](https://www.rarlab.com/rar_add.htm))

Afterwards, open a MINGW64 shell in MComix root directory and execute:

~~~~~~
:::bash
python win32/build_pyinstaller.py
~~~~~~

This will compile all necessary libraries and files, and copy them to the directory `dist`.

Afterwards, switch back to a regular Windows console and build the MSI installer. This requires the [WiX toolset](https://wixtoolset.org/docs/wix3/) on your PATH. Navigate to MComix' root folder and execute:

~~~~~~~
:::bash
python win32/build_msi.py
~~~~~~~

You will be notified if problems occured while the installer is building. The finished installer will be placed in the `dist` directory.

Uploading a new release
-----------------------

The procedure is fairly straight-forward. First, switch to the list of files on MComix' project page, then create a new folder corresponding the the version to be released, e.g. `MComix 1.3.0`. Open the folder, click on the "Add file" button, and upload the previously created archive files (`mcomix-version.tar.gz`, `mcomix-win64-version.zip` and `mcomix-win64-version,msi`). When uploading has finished, the now uploaded files should be selected as default files for people visiting the MComix project page. To do this, click on the (i) icon to the right of each file.

1. Mark the MSI installer as default file for Windows.
2. Mark the tar.gz archive as default file for everything else.

Sometimes, uploading the windows packages using the web form can time out. In this case, the files can be uploaded with scp following the [SCP upload manual](https://sourceforge.net/p/forge/documentation/SCP/) of SourceForge.

At this point, creating a news entry containing the changes in this version (copy-pasted from `ChangeLog.md`) might be advisable.


Post-release tasks
------------------

After releasing a new version, it is helpful to edit `mcomix/constants.py` and increase the version number. Also append `-dev0` so that people running MComix from Git source have some indicator that they're running a work-in-progress version.

On SourceForge, new milestones corresponding to the new version should be started and the old milestones marked as closed. Only the "Support Requests" and "Bugs" trackers need milestones. The milestone "Git" should always be open. The milestone is mainly useful for people reporting bugs - this allows to identify the version where the bug occurs, or -alternatively- where the bug has been fixed.
