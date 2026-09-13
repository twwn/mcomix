# Installation

[TOC]

## Linux

Most distributions package MComix. Install it with the distribution's own package manager where that version is current, and from Flathub where it is not.

Distribution | Command
-------------|--------
Debian 12 or later, Ubuntu 23.04 or later | `sudo apt install mcomix`
openSUSE Leap 15.4 or later | `sudo zypper install mcomix`
Arch Linux, from the AUR | `yay -S mcomix`
Any, with [Flatpak](https://flatpak.org/setup/) | `flatpak install flathub net.sourceforge.mcomix`

## Windows

Package manager | Command
----------------|--------
[WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/) | `winget install mcomix`
[Chocolatey](https://chocolatey.org/install) | `choco install -y mcomix`
[Scoop](https://scoop.sh/), Extras bucket | `scoop bucket add extras`, then `scoop install extras/mcomix`

Without a package manager, run the MSI installer, which needs administrator rights. Where those are not available, extract `mcomix-win64-<version>.zip` anywhere and run `MComix.exe` from there. Both carry everything MComix needs.

Uninstalling leaves the preferences, the library and the bookmarks in `%APPDATA%\MComix`. Delete that folder to remove them as well.

<a name="dependencies"></a>
## Dependencies

Running MComix from source requires:

- [Python 3.12](https://www.python.org/) or newer;
- [GTK 4](https://www.gtk.org/), [PyGObject](https://pygobject.readthedocs.io/) 3.46.0 or newer and [pycairo](https://github.com/pygobject/pycairo) 1.25.0 or newer;
- [Pillow](https://pypi.org/project/Pillow/) 10.1.0 or newer.

Everything else is optional. Programs are looked for on the `PATH`.

Package or program | What it adds
-------------------|-------------
[libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) | MComix follows the desktop's GTK 4 theme throughout. Without it, it follows as much of the theme as plain GTK 4 can.
[PyMuPDF](https://pypi.org/project/PyMuPDF/) 1.23.5 or newer, or `mutool` from [MuPDF](https://mupdf.com/) | PDF files.
The [UnRAR library](https://www.rarlab.com/rar_add.htm) (`libunrar.so` or `UnRAR64.dll`), or the `unrar` or `rar` program | RAR files. `unrar-free` is not used.
`7z` | 7z files; ZIP, LHA, xz and lzma files that Python cannot read itself; and RAR files, as a last resort.
`lha` | LHA files, where there is no `7z`.
`unzip` | ZIP files that Python cannot read itself, where there is no `7z`.
[chardet](https://pypi.org/project/chardet/) | Guesses the encoding of file names and comment files that are not UTF-8.

## Running from source

Install GTK 4 and PyGObject first, as PyGObject's [Getting Started guide](https://pygobject.readthedocs.io/en/latest/getting_started.html) describes. Then create a [virtual environment](https://docs.python.org/3/library/venv.html) and install MComix into it from the source archive:

~~~~~~
:::bash
python3 -m venv --system-site-packages mcomix-venv
tar -xzf mcomix-<version>.tar.gz
cd mcomix-<version>
../mcomix-venv/bin/python -m pip install .
~~~~~~

`--system-site-packages` lets the environment use the PyGObject installed above; without it, pip tries to build PyGObject from source. Install `'.[fileformats]'` instead of `.` to add PyMuPDF and chardet. MComix is then run as `mcomix-venv/bin/mcomix`.

On Linux, the `share` folder of the source archive holds the desktop file, the icons, the MIME types, the AppStream metadata and the manual page, laid out as they belong under `/usr/local/share`. Copy them there for desktop integration; pip neither installs nor removes them.

To uninstall, delete the virtual environment. The preferences are kept in `~/.config/mcomix`, and the library and the bookmarks in `~/.local/share/mcomix`.

## Developing MComix

Clone the repository, and install it in editable mode with the development tools, so that changes to the source take effect the next time MComix starts:

~~~~~~
:::bash
git clone https://git.code.sf.net/p/mcomix/git mcomix
cd mcomix
../mcomix-venv/bin/python -m pip install -e '.[dev]'
~~~~~~

The test suite opens windows, so run it under `xvfb-run`:

~~~~~~
:::bash
xvfb-run -a ../mcomix-venv/bin/python -m pytest test/ -n 8
~~~~~~
