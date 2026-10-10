#!/usr/bin/env python3
"""Write the Flathub manifest for a release.

flatpak/io.github.twwn.mcomix.yml builds the tree it sits in, which is
what a local build and the release workflow want.  Flathub builds from
sources it can fetch, so the copy submitted there takes MComix from the
release's tag on GitHub instead; everything else is the same file.

    python3 flatpak/flathub_manifest.py <tag> <commit> > io.github.twwn.mcomix.yml
"""

import os
import re
import sys

MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'io.github.twwn.mcomix.yml')

#: The repository a release is fetched from.
REPOSITORY = 'https://github.com/twwn/mcomix.git'

#: The source of the last module, the tree beside this script.
_LOCAL_SOURCE = re.compile(
    r'^      - type: dir\n        path: \.\.\n        skip:\n(?:          - .+\n)+\Z',
    re.MULTILINE)


def flathub_manifest(manifest: str, tag: str, commit: str) -> str:
    """<manifest> with MComix taken from <tag>, at <commit>."""
    if not re.fullmatch(r'\d\d\.\d\d(\.\d+)?', tag):
        raise ValueError('not a release tag: %r' % tag)
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('not a full commit hash: %r' % commit)
    source = ('      - type: git\n'
              '        url: %s\n'
              "        tag: '%s'\n"
              '        commit: %s\n'
              '        x-checker-data:\n'
              '          type: git\n'
              "          tag-pattern: ^(\\d\\d\\.\\d\\d(?:\\.\\d+)?)$\n"
              % (REPOSITORY, tag, commit))
    # A function, so that the backslashes are not read as a template's.
    released, count = _LOCAL_SOURCE.subn(lambda match: source, manifest)
    if count != 1:
        raise ValueError('the manifest does not end in the local source')
    return released


def main() -> None:
    tag, commit = sys.argv[1:3]
    with open(MANIFEST, encoding='utf-8') as source:
        sys.stdout.write(flathub_manifest(source.read(), tag, commit))


if __name__ == '__main__':
    main()
