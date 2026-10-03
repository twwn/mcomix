""" MComix' own icons, as an icon theme finds them. """

from gi.repository import Gtk

from . import MComixTest

from mcomix import icons


class OwnIconsTest(MComixTest):

    def test_loading_them_again_adds_nothing_to_the_search(self):
        """Every test that builds a window loads the icons, and each load
        put MComix' directory on the display's search path once more:
        after two hundred tests an icon lookup went through two hundred
        copies of it, and presenting a window took 70 ms instead of 1."""
        icons.load_icons()
        icons.load_icons()
        path = icons.icon_theme().get_search_path()
        self.assertEqual(1, path.count(icons.icon_search_path()))

    def _theme(self):
        """An icon theme that searches MComix' own icons and nothing
        else: whatever it finds, the program carries."""
        theme = Gtk.IconTheme()
        theme.set_search_path([icons.icon_search_path()])
        return theme

    def test_the_window_icon_is_among_them(self):
        """main.py names the window icon "mcomix", which only a copy
        installed under share/icons supplied: pip installs none, and the
        Windows build collects MSYS2's hicolor theme, which has no MComix
        in it, so the window went without its icon."""
        theme = self._theme()
        self.assertTrue(theme.has_icon('mcomix'))
        for size in (16, 48, 256):
            with self.subTest(size=size):
                found = theme.lookup_icon('mcomix', None, size, 1,
                                          Gtk.TextDirection.NONE, 0)
                self.assertTrue(found.get_file().get_path().endswith(
                    'mcomix.png'))

    def test_the_toolbar_icons_are_among_them(self):
        """So that the test above, which finds nothing in a theme that
        cannot read the directory, says something."""
        self.assertTrue(self._theme().has_icon('mcomix-archive'))
