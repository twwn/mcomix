# -*- coding: utf-8 -*-

"""The library's cover area, and the black it is painted on."""

from gi.repository import Gtk

from . import MComixTest, wait_for
from .test_theme import background_of

from mcomix.library import book_area


class _Event(object):

    """Stands in for the observable the backend exposes."""

    def __iadd__(self, handler):
        return self


class _Backend(object):

    book_added_to_collection = _Event()


class _Library(object):

    backend = _Backend()


class BlackBackgroundTest(MComixTest):

    """Covers are shown on black whatever the theme's base colour is.

    A style provider belongs to a display in GTK4 rather than to a
    widget, so the rule reaches this view through a class rather than by
    being attached to it. Nothing about that is visible until something
    is painted, which is what this measures.
    """

    def setUp(self):
        super(BlackBackgroundTest, self).setUp()
        self.area = book_area._BookArea(_Library())
        self.window = Gtk.Window()
        self.window.set_default_size(200, 200)
        self.window.set_child(self.area)

    def tearDown(self):
        # A window left on screen is answered by whatever looks for one
        # next.
        self.window.destroy()
        super(BlackBackgroundTest, self).tearDown()

    def test_the_covers_are_painted_on_black(self):
        self.window.present()
        wait_for(lambda: self.area._iconview.get_width() > 0)
        self.assertEqual('rgb(0,0,0)', background_of(self.area._iconview))

    def test_the_view_carries_the_class_the_rule_is_written_against(self):
        self.assertTrue(self.area._iconview.has_css_class(
            book_area._BookArea._BLACK_CSS_CLASS))


# vim: expandtab:sw=4:ts=4
