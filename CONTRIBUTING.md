# Contributing

Bug reports, ideas and pull requests are welcome.

## Set up

[Development](docs/development.md#set-up) has the steps: GTK 4, PyGObject, then `pip install -e '.[dev,fileformats]'`.

## Check

All three have to pass, as they do on GitHub ([more](docs/development.md#checks)):

```bash
xvfb-run -a python -m pytest test/ -n auto
python -m flake8 --select=F mcomix/ test/
python -m mypy mcomix
```

## Change

- One change per pull request, with a test that fails without it.
- Docs under `docs/` follow the change.
- New strings go into every catalogue: [Translations](docs/development.md#translations).
- Commit subjects start with a type (`fix:`, `feat:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`) and say what was wrong.
- Write briefly: one fact per line.

## Report a bug

Use the [bug form](https://github.com/twwn/mcomix/issues/new/choose).
`-W debug -o mcomix.log` writes the log it asks for: see [Troubleshooting](docs/troubleshooting.md#logs).
