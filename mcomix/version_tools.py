"""Compare the version strings reported by the tools MComix probes for.

This used to be packaging's LegacyVersion, which upstream removed in
version 22.0, and for which a copy of packaging 21.0 was vendored. Only
the plain dotted versions that mutool and PyMuPDF report have to be
ordered, so a small natural-order comparison does the job without a
dependency - and, unlike a strict PEP 440 parser, it cannot raise on an
unexpected version string.
"""

import functools
import re

__all__ = ["Version"]

_COMPONENT_RE = re.compile(r'(\d+)')

# Suffixes marking a version as preceding the release it belongs to.
_PRE_RELEASE_MARKERS = frozenset(
    ('a', 'alpha', 'b', 'beta', 'c', 'rc', 'pre', 'preview'))

# Ranks deciding how the kinds of component compare against each other:
# "1.8dev1" < "1.8rc1" < "1.8unknown" < "1.8" < "1.8.1".
_DEV, _PRE_RELEASE, _OTHER, _RELEASE, _NUMBER = range(5)

_SEPARATORS = '.-_+ '


def _sort_key(version: str) -> "tuple[tuple[int, int | str], ...]":
    """Return a tuple ordering <version> against other versions."""
    key: "list[tuple[int, int | str]]" = []
    for token in _COMPONENT_RE.split(version.strip().lower()):
        token = token.strip(_SEPARATORS)
        if not token:
            continue
        # isdecimal(), not isdigit(), which int() cannot parse.
        if token.isdecimal():
            key.append((_NUMBER, int(token)))
        elif token == 'dev':
            key.append((_DEV, token))
        elif token in _PRE_RELEASE_MARKERS:
            key.append((_PRE_RELEASE, token))
        else:
            key.append((_OTHER, token))
    # "1.8.0" names the same release as "1.8".
    while len(key) > 1 and key[-1] == (_NUMBER, 0):
        key.pop()
    # Marks the end of the version, so that a release sorts after its own
    # pre-releases but before any version with a further component.
    key.append((_RELEASE, ''))
    return tuple(key)


@functools.total_ordering
class Version:
    """A version string that compares in its natural order.

    "1.9" sorts before "1.10", and "1.8dev1" and "1.8rc1" before "1.8".
    """

    def __init__(self, version: str) -> None:
        self._version = version
        self._key = _sort_key(version)

    def __str__(self) -> str:
        return self._version

    def __repr__(self) -> str:
        return '%s(%r)' % (type(self).__name__, self._version)

    def __hash__(self) -> int:
        return hash(self._key)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key == other._key

    def __lt__(self, other: 'Version') -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key < other._key

# vim: expandtab:sw=4:ts=4
