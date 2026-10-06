"""theme.py - Following the colours a desktop theme states."""

import re

from collections.abc import Sequence
from typing import Any

import gi
from gi.repository import Gdk, Gtk

from mcomix import constants
from mcomix import log
from mcomix import portability
from mcomix.preferences import prefs

#: The CSS class that outlines a page picked out with CTRL and a click,
#: in the main view and in the thumbnail bar.
PICKED_OUT_CLASS = 'mcomix-selected-page'
#: The CSS class on the page waiting to be swapped with another.  Both
#: are drawn the same way, bar what tells them apart.
MARKED_CLASS = 'mcomix-marked-page'

#: The names libadwaita gives the colours an application is painted in.
#: A user stylesheet that defines them - Gradience writes one, and so do
#: most GTK4 themes - is written for libadwaita applications, whose
#: stylesheet is the only thing that reads them.  Plain GTK4 paints its
#: own stock colours instead, so MComix stayed grey while every rule
#: such a theme states outright applied as written: a file chooser with
#: a pitch-black sidebar against a grey dialog, where a libadwaita
#: application of the same theme is black throughout.
#:
#: A colour nobody defined drops the one declaration that names it, so a
#: desktop that says nothing about these is left exactly as it was.
_PALETTE = '''
window {
    background-color: @window_bg_color;
    color: @window_fg_color;
}

window.dialog {
    background-color: @dialog_bg_color;
    color: @dialog_fg_color;
}

headerbar {
    background-color: @headerbar_bg_color;
    color: @headerbar_fg_color;
}

popover > contents {
    background-color: @popover_bg_color;
    color: @popover_fg_color;
}

.view, textview > text {
    background-color: @view_bg_color;
    color: @view_fg_color;
}

notebook > stack, .toolbar, actionbar > revealer > box {
    background-color: @window_bg_color;
    color: @window_fg_color;
}

.sidebar, .navigation-sidebar {
    background-color: @sidebar_bg_color;
    color: @sidebar_fg_color;
}
'''

#: The outline round a page a reader has picked out or marked, in the
#: main view and in the thumbnail bar.  Not part of the palette, which
#: is loaded only where MComix states colours of its own: with
#: libadwaita running and the colour scheme left to the system, that is
#: never, and the pages went unmarked.
_PAGE_MARKS = '''
/* A page a reader has said something about: picked out to delete, or
   marked to swap with another.  An outline rather than a border, which
   would take room and move the page it is drawn around, and offset
   inwards, since a page is drawn to the edge of the box it was laid
   out in and an outline outside that would be off screen. */
picture.mcomix-selected-page, picture.mcomix-marked-page {
    /* Stated twice: a theme that does not define an accent colour -
       GTK has only defined one since 4.14 - leaves the second
       declaration unparsed, and the first one stands. */
    outline: 4px solid rgb(53, 132, 228);
    outline: 4px solid @accent_bg_color;
    outline-offset: -4px;
}

/* What tells the two apart at a glance, the rest being shared.  A page
   picked out is one Delete takes out of the book for good, so it is in
   the red of the button that deletes for good, and the same twice over
   for a theme without the colour.  The page marked to be swapped is
   dashed.  A page can be both at once, and is then drawn red and
   dashed. */
picture.mcomix-selected-page {
    outline-color: rgb(224, 27, 36);
    outline-color: @destructive_bg_color;
}

picture.mcomix-marked-page {
    outline-style: dashed;
}
'''

#: The CSS class on the lines between the status bar's fields.
STATUS_SEPARATOR_CLASS = 'mcomix-status-separator'

#: The lines between the status bar's fields.  Adwaita draws a
#: separator in 15 per cent of the colour of the text beside it, which
#: in a dark theme left the fields with nothing visible between them.
#: Half that colour shows in light, dark and black alike, and in
#: whatever colours a desktop theme sets.
_STATUS_SEPARATORS = '''
separator.mcomix-status-separator {
    background-color: alpha(currentColor, 0.5);
}
'''

#: How MComix may be painted.  "System" is whatever the desktop says;
#: the rest override it, and black is a dark theme whose backgrounds are
#: no light at all, which is what an OLED screen shows them as.
SYSTEM, LIGHT, DARK, BLACK = 'system', 'light', 'dark', 'black'

#: Where libadwaita keeps the stylesheet it states its own colours in,
#: and how its dark ones are told apart from its light ones there: its
#: gtk.css from 1.9, its default.css in 1.8, each stating the light
#: colours and the dark ones under a media query.
_ADWAITA_STYLESHEETS = ('/org/gnome/Adwaita/styles/gtk.css',
                        '/org/gnome/Adwaita/styles/default.css')
#: Where libadwaita up to 1.7 kept them instead: one stylesheet for the
#: light colours and one for the dark, with no media query to tell them
#: apart.  1.5.0 is Ubuntu 24.04's.
_ADWAITA_DEFAULTS = '/org/gnome/Adwaita/styles/defaults-%s.css'
_DARK_MEDIA = '@media (prefers-color-scheme: dark) {'
_DEFINE = re.compile(r'@define-color\s+([A-Za-z0-9_]+)\s+([^;]+);')

#: The colours that decide whether a window reads as light or as dark.
#: A scheme MComix was asked for states all of them, so that half a
#: theme cannot be left behind; what a theme says about its accents,
#: and about what is destructive or successful, is still its own.
_SURFACE = (
    'window_bg_color', 'window_fg_color',
    'view_bg_color', 'view_fg_color',
    'headerbar_bg_color', 'headerbar_fg_color', 'headerbar_border_color',
    'headerbar_backdrop_color', 'headerbar_shade_color',
    'headerbar_darker_shade_color',
    'sidebar_bg_color', 'sidebar_fg_color', 'sidebar_backdrop_color',
    'sidebar_shade_color', 'sidebar_border_color',
    'secondary_sidebar_bg_color', 'secondary_sidebar_fg_color',
    'secondary_sidebar_backdrop_color', 'secondary_sidebar_shade_color',
    'secondary_sidebar_border_color',
    'card_bg_color', 'card_fg_color', 'card_shade_color',
    'dialog_bg_color', 'dialog_fg_color',
    'popover_bg_color', 'popover_fg_color', 'popover_shade_color',
    'thumbnail_bg_color', 'thumbnail_fg_color',
    'shade_color', 'scrollbar_outline_color',
)

#: The ones pitch black paints black.  The rest of a dark theme - its
#: text, its shading, the overlay a card is drawn with - is unchanged,
#: which is what keeps black backgrounds readable.
_BLACKENED = (
    'window_bg_color', 'view_bg_color', 'headerbar_bg_color',
    'headerbar_backdrop_color', 'sidebar_bg_color', 'sidebar_backdrop_color',
    'secondary_sidebar_bg_color', 'secondary_sidebar_backdrop_color',
    'dialog_bg_color', 'popover_bg_color', 'thumbnail_bg_color',
)

#: Kept alive for as long as the display is: a provider that is dropped
#: takes its styling with it.
_provider = None
#: The provider that states a scheme's colours, while one is stated.
_stated: "Gtk.CssProvider | None" = None
#: The provider of MComix' own rules: the outline round marked pages,
#: the status bar's separators.
_own_styles: "Gtk.CssProvider | None" = None
#: Whether libadwaita is running, which decides who answers for the
#: light and the dark.
_started = False


def follow_theme() -> None:
    """Paint MComix the way the desktop's theme says to.

    libadwaita's stylesheet is the only one that reads the colour names
    a GTK4 theme states, so hand the job to it where it is installed:
    MComix then follows the theme throughout, as every other GTK4
    application on the desktop does.  Where it is not, the palette
    below maps what the theme states onto the widgets plain GTK4
    styles - less thorough, but better than ignoring the theme.
    """
    show_own_styles()
    if not _start_libadwaita():
        follow_palette()
    apply_colour_scheme()


def show_own_styles(display: "Gdk.Display | None" = None) -> None:
    """Draw the outline round pages picked out or marked to swap, and
    the lines between the status bar's fields.

    At application priority, as the palette is, so that a user's own
    stylesheet can still draw them differently.  Once per display.
    """
    global _own_styles
    if display is None:
        display = Gdk.Display.get_default()
    if display is None or _own_styles is not None:
        return
    _own_styles = Gtk.CssProvider()
    _own_styles.load_from_string(_PAGE_MARKS + _STATUS_SEPARATORS)
    Gtk.StyleContext.add_provider_for_display(
        display, _own_styles, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def apply_colour_scheme(scheme: str | None = None) -> None:
    """Paint MComix as <scheme> says, the preference by default."""
    if scheme is None:
        scheme = prefs['colour scheme']
    _prefer_dark(scheme)
    _state_colours(_definitions(scheme))


def background(colour: Sequence[float],
               dynamic: bool = False) -> Sequence[float]:
    """<colour>, or black where MComix was told to be pitch black.

    A page's own background is the largest thing on the screen, and the
    grey it defaults to is light an OLED screen would not otherwise
    emit, so pitch black means black there too.

    Except where <dynamic> says the colour was read off the picture:
    asking for a background that follows what is on the page is a more
    specific instruction than a colour scheme is, and answering it with
    black would be turning a preference off without saying so.
    """
    if prefs['colour scheme'] == BLACK and not dynamic:
        return [0.0, 0.0, 0.0, 1.0]
    return colour


def _prefer_dark(scheme: str) -> None:
    """Ask for the light or the dark of whatever theme is in use."""
    manager = _style_manager()
    if manager is not None:
        from gi.repository import Adw
        manager.set_color_scheme({
            SYSTEM: Adw.ColorScheme.DEFAULT,
            LIGHT: Adw.ColorScheme.FORCE_LIGHT,
        }.get(scheme, Adw.ColorScheme.FORCE_DARK))
        return
    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    if scheme == SYSTEM:
        # Plain GTK4 does not read the desktop's colour scheme itself.
        lightness = portability.is_system_ui_dark_themed()
        dark = lightness == constants.SystemThemeLightness.DARK
    else:
        dark = scheme != LIGHT
    settings.set_property('gtk-application-prefer-dark-theme', dark)


def _definitions(scheme: str) -> dict[str, str]:
    """The colours <scheme> states, or none where it states nothing.

    Following the system states nothing: whatever the desktop's theme
    holds is the answer.  The rest were asked for, so they answer with
    libadwaita's own light or dark colours - read from its stylesheet
    rather than copied out of it, so they cannot fall behind it - and
    pitch black blacks out the backgrounds among them.
    """
    if scheme == SYSTEM:
        return {}
    colours = _adwaita_colours(dark=scheme != LIGHT)
    if scheme == BLACK:
        colours.update(dict.fromkeys(_BLACKENED, '#000000'))
    return colours


def _adwaita_colours(dark: bool) -> dict[str, str]:
    """libadwaita's own light or dark colours, where it is installed.

    Read from the one stylesheet libadwaita 1.8 and later carry, or
    else from the light or the dark one of the two that came before.
    """
    if not _started:
        return {}
    text = None
    for path in _ADWAITA_STYLESHEETS:
        text = _resource_text(path)
        if text is not None:
            break
    if text is None:
        text = _resource_text(
            _ADWAITA_DEFAULTS % ('dark' if dark else 'light'))
    if text is None:
        return {}
    return _parse_colours(text, dark)


def _resource_text(path: str) -> str | None:
    """The text of the resource at <path>, or None where there is none."""
    try:
        from gi.repository import Gio
        stylesheet = Gio.resources_lookup_data(
            path, Gio.ResourceLookupFlags.NONE)
        data = stylesheet.get_data()
        if data is None:
            return None
        return data.decode('utf-8')
    except Exception as error:
        log.debug('Could not read libadwaita\'s own colours: %s', error)
        return None


def _parse_colours(text: str, dark: bool) -> dict[str, str]:
    """The surface colours <text> states, light or dark."""
    colours: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        # Its light colours stand on their own; its dark ones are
        # stated together, under what the desktop's preference reads
        # as.  Nothing else there is a colour MComix has any use for.
        if line.startswith('@define-color'):
            wanted = True
        elif line.startswith(_DARK_MEDIA) and '@media' not in line[len(_DARK_MEDIA):]:
            wanted = dark
        else:
            continue
        if wanted:
            colours.update(_DEFINE.findall(line))
    return {name: value for name, value in colours.items()
            if name in _SURFACE}


def _state_colours(colours: dict[str, str],
                   display: "Gdk.Display | None" = None) -> None:
    """State <colours>, and the rules that read them, or stop stating."""
    global _stated
    if display is None:
        display = Gdk.Display.get_default()
    if display is None:
        return
    if _stated is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _stated)
        _stated = None
    if not colours:
        return
    _stated = Gtk.CssProvider()
    # The rules as well as the colours: a theme that states a colour
    # outright, as Gradience does for the file chooser's sidebar, is
    # answering for that widget itself and would otherwise stand.
    _stated.load_from_string(
        ''.join('@define-color %s %s;\n' % pair
                for pair in sorted(colours.items())) + _PALETTE)
    # Above the user's own stylesheet rather than below it, as the
    # palette is: this is not a guess at what the desktop wants but an
    # answer MComix was given.
    Gtk.StyleContext.add_provider_for_display(
        display, _stated, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)


def _style_manager() -> Any:  # type: ignore[explicit-any]  # libadwaita is optional, so there is no Adw to name
    """libadwaita's, where libadwaita is running.

    Any, because libadwaita is optional: there is no Adw to name in an
    annotation on a machine that has none.
    """
    if not _started:
        return None
    from gi.repository import Adw
    return Adw.StyleManager.get_default()


def _start_libadwaita() -> bool:
    """Start libadwaita, and say whether it is there to be started."""
    global _started
    try:
        gi.require_version('Adw', '1')
        from gi.repository import Adw
    except (ImportError, ValueError):
        log.debug('libadwaita is not installed; following what of the '
                  'theme plain GTK4 can be told.')
        return False
    Adw.init()
    _started = True
    return True


def follow_palette(display: "Gdk.Display | None" = None) -> None:
    """Paint MComix in the colours <display>'s theme defines.

    The provider goes on at application priority, below the user's own
    stylesheet, so anything that stylesheet states for itself still
    wins.  This only fills in what plain GTK4 leaves out.
    """
    global _provider
    if display is None:
        display = Gdk.Display.get_default()
    if display is None or _provider is not None:
        return
    _provider = Gtk.CssProvider()
    _provider.load_from_string(_PALETTE)
    Gtk.StyleContext.add_provider_for_display(
        display, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

# vim: expandtab:sw=4:ts=4
