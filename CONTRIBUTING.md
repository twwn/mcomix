# Contributing

Bug reports, ideas and pull requests are welcome.

## Set up

[Installation](docs/Installation.md#developing-mcomix) has the steps: GTK 4, PyGObject, then `pip install -e '.[dev]'`.

## Check

All three have to pass, as they do on GitHub:

```bash
xvfb-run -a python -m pytest test/ -n auto
python -m flake8 --select=F mcomix/ test/
python -m mypy mcomix
```

## Change

- One change per pull request, with a test that fails without it.
- Docs under `docs/` follow the change.
- New strings go into every catalogue: [Maintenance](docs/Maintenance.md#translation-files).
- Commit subjects start with a type (`fix:`, `feat:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`) and say what was wrong.
- Write briefly: one fact per line.

## Report a bug

Use the [bug form](https://github.com/twwn/mcomix/issues/new/choose).
`-W debug -o mcomix.log` writes the log it asks for.
