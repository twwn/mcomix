""" i18n.py - Encoding and translation handler."""

import gettext
import io
import locale
import os
import pkgutil
import re
import sys

try:
    import chardet
except ImportError:
    chardet = None  # type: ignore[assignment]

from mcomix import preferences
from mcomix import portability
from mcomix import constants
from mcomix import log

# Translation instance to enable other modules to use
# functions other than the global _() if necessary
_translation: gettext.NullTranslations | None = None

#: The locale identifier install_gettext() last resolved the interface
#: language to. Read it through get_language() rather than directly.
_language = 'C'

#: What install_gettext() was asked for, before it resolved anything:
#: the "language" preference, or the code --language named. Read it
#: through get_language_preference().
_language_preference = 'auto'

#: Languages MComix is translated into whose script runs right to left.
#: Pango knows the full set, but pango_language_get_direction() has no
#: introspection binding, so the two that have catalogues are listed here.
_RTL_LANGUAGES = frozenset(('fa', 'he'))


def to_unicode(string: str | bytes) -> str:
    """Convert <string> to unicode. First try the default filesystem
    encoding, and then fall back on some common encodings.
    """
    if isinstance(string, str):
        return string

    # Try chardet heuristic
    if chardet:
        probable_encoding = chardet.detect(string)['encoding'] or \
            locale.getpreferredencoding()  # Fallback if chardet detection fails
    else:
        probable_encoding = locale.getpreferredencoding()

    for encoding in (
            probable_encoding,
            sys.getfilesystemencoding(),
            'utf-8',
            'latin-1'):

        try:
            ustring = str(string, encoding)
            return ustring

        except (UnicodeError, LookupError):
            pass

    return string.decode('utf-8', 'replace')


def to_utf8(string: str | bytes) -> bytes:
    """ Helper function that converts unicode objects to UTF-8 encoded
    strings. Non-unicode strings are assumed to be already encoded
    and returned as-is. """

    if isinstance(string, str):
        return string.encode('utf-8')
    else:
        return string


def install_gettext(force_lang: str | None = None) -> None:
    """ Initialize gettext with the correct directory that contains
    MComix translations. This has to be done before any calls to gettext.gettext
    have been made to ensure all strings are actually translated. """

    # Add the sources' base directory to PATH to allow development without
    # explicitly installing the package.
    sys.path.append(constants.BASE_PATH)

    # Initialize default locale. The environment routinely names a locale
    # the system has not generated - a French desktop on an installation
    # carrying only C.UTF-8 and en_US.UTF-8 is enough - and setlocale()
    # answers that with locale.Error. It decides how numbers and dates are
    # formatted, not which catalogue is loaded below, so a failure here is
    # worth saying out loud and no reason to stop.
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        log.warning('Could not use the locale the environment asks for; '
                    'falling back on the C locale.')

    if force_lang is not None:
        lang = force_lang
        lang_identifiers = [lang]
    elif preferences.prefs['language'] != 'auto':
        lang = preferences.prefs['language']
        lang_identifiers = [lang]
    else:
        # Get the user's current locale
        lang = portability.get_default_locale()
        # No public equivalent: _expand_lang turns a locale identifier
        # into the candidates gettext itself would search for.
        lang_identifiers = gettext._expand_lang(lang)  # type: ignore[attr-defined]

    # Make sure GTK uses the correct language.
    os.environ['LANGUAGE'] = lang

    # Remember both before the loop below reuses the name: the locale
    # that was resolved, and what it was resolved from.
    global _language, _language_preference
    _language = lang
    _language_preference = (force_lang if force_lang is not None
                            else preferences.prefs['language'])

    domain = constants.APPNAME.lower()

    # Search for .mo files manually, since gettext doesn't support packaged resources
    translation: gettext.NullTranslations = gettext.NullTranslations()
    for lang in lang_identifiers:
        resource = os.path.join('messages', lang, 'LC_MESSAGES', '%s.mo' % domain)
        try:
            translation_content = pkgutil.get_data('mcomix', resource)
        except FileNotFoundError:
            continue
        if translation_content is None:
            continue
        translation = gettext.GNUTranslations(io.BytesIO(translation_content))
        break

    global _translation
    _translation = translation


def get_language() -> str:
    """Returns the locale identifier of the language the interface is being
    displayed in. This is the preference, the --language argument or the
    user's locale, whichever install_gettext() settled on."""
    return _language


def get_language_preference() -> str:
    """What the interface on screen was built from: a language code, or
    'auto'.

    This is the value the preferences dialog offers, so it is the one a
    choice made there can be compared against. get_language() answers
    with the locale that was resolved from it instead, which 'auto'
    never equals and which a preference of 'pt_BR' need not either.
    """
    return _language_preference


def is_rtl_language() -> bool:
    """Returns whether the interface language is written right to left."""
    return re.split(r'[-_.@]', _language, maxsplit=1)[0] in _RTL_LANGUAGES


def get_translation() -> gettext.NullTranslations:
    """Returns the loaded translation instance.
    (gettext.GNUTranslations is a subclass of NullTranslations.)"""
    return _translation or gettext.NullTranslations()


def _(message: str) -> str:
    """Translate the messsage using the current translator."""
    return get_translation().gettext(message)


def to_display_string(string: str) -> str:
    """ Converts a string to a valid UTF-8 string at the expense of data accuracy. """
    return string.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace')

# vim: expandtab:sw=4:ts=4
