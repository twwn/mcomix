""" preferences.py - Contains the preferences and the functions to read and
write them.  """

import copy
import json
import os
import pickle
import shutil
import sys
import types
import typing
from collections.abc import Sequence
from typing import Any, TypedDict, cast

from mcomix import constants
from mcomix import tools

#: Bumped whenever a stored preference changes format, so that a file
#: written by an older MComix can be brought forward on the next start.
#: History:
#:   1: background colours are Gdk.RGBA components - four floats between
#:      0 and 1 - where they used to be three 16-bit integers.
#:   2: the answer to the prompt that deletes the opened file is stored
#:      under "delete-opened-file", where the name used to be misspelt.
#:   3: "store recent file info" is True or False, where MComix before
#:      2012 stored 0 (nothing), 1 (the file) or 2 (the file and page).
CONFIG_FORMAT_VERSION = 4

#: The key the version above is stored under.  It lives among the
#: preferences rather than wrapping them, so the file stays a flat mapping.
_FORMAT_VERSION_KEY = 'config format version'

#: MComix' traditional background: a near-black grey.  Written the way it
#: divides out of the 16-bit 5000 it was stored as before version 1.
DEFAULT_BG_COLOUR = [5000 / 65535, 5000 / 65535, 5000 / 65535, 1.0]

#: Every preference there is: the name it goes under in the file, and
#: the type it holds.  The defaults below are annotated with this, so the
#: checker holds the two tables together - a preference named in one and
#: not the other is an error, and so is a default of the wrong type - and
#: every `prefs['...']` in MComix is checked against it.
Preferences = TypedDict('Preferences', {
    'config format version': int,
    'comment extensions': list[str],
    'keep archive format when saving': bool,
    'auto load last file': bool,
    'open library on startup': bool,
    'page of last file': int,
    'member of last file': str,
    'path to last file': str,
    'number of key presses before page turn': int,
    'auto open next archive': bool,
    'auto open next directory': bool,
    'open first file in prev archive': bool,
    'open first file in prev directory': bool,
    'sort by': int,
    'sort order': int,
    'sort archive by': int,
    'sort archive order': int,
    'bg colour': list[float],
    'thumb bg colour': list[float],
    'smart bg': bool,
    'smart thumb bg': bool,
    'checkered bg for transparent images': bool,
    'stretch': bool,
    'default double page': bool,
    'default fullscreen': bool,
    'zoom mode': int,
    'default manga mode': bool,
    # The dialog's spinner for this one has a decimal place.
    'lens magnification': float,
    'lens size': int,
    'virtual double page for fitting images': int,
    'double step in double page mode': bool,
    'skip broken pages': bool,
    'show page numbers on thumbnails': bool,
    'thumbnail size': int,
    'colour scheme': str,
    'create thumbnails': bool,
    'number of pixels to scroll per key event': int,
    'number of pixels to scroll per mouse wheel event': int,
    'slideshow delay': int,
    'slideshow can go to next archive': bool,
    'number of pixels to scroll per slideshow event': int,
    'smart scroll': bool,
    'invert smart scroll': bool,
    'smart scroll percentage': float,
    'flip with wheel': bool,
    'store recent file info': bool,
    'hide all': bool,
    'hide all in fullscreen': bool,
    'path of last browsed in filechooser': str,
    'store last saved in directory': bool,
    'path of last saved in filechooser': str,
    'recent move destinations': list[str],
    'last filter in main filechooser': int,
    'last filter in library filechooser': int,
    'show menubar': bool,
    'previous quit was quit and save': bool,
    'show scrollbar': bool,
    'show statusbar': bool,
    'show toolbar': bool,
    'show thumbnails': bool,
    'rotation': int,
    'auto rotate from exif': bool,
    'auto rotate depending on size': int,
    'vertical flip': bool,
    'horizontal flip': bool,
    'keep transformation': bool,
    'stored dialog choices': dict[str, int],
    'brightness': float,
    'contrast': float,
    'saturation': float,
    'sharpness': float,
    'auto contrast': bool,
    'invert color': bool,
    'max pages to cache': int,
    'window height': int,
    'window width': int,
    'window maximized': bool,
    'pageselector height': int,
    'pageselector width': int,
    'library cover size': int,
    'last library collection': "int | None",
    'lib window height': int,
    'lib window width': int,
    'lib sort key': int,
    'lib sort order': int,
    'language': str,
    'statusbar fields': int,
    'max threads': int,
    'max extract threads': int,
    'scaling quality': int,
    'escape quits': bool,
    'fit to size width wide': int,
    'fit to size height wide': int,
    'fit to size width other': int,
    'fit to size height other': int,
    'scan for new books on library startup': bool,
    'openwith commands': "list[Sequence[str | bool]]",
    'hidden bookmark columns': list[str],
    'animation mode': int,
    'double page autoresize': int,
    'space between two pages': int,
})


class _Preferences(dict[str, object]):

    """The preferences, which see themselves written out when they change.

    MComix wrote them at quit and only then, so anything that ended a
    window another way - a crash, a kill, a session ending underneath it
    - lost every setting made since it opened.  Changing one now
    schedules the write instead, and quitting is only the last of them.
    """

    def __setitem__(self, key: str, value: object) -> None:
        was = self.get(key, _NOTHING)
        super().__setitem__(key, value)
        if value != was:
            changed()

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        changed()

    def update(self, *args: object, **keywords: object) -> None:
        super().update(*args, **keywords)
        changed()

    def clear(self) -> None:
        super().clear()
        changed()


#: Stands for a preference that is not there, where None is a value some
#: of them really hold.
_NOTHING = object()

#: What every preference holds before a file is read over it.
_DEFAULTS: Preferences = {
    'config format version': CONFIG_FORMAT_VERSION,
    'comment extensions': constants.ACCEPTED_COMMENT_EXTENSIONS,
    'keep archive format when saving': False,
    'auto load last file': False,
    'open library on startup': False,
    'page of last file': 1,
    'member of last file': '',
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
    'checkered bg for transparent images': True,
    'stretch': False,
    'default double page': False,
    'default fullscreen': False,
    'zoom mode': constants.ZoomMode.BEST,
    'default manga mode': False,
    'lens magnification': 2,
    'lens size': 200,
    'virtual double page for fitting images': (constants.SHOW_DOUBLE_AS_ONE_TITLE
                                               | constants.SHOW_DOUBLE_AS_ONE_WIDE),
    'double step in double page mode': True,
    'skip broken pages': False,
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
    'recent move destinations': [],
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
    'statusbar fields': (constants.STATUS_PAGE | constants.STATUS_RESOLUTION
                         | constants.STATUS_PATH | constants.STATUS_FILENAME
                         | constants.STATUS_FILESIZE),
    'max threads': 3,
    'max extract threads': 4,
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
}

#: All the preferences are stored here.  The instance is a dict that
#: schedules a write when it is assigned to; it is handed out as the
#: TypedDict above so that every subscript in MComix is checked, which a
#: dict subclass cannot be and a TypedDict cannot do.
prefs = cast(Preferences, _Preferences(copy.deepcopy(_DEFAULTS)))


def by_name(name: str) -> Any:  # type: ignore[explicit-any]  # whatever that preference holds
    """The preference called <name>, looked up at run time.

    The preferences dialog and the menu's toggles work over names they
    are handed rather than names written into them, which is the one
    thing the mapping's type cannot check.  Any, because the answer is
    whatever that preference holds.
    """
    return cast("dict[str, object]", prefs)[name]


def set_by_name(name: str, value: Any) -> None:  # type: ignore[explicit-any]  # whatever that preference holds
    """Set the preference called <name>, looked up at run time.

    A name that is not one of the preferences is refused: a mapping
    would take it and keep it, so a name misspelt in the dialog would
    read as a setting that quietly does nothing.
    """
    if name not in _DEFAULTS:
        raise KeyError('%r is not a preference' % name)
    cast("dict[str, object]", prefs)[name] = value


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
_as_read: dict[str, object] = {}


def migrate_home_config_path() -> None:
    """ Migrate the old configuration directory in the user's
    home directory to %APPDATA% on Win32, if the directory
    doesn't already exist. """
    if sys.platform == "win32":
        old_config_dir = os.path.join(constants.HOME_DIR, "MComix")
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


def _rgba_from_16bit_colour(colour: object) -> list[float]:
    """Turn a 16-bit RGB triple into the components Gdk.RGBA takes.

    Whatever the file held, which need not be a colour at all: the
    default is a better answer for anything that is not one than a
    crash on the way up.
    """
    if not isinstance(colour, Sequence) or len(colour) < 3:
        return list(DEFAULT_BG_COLOUR)
    # Already RGBA: MComix 3.2 writes a migrated file back without the
    # format version it does not know, and a 16-bit component was always
    # a whole number, never a float.
    if all(isinstance(component, float) and 0.0 <= component <= 1.0
           for component in colour[:4]):
        return list(colour[:3]) + [colour[3] if len(colour) > 3 else 1.0]
    components = []
    for component in colour[:3]:
        if not isinstance(component, (int, float)):
            return list(DEFAULT_BG_COLOUR)
        components.append(component / 65535.0)
    return components + [1.0]


def _fits(value: object, key: str) -> bool:
    """Whether <value> is of the type the preference <key> holds, as the
    Preferences table declares it.  A list of numbers - a colour - also
    has to be as long as its default."""
    if not _of_type(value, typing.get_type_hints(Preferences)[key]):
        return False
    default = cast("dict[str, object]", _DEFAULTS)[key]
    if (isinstance(default, list) and default
            and isinstance(default[0], float)):
        return len(cast(list[object], value)) == len(default)
    return True


def _of_type(value: object, annotation: object) -> bool:
    """Whether <value> is of the type <annotation> names: the plain
    types JSON gives, lists and dicts of them, and unions."""
    if annotation is type(None):
        return value is None
    origin = typing.get_origin(annotation)
    arguments = typing.get_args(annotation)
    if origin in (types.UnionType, typing.Union):
        return any(_of_type(value, member) for member in arguments)
    if origin is list or origin is Sequence or annotation is list:
        return isinstance(value, list) and all(
            _of_type(item, arguments[0]) for item in value) \
            if arguments else isinstance(value, list)
    if origin is dict:
        return isinstance(value, dict) and all(
            _of_type(item_key, arguments[0])
            and _of_type(item, arguments[1])
            for item_key, item in value.items())
    if annotation is bool:
        return isinstance(value, bool)
    # JSON has one kind of number, and a bool is an int to Python.
    if annotation is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if annotation is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(annotation, type) and isinstance(value, annotation)


def _migrate_preferences(saved_prefs: dict[str, object]) -> None:
    """Bring <saved_prefs> forward to CONFIG_FORMAT_VERSION, in place.

    A file older than the current format is backed up first, once, before
    anything in it is rewritten.
    """
    stored_version = saved_prefs.get(_FORMAT_VERSION_KEY, 0)
    # A file that says nothing sensible about the format it is in is
    # taken to be the oldest there is, which is where the steps below
    # start: comparing a hand-edited "1" against a number raised.
    version = stored_version if isinstance(stored_version, int) else 0
    if version >= CONFIG_FORMAT_VERSION:
        return

    _back_up_preferences(version)

    if version < 1:
        for key in ('bg colour', 'thumb bg colour'):
            if key in saved_prefs:
                saved_prefs[key] = _rgba_from_16bit_colour(saved_prefs[key])

    if version < 2:
        choices = saved_prefs.get('stored dialog choices')
        if isinstance(choices, dict) and 'delete-opend-file' in choices:
            choices['delete-opened-file'] = choices.pop('delete-opend-file')

    if version < 3:
        # Carried forward unchanged by every MComix since, for as long as
        # nobody touched the setting, and a number is not what the
        # preference holds now: left as it was, a 0 was taken for no
        # answer and recent files were stored after all.
        stored = saved_prefs.get('store recent file info')
        if isinstance(stored, int) and not isinstance(stored, bool):
            saved_prefs['store recent file info'] = stored != 0

    if version < 4:
        # One was the default until format 4, and MComix 3 wrote every
        # preference into the file, default or not: a 1 there is nearly
        # always that default carried forward rather than an answer, and
        # left as it was it kept every archive to the single extraction
        # thread the new default was raised to get past.
        if saved_prefs.get('max extract threads') == 1:
            del saved_prefs['max extract threads']

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
        else:
            # JSON, but not of preferences: it is set aside as a file
            # that will not parse is, rather than stopping MComix.
            if not isinstance(saved_prefs, dict):
                _move_corrupt_file_aside(
                    constants.PREFERENCE_PATH,
                    ValueError('%s where preferences belong'
                               % type(saved_prefs).__name__))
                saved_prefs = None

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
        # A file written by a later MComix, or edited by hand, can name
        # preferences this one has never heard of; those are left where
        # they are rather than taken in.
        for key in saved_prefs:
            if key not in _DEFAULTS:
                continue
            # A value of another type, typed into the file by hand, is
            # left where it is too: taken in, it would reach code that
            # can do nothing with it - a lens of size "big" - at the
            # first moment it was read.
            if not _fits(saved_prefs[key], key):
                print('! Ignoring the preference %r: %r is not what it holds'
                      % (key, saved_prefs[key]))
                continue
            set_by_name(key, saved_prefs[key])

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


def _stored_preferences() -> dict[str, object]:
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


def _changed_here() -> dict[str, object]:
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
    # Made at start-up, but it may have gone since.
    os.makedirs(os.path.dirname(constants.PREFERENCE_PATH), exist_ok=True)
    with tools.atomic_write(constants.PREFERENCE_PATH) as config_file:
        json.dump(stored, config_file, indent=2)
    # What was just written is this instance's baseline from now on.
    # Left at what was read, every later write carried every change ever
    # made here, over whatever another window had set since.  An instance
    # that has read nothing keeps its empty baseline, and writes nothing.
    global _as_read
    if _as_read:
        _as_read = copy.deepcopy(dict(prefs))

# vim: expandtab:sw=4:ts=4
