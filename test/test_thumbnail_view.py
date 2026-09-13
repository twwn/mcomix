# -*- coding: utf-8 -*-

""" The views that make their thumbnails as they are scrolled into view. """

from gi.repository import GdkPixbuf, Gtk

from . import MComixTest

from mcomix import thumbnail_view


class VisibleRangeTest(MComixTest):

    def setUp(self):
        super(VisibleRangeTest, self).setUp()
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, bool)
        filler = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                      64, 64)
        filler.fill(0)
        for index in range(8):
            self.store.append([filler, 'page %d' % index,
                               '/nowhere/%d.png' % index, False])
        self.view = thumbnail_view.ThumbnailIconView(self.store, 2, 0, 3)

    def tearDown(self):
        self.view.stop_update()
        super(VisibleRangeTest, self).tearDown()

    def test_a_view_that_is_not_laid_out_yet_asks_again(self):
        # An icon view answers None to get_visible_range() until it has
        # been laid out, and neither being mapped nor its adjustment
        # settling is late enough.  Nothing asked again, so the
        # thumbnails were never made and every cell stayed empty.
        self.assertIsNone(self.view.get_visible_range())
        self.view.draw_thumbnails_on_screen()
        self.assertIsNotNone(self.view._retry,
                             'nothing will ask the view again')

    def test_it_does_not_ask_for_ever(self):
        self.view._retries_left = 1
        self.view.draw_thumbnails_on_screen()
        self.assertIsNotNone(self.view._retry)
        self.view._retry = None
        self.view.draw_thumbnails_on_screen()
        self.assertIsNone(self.view._retry,
                          'the view is still being asked after giving up')

    def test_one_pending_question_at_a_time(self):
        self.view.draw_thumbnails_on_screen()
        first = self.view._retry
        self.view.draw_thumbnails_on_screen()
        self.assertEqual(self.view._retry, first,
                         'the view queued a second question')

# vim: expandtab:sw=4:ts=4
