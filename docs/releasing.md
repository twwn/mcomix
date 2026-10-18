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
2. Builds the source archive on Linux, the Windows zip and MSI installer in MSYS2, and the [Flatpak](#flatpak) bundle.
3. Starts the built `MComix.exe` on a PDF and on a missing book; any error fails the run.
4. Publishes the GitHub release: the four files, a `SHA256SUMS` file, and the release's `ChangeLog.md` section as its notes.
   A Flatpak that failed to build is left out with a warning; the release goes out without it.
5. Attests each file's build provenance: `gh attestation verify <file> --repo twwn/mcomix` proves it was built there, from the tag.
6. Runs `.github/workflows/publish.yml`: the [packages](#packages).

- To release a tag again, after moving it: push it again (`git push -f origin 26.10`), or run the workflow from the Actions tab, from the tag ("Use workflow from", Tags).
  A draft release is replaced. A published one is not: delete it by hand first, keeping the tag.
- A changed section in `ChangeLog.md` changes the published notes too: `.github/workflows/release-notes.yml` runs on every push to `main` that changes the file, and replaces each release's notes that no longer match its section.
- The build takes everything at its newest: MSYS2's packages, 7-Zip from the runner, the newest non-beta UnRAR.dll from RARLAB's site. The run's summary lists versions and sizes.
- Without a tag it makes a test build: every Monday, for a pull request that changes the build, and by hand from a branch.
  Its files stay with the run for two weeks. A failed Monday build means something the build takes has changed.

## Packages

`publish.yml` runs after the release workflow, for a release published by hand, and by hand, given the tag.
Each package has a [GitHub environment](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments) of its own, which holds its secret.
Only that package's job can read it. Without the secret the job is skipped with a notice.

Environment | Secret | For
------------|--------|----
`chocolatey` | `CHOCOLATEY_API_KEY` | An API key of the Chocolatey account `win32/mcomix.nuspec` names as its owner.
`winget` | `WINGET_TOKEN` | A classic token with the `public_repo` scope, of the account whose fork of [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) opens the pull request.

### Setting up the environments

Once, in the repository's Settings, Environments, for each of the two:

1. New environment, named as in the table.
2. Deployment branches and tags: Selected branches and tags. Add the tag rule `[0-9][0-9].[0-9][0-9]*`, and nothing else.
   A run by hand then has to start from the tag ("Use workflow from", Tags).
3. Optional: Required reviewers, yourself. Each run then waits for your approval before it can read the secret.
4. Environment secrets: add the secret.

Never add these secrets as repository secrets: every workflow could read them.

### Chocolatey

1. Sign in at [community.chocolatey.org](https://community.chocolatey.org/account/Register), as the owner the nuspec names.
2. Account: copy the API key. It can push every package of the account: keep it in the environment only.
3. A new key, after a leak or a change of hands: Account, Regenerate. Then replace the secret.

The job pushes `mcomix-gtk`. Packages are moderated, so the version appears some time later. (`mcomix` there is the original MComix 3.)

### winget

1. Make a separate GitHub account for the bot, with two-factor authentication. A classic token reaches every public repository its account can write to: this account can write to its fork alone.
2. Fork [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) to it.
3. Under that account: Settings, Developer settings, Tokens (classic). Scope `public_repo` only, with an expiry date. Fine-grained tokens cannot open a pull request on another owner's repository.
4. Store it as `WINGET_TOKEN` in the `winget` environment. Set the repository variable `WINGET_FORK_USER` to the bot's name.
5. Submit the first version by hand: winget only updates a package it has. Use `komac new` or `wingetcreate new`, under the identifier in the repository variable `WINGET_IDENTIFIER` (`twwn.MComix` where it is not set). `MComix.MComix` is the original MComix 3.

The job then opens a pull request with each new version. Renew the token before it expires.

### Flatpak

The release workflow builds the Flatpak, `io.github.twwn.mcomix`, from `flatpak/io.github.twwn.mcomix.yml`, and attaches `mcomix-<version>.flatpak` to the release.

- Flathub lists an app once its submission is accepted: [Flathub's guide](https://docs.flathub.org/docs/for-app-authors/submission) has the steps, [its requirements](https://docs.flathub.org/docs/for-app-authors/requirements) the rules the manifest must meet.
- After that, no secret is needed. Flathub's own checker reads the `x-checker-data` of the manifest's MComix source every two hours, and opens the pull request for a new tag on [flathub/io.github.twwn.mcomix](https://github.com/flathub/io.github.twwn.mcomix). Merging it publishes the update.
- The name stays MComix; only the id tells it from Flathub's `net.sourceforge.mcomix`, the original MComix 3.

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

### Flatpak bundle

With [flatpak-builder](https://docs.flatpak.org/en/latest/flatpak-builder.html) and Flathub set up for the user:

```bash
flatpak-builder --user --install-deps-from=flathub --force-clean --repo=repo build-dir flatpak/io.github.twwn.mcomix.yml
flatpak build-bundle repo dist/mcomix-<version>.flatpak io.github.twwn.mcomix --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo
```

### GitHub release

Draft a release from the tag, named `MComix <version>`, with the release's section of `ChangeLog.md` as its notes.
Attach `mcomix-<version>.tar.xz`, `mcomix-win64-<version>.zip`, `mcomix-win64-<version>.msi` and `mcomix-<version>.flatpak`.
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
