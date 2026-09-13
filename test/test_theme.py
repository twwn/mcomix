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
        self.window = Gtk.Window()
        self.window.set_default_size(200, 200)

    def tearDown(self):
        self.window.destroy()
        if self.user is not None:
            Gtk.StyleContext.remove_provider_for_display(self.display,
                                                         self.user)
        super(PaletteTest, self).tearDown()

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

    def test_the_palette_goes_on_once(self):
        theme.follow_palette()
        provider = theme._provider
        theme.follow_palette()
        self.assertIs(theme._provider, provider)

# vim: expandtab:sw=4:ts=4
