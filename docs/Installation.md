# Installation

> [!NOTE]
> The `mcomix` packages in Linux distributions, Flathub, WinGet and Scoop are the original MComix 3 on GTK 3, not this version.

## Windows

Every [release](https://github.com/twwn/mcomix/releases) has two downloads, each with everything MComix needs:

- the **MSI installer** (needs administrator rights);
- the **portable zip**, `mcomix-win64-<version>.zip`: extract it anywhere and run `MComix.exe`.

Or, with [Chocolatey](https://chocolatey.org/install):

```powershell
choco install -y mcomix-gtk
```

Uninstalling keeps your preferences, library and bookmarks in `%APPDATA%\MComix`; delete that folder to remove them too.

## Linux

Install from source, as [Running from source](#running-from-source) describes.

## Dependencies

From source, MComix needs:

- [Python 3.12](https://www.python.org/) or newer;
- [GTK 4](https://www.gtk.org/), [PyGObject](https://pygobject.readthedocs.io/) 3.46.0 or newer and [pycairo](https://github.com/pygobject/pycairo) 1.25.0 or newer;
- [Pillow](https://pypi.org/project/Pillow/) 10.1.0 or newer.

Everything else is optional; programs are found on the `PATH`.

Package or program | What it adds
-------------------|-------------
[libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) | MComix follows the desktop's GTK 4 theme throughout. Without it, it follows as much of the theme as plain GTK 4 can.
[PyMuPDF](https://pypi.org/project/PyMuPDF/) 1.24.7 or newer, or `mutool` from [MuPDF](https://mupdf.com/) | PDF files.
The [UnRAR library](https://www.rarlab.com/rar_add.htm) (`libunrar.so` or `UnRAR64.dll`), or the `unrar` or `rar` program | RAR files. `unrar-free` is not used.
`7z` | 7z files; ZIP, LHA, xz and lzma files that Python cannot read itself; and RAR files, as a last resort.
`lha` | LHA files, where there is no `7z`.
`unzip` | ZIP files that Python cannot read itself, where there is no `7z`.
[chardet](https://pypi.org/project/chardet/) | Guesses the encoding of file names and comment files that are not UTF-8.

## Running from source

Install GTK 4 and PyGObject first ([PyGObject's guide](https://pygobject.readthedocs.io/en/latest/getting_started.html)). Then install MComix into a [virtual environment](https://docs.python.org/3/library/venv.html) from the source archive attached to each [release](https://github.com/twwn/mcomix/releases):

```bash
python3 -m venv --system-site-packages mcomix-venv
tar -xzf mcomix-<version>.tar.gz
cd mcomix-<version>
../mcomix-venv/bin/python -m pip install .
```

`--system-site-packages` lets the environment use the system's PyGObject, which pip would otherwise try to build. Install `'.[fileformats]'` instead of `.` to add PyMuPDF and chardet. Run MComix as `mcomix-venv/bin/mcomix`.

For desktop integration on Linux, copy the source archive's `share` folder - desktop file, icons, MIME types, AppStream metadata and manual page - to `/usr/local/share`. pip neither installs nor removes it.

To uninstall, delete the virtual environment. Preferences live in `~/.config/mcomix`, the library and bookmarks in `~/.local/share/mcomix`.

## Developing MComix

Clone the repository and install it in editable mode with the development tools; changes take effect the next time MComix starts:

```bash
git clone https://github.com/twwn/mcomix.git
cd mcomix
../mcomix-venv/bin/python -m pip install -e '.[dev]'
```

The tests open windows, so run them under `xvfb-run`:

```bash
xvfb-run -a ../mcomix-venv/bin/python -m pytest test/ -n 8
```
