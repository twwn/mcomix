# MComix

MComix is a customizable image viewer for reading comic books, both Western
comics and manga. It opens images on their own, in a directory, or in
ZIP/CBZ, RAR/CBR, 7z/CB7, tar/CBT, LHA/LZH, PDF/CBP and AZW3 (MobiPocket)
files. It is written in Python with GTK 4 through the PyGObject bindings, and
runs on Linux and Windows.

![MComix' main window](docs/images/mcomix-mainwindow.png)

*The comic shown is "The Potion of Flight", episode 1 of
[Pepper&Carrot](https://www.peppercarrot.com/) by David Revoy, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and scaled down.*

- Reads images, directories and ZIP, RAR, 7z, tar, LHA, PDF and AZW3 files
  directly, and writes archives back from its own editor.
- Fullscreen and double page modes, manga (right-to-left) reading, and fits
  the page to the window's width, its height, both, or a size of your own.
- Smart scrolling walks a page in reading order, one key at a time.
- A library that keeps collections, covers and reading progress, and watches
  folders for new books.
- Bookmarks, thumbnails, a magnifying lens, image enhancement, and external
  commands that run programs of your own on the open file.
- Follows the desktop's light or dark theme, with a pitch black variant for
  OLED screens.
- 24 complete translations.

## What this repository is

This is a fork of [MComix](https://sourceforge.net/projects/mcomix/), itself
a fork of Comix, whose development stopped in late 2009. Upstream MComix 3.2
runs on GTK 3; everything below is what this repository adds on top of it,
and the GTK 4 work is offered back upstream. [ChangeLog.md](ChangeLog.md) has
the full list, release by release.

**GTK 4.** The whole interface was ported: menus are Gio menu models rather
than `Gtk.UIManager`, the widgets GTK 4.10 deprecated are gone, and the
window follows the desktop's light or dark theme, fully where libadwaita is
installed.

**A modernized code base.** Python 3.12 is the floor, GTK 3 support and dead
code are gone, and the tree is annotated for mypy, which runs at `--strict`
with explicit `Any` disallowed and reports nothing across 161 modules.
pyflakes is silent. The test suite, which had stopped running, is back at
3,104 tests over 81 files, and [GitHub Actions](.github/workflows/tests.yml)
runs all three gates on Python 3.12 and 3.14 and the suite again at the
declared dependency floors.

**Speed**, measured before and after:

- Adding 2,000 books to the library took 32.8 s with a commit per write and
  takes 39 ms in one transaction; the watch-list scan and the collection
  sweep make one query instead of one per book, 15.2 ms instead of 203.7 ms
  over 40,000 books.
- An animated page is decoded by Pillow on a worker thread into a paintable
  that only invalidates its contents. A 30 fps WebP played at 13.6 fps
  before, with each frame replacing the texture and laying the window out
  again.
- The PDF handler imports PyMuPDF only inside its worker process, so a
  session that opens no PDF never pays for it.

**Features.** Pages can be deleted, renamed, reordered and swapped while
reading, with an undo stack; the archive editor undoes, redoes, writes a book
back in the format it was opened in, and keeps every file the original held
alongside a generated ComicInfo.xml. Properties reads series, issue number,
title and writer from ComicInfo.xml. A middle click opens a recent file, a
bookmark or a library cover in a new window, and the mouse's thumb buttons
turn back a page and show the OSD panel. Preferences are saved as they
change, without undoing another window's, and every "Do not ask again" answer
can be taken back on its own.

**Bug fixes**, sixty commits' worth, many of them long-standing: instances
quitting at once truncated each other's preferences and keybindings, one bad
line in `keybindings.conf` silenced a shortcut, an interrupted library
upgrade could leave the library unopenable, encrypted RAR files could not be
opened through the UnRAR library, PDF pages past 9999 opened the wrong page,
closed dialogs and library windows were never freed, and letter shortcuts did
nothing while Caps Lock was on.

**Translations.** All 24 catalogues are complete and checked by the suite:
plural forms reach every form a language has, menu labels keep a mnemonic of
their own per language, and eighteen labels in eight languages that said
something other than what they name were corrected.

## Installation

The [Installation](docs/Installation.md) page lists the packages for Linux
distributions and Windows, what MComix needs to run, and how to run it from
source. Most users will find it easiest to install the package their
operating system provides.

## Documentation

The [Documentation](docs/Documentation.md) page is the user manual;
[Preferences](docs/Preferences.md), [Keybindings](docs/Keybindings.md) and
[External Commands](docs/External_Commands.md) have pages of their own, and
[Maintenance](docs/Maintenance.md) describes releasing a version.
[docs/](docs/README.md) is the index.

## Contributing

Bug reports and patches are welcome through the repository's
[issue tracker](https://github.com/twwn/mcomix/issues) and pull requests. A
change to the program carries its documentation and its tests: `pytest`,
`flake8 --select=F mcomix/ test/` and `mypy mcomix` all have to stay clean,
as they do in CI.

## Credits

Comix was originally developed by Pontus Ekberg. Many thanks to him and to
everyone who has contributed translations, suggestions, bug reports and fixes
since.

The rotation, flip, thumbnail and transformation icons are taken from The
GIMP, and the bookmark, archive, image and image enhancement icons from the
Tango Desktop Project. Most other icons are made by Victor Castillejo,
creator of the GNOME-Colors icon theme. The symbolic icons for the fit modes
were drawn for MComix after GNOME's Adwaita icons.

## License

GNU General Public License, version 2 or any later version; see
[COPYING](COPYING).
