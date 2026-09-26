#!/usr/bin/env python3
"""Build the source archive of a release: dist/mcomix-<version>.tar.xz.

It is the sdist that "python -m build -s" makes, under two changes.
The version is spelt as mcomix/constants.py spells it: Python's
packaging normalises 26.09 to 26.9, in the file's name and in the folder
it unpacks to, and the Windows packages and the tag keep the 0.  And it
is compressed with xz, as Linux source releases customarily are, rather
than gzip: smaller, and pip installs it the same.  The metadata inside
(PKG-INFO) still says 26.9, which is what pip reports either way.

Run it from the checkout, on Linux: files packed on Windows would get
executable permission bits.
"""

import glob
import lzma
import os
import re
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def version() -> str:
    """VERSION as mcomix/constants.py spells it."""
    with open(os.path.join(HERE, 'mcomix', 'constants.py'),
              encoding='utf-8') as constants:
        match = re.search(r"^VERSION = '(.*)'$", constants.read(), re.M)
    if match is None:
        sys.exit('mcomix/constants.py has no VERSION')
    return match.group(1)


def repack(sdist: str, target: str, prefix: str) -> None:
    """Copy <sdist> to <target>, xz-compressed, with every member moved
    from the folder it is in to <prefix>."""
    with tarfile.open(sdist) as source, \
            tarfile.open(target, 'w:xz',
                         preset=9 | lzma.PRESET_EXTREME) as packed:
        for member in source.getmembers():
            _top, sep, rest = member.name.partition('/')
            member.name = prefix + sep + rest
            content = source.extractfile(member) if member.isfile() else None
            packed.addfile(member, content)


def main() -> None:
    name = 'mcomix-' + version()
    dist = os.path.join(HERE, 'dist')
    os.makedirs(dist, exist_ok=True)
    with tempfile.TemporaryDirectory() as built:
        subprocess.run([sys.executable, '-m', 'build', '-s',
                        '--outdir', built, HERE], check=True)
        sdist, = glob.glob(os.path.join(built, 'mcomix-*.tar.gz'))
        target = os.path.join(dist, name + '.tar.xz')
        repack(sdist, target, name)
    print('Wrote', os.path.relpath(target))


if __name__ == '__main__':
    main()
