# MComix

**A fast, keyboard-friendly comic and manga reader for Linux and Windows, built on GTK 4.**

[![Tests](https://github.com/twwn/mcomix/actions/workflows/tests.yml/badge.svg)](https://github.com/twwn/mcomix/actions/workflows/tests.yml)
[![Latest release](https://img.shields.io/github/v/release/twwn/mcomix?sort=date)](https://github.com/twwn/mcomix/releases/latest)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License: GPL v2+](https://img.shields.io/badge/license-GPL%20v2%2B-green)](COPYING)

![MComix' main window](docs/images/mcomix-mainwindow.png)

<sub>Shown: "The Potion of Flight", episode 1 of [Pepper&Carrot](https://www.peppercarrot.com/) by David Revoy, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), scaled down.</sub>

## Highlights

- **Opens everything** – images, folders, CBZ/ZIP, CBR/RAR (split volumes too), CB7/7z, CBT/tar, LHA, PDF and AZW3.
- **Reads your way** – single or double page, manga right-to-left, fit to width, height or both, and smart scrolling that walks a page in reading order.
- **Edits books** – rename, reorder, swap and delete pages while reading, with undo, and write the archive back in its own format with a ComicInfo.xml.
- **Library** – collections, covers, reading progress and watched folders.
- **Looks at home** – follows your light or dark theme, with a pitch-black variant for OLED screens.
- **Speaks your language** – 24 complete translations.
- **Plus** bookmarks, a magnifying lens, image enhancement and your own external commands.

## Install

**Windows** – grab the MSI installer or the portable zip from the [latest release](https://github.com/twwn/mcomix/releases/latest), or use Chocolatey:

```powershell
choco install mcomix-gtk
```

**Linux** – install GTK 4 and PyGObject from your distribution, download the source archive from the [latest release](https://github.com/twwn/mcomix/releases/latest), then:

```bash
python3 -m venv --system-site-packages ~/mcomix-venv
~/mcomix-venv/bin/pip install "./mcomix-<version>.tar.xz[fileformats]"
~/mcomix-venv/bin/mcomix
```

[Install](docs/install.md) has the details: optional helpers (unrar, 7z, MuPDF), desktop integration, uninstalling.

> [!NOTE]
> The `mcomix` packages in Linux distributions, Flathub, WinGet and Scoop are the original MComix 3 on GTK 3, not this version.

## Documentation

- [Reading](docs/reading.md) – opening books, fit modes, double page and manga, slideshow
- [Editing books](docs/editing.md) – rename, reorder and delete pages; save archives
- [Library](docs/library.md) – collections, covers, watched folders
- [Preferences](docs/preferences.md) · [Keyboard and mouse](docs/shortcuts.md) · [External commands](docs/external-commands.md)
- [Troubleshooting](docs/troubleshooting.md) – logs, common problems, reporting a bug
- [Changelog](ChangeLog.md) – what changed, release by release

All pages: [docs](docs/README.md).

## About this fork

MComix continues [Comix](https://comix.sourceforge.net/), which stopped in 2009. This repository takes [MComix 3](https://sourceforge.net/projects/mcomix/) from GTK 3 to GTK 4 and keeps going:

- **Modern code** – Python 3.12+, fully typed (`mypy --strict`), and a large test suite run on every push, at the newest Python and at the oldest supported dependencies.
- **Faster** – adding books to the library is hundreds of times quicker, watched-folder scans over ten times, and animated pages play at their full frame rate.
- **Sturdier** – well over a hundred fixes, from lost settings and garbled file names to PDFs past page 9,999.

The GTK 4 port is offered back upstream.

## Contributing

Issues and pull requests are welcome: see [Contributing](CONTRIBUTING.md) and [Development](docs/development.md).
Questions go to [Discussions](https://github.com/twwn/mcomix/discussions).

## Credits

Comix was created by Pontus Ekberg; thanks to him and to everyone who has contributed code, translations and bug reports since. Icons come from The GIMP, the Tango Desktop Project and Victor Castillejo's GNOME-Colors, and the fit-mode icons were drawn for MComix after GNOME's Adwaita.

## License

[GPL v2](COPYING) or any later version.
