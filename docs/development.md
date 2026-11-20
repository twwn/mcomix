# Development

## Set up

Install GTK 4 and PyGObject from your distribution, as for [Install](install.md), then:

```bash
git clone https://github.com/twwn/mcomix.git
cd mcomix
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev,fileformats]'
.venv/bin/mcomix
```

- `-e` installs in place: a change takes effect the next time MComix starts.
- `.[dev]` adds pytest, pytest-xdist, flake8, mypy, the GTK type stubs and `build`.

## Checks

Three checks, clean before every commit, as CI runs them:

```bash
xvfb-run -a .venv/bin/python -m pytest test/ -n auto
.venv/bin/python -m flake8 --select=F mcomix/ test/
.venv/bin/python -m mypy mcomix
```

- The tests open windows. Under `xvfb-run` they stay off your desktop, also in a Wayland session.
- A test that fails under `-n auto` but passes alone is a bug, not bad luck: a race, or state one test leaves behind.
- mypy runs strict, with no explicit `Any`: new code is fully annotated.
- Base a new test on `test.MComixTest`. It points the preferences, library, bookmarks and recent files at a temporary home, so no test touches yours.

## Writing tests

Use what `test/__init__.py` has before writing a set-up or helper of your own.
`test/test_copies.py` fails when a function body of some size appears twice, in the tests or the program.
It also fails when five statements in a row, imports aside, appear twice in the tests: make them a helper.

Class or helper | For
----------------|----
`MComixTest` | Every test: a temporary home, preferences reset. `self.extracted(archive, name)` reads a member as the archive extracts it.
`MainWindowOpenTest` | A test with the main window open and no book.
`MainWindowLaterTest` | A test that opens the main window itself, if at all; it is closed afterwards.
`open_main_window()`, `close_main_window()` | The main window as MComix opens and quits it; `close_a_main_window(window)` quits one the test built itself.
`open_main_window_on_a_book()` | The main window opened on a four-page ZIP, once its pages are listed.
`self.window_holding(child, size)` | A window of the test's own holding a widget, on screen, destroyed after the test.
`self.make_user_directories()` | The configuration, data and thumbnail folders, which `setUp()` names but does not make.
`self.wait_for_pages(count)` | Wait for the book opened in `self.window` to have its pages listed: any, or `count` of them.
`pump()`, `wait_for()`, `wait_frames()` | Let the main loop run; wait for a condition rather than a time.
`children()`, `descendants()` | The widgets inside a widget.
`visible_prompts()`, `prompts_over(window)` | The message dialogs on screen, or standing over a window.
`notebook_tabs(notebook)` | The labels of a notebook's tabs.
`simple_file_chooser()` | The `SimpleFileChooserDialog` on screen, if any.
`hold_open(popover)` | A popover that stays open under Xvfb.
`take_activation_from(test, window)` | Another window made active, so that `window` is not.
`keep_focus_within(window)` | The focus state kept on a window's widgets while another worker's window has the keyboard.
`focused_row(window)` | The column list row under a window's focus widget, or None.
`refuse_passwords(test)` | Cancel every password prompt; the archives asked about are listed.
`FolderDialogStub(folder)` | Stands in for a folder chooser's answer.
`StubFileHandler` | A window's file handler with no book and the `file_opened` and `file_closed` signals, for a menu's tests.
`windows_refusal(name)` | `os.remove` or `os.unlink` refusing a read-only file, as on Windows.
`replace_held_once()` | `os.replace` refusing once, as on Windows while another process holds the file.
`fresh_bookmarks_store()` | The bookmarks store read again from the test's home. `setUp()` does it already.
`session_tmp_dir()` | A folder that lasts the whole run, for what goes on writing after its test.
`sample_pages(count)` | Paths of up to three pictures to pack or open.
`pixel(pixbuf, x, y)` | One pixel's channels.
`get_testfile_path(...)` | A file under `test/files/`.
`NORMAL_ZIP` | `test/files/archives/01-ZIP-Normal.zip`, the book most tests open.

A helper several tests of one file share goes on a base class in that file.
A helper another file needs goes into `test/__init__.py` and this table.
Before moving a method out of a class, check no subclass overrides it.
Imports go at the top of the test module. One inside a test needs a reason: an optional library, or a module whose import the test watches.
Undo what a test changes with `mock.patch`, `self.enterContext()` or `self.addCleanup()`, not by hand in a `finally`.
Name each case of a loop with `self.subTest()`, not with a failure message built by hand.
A search or filter a test types is matched against paths too, and `self.tmp_dir` ends in random letters, digits and underscores: give each word a dash, which the folder's name cannot hold.
The CI also runs the tests on Windows and with the oldest supported libraries. Do not assume animations are on, that a key types what its name says, or that PyGObject hands back render nodes: wait for the size, check the keymap, or skip there.

Waiting:

- Wait for what the test needs, with `wait_for()`, `self.wait_for_pages()` or `wait_frames()`, never for a guessed time. `time.sleep()` belongs only in a polling loop or a stand-in for slow work.
- A style, a layout or a paint comes with the frame clock: wait for a few frames, not milliseconds.
- A pause or poll MComix keeps (a search delay, a preview poll) is patched shorter or called at once, not waited out.
- Something asynchronous: assert what the call set at once, then pump, then assert what the answer changed.
- A check that something does not happen waits a short, bounded time, and has been shown to fail when it does happen.

A test that leaves a window on screen fails with "left on screen". Destroy what you present, or use `self.window_holding()`.

## Writing code

What the refactors and speed-ups of the program taught, so it is not written again:

- GTK 4 sets these already: a widget is visible from the start (windows and popovers aside), a window is resizable, a label is centred both ways, a scrolled window shows its scroll bars as needed. Set them only to undo something.
- A `Gio.Menu` item shows no tooltip.
- `test/test_copies.py` fails on a function body written twice. Make one function and pass the difference.
- Leave out what nothing reads: a parameter only MComix passes, a method that only calls the one it overrides, a constant. A value read only in the method that sets it is a local, not an attribute.
- Do not test what the annotation already rules out. mypy runs strict.
- Sort on keys made once per item, such as `tools.natural_key()`, not by comparing pairs in Python. Keep the keys where the same items are sorted again.
- Build a menu or a dialog when it is first opened, not at start, and once.
- Opening a book reads that book. Do not open or read every file beside it on the main thread; cache what a later open asks again.
- Keep steps that run in order, such as the preferences' migrations, in that order in the code.
- A confirmation's two buttons come from `Dialog.add_confirmation_buttons()`: the answer that changes nothing first, pressed by Enter, then the one that acts, drawn as destructive.

## Layout

Path | What
-----|-----
`mcomix/` | The program. `mcomix/archive/` reads and writes archives; `mcomix/library/` is the library.
`mcomix/messages/` | Translations.
`test/` | The tests; `test/files/` the books they open.
`share/` | Desktop file, icons, MIME types, AppStream metadata, man page.
`artwork/` | The icon's source, and the Makefile that draws every size from it: see its [README](../artwork/README.md).
`win32/` | The Windows build, the MSI installer and the Chocolatey package.
`flatpak/` | The Flatpak's manifest, and the scripts that write the Flathub manifest from it and keep its format: see [Releasing](releasing.md#flatpak).
`fuzz/` | The [fuzz targets](#fuzzing) and their seeds.
`mcomixstarter.py` | The script the Windows build freezes into `MComix.exe`.
`tools/` | `source_archive.py`, which builds the source archive: see [Releasing](releasing.md#source-archive).
`.github/` | The [workflows](#continuous-integration), issue forms, pull request template and Dependabot's settings.
`docs/` | This documentation. `test/test_wiki.py` checks it against the code.

## Translations

A new or changed translatable string needs three files updated:

1. the template `mcomix/messages/mcomix.pot`;
2. every catalogue, `mcomix/messages/*/LC_MESSAGES/mcomix.po`;
3. each compiled `mcomix.mo` beside it.

All are kept in Git, and `test/test_messages.py` fails until they agree with the source. From the repository's root, with GNU gettext:

```bash
#!/bin/sh
VERSION=$(grep VERSION mcomix/constants.py | sed -e "s/VERSION = //" -e "s/'//g")
MAINTAINER="https://github.com/twwn/mcomix/issues"

xgettext -LPython -omcomix.pot -pmcomix/messages/ -cTRANSLATORS \
	--from-code=utf-8 --package-name=MComix --package-version=${VERSION} \
	--msgid-bugs-address=${MAINTAINER} \
	mcomix/*.py mcomix/archive/*.py mcomix/library/*.py

for pofile in mcomix/messages/*/LC_MESSAGES/*.po
do
	# msgmerge marks the old translation of a changed string fuzzy, and
	# msgfmt leaves fuzzy entries out, so nothing uncertain is shipped.
	msgmerge -U --backup=none ${pofile} mcomix/messages/mcomix.pot
	msgfmt ${pofile} -o ${pofile%.*}.mo
done
```

A new language: copy the template to `mcomix/messages/<code>/LC_MESSAGES/mcomix.po`, translate it, run the script, and add the language to the list in `mcomix/preferences_dialog.py`.
Translate the desktop entry's `GenericName`, `Comment` and `Keywords` in `share/applications/mcomix.desktop`, and the summary and each paragraph of the description in `share/metainfo/mcomix.metainfo.xml`, too: `test/test_desktop_entry.py` checks that both speak every language there is a catalogue for.

## Fuzzing

`fuzz/` holds [Atheris](https://github.com/google/atheris) targets for the readers MComix runs on whatever file it is handed: `fuzz_ion.py` (the Ion inside KFX books), `fuzz_kfx.py`, `fuzz_epub.py`, `fuzz_mobi.py`, `fuzz_comicinfo.py`, and `fuzz_sniff.py` (telling a file's format and reading RAR and KFX volume headers, which every file in a listed folder goes through).
Each states what its reader may raise; anything else, a hang or memory without bound is a finding.
Atheris has wheels for Python 3.12 to 3.14 and needs the GTK bindings MComix imports, so a virtual environment on the system's Python does:

```bash
python3 -m venv --system-site-packages ~/fuzz-venv
~/fuzz-venv/bin/pip install --require-hashes -r .github/requirements/fuzz.txt
mkdir -p /tmp/fuzz-kfx
~/fuzz-venv/bin/python fuzz/fuzz_kfx.py /tmp/fuzz-kfx fuzz/corpus/kfx fuzz/regressions/kfx -max_total_time=300
```

- `fuzz/corpus/<target>/` are the seeds, which `fuzz/make_seeds.py` writes from the test suite's builders.
- An input that failed goes in `fuzz/regressions/<target>/` with the fix: `test/test_fuzz_targets.py` runs every target over its seeds and its regressions, without Atheris.

## Continuous integration

Workflow | Runs | Does
---------|------|-----
`tests.yml` | Every push to `main`, every pull request, Mondays; not for a change to the manual or `artwork/` alone | The three checks on Python 3.12, 3.13, 3.14 and the newest Python, on Ubuntu 26.04 (GTK 4.22); the tests again on the oldest dependency versions `pyproject.toml` allows, on Ubuntu 24.04 (GTK 4.14).
`docs.yml` | A push to `main` or a pull request that changes the manual, a Markdown file or an issue form | The manual's own tests: `test_wiki.py`, `test_keybindings.py`, and the variables test in `test_openwith_command.py`.
`codeql.yml` | A push to `main` or a pull request that changes Python code or a workflow, Mondays | Code scanning of the Python code and the workflows.
`release.yml` | A version tag, a push to `main` or a pull request that changes the build, Mondays | Builds and tests the release files: see [Releasing](releasing.md).
`pages.yml` | A push to `main` that changes a page | Publishes the manual on [GitHub Pages](https://twwn.github.io/mcomix/).
`release-notes.yml` | A push to `main` that changes `ChangeLog.md` | Makes each published release's notes its `ChangeLog.md` section again.
`windows-tests.yml` | Every push to `main` and every pull request that changes more than the manual, by hand | The tests on Windows, in MSYS2's UCRT64 environment, as the Windows packages are built, with the UnRAR.dll they carry. The installed environment is cached for a week.
`workflows.yml` | A push to `main` or a pull request that changes a workflow, Mondays | Lints the workflows: actionlint, with shellcheck over their scripts, and zizmor, with its online audits.
`scorecard.yml` | A push to `main` that changes `.github/`, Mondays | [OpenSSF Scorecard](https://scorecard.dev/viewer/?uri=github.com/twwn/mcomix)'s supply-chain checks; findings under the Security tab, the result behind the badge on the front page.
`fuzz.yml` | A push to `main` or a pull request that changes a fuzzed reader or `fuzz/`; Mondays, by hand | The [fuzz targets](#fuzzing), a minute each, ten on Mondays from the corpus the last run grew; a failing input is kept as the run's artifact.
`flatpak-updates.yml` | Mondays, by hand | Checks the Flatpak's modules against their newest releases: see [Releasing](releasing.md#flatpak).
Dependabot | Monthly | Pull requests updating the actions the workflows use, and the tools they install with pip (build, twine, zizmor), pinned with their hashes in `.github/requirements/`.
