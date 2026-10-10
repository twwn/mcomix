# Install

> [!NOTE]
> The `mcomix` packages in Linux distributions, Flathub, WinGet and Scoop are the original MComix 3 on GTK 3, not this version.

## Windows

Every [release](https://github.com/twwn/mcomix/releases) has two downloads, each with everything MComix needs:

- the **MSI installer** (needs administrator rights);
- the **portable zip**, `mcomix-win64-<version>.zip`: extract it anywhere and run `MComix.exe`.

Both need 64-bit Windows 10 or 11.

Or, with [Chocolatey](https://chocolatey.org/install):

```powershell
choco install -y mcomix-gtk
```

Uninstalling keeps your preferences, library and bookmarks in `%APPDATA%\MComix`; delete that folder to remove them too.

## Linux

Install from source, into a [virtual environment](https://docs.python.org/3/library/venv.html):

1. Install GTK 4 and PyGObject from your distribution ([PyGObject's guide](https://pygobject.readthedocs.io/en/latest/getting_started.html)).
2. Download `mcomix-<version>.tar.xz` from a [release](https://github.com/twwn/mcomix/releases).
3. Install and run:

```bash
python3 -m venv --system-site-packages ~/mcomix-venv
~/mcomix-venv/bin/pip install "./mcomix-<version>.tar.xz[fileformats]"
~/mcomix-venv/bin/mcomix
```

- `--system-site-packages` uses the system's PyGObject, which pip would otherwise try to build.
- `[fileformats]` adds PyMuPDF (PDF) and chardet (non-UTF-8 names); leave it out to go without.
- To start it as `mcomix`: `ln -s ~/mcomix-venv/bin/mcomix ~/.local/bin/`, where `~/.local/bin` is on the `PATH`.
- Desktop integration: copy the source archive's `share` folder (desktop file, icons, MIME types, AppStream metadata, man page) to `/usr/local/share`. pip neither installs nor removes it. The desktop file starts `mcomix`, so it needs the link above.

### Flatpak

This version is not on Flathub yet. It builds as a Flatpak with id `io.github.twwn.mcomix`, beside Flathub's `net.sourceforge.mcomix`, the original MComix 3.
In the source tree, with [flatpak-builder](https://docs.flatpak.org/en/latest/flatpak-builder.html) and Flathub set up for the user:

```bash
flatpak-builder --user --install-deps-from=flathub --install --force-clean build-dir flatpak/io.github.twwn.mcomix.yml
flatpak run io.github.twwn.mcomix
```

- It brings 7-Zip, UnRAR, DjVuLibre, PyMuPDF and chardet along: every format opens.
- It sees the Documents, Downloads, Pictures and Desktop folders and removable media; more with `flatpak override --user --filesystem=<folder> io.github.twwn.mcomix`.
- Its preferences and library are kept apart, in `~/.var/app/io.github.twwn.mcomix`.
- Uninstall: delete `~/mcomix-venv` and the link. Your settings stay: see [Settings and data](troubleshooting.md#settings-and-data).

## Requirements

- [Python 3.12](https://www.python.org/) or newer
- [GTK 4](https://www.gtk.org/), [PyGObject](https://pygobject.readthedocs.io/) 3.46.0 or newer, [pycairo](https://github.com/pygobject/pycairo) 1.25.0 or newer
- [Pillow](https://pypi.org/project/Pillow/) 10.1.0 or newer

Pages are read by Pillow, and by GTK's image loaders (gdk-pixbuf, or glycin) where Pillow cannot. A format either of them reads opens: JPEG, PNG, GIF, WebP, BMP and TIFF everywhere; JPEG XL, HEIF and others where a loader for them is installed.
A page with a colour profile, a CMYK scan included, is shown converted into sRGB, or into the screen's profile where the preferences name one.

Optional; programs are found on the `PATH`:

Package or program | Adds
-------------------|-----
[libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) | Follows the desktop's GTK 4 theme fully. Without it, as far as plain GTK 4 can.
[PyMuPDF](https://pypi.org/project/PyMuPDF/) 1.24.7 or newer, or `mutool` from [MuPDF](https://mupdf.com/) | PDF files.
The [UnRAR library](https://www.rarlab.com/rar_add.htm) (`libunrar.so` or `UnRAR64.dll`), or the `unrar` or `rar` program | RAR files. `unrar-free` is not used.
`7z` | 7z files; ZIP, LHA, xz and lzma files Python cannot read; RAR as a last resort.
`lha` | LHA files, without `7z`.
`ddjvu` and `djvused` from [DjVuLibre](https://djvu.sourceforge.net/) | DjVu files.
`unzip` | ZIP files Python cannot read, without `7z`.
`xz` | Writes an edited `.tar.xz` book on every core, not one.
[chardet](https://pypi.org/project/chardet/) | Guesses the encoding of file names and comments that are not UTF-8.
[pillow-avif-plugin](https://pypi.org/project/pillow-avif-plugin/) | AVIF pages, where Pillow is older than 11.3 or was built without libavif, and gdk-pixbuf has no AVIF loader.

The Windows packages include everything but `lha` and `unzip`, which `7z` stands in for, and DjVuLibre.

Opening a file whose program is missing says which one it needs.

## Develop

See [Development](development.md).
