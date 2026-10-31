"""Fuzz target: mcomix.archive.ion.loads(), the binary Ion reader every
KFX book goes through.

Whatever the bytes, loads() answers with a value or raises IonError,
which the KFX handler turns into "not a Kindle book MComix can read";
any other exception, a hang or memory without bound is a finding.
"""

import sys

import _setup  # noqa: F401  # the path and the folders, before MComix

import atheris

with atheris.instrument_imports(include=['mcomix']):
    from mcomix.archive import ion


def TestOneInput(data: bytes) -> None:
    try:
        ion.loads(data)
    except ion.IonError:
        pass


if __name__ == '__main__':
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
