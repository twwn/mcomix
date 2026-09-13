""" How large a preview of a page is drawn. """

from gi.repository import Gtk

from . import MComixTest

from mcomix import preview


class PreviewSizeTest(MComixTest):

    def test_a_preview_is_never_smaller_than_it_was_asked_for(self):
        widget = Gtk.Window()
        self.assertGreaterEqual(preview.scaled(80, widget), 80)
        widget.destroy()

    def test_the_factor_stays_between_one_and_three(self):
        widget = Gtk.Window()
        factor = preview.screen_factor(widget)
        self.assertGreaterEqual(factor, 1.0)
        self.assertLessEqual(factor, preview._MAX_FACTOR)
        widget.destroy()

    def test_a_screen_with_nothing_to_say_changes_nothing(self):
        # No widget, no display, no monitors: the size stands.
        self.assertEqual(preview.screen_factor(None), 1.0)
        self.assertEqual(preview.scaled(125, None), 125)

    def test_every_previewer_asks_the_same_way(self):
        # The sidebar, the library and the archive editor all drew their
        # own fixed size, so all three were small on a tall screen.
        import inspect
        from mcomix import (edit_image_area, file_chooser_base_dialog,
                            thumbbar)
        from mcomix.library import book_area
        for module in (thumbbar, book_area, edit_image_area,
                       file_chooser_base_dialog):
            self.assertIn('preview.scaled', inspect.getsource(module),
                          '%s sizes its preview by itself'
                          % module.__name__)

# vim: expandtab:sw=4:ts=4
