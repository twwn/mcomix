"""What every fuzz target does before it imports MComix.

The targets run as scripts, `python fuzz/fuzz_ion.py <corpus> [libFuzzer
options]`, so the checkout they sit in is put on the path; and MComix
works out its configuration and data folders when it is imported, so
those are pointed into a temporary folder first, where nothing a target
does can touch the reader's own.
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HOME = tempfile.mkdtemp(prefix='mcomix-fuzz-')
for variable in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
    os.environ[variable] = os.path.join(HOME, variable.lower())

# The versions MComix asks for in run.py, before image_tools imports Gtk.
import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
