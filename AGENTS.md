# Notes for coding agents

MComix is a GTK 4 comic reader in Python. Before you change anything:

- Before writing or changing a test, read [Writing tests](docs/development.md#writing-tests). Base every test on `test.MComixTest`, which keeps the preferences, library and bookmarks away from the real ones, and use the helpers in `test/__init__.py` instead of writing your own.
- Before changing anything under `mcomix/`, read [Writing code](docs/development.md#writing-code). It lists what earlier refactors and speed-ups found, so the same code is not written again.
- Run the three [checks](docs/development.md#checks) before every commit: pytest under `xvfb-run`, `flake8 --select=F` and strict mypy. The tests open windows, so without Xvfb they land on your desktop.
- A new or changed user-visible string goes into the template and all 24 catalogues: see [Translations](docs/development.md#translations).
- A change the reader can see is described in the manual under `docs/`.
