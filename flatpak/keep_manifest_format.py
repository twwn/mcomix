#!/usr/bin/env python3
"""Keep the new values the Flatpak's checker wrote, and not its formatting.

flatpak-external-data-checker, once it has one new value, writes the whole
manifest over in its own YAML style: lines folded at 80 columns, quotes
dropped where YAML does not need them.  In the diff, that cannot be told
from a newer release.  This puts each new value into the manifest as it
was, which leaves a diff of the new values alone.

    python3 flatpak/keep_manifest_format.py <manifest as it was> <manifest as the checker wrote it>

The second file is overwritten.  It stays as the checker wrote it when
something other than values changed, such as a key it added.
"""

import re
import sys


def _words(text: str) -> list[re.Match[str]]:
    """The words of <text>, each without the quotes around it."""
    return list(re.finditer(r"(?<!\S)'?(\S+?)'?(?!\S)", text))


def keep_format(old: str, new: str) -> str:
    """<old>, with the values that <new> changed."""
    old_words = _words(old)
    new_words = _words(new)
    if len(old_words) != len(new_words):
        return new
    kept = []
    position = 0
    for old_word, new_word in zip(old_words, new_words):
        if old_word.group(1) != new_word.group(1):
            kept += old[position:old_word.start(1)], new_word.group(1)
            position = old_word.end(1)
    kept.append(old[position:])
    return ''.join(kept)


def main() -> None:
    old_path, new_path = sys.argv[1:3]
    with open(old_path, encoding='utf-8') as old:
        with open(new_path, encoding='utf-8') as new:
            kept = keep_format(old.read(), new.read())
    with open(new_path, 'w', encoding='utf-8') as new:
        new.write(kept)


if __name__ == '__main__':
    main()
