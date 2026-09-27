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

## Layout

Path | What
-----|-----
`mcomix/` | The program. `mcomix/archive/` reads and writes archives; `mcomix/library/` is the library.
`mcomix/messages/` | Translations.
`test/` | The tests; `test/files/` the books they open.
`share/` | Desktop file, icons, MIME types, AppStream metadata, man page.
`win32/` | The Windows build.
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

## Continuous integration

Workflow | Runs | Does
---------|------|-----
`tests.yml` | Every push to `main`, every pull request, Mondays | The three checks on Python 3.12 and the newest Python, on Ubuntu 26.04 (GTK 4.22); the tests again on the oldest dependency versions `pyproject.toml` allows, on Ubuntu 24.04 (GTK 4.14).
`codeql.yml` | The same | Code scanning of the Python code and the workflows.
`release.yml` | A version tag, a pull request that changes the build, Mondays | Builds and tests the release files: see [Releasing](releasing.md).
`windows-tests.yml` | By hand | The tests on Windows, in MSYS2's UCRT64 environment, as the Windows packages are built.
Dependabot | Monthly | Pull requests updating the actions the workflows use.
