# Releasing

Versions are year and month: `26.10` for October 2026. A second release that month is `26.10.1`.

## Steps

1. Give the release its section in `ChangeLog.md`: a `# MComix <version>` heading, a `## Release date:` line below it. Each entry on one line, however long: the release notes keep every line break.
2. Set `VERSION` in `mcomix/constants.py`, and the version and month in the first line of the man page, `share/man/man1/mcomix.1.gz` (unpack, edit, pack with `gzip -9n`).
3. Regenerate the translation files, as in [Development](development.md#translations). The template's header carries the version.
4. Add the release to `share/metainfo/mcomix.metainfo.xml`.
5. Commit as "MComix 26.10", tag the commit, push both:

```bash
git tag -a 26.10 -m "Version 26.10"
git push origin main 26.10
```

The tag starts the release workflow. The rest is automatic.

## The release workflow

`.github/workflows/release.yml`, on a version tag:

1. Checks that the tag is `VERSION` in `mcomix/constants.py`.
2. Builds the source archive on Linux, and the Windows zip and MSI installer in MSYS2.
3. Starts the built `MComix.exe` on a PDF and on a missing book; any error fails the run.
4. Publishes the GitHub release: the three files, a `SHA256SUMS` file, and the release's `ChangeLog.md` section as its notes.
5. Attests each file's build provenance: `gh attestation verify <file> --repo twwn/mcomix` proves it was built there, from the tag.
6. Runs `.github/workflows/publish.yml`: the [packages](#packages).

- To release a tag again, after moving it: push it again (`git push -f origin 26.10`), or run the workflow from the Actions tab, given the tag.
  A draft release is replaced. A published one is not: delete it by hand first, keeping the tag.
- The build takes everything at its newest: MSYS2's packages, 7-Zip from the runner, the newest non-beta UnRAR.dll from RARLAB's site. The run's summary lists versions and sizes.
- Without a tag it makes a test build: every Monday, for a pull request that changes the build, and by hand with the tag left empty.
  Its files stay with the run for two weeks. A failed Monday build means something the build takes has changed.

## Packages

`publish.yml` runs after the release workflow, for a release published by hand, and by hand, given the tag.
Each package needs a repository secret, and is skipped with a notice without it:

Secret | For
-------|----
`CHOCOLATEY_API_KEY` | An API key of the Chocolatey account `win32/mcomix.nuspec` names as its owner.
`WINGET_TOKEN` | A classic token with the `public_repo` scope, of an account with a fork of [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs).

- Chocolatey: pushes `mcomix-gtk`. Packages are moderated, so the version appears some time later. (`mcomix` there is the original MComix 3.)
- winget: opens a pull request with the new version. winget only updates a package it has: submit the first version by hand, with `komac new` or `wingetcreate new`, under the identifier in the repository variable `WINGET_IDENTIFIER` (`twwn.MComix` where it is not set). `MComix.MComix` is the original MComix 3.

## Building by hand

The same steps, without GitHub Actions.

### Source archive

On Linux, [set up for development](development.md#set-up), then:

```bash
python3 tools/source_archive.py
```

This writes `dist/mcomix-<version>.tar.xz`: the sdist, compressed with xz, named with the version as the tag spells it. Not on Windows: files in the archive would get executable permission bits.

### Windows packages

Build in [MSYS2](https://www.msys2.org/)'s UCRT64 environment, the one MSYS2 builds PyMuPDF for (with CLANG64). The packages, updated with `pacman -Syuu` before each release:

- `mingw-w64-ucrt-x86_64-gtk4`
- `mingw-w64-ucrt-x86_64-adwaita-icon-theme`
- `mingw-w64-ucrt-x86_64-libadwaita`
- `mingw-w64-ucrt-x86_64-libjxl`
- `mingw-w64-ucrt-x86_64-python`
- `mingw-w64-ucrt-x86_64-python-gobject`
- `mingw-w64-ucrt-x86_64-python-pillow`
- `mingw-w64-ucrt-x86_64-python-pip`
- `mingw-w64-ucrt-x86_64-python-pymupdf`
- `mingw-w64-ucrt-x86_64-pyinstaller`

`win32/build_pyinstaller.py` and `.github/workflows/release.yml` name the same list; `test/test_wiki.py` checks that all three agree.

The build copies these archive programs from `../mcomix-other`, beside the checkout. A folder that is not there is left out.

Folder | Files | From
-------|-------|-----
`7z` | `7z.exe`, `7z.dll`, `License.txt` | [7-Zip](https://www.7-zip.org/download.html)
`unrar` | `UnRAR64.dll`, `license.txt` | [RARLAB](https://www.rarlab.com/rar_add.htm)

There is no `mutool`: PyMuPDF carries its own MuPDF, and a second one would add 47 MB.

In a UCRT64 shell in the checkout, build `dist/MComix` and `dist/mcomix-win64-<version>.zip`:

```bash
python win32/build_pyinstaller.py
```

Then, with the [WiX Toolset](https://wixtoolset.org/docs/wix3/) version 3 on the `PATH`, build `dist/mcomix-win64-<version>.msi`:

```bash
python win32/build_msi.py
```

It also writes the installer's SHA-256 to `win32/tools/checksum.sha256` and the version to `win32/tools/release.txt`, for the Chocolatey package.

### GitHub release

Draft a release from the tag, named `MComix <version>`, with the release's section of `ChangeLog.md` as its notes.
Attach `mcomix-<version>.tar.xz`, `mcomix-win64-<version>.zip` and `mcomix-win64-<version>.msi`.
The Chocolatey package downloads the MSI from exactly that release, under exactly that name.

### Chocolatey package

The package does not carry MComix: it downloads the MSI installer from the GitHub release and checks it against `win32/tools/checksum.sha256`.

- Publish the release first.
- Pack the checksum and release files the build of that same installer wrote. They are not kept in Git, since they describe one build.
- `release.txt` exists because Chocolatey reads a version as a number, and turns 26.09 into 26.9.0.

With the [Chocolatey CLI](https://chocolatey.org/install), in the checkout:

```bash
choco pack win32/mcomix.nuspec --version <version> --out dist
choco push dist/mcomix-gtk.<version>.nupkg --source https://push.chocolatey.org/
```

- `choco pack` may add a third number, as `mcomix-gtk.26.10.0.nupkg`: push the file it names.
- Pushing needs the owner's API key, set once with `choco apikey`.

## After a release

Close the release's milestone and open one for the next, so an issue can say which version a bug occurs in, or was fixed in.
