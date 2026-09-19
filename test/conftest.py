"""What pytest needs before any test is collected."""

import sys
import types

import gi._gi

# A GLib warning in the GObject domain reaches Python as gi's Warning,
# whose module says it is "gobject".  pytest-xdist sends each warning a
# worker records back to the controlling process by that module and
# class name, and the controller imports the module to rebuild it; but
# PyGObject puts a stand-in under that name that raises on every
# attribute, to turn away code written for the old static bindings.  The
# worker was then taken down, and the warning - the one thing worth
# reading - lost with it.  A module holding the class is enough.
_gobject = types.ModuleType('gobject')
_gobject.Warning = gi._gi.Warning  # type: ignore[attr-defined]
sys.modules['gobject'] = _gobject
