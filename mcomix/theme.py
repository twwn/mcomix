"""theme.py - Following the colours a desktop theme states."""

from gi.repository import Gdk, Gtk

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

.sidebar, .navigation-sidebar {
    background-color: @sidebar_bg_color;
    color: @sidebar_fg_color;
}
'''

#: Kept alive for as long as the display is: a provider that is dropped
#: takes its styling with it.
_provider = None


def follow_palette(display=None) -> None:
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
