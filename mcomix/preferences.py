""" preferences.py - Contains the preferences and the functions to read and
write them.  """

import json
import os
import pickle
import shutil
import sys

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

# All the preferences are stored here.
prefs = {
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
    'create thumbnails': True,
    'archive thumbnail as icon' : False,
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
    'window x': 0,
    'window y': 0,
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
    'wrap mouse scroll': False,
    'scaling quality': 2,  # GdkPixbuf.InterpType.BILINEAR
    'escape quits': False,
    'fit to size width wide': 3790,
    'fit to size height wide': 960,
    'fit to size width other': 1450,
    'fit to size height other': 1800,
    'scan for new books on library startup': True,
    'openwith commands': [],  # (label, command) pairs
    'animation mode': constants.ANIMATION_NORMAL,
    'double page autoresize': constants.DOUBLE_PAGE_AUTORESIZE_SIZE,
    'space between two pages': 2,
}


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


def _rgba_from_16bit_colour(colour):
    """Turn a 16-bit RGB triple into the components Gdk.RGBA takes."""
    try:
        red, green, blue = (component / 65535.0 for component in colour[:3])
    except (TypeError, ValueError):
        # Not a colour at all; the default is a better guess than a crash.
        return list(DEFAULT_BG_COLOUR)
    return [red, green, blue, 1.0]


def _migrate_preferences(saved_prefs: dict) -> None:
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

def write_preferences_file() -> None:
    """Write preference data to disk."""
    # TODO: it might be better to save only those options that were (ever)
    # explicitly changed by the used, leaving everything else as default
    # and available (if really needed) to change of defaults on upgrade.
    # XXX: constants.VERSION? It's *preferable* to not complicate the YAML
    # file by adding a `{'version': constants.VERSION, 'prefs': config}`
    # dict or a list.  Adding an extra init line sounds bad too.
    with tools.atomic_write(constants.PREFERENCE_PATH) as config_file:
        json.dump(prefs, config_file, indent=2)

# vim: expandtab:sw=4:ts=4
