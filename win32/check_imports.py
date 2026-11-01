"""Fail when a file of the Windows bundle imports a DLL nothing provides.

Usage: python win32/check_imports.py dist/MComix [<system folder>]

Every .exe, .dll and .pyd under the bundle is read with pefile, its
import table and its delay-import table both.  An import is satisfied by
a file of that name anywhere in the bundle, by an API set (api-ms-win-*,
ext-ms-win-*), or by a DLL in the system folder, %SystemRoot%\\System32
unless another is named.  Windows compares DLL names without regard to
case, and so does this.

The release workflow's smoke run starts MComix on a PDF, which loads
only what a PDF needs.  A DLL that only one image format's gdk-pixbuf
loader imports, libjxl's for JPEG XL or librsvg's for SVG, would go
missing from the bundle without that run noticing; this reads them all.

The Visual C++ runtimes are left out of the system folder: the runner
has the redistributable installed, a fresh Windows does not, and
nothing MSYS2 builds should need it.

Exits with 1, naming each DLL left over and the files that import it.
"""

import collections
import os
import re
import sys
from collections.abc import Iterable, Mapping

#: What a runner's System32 holds and a Windows without the Visual C++
#: redistributable lacks.  msvcrt.dll is Windows' own and is kept;
#: mfc\d, not mfc, keeps Media Foundation's mfcore.dll.
REDISTRIBUTABLE = re.compile(
    r'^(vcruntime|msvcp|msvcr\d|concrt|vcomp|vccorlib|mfc\d|d3dx|ucrtbased)')

#: The prefixes of the API sets, which Windows maps to its own DLLs.
API_SETS = ('api-ms-win-', 'ext-ms-win-')

#: The extensions of the files the bundle loads as code.
PE_EXTENSIONS = ('.exe', '.dll', '.pyd')


def read_imports(bundle: str) -> tuple[set[str], dict[str, set[str]]]:
    """The names of the bundle's PE files, and for each DLL name the
    files (relative to the bundle) that import it, all in lower case."""
    import pefile

    provided: set[str] = set()
    importers: dict[str, set[str]] = collections.defaultdict(set)
    tables = [pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
              pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']]
    for root, _dirs, files in os.walk(bundle):
        for name in files:
            if not name.lower().endswith(PE_EXTENSIONS):
                continue
            provided.add(name.lower())
            path = os.path.join(root, name)
            pe = pefile.PE(path, fast_load=True)
            try:
                pe.parse_data_directories(directories=tables)
                for table in ('DIRECTORY_ENTRY_IMPORT',
                              'DIRECTORY_ENTRY_DELAY_IMPORT'):
                    for entry in getattr(pe, table, ()):
                        importers[entry.dll.decode('ascii').lower()].add(
                            os.path.relpath(path, bundle))
            finally:
                pe.close()
    return provided, importers


def system_dlls(names: Iterable[str]) -> set[str]:
    """The names of a system folder that a fresh Windows has too."""
    return {name.lower() for name in names
            if not REDISTRIBUTABLE.match(name.lower())}


def unresolved(provided: set[str], importers: Mapping[str, set[str]],
               system: set[str]) -> list[str]:
    """The imported names neither the bundle nor Windows provides."""
    return sorted(name for name in importers
                  if name.lower() not in provided
                  and name.lower() not in system
                  and not name.lower().startswith(API_SETS))


def main(argv: list[str]) -> int:
    bundle = argv[0]
    system_folder = argv[1] if len(argv) > 1 else os.path.join(
        os.environ['SystemRoot'], 'System32')
    provided, importers = read_imports(bundle)
    missing = unresolved(provided, importers,
                         system_dlls(os.listdir(system_folder)))
    print(f'{len(importers)} DLLs imported by the files of {bundle}, '
          f'{len(missing)} of them in neither the bundle nor Windows')
    for name in missing:
        print(f'::error::{name} is imported by '
              f'{", ".join(sorted(importers[name]))}, and neither the '
              f'bundle nor Windows has it')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
