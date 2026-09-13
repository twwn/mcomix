# -*- coding: utf-8 -*-

"""Following the colours a desktop theme states.

A GTK4 theme states its colours as the names libadwaita reads.  Plain
GTK4 reads none of them, so MComix kept the stock grey while whatever
such a theme states outright - the file chooser's sidebar, in the case
that brought this up - applied as written, and the dialog came out grey
with a pitch-black sidebar in it.
"""

from gi.repository import Gdk, Gsk, Gtk

from . import MComixTest, wait_for

from mcomix import theme
from mcomix.preferences import prefs


def background_of(window):
    """The colour <window> is actually painted in."""
    wait_for(lambda: False, seconds=0.2)
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    widest = []

    def walk(node):
        if node is None:
            return
        kind = node.get_node_type()
        if kind == Gsk.RenderNodeType.COLOR_NODE:
            size = node.get_bounds().size
            widest.append((size.width * size.height,
                           node.get_color().to_string()))
        if kind == Gsk.RenderNodeType.CONTAINER_NODE:
            for index in range(node.get_n_children()):
                walk(node.get_child(index))
        elif hasattr(node, 'get_child'):
            try:
                walk(node.get_child())
            except TypeError:
                pass

    walk(snapshot.to_node())
    return max(widest)[1] if widest else None


class PaletteTest(MComixTest):

    _COLOUR = 'rgb(1,2,3)'

    def setUp(self):
        super(PaletteTest, self).setUp()
        self.display = Gdk.Display.get_default()
        self.user = None
        self._drop_palette()
        self.window = Gtk.Window()
        self.window.set_default_size(200, 200)

    def tearDown(self):
        self.window.destroy()
        if self.user is not None:
            Gtk.StyleContext.remove_provider_for_display(self.display,
                                                         self.user)
        self._drop_palette()
        super(PaletteTest, self).tearDown()

    def _drop_stated(self):
        theme.apply_colour_scheme(theme.SYSTEM)

    def _drop_palette(self):
        """Leave the display as this test found it."""
        if theme._provider is not None:
            Gtk.StyleContext.remove_provider_for_display(self.display,
                                                         theme._provider)
            theme._provider = None
        theme.apply_colour_scheme(theme.SYSTEM)

    def _state(self, css):
        """Say what a desktop theme states, where GTK expects to read it."""
        self.user = Gtk.CssProvider()
        self.user.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            self.display, self.user, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def test_a_window_takes_the_colour_the_theme_names(self):
        self._state('@define-color window_bg_color rgb(1,2,3);')
        theme.follow_palette()
        self.window.present()
        self.assertEqual(background_of(self.window), self._COLOUR)

    def test_a_sidebar_is_painted_like_the_rest_of_the_window(self):
        # The whole point: one colour for the dialog and the sidebar in
        # it, rather than the theme's black against GTK's grey.
        self._state('@define-color window_bg_color rgb(1,2,3);'
                    '@define-color sidebar_bg_color rgb(1,2,3);')
        theme.follow_palette()
        sidebar = Gtk.Box()
        sidebar.add_css_class('navigation-sidebar')
        sidebar.set_size_request(200, 200)
        self.window.set_child(sidebar)
        self.window.present()
        self.assertEqual(background_of(self.window), self._COLOUR)

    def test_a_colour_nobody_names_costs_nothing(self):
        # Every rule the palette states names a colour a theme may not
        # define.  GTK drops that one declaration and keeps the rest,
        # which is what lets the palette be applied unconditionally.
        provider = Gtk.CssProvider()
        provider.load_from_string('window { background-color: @nosuchcolour; }'
                                  'window { background-color: rgb(1,2,3); }')
        Gtk.StyleContext.add_provider_for_display(
            self.display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        try:
            self.window.present()
            self.assertEqual(background_of(self.window), self._COLOUR)
        finally:
            Gtk.StyleContext.remove_provider_for_display(self.display,
                                                         provider)

    def test_libadwaita_does_the_job_where_it_is_installed(self):
        # It reads the colours a theme states itself, which is what the
        # palette below is imitating; running both would be pointless.
        started = theme._start_libadwaita
        theme._start_libadwaita = lambda: True
        try:
            theme.follow_theme()
        finally:
            theme._start_libadwaita = started
        self.assertIsNone(theme._provider)

    def test_the_palette_stands_in_where_it_is_not(self):
        started = theme._start_libadwaita
        theme._start_libadwaita = lambda: False
        try:
            theme.follow_theme()
        finally:
            theme._start_libadwaita = started
        self.assertIsNotNone(theme._provider)

    def test_pitch_black_wins_over_what_the_desktop_states(self):
        # Not a guess at what the desktop wants, but an answer MComix
        # was given: a theme that states white is not to overrule it.
        self._state('@define-color window_bg_color #ffffff;')
        theme.follow_palette()
        theme.apply_colour_scheme(theme.BLACK)
        self.window.present()
        self.assertEqual(background_of(self.window), 'rgb(0,0,0)')

    def test_following_the_system_gives_the_theme_back(self):
        self._state('@define-color window_bg_color #ffffff;')
        theme.follow_palette()
        theme.apply_colour_scheme(theme.BLACK)
        theme.apply_colour_scheme(theme.SYSTEM)
        self.window.present()
        self.assertIsNone(theme._stated)
        self.assertEqual(background_of(self.window), 'rgb(255,255,255)')

    def test_the_light_and_the_dark_are_asked_for_by_name(self):
        settings = Gtk.Settings.get_default()
        for scheme, dark in ((theme.DARK, True), (theme.LIGHT, False),
                             (theme.BLACK, True)):
            theme.apply_colour_scheme(scheme)
            self.assertEqual(
                settings.get_property('gtk-application-prefer-dark-theme'),
                dark, 'the %s scheme' % scheme)

    def test_pitch_black_reaches_the_page_behind_the_picture(self):
        # The largest thing on the screen, and the one the preference
        # was asked for.
        prefs['colour scheme'] = theme.BLACK
        self.assertEqual(theme.background([0.5, 0.5, 0.5, 1.0]),
                         [0.0, 0.0, 0.0, 1.0])

    def test_any_other_scheme_leaves_the_background_alone(self):
        grey = [0.5, 0.5, 0.5, 1.0]
        for scheme in (theme.SYSTEM, theme.LIGHT, theme.DARK):
            prefs['colour scheme'] = scheme
            self.assertIs(theme.background(grey), grey, 'the %s scheme'
                          % scheme)

    def test_an_explicit_scheme_beats_a_rule_the_theme_states(self):
        # A theme that states a widget's colour outright - Gradience
        # writes .navigation-sidebar that way - is answering for that
        # widget itself, and would stand over a colour alone.
        self._state('@define-color window_bg_color rgb(255,0,0);'
                    '.navigation-sidebar { background-color: rgb(255,0,0); }')
        stock = theme._adwaita_colours
        theme._adwaita_colours = lambda dark: {'window_bg_color': 'rgb(1,2,3)',
                                               'sidebar_bg_color': 'rgb(1,2,3)'}
        try:
            theme.apply_colour_scheme(theme.LIGHT)
        finally:
            theme._adwaita_colours = stock
        sidebar = Gtk.Box()
        sidebar.add_css_class('navigation-sidebar')
        sidebar.set_size_request(200, 200)
        self.window.set_child(sidebar)
        self.window.present()
        self.assertEqual(background_of(self.window), self._COLOUR)

    def test_the_light_and_the_dark_are_read_from_libadwaita(self):
        # Read rather than copied, so that they cannot fall behind it.
        stylesheet = (
            '@define-color window_bg_color #fafafb;\n'
            '@define-color accent_bg_color #3584e4;\n'
            '@media (prefers-color-scheme: dark) { '
            '@define-color window_bg_color #222226; '
            '@define-color accent_bg_color #78aeed; }\n')
        self.assertEqual(theme._parse_colours(stylesheet, dark=False),
                         {'window_bg_color': '#fafafb'})
        self.assertEqual(theme._parse_colours(stylesheet, dark=True),
                         {'window_bg_color': '#222226'})

    def test_the_palette_goes_on_once(self):
        theme.follow_palette()
        provider = theme._provider
        theme.follow_palette()
        self.assertIs(theme._provider, provider)

class PitchBlackBackgroundTest(MComixTest):

    """What pitch black does to a background that follows the picture.

    The scheme blacks out the page area, which is the point of it on an
    OLED screen. A dynamic background is a more specific instruction
    than a colour scheme, though, so pitch black may not quietly turn
    the preference off.
    """

    _PICTURE = [0.5, 0.25, 0.75, 1.0]

    def test_the_fixed_colour_is_blacked_out(self):
        prefs['colour scheme'] = theme.BLACK
        self.assertEqual(theme.background(list(self._PICTURE)),
                         [0.0, 0.0, 0.0, 1.0])

    def test_a_colour_read_off_the_picture_is_left_alone(self):
        prefs['colour scheme'] = theme.BLACK
        self.assertEqual(theme.background(list(self._PICTURE), dynamic=True),
                         self._PICTURE)

    def test_another_scheme_leaves_both_alone(self):
        for scheme in (theme.SYSTEM, theme.LIGHT, theme.DARK):
            prefs['colour scheme'] = scheme
            for dynamic in (False, True):
                self.assertEqual(
                    theme.background(list(self._PICTURE), dynamic=dynamic),
                    self._PICTURE, '%s, dynamic=%s' % (scheme, dynamic))


# vim: expandtab:sw=4:ts=4
