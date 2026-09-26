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

**Linux and from source** – install GTK 4 and PyGObject from your distribution, then:

```bash
python3 -m venv --system-site-packages ~/.local/mcomix
~/.local/mcomix/bin/pip install "mcomix-<version>.tar.gz[fileformats]"
~/.local/mcomix/bin/mcomix
```

The source archive is attached to every [release](https://github.com/twwn/mcomix/releases). [Installation](docs/Installation.md) has the details, the optional helpers (unrar, 7z, MuPDF) and desktop integration.

> [!NOTE]
> The `mcomix` packages in Linux distributions, Flathub, WinGet and Scoop are the original MComix 3 on GTK 3, not this version.

## Documentation

| | |
|---|---|
| [User manual](docs/Documentation.md) | Reading, editing, the library |
| [Preferences](docs/Preferences.md) | Every option, explained |
| [Keybindings](docs/Keybindings.md) | Keys and mouse buttons |
| [External commands](docs/External_Commands.md) | Run your own programs on the open file |
| [Maintenance](docs/Maintenance.md) | Translations, builds and releases |
| [ChangeLog](ChangeLog.md) | What changed, release by release |

## About this fork

MComix continues [Comix](https://comix.sourceforge.net/), which stopped in 2009. This repository takes [MComix 3](https://sourceforge.net/projects/mcomix/) from GTK 3 to GTK 4 and keeps going:

- **Modern code** – Python 3.12+, fully typed (`mypy --strict`), and a large test suite run on every push, at the newest Python and at the oldest supported dependencies.
- **Faster** – adding books to the library is hundreds of times quicker, watched-folder scans over ten times, and animated pages play at their full frame rate.
- **Sturdier** – well over a hundred fixes, from lost settings and garbled file names to PDFs past page 9,999.

The GTK 4 port is offered back upstream.

## Contributing

Issues and pull requests are welcome. A change carries its tests and docs, and keeps the three checks clean:

```bash
xvfb-run -a python -m pytest test/ -n auto
python -m flake8 --select=F mcomix/ test/
python -m mypy mcomix
```

## Credits

Comix was created by Pontus Ekberg; thanks to him and to everyone who has contributed code, translations and bug reports since. Icons come from The GIMP, the Tango Desktop Project and Victor Castillejo's GNOME-Colors, and the fit-mode icons were drawn for MComix after GNOME's Adwaita.

## License

[GPL v2](COPYING) or any later version.
