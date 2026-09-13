""" preferences.py - Contains the preferences and the functions to read and
write them.  """

import copy
import json
import os
import pickle
import shutil
import sys
from typing import Any

from mcomix import constants
from mcomix import tools

#: Bumped whenever a stored preference changes format, so that a file
#: written by an older MComix can be brought forward on the next start.
#: History:
#:   1: background colours are Gdk.RGBA components - four floats between
#:      0 and 1 - where they used to be three 16-bit integers.
CONFIG_FORMAT_VERSION = 1

#: The key the version above is stored under.  It lives among the
#: preferences rather than wrapping them, so the file stays a flat mapping.
_FORMAT_VERSION_KEY = 'config format version'

#: MComix' traditional background: a near-black grey.  Written the way it
#: divides out of the 16-bit 5000 it was stored as before version 1.
DEFAULT_BG_COLOUR = [5000 / 65535, 5000 / 65535, 5000 / 65535, 1.0]

class _Preferences(dict[str, Any]):

    """The preferences, which see themselves written out when they change.

    MComix wrote them at quit and only then, so anything that ended a
    window another way - a crash, a kill, a session ending underneath it
    - lost every setting made since it opened.  Changing one now
    schedules the write instead, and quitting is only the last of them.
    """

    def __setitem__(self, key: str, value: Any) -> None:
        was = self.get(key, _NOTHING)
        super().__setitem__(key, value)
        if value != was:
            changed()

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        changed()

    def update(self, *args: Any, **keywords: Any) -> None:
        super().update(*args, **keywords)
        changed()

    def clear(self) -> None:
        super().clear()
        changed()


#: Stands for a preference that is not there, where None is a value some
#: of them really hold.
_NOTHING = object()

# All the preferences are stored here.
prefs = _Preferences({
    _FORMAT_VERSION_KEY: CONFIG_FORMAT_VERSION,
    'comment extensions': constants.ACCEPTED_COMMENT_EXTENSIONS,
    'auto load last file': False,
    'page of last file': 1,
    'path to last file': '',
    'number of key presses before page turn': 3,
    'auto open next archive': True,
    'auto open next directory': True,
    'open first file in prev archive': False,
    'open first file in prev directory': False,
    'sort by': constants.SORT_NAME,  # Normal files obtained by directory listing
    'sort order': constants.SORT_ASCENDING,
    'sort archive by': constants.SORT_NAME,  # Files in archives
    'sort archive order': constants.SORT_ASCENDING,
    'bg colour': list(DEFAULT_BG_COLOUR),
    'thumb bg colour': list(DEFAULT_BG_COLOUR),
    'smart bg': False,
    'smart thumb bg': False,
    'thumbnail bg uses main colour': False,
    'checkered bg for transparent images': True,
    'stretch': False,
    'default double page': False,
    'default fullscreen': False,
    'zoom mode': constants.ZoomMode.BEST,
    'default manga mode': False,
    'lens magnification': 2,
    'lens size': 200,
    'virtual double page for fitting images': constants.SHOW_DOUBLE_AS_ONE_TITLE | \
                                              constants.SHOW_DOUBLE_AS_ONE_WIDE,
    'double step in double page mode': True,
    'show page numbers on thumbnails': True,
    'thumbnail size': 80,
    'colour scheme': 'system',
    'create thumbnails': True,
    'number of pixels to scroll per key event': 50,
    'number of pixels to scroll per mouse wheel event': 50,
    'slideshow delay': 3000,
    'slideshow can go to next archive': True,
    'number of pixels to scroll per slideshow event': 50,
    'smart scroll': True,
    'invert smart scroll': False,
    'smart scroll percentage': 0.5,
    'flip with wheel': True,
    'store recent file info': True,
    'hide all': False,
    'hide all in fullscreen': True,
    'path of last browsed in filechooser': constants.HOME_DIR,
    'store last saved in directory': True,
    'path of last saved in filechooser': constants.HOME_DIR,
    'last filter in main filechooser': 0,
    'last filter in library filechooser': 1,
    'show menubar': True,
    'previous quit was quit and save': False,
    'show scrollbar': True,
    'show statusbar': True,
    'show toolbar': True,
    'show thumbnails': True,
    'rotation': 0,
    'auto rotate from exif': True,
    'auto rotate depending on size': constants.AUTOROTATE_NEVER,
    'vertical flip': False,
    'horizontal flip': False,
    'keep transformation': False,
    'stored dialog choices': {},
    'brightness': 1.0,
    'contrast': 1.0,
    'saturation': 1.0,
    'sharpness': 1.0,
    'auto contrast': False,
    'invert color': False,
    'max pages to cache': 7,
    'window height': 600,
    'window width': 640,
    'window maximized': False,
    'pageselector height': -1,
    'pageselector width': -1,
    'library cover size': 125,
    'last library collection': None,
    'lib window height': 600,
    'lib window width': 500,
    'lib sort key': constants.SORT_PATH,
    'lib sort order': constants.SORT_ASCENDING,
    'language': 'auto',
    'statusbar fields': constants.STATUS_PAGE | constants.STATUS_RESOLUTION | \
                        constants.STATUS_PATH | constants.STATUS_FILENAME | constants.STATUS_FILESIZE,
    'max threads': 3,
    'max extract threads': 1,
    'scaling quality': 2,  # GdkPixbuf.InterpType.BILINEAR
    'escape quits': False,
    'fit to size width wide': 3790,
    'fit to size height wide': 960,
    'fit to size width other': 1450,
    'fit to size height other': 1800,
    'scan for new books on library startup': True,
    'openwith commands': [],  # (label, command) pairs
    # Which bookmark columns the headings' menu has been asked to hide,
    # by the attribute each of them shows.  Location is the one there is
    # rarely room for beside the others.
    'hidden bookmark columns': ['path'],
    'animation mode': constants.ANIMATION_NORMAL,
    'double page autoresize': constants.DOUBLE_PAGE_AUTORESIZE_SIZE,
    'space between two pages': 2,
})

#: How long a change waits for the ones after it before the file is
#: written.  Long enough that dragging a slider writes once rather than
#: once a pixel, short enough that nothing anybody remembers doing is
#: still unwritten when a window goes away without being closed.
_WRITE_DELAY_MS = 2000

#: The GLib source the next write is waiting on, or 0.
_write_source = 0

#: The preferences as they stood when the file was last read.  What this
#: instance has changed is what differs from these, and that is all it
#: writes: MComix runs one process per window, each holding a copy of
#: every preference, so an instance that wrote the lot would put back
#: what another one changed while it was running.  Empty until the file
#: is read, which means an instance that never read one has nothing of
#: its own to write.
_as_read: dict[str, Any] = {}


def migrate_home_config_path() -> None:
    """ Migrate the old configuration directory in the user's
    home directory to %APPDATA% on Win32, if the directory
    doesn't already exist. """
    if sys.platform == "win32":
        old_config_dir = os.path.join(os.path.expanduser("~"), "MComix")
        if os.path.isdir(old_config_dir) and not os.path.isdir(constants.CONFIG_DIR):
            shutil.move(old_config_dir, constants.CONFIG_DIR)


def _move_corrupt_file_aside(path: str, error: BaseException) -> None:
    """ Rename an unreadable configuration file, so a fresh one can be
    written in its place. """
    # Gettext might not be installed yet at this point.
    corrupt_name = "%s.broken" % path
    print('! Corrupt preferences file (%s), moving to "%s".' % (error, corrupt_name))
    try:
        os.replace(path, corrupt_name)
    except OSError as rename_error:
        print('! Could not move it: %s' % rename_error)


def _back_up_preferences(version: int) -> None:
    """Keep the preferences file as it stands before it is migrated.

    The copy is named after the format it holds, so that it collides
    neither with a backup the user made themselves nor with the backup of
    a later migration, and is never overwritten: if one is already there
    it is from an earlier run and is the more original of the two.
    """
    if not os.path.isfile(constants.PREFERENCE_PATH):
        return
    backup = '%s.v%d' % (constants.PREFERENCE_PATH, version)
    if os.path.exists(backup):
        return
    try:
        shutil.copyfile(constants.PREFERENCE_PATH, backup)
        # Gettext might not be installed yet at this point.
        print('! Preferences upgraded, keeping the previous file as "%s".' % backup)
    except OSError as error:
        print('! Could not back up the preferences file: %s' % error)


def _rgba_from_16bit_colour(colour: Any) -> list[float]:
    """Turn a 16-bit RGB triple into the components Gdk.RGBA takes."""
    try:
        red, green, blue = (component / 65535.0 for component in colour[:3])
    except (TypeError, ValueError):
        # Not a colour at all; the default is a better guess than a crash.
        return list(DEFAULT_BG_COLOUR)
    return [red, green, blue, 1.0]


def _migrate_preferences(saved_prefs: dict[str, Any]) -> None:
    """Bring <saved_prefs> forward to CONFIG_FORMAT_VERSION, in place.

    A file older than the current format is backed up first, once, before
    anything in it is rewritten.
    """
    version = saved_prefs.get(_FORMAT_VERSION_KEY, 0)
    if version >= CONFIG_FORMAT_VERSION:
        return

    _back_up_preferences(version)

    if version < 1:
        for key in ('bg colour', 'thumb bg colour'):
            if key in saved_prefs:
                saved_prefs[key] = _rgba_from_16bit_colour(saved_prefs[key])

    saved_prefs[_FORMAT_VERSION_KEY] = CONFIG_FORMAT_VERSION


def read_preferences_file() -> None:
    """Read preferences data from disk."""

    saved_prefs = None

    migrate_home_config_path()

    if os.path.isfile(constants.PREFERENCE_PATH):
        try:
            with open(constants.PREFERENCE_PATH, 'r') as config_file:
                saved_prefs = json.load(config_file)
        except ValueError as error:
            # Unparsable: json raises JSONDecodeError, and a file in some
            # other encoding raises UnicodeDecodeError. Both are ValueErrors.
            _move_corrupt_file_aside(constants.PREFERENCE_PATH, error)
        except OSError as error:
            # Readable again next time, most likely; leave the file alone.
            print('! Could not read preferences file: %s' % error)

    elif os.path.isfile(constants.PREFERENCE_PICKLE_PATH):
        try:
            with open(constants.PREFERENCE_PICKLE_PATH, 'rb') as config_file:
                pickle.load(config_file)  # Version record, no longer used.
                saved_prefs = pickle.load(config_file)

            # Remove legacy format preferences file
            os.unlink(constants.PREFERENCE_PICKLE_PATH)
        except Exception:
            # Gettext might not be installed yet at this point.
            print(('! Corrupt legacy preferences file "%s", ignoring...' %
                   constants.PREFERENCE_PICKLE_PATH))

    if saved_prefs:
        _migrate_preferences(saved_prefs)
        for key in saved_prefs:
            if key in prefs:
                prefs[key] = saved_prefs[key]

    global _as_read
    _as_read = copy.deepcopy(dict(prefs))
    # Reading is not changing, whatever the assignments above look like.
    cancel_scheduled_write()


def changed() -> None:
    """Note that a preference has changed, and see it written out.

    The mapping calls this itself when it is assigned to.  Code that
    reaches inside a preference and changes what is in there - a list,
    or the dictionary of remembered dialog answers - has to say so, the
    mapping being none the wiser.

    The write waits, so that a run of changes costs one of them, and
    happens on the main loop: without one running there is nothing to
    write it, and quitting writes them all anyway.
    """
    global _write_source
    if _write_source:
        return
    from gi.repository import GLib
    _write_source = GLib.timeout_add(_WRITE_DELAY_MS, _write_now)


def _write_now() -> bool:
    """Write the preferences the delay above was counting down for."""
    global _write_source
    _write_source = 0
    write_preferences_file()
    return False  # GLib.SOURCE_REMOVE


def cancel_scheduled_write() -> None:
    """Drop a write that has not happened yet.

    What it would have written is either already on disk or no longer
    this instance's to write.
    """
    global _write_source
    if not _write_source:
        return
    from gi.repository import GLib
    GLib.source_remove(_write_source)
    _write_source = 0


def _stored_preferences() -> dict[str, Any]:
    """Whatever is in the preferences file now, or nothing.

    Nothing is also the answer for a file that cannot be read: writing
    this instance's own preferences over it is then the best that can be
    done, and is what MComix always did.

    What comes back is brought forward to the current format, because it
    is what the preferences are about to be written into: a value this
    instance never touched would otherwise be left in the file in a
    format the file then claims not to be in.
    """
    try:
        with open(constants.PREFERENCE_PATH, 'r') as config_file:
            stored = json.load(config_file)
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    _migrate_preferences(stored)
    return stored


def _changed_here() -> dict[str, Any]:
    """The preferences this instance has changed since it read them.

    A preference the baseline does not name is not one of them, and the
    baseline names every preference there is once the file has been read.
    Before that it is empty, and an instance that has read nothing has
    changed nothing: counting the whole default dictionary as changed
    there would put the defaults over a file full of the user's answers.
    """
    return {key: value for key, value in prefs.items()
            if key in _as_read and value != _as_read[key]}


def write_preferences_file() -> None:
    """Write preference data to disk.

    Only what this instance changed is written over what the file holds,
    because it is not the only MComix there is: every window is a process
    of its own, each with the preferences as they stood when it started,
    and one that wrote all of them would undo every change another
    window had made in the meantime - which reads as settings that do
    not stick.
    """
    cancel_scheduled_write()
    stored = _stored_preferences()
    stored.update(_changed_here())
    # Whoever wrote the file last says what format it is in.
    stored[_FORMAT_VERSION_KEY] = CONFIG_FORMAT_VERSION
    with tools.atomic_write(constants.PREFERENCE_PATH) as config_file:
        json.dump(stored, config_file, indent=2)

# vim: expandtab:sw=4:ts=4
