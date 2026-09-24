""" i18n.py - Encoding and translation handler."""

import gettext
import io
import locale
import os
import pkgutil
import re
import sys
from collections.abc import Sequence

try:
    import chardet
except ImportError:
    chardet = None  # type: ignore[assignment]

#: Which chardet this is: 7 was written anew, and reads its confidence
#: differently.
_CHARDET_MAJOR = int(chardet.__version__.split('.')[0]) if chardet else 0

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


def guess_encoding(data: bytes, sure: bool = False) -> str | None:
    """The encoding chardet, where it is installed, reads <data> in.

    Only the encodings in use on the web are considered, which is what
    chardet 6 considers unless told otherwise; chardet 7 considers every
    encoding it knows, and read the Latin-1 of a comment as MacCyrillic
    and thirty Shift-JIS page names as EBCDIC.  chardet 5 has no such
    choice to make.

    With <sure>, a guess chardet is not sure of is None.  Up to chardet
    6 a confidence of 0.5 separates them; chardet 7 puts its
    confidences on another scale altogether - page names it read right
    came at 0.01 to 0.43, and some it read wrong at 0.027 - so a guess
    from it is taken as it is.
    """
    if not chardet:
        return None
    era = getattr(chardet, 'EncodingEra', None)
    if era is not None:
        guessed = chardet.detect(data, encoding_era=era.MODERN_WEB)
    else:
        guessed = chardet.detect(data)
    encoding = guessed['encoding']
    if (sure and encoding is not None and _CHARDET_MAJOR < 7
            and guessed['confidence'] < 0.5):
        return None
    return encoding


#: The code pages of DOS, which DOS programs - and Windows' zip folders,
#: which write the OEM code page - wrote text and names in.  chardet
#: does not consider them among the encodings of the web, and cannot
#: tell them from those by the bytes alone.  Code page 866, Russian
#: DOS, is not among them: it reads every byte above 127 as a Cyrillic
#: letter, so any text would read as letters in it.
DOS_CODE_PAGES = ('cp437', 'cp850')


def best_decoding(items: Sequence[bytes],
                  candidates: Sequence[str]) -> str | None:
    """The one of <candidates> that reads every one of <items> with the
    largest share of letters among what is not ASCII, or None if none
    reads them all; on a tie the one named first.

    The same bytes in the wrong one of two single-byte code pages come
    out as signs - currency, box drawing - where the right one gives
    letters: "Mañana" written by DOS is "Ma¤ana" in Windows-1252,
    "Größe" written by Windows "Gr÷▀e" in code page 437.  Kana and
    ideographs are letters too.
    """
    best, best_share = None, -1.0
    for encoding in candidates:
        try:
            texts = [item.decode(encoding) for item in items]
        except (UnicodeDecodeError, LookupError):
            continue
        others = [character for text in texts for character in text
                  if not character.isascii()]
        share = (sum(character.isalpha() for character in others)
                 / len(others)) if others else 1.0
        if share > best_share:
            best, best_share = encoding, share
    return best


def to_unicode(string: str | bytes) -> str:
    """<string> as text: as UTF-8 if it is that, or else in whichever of
    chardet's guess (the locale's encoding where chardet is not
    installed), the file system's encoding, the DOS code pages and
    Latin-1 reads it best (best_decoding()).  Latin-1 reads any bytes,
    so something always comes back.
    """
    if isinstance(string, str):
        return string
    try:
        return string.decode('utf-8')
    except UnicodeDecodeError:
        pass
    candidates = [guess_encoding(string) or locale.getpreferredencoding(),
                  sys.getfilesystemencoding(), *DOS_CODE_PAGES, 'latin-1']
    encoding = best_decoding([string], candidates) or 'latin-1'
    return string.decode(encoding)


def to_utf8(string: str | bytes) -> bytes:
    """ Helper function that converts unicode objects to UTF-8 encoded
    strings. Non-unicode strings are assumed to be already encoded
    and returned as-is. """

    if isinstance(string, str):
        return string.encode('utf-8')
    else:
        return string


def catalogue_candidates(name: str) -> list[str]:
    """The catalogue directories to try for the locale <name>, best first.

    What gettext searches for, less the variants with a character set in
    them, which no catalogue directory carries: "sr@latin" is tried as
    sr_RS@latin, sr@latin, sr_RS and sr.  locale.normalize() fills in
    what the name leaves out, so "zh" alone finds zh_CN.  This did the
    same through gettext's private _expand_lang().
    """
    normalized = locale.normalize(name)
    base, _at, modifier = normalized.partition('@')
    language, _underscore, territory = base.partition('.')[0].partition('_')
    candidates = []
    for suffix in (['@' + modifier] if modifier else []) + ['']:
        if territory:
            candidates.append('%s_%s%s' % (language, territory, suffix))
        candidates.append(language + suffix)
    return candidates


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
        lang_identifiers = catalogue_candidates(lang)

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
    """Translate the message using the current translator."""
    return get_translation().gettext(message)


def to_display_string(string: str) -> str:
    """ Converts a string to a valid UTF-8 string at the expense of data accuracy. """
    return string.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace')

# vim: expandtab:sw=4:ts=4
