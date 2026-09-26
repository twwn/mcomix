# Troubleshooting

## Logs

A log says what MComix did, and is the first thing a bug report needs.

```bash
mcomix -W debug -o mcomix.log
```

On Windows, in PowerShell (the installer puts MComix in `C:\Program Files\MComix`; for the zip, use its folder):

```powershell
& 'C:\Program Files\MComix\MComix.exe' -W debug -o "$HOME\mcomix.log"
```

- `-W` sets the detail: `all`, `debug`, `info`, `warn` (default) or `error`.
- `-o` writes the log to a file as well. `MComix.exe` has no console, so on Windows the file is the only way to see it.
- An error MComix did not expect is logged with its traceback.

## A book does not open

- RAR, 7z, LHA and PDF need a helper program or library: see [Install](install.md#requirements). The Windows packages carry them.
- MComix does not use `unrar-free`.
- Otherwise, run MComix with a log as above, open the book, and attach the log to a bug report.

## The window stays black, flickers or crashes at start

GTK draws with the graphics card, and some drivers fail at it. Its software renderer avoids them:

- Linux: `GSK_RENDERER=cairo mcomix`
- Windows, in PowerShell: `$env:GSK_RENDERER = 'cairo'; & 'C:\Program Files\MComix\MComix.exe'`

If that helps, set `GSK_RENDERER=cairo` in your environment for good, and mention the driver in a bug report.

## Wrong version

- "File &rarr; About" shows the version; so does `mcomix --version` on Linux.
- This MComix counts year and month, as 26.09.
- MComix 3.x is the original on GTK 3: the `mcomix` package of Linux distributions, Flathub, WinGet and Scoop.

## Settings and data

What | Linux | Windows
-----|-------|--------
Preferences (`preferences.conf`), keys (`keybindings.conf`) | `~/.config/mcomix` | `%APPDATA%\MComix`
Library, bookmarks, last pages, library covers | `~/.local/share/mcomix` | `%APPDATA%\MComix`
Thumbnails of books and images | `~/.cache/thumbnails`, shared with other programs | `%APPDATA%\MComix\.thumbnails`

On Linux, `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_CACHE_HOME` move these.

To start over, quit MComix and delete `preferences.conf`, `keybindings.conf`, or the whole folder.
Without quitting: "Clear dialog choices" in the preferences asks every question again, and "Reset keys" on the Shortcuts tab puts back the default keys.

## Reporting a bug

1. Check the [open issues](https://github.com/twwn/mcomix/issues).
2. [Open a bug report](https://github.com/twwn/mcomix/issues/new/choose): the form asks for the version, the system and the steps.
3. Attach the log, and a book that shows the problem if you can share one.

A security problem goes to a [private advisory](https://github.com/twwn/mcomix/security/advisories/new) instead: see [Security](../SECURITY.md).
