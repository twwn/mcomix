"""Following the colours a desktop theme states.

A GTK4 theme states its colours as the names libadwaita reads.  Plain
GTK4 reads none of them, so MComix kept the stock grey while whatever
such a theme states outright - the file chooser's sidebar, in the case
that brought this up - applied as written, and the dialog came out grey
with a pitch-black sidebar in it.
"""

import json
import os
import subprocess
import sys
import unittest
import unittest.mock

import gi
from gi.repository import Gdk, Gio, GLib, Gsk, Gtk

from . import MComixTest, wait_for

from mcomix import theme
from mcomix.preferences import prefs


def background_of(window, topmost=False):
    """The colour <window> is actually painted in.

    The widest colour painted, or with <topmost> the last painted of the
    widest: a view that fills the window is painted over the window's
    own background, which is just as wide.

    Waiting on the window's own size rather than for a fixed interval:
    the frame clock may not have run within one under load, and a window
    that has not been allocated snapshots to nothing at all, which read
    as the palette not having been applied.
    """
    if gi.version_info < (3, 48):
        # A render node is a fundamental type, and PyGObject hands those
        # to Python only from 3.48 on: 3.46 raises "No means to translate
        # argument or return value for 'GskColorNode'".  MComix itself
        # never reads a render node, so only this way of looking at what
        # was painted is out of reach there.
        raise unittest.SkipTest('PyGObject %s cannot read render nodes'
                                % gi.__version__)
    if not wait_for(lambda: window.get_width() > 0
                    and window.get_height() > 0, seconds=5):
        raise AssertionError('the window was never allocated')
    paintable = Gtk.WidgetPaintable.new(window)
    widest = []

    def walk(node):
        if node is None:
            return
        kind = node.get_node_type()
        if kind == Gsk.RenderNodeType.COLOR_NODE:
            size = node.get_bounds().size
            widest.append((size.width * size.height,
                           len(widest) if topmost else 0,
                           node.get_color().to_string()))
        if kind == Gsk.RenderNodeType.CONTAINER_NODE:
            for index in range(node.get_n_children()):
                walk(node.get_child(index))
        elif hasattr(node, 'get_child'):
            try:
                walk(node.get_child())
            except TypeError:
                pass

    for _ in range(20):
        widest.clear()
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, window.get_width(), window.get_height())
        walk(snapshot.to_node())
        if widest:
            break
        wait_for(lambda: False, seconds=0.05)
    return max(widest)[2] if widest else None


class PaletteTest(MComixTest):

    _COLOUR = 'rgb(1,2,3)'

    def setUp(self):
        super().setUp()
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
        super().tearDown()

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



class LibadwaitaStylesheetsTest(MComixTest):

    """Where the colours are read from, with libadwaita's resources
    stood in for: the one gtk.css of 1.9, the one default.css of 1.8,
    or the light and the dark stylesheets of the releases before."""

    # As libadwaita 1.5.0's _defaults.scss compiles, the lines that
    # matter to MComix (sassc -t compact keeps one to a line).
    _DEFAULTS = {
        'light': '@define-color window_bg_color #fafafa;\n'
                 '@define-color window_fg_color rgba(0, 0, 0, 0.8);\n'
                 '@define-color accent_bg_color @blue_3;\n',
        'dark': '@define-color window_bg_color #242424;\n'
                '@define-color window_fg_color white;\n'
                '@define-color accent_bg_color @blue_3;\n',
    }

    def _colours(self, resources, dark):
        def lookup(path, flags):
            if path not in resources:
                raise GLib.Error('no resource at %s' % path)
            return GLib.Bytes.new(resources[path].encode('utf-8'))

        with unittest.mock.patch.object(theme, '_started', True), \
                unittest.mock.patch.object(Gio, 'resources_lookup_data',
                                           side_effect=lookup):
            return theme._adwaita_colours(dark)

    def test_up_to_1_7_each_variant_is_read_from_its_own_stylesheet(self):
        resources = {'/org/gnome/Adwaita/styles/defaults-%s.css' % variant:
                     text for variant, text in self._DEFAULTS.items()}
        self.assertEqual({'window_bg_color': '#fafafa',
                          'window_fg_color': 'rgba(0, 0, 0, 0.8)'},
                         self._colours(resources, dark=False))
        self.assertEqual({'window_bg_color': '#242424',
                          'window_fg_color': 'white'},
                         self._colours(resources, dark=True))

    def test_the_one_stylesheet_of_1_9_is_read_first(self):
        resources = {
            '/org/gnome/Adwaita/styles/gtk.css':
                '@define-color window_bg_color #fafafb;\n'
                '@media (prefers-color-scheme: dark) { '
                '@define-color window_bg_color #222226; }\n',
            '/org/gnome/Adwaita/styles/defaults-dark.css':
                '@define-color window_bg_color #242424;\n',
        }
        self.assertEqual({'window_bg_color': '#222226'},
                         self._colours(resources, dark=True))

    def test_1_8_keeps_both_variants_in_default_css(self):
        resources = {
            '/org/gnome/Adwaita/styles/default.css':
                '@define-color window_bg_color #fafafb;\n'
                '@media (prefers-color-scheme: dark) { '
                '@define-color window_bg_color #222226; }\n',
            '/org/gnome/Adwaita/styles/main.css':
                '.background { color: red; }\n',
        }
        self.assertEqual({'window_bg_color': '#fafafb'},
                         self._colours(resources, dark=False))
        self.assertEqual({'window_bg_color': '#222226'},
                         self._colours(resources, dark=True))

    def test_no_stylesheet_at_all_states_nothing(self):
        self.assertEqual({}, self._colours({}, dark=True))


class LibadwaitaColoursTest(MComixTest):

    """The light and the dark libadwaita states, read out of the
    stylesheet it carries.

    Where libadwaita is running MComix takes its surface colours from
    there rather than copying them, so a libadwaita that moved or
    renamed its stylesheet would leave every scheme with no colours at
    all, silently.  Starting libadwaita cannot be undone and takes over
    the look of every window after it, so it is started in a process of
    its own.

    libadwaita 1.9 carries one gtk.css (1.9.4 here) and 1.8 one
    default.css, each stating the light colours and the dark ones under
    a prefers-color-scheme query; up to 1.7 - 1.5.0 is Ubuntu 24.04's
    and so the GitHub jobs' - it carries a defaults-light.css and a
    defaults-dark.css.  Each is read where it is the one there, so this
    runs against any of them.
    """

    _SCRIPT = (
        'import json\n'
        'from mcomix import theme\n'
        'if not theme._start_libadwaita():\n'
        '    print(json.dumps(None))\n'
        'else:\n'
        '    from gi.repository import Adw\n'
        '    print(json.dumps([[Adw.get_major_version(),\n'
        '                       Adw.get_minor_version()]]\n'
        '                     + [theme._definitions(scheme) for scheme in\n'
        '                        (theme.LIGHT, theme.DARK, theme.BLACK,\n'
        '                         theme.SYSTEM)]))\n')

    def test_each_scheme_states_the_colours_it_is_named_for(self):
        environment = dict(os.environ, HOME=self.tmp_dir)
        result = subprocess.run(
            [sys.executable, '-c', self._SCRIPT], capture_output=True,
            text=True, timeout=30, env=environment,
            cwd=os.path.dirname(os.path.dirname(theme.__file__)))
        self.assertEqual(0, result.returncode, result.stderr)
        answer = json.loads(result.stdout.splitlines()[-1])
        if answer is None:
            self.skipTest('libadwaita is not installed')
        version, light, dark, black, system = answer
        for name, colours in (('light', light), ('dark', dark),
                              ('pitch black', black)):
            with self.subTest(scheme=name, libadwaita=version):
                self.assertIn('window_bg_color', colours)
                self.assertIn('view_fg_color', colours)
        self.assertNotEqual(light['window_bg_color'],
                            dark['window_bg_color'])
        self.assertEqual('#000000', black['window_bg_color'])
        self.assertEqual(dark['view_fg_color'], black['view_fg_color'])
        self.assertEqual({}, system)

# vim: expandtab:sw=4:ts=4


def _border_nodes(window, colours=False):
    """Every border node painted when <window> is drawn, as the widths of
    its four sides - how an outline comes out of the renderer - or, with
    <colours>, as those widths paired with the colours of the sides."""
    if gi.version_info < (3, 48):
        raise unittest.SkipTest('PyGObject %s cannot read render nodes'
                                % gi.__version__)
    if not wait_for(lambda: window.get_width() > 0
                    and window.get_height() > 0, seconds=5):
        raise AssertionError('the window was never allocated')
    paintable = Gtk.WidgetPaintable.new(window)
    found = []

    def walk(node):
        if node is None:
            return
        kind = node.get_node_type()
        if kind == Gsk.RenderNodeType.BORDER_NODE:
            widths = tuple(node.get_widths())
            found.append((widths, tuple(node.get_colors())) if colours
                         else widths)
        if kind == Gsk.RenderNodeType.CONTAINER_NODE:
            for index in range(node.get_n_children()):
                walk(node.get_child(index))
        elif hasattr(node, 'get_child'):
            try:
                walk(node.get_child())
            except TypeError:
                pass

    for _ in range(20):
        found.clear()
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        walk(node)
        if node is not None:
            break
        wait_for(lambda: False, seconds=0.05)
    return found


class PageMarkTest(MComixTest):

    """The outline round a page picked out or marked to swap.

    Its rule was in the palette, which MComix states only where it has
    colours of its own to state: with libadwaita running and the colour
    scheme left to the system - what a new profile has - nothing loaded
    it, and a page picked out looked like any other.
    """

    def _drawn(self, *classes):
        """A window holding a page with <classes>, drawn."""
        from gi.repository import Gdk as _Gdk
        prefs['colour scheme'] = theme.SYSTEM
        theme.follow_theme()
        picture = Gtk.Picture()
        texture = _Gdk.MemoryTexture.new(
            4, 4, _Gdk.MemoryFormat.R8G8B8A8, gi.repository.GLib.Bytes.new(
                b'\xff' * 64), 16)
        picture.set_paintable(texture)
        picture.set_size_request(40, 40)
        for css_class in classes:
            picture.add_css_class(css_class)
        window = Gtk.Window()
        window.set_child(picture)
        window.set_default_size(60, 60)
        window.present()
        self.addCleanup(self._take_down, window)
        return window

    @staticmethod
    def _take_down(window):
        from gi.repository import Gdk as _Gdk
        window.destroy()
        # Off the display again: it is shared by every test that runs
        # after this one in the same worker.
        if theme._own_styles is not None:
            Gtk.StyleContext.remove_provider_for_display(
                _Gdk.Display.get_default(), theme._own_styles)
            theme._own_styles = None

    def test_a_picked_out_page_is_outlined_whatever_the_colour_scheme(self):
        window = self._drawn(theme.PICKED_OUT_CLASS)
        self.assertTrue(_border_nodes(window), 'nothing outlined the page')

    def test_a_picked_out_page_is_outlined_in_red(self):
        """Delete takes it out of the book for good, and the button that
        deletes for good is red; the outline was the accent's blue."""
        window = self._drawn(theme.PICKED_OUT_CLASS)
        # The outline's own width: on Windows the window's decorations
        # draw a border of their own, a pixel wide and nearly clear.
        sides = [side for widths, colours in _border_nodes(window,
                                                           colours=True)
                 if widths == (4, 4, 4, 4) for side in colours]
        self.assertTrue(sides, 'nothing outlined the page')
        for side in sides:
            self.assertGreater(side.red, 0.6, side.to_string())
            self.assertLess(side.green, 0.4, side.to_string())
            self.assertLess(side.blue, 0.4, side.to_string())


class ViewColourTest(MComixTest):

    """The colours MComix was told to paint its own views in.

    A colour scheme other than the system's states the palette above the
    application's rules, and its rule for every view named the theme's
    view colour: the thumbnail bar kept the colour chosen for it only
    behind its rows, and was white below them in the light scheme.
    """

    _COLOUR = [1 / 255, 2 / 255, 3 / 255, 1.0]

    def setUp(self):
        super().setUp()
        self.addCleanup(theme.apply_colour_scheme, theme.SYSTEM)
        self.window = Gtk.Window()
        self.window.set_default_size(200, 200)
        self.addCleanup(self.window.destroy)

    def _painted(self, view):
        """What <view>, filling the window, is painted in, per scheme."""
        self.window.set_child(view)
        self.window.present()
        painted = {}
        for scheme in (theme.LIGHT, theme.DARK, theme.BLACK):
            theme.apply_colour_scheme(scheme)
            view.queue_draw()
            painted[scheme] = background_of(self.window, topmost=True)
        return painted

    def test_the_thumbnail_bar_keeps_its_colour_whatever_the_scheme(self):
        from mcomix import image_tools, thumbnail_list
        view = thumbnail_list.ThumbnailListView()
        view.set_background(self._COLOUR,
                            image_tools.text_color_for_background_color(
                                self._COLOUR))
        for scheme, colour in self._painted(view).items():
            self.assertEqual(colour, 'rgb(1,2,3)', scheme)

    def test_the_library_covers_stay_on_black_whatever_the_scheme(self):
        from mcomix import thumbnail_list
        from mcomix.library import book_area
        view = thumbnail_list.ThumbnailGridView()
        view.add_css_class(book_area._BookArea._BLACK_CSS_CLASS)
        book_area._paint_black(view.get_display(),
                               book_area._BookArea._BLACK_CSS_CLASS)
        for scheme, colour in self._painted(view).items():
            self.assertEqual(colour, 'rgb(0,0,0)', scheme)
