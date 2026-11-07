"""Continuous mode: the book as one strip, its pages one below the
other without a gap (upstream feature requests 123 and 126)."""

import os
import unittest.mock
import zipfile

from PIL import Image

from . import MComixTest, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import image_tools
from mcomix import keybindings
from mcomix import main
from mcomix import osd
from mcomix import page_marks
from mcomix import page_rotations
from mcomix import preferences
from mcomix import ui
from mcomix.preferences import prefs


class _StripTest(MComixTest):

    """A window on a book of long pages, in a view of a known size."""

    #: The pages, each (width, height); most as a strip's are, one wider.
    PAGES = ((100, 300), (100, 300), (200, 300), (100, 300), (100, 300),
             (100, 300), (100, 300), (100, 300))
    #: The room the pages are told they have.
    VIEW = (200, 400)
    CONTINUOUS = True
    #: Whether the book, whose pages are long, may put itself in the
    #: mode; off where a test is about the mode being off.
    DETECT = False
    #: The Exif orientation of a page, by its number, where it has one.
    EXIF: dict[int, int] = {}

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        prefs['continuous mode'] = self.CONTINUOUS
        prefs['continuous for long strips'] = self.DETECT
        # As wide as the view, which keeps the sums in the tests short.
        prefs['continuous width'] = 100
        prefs['default double page'] = False
        prefs['default manga mode'] = False
        icons.load_icons()
        keybindings._manager = None
        self.book = os.path.join(self.tmp_dir, 'strip.zip')
        with zipfile.ZipFile(self.book, 'w') as archive:
            for number, size in enumerate(self.PAGES, 1):
                name = os.path.join(self.tmp_dir, 'page.png')
                exif = Image.Exif()
                if number in self.EXIF:
                    exif[0x0112] = self.EXIF[number]
                Image.new('RGB', size, (number * 30, 0, 0)).save(
                    name, exif=exif)
                archive.write(name, '%02d.png' % number)
        self.window = main.MainWindow(open_path=self.book)
        main.set_main_window(self.window)
        view = unittest.mock.patch.object(
            self.window, 'get_visible_area_size', return_value=self.VIEW)
        view.start()
        self.addCleanup(view.stop)
        # The page area is told the same.  It scrolls no further than
        # its own height allows, and that is the window's, which is as
        # large as the screen lets it be: a page shown at its end stood
        # at 200 on a screen of 640x480 and at 92 on one of 1280x1024.
        area = self.window.page_area
        configure = area._configure
        across = area.get_hadjustment()

        def configured(adjustment, _viewport, content, wanted=None):
            configure(adjustment, self.VIEW[adjustment is not across],
                      content, wanted)

        room = unittest.mock.patch.object(area, '_configure', configured)
        room.start()
        self.addCleanup(room.stop)
        handler = self.window.imagehandler
        self.assertTrue(wait_for(
            lambda: all(handler.page_is_available(page)
                        for page in range(1, len(self.PAGES) + 1)),
            seconds=20))
        self._redraw()

    def tearDown(self):
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _redraw(self):
        self.window.draw_image()
        self.assertTrue(wait_for(
            lambda: not self.window._waiting_for_redraw))
        pump()

    def _boxes(self):
        return [(box.get_position(), box.get_size())
                for box in self.window.layout.get_content_boxes()]

    def _shown(self):
        return [image for image in self.window.images if image.get_visible()]


class StackTest(_StripTest):

    def test_the_pages_are_stacked_as_wide_as_the_view(self):
        """200 wide, a page of 100x300 is 600 high and one of 200x300 is
        300: two screens are 800, which the second and third page
        cover, below the first."""
        self.assertEqual(
            [((0, 0), (200, 600)), ((0, 600), (200, 600)),
             ((0, 1200), (200, 300))], self._boxes())

    def test_there_is_no_gap_between_them(self):
        prefs['space between two pages'] = 12
        self.window.update_space()
        self.window.set_page(2)
        self._redraw()
        boxes = self._boxes()
        self.assertEqual([((0, 0), (200, 600)), ((0, 600), (200, 300)),
                          ((0, 900), (200, 600))], boxes)
        for (above, size), (below, _size) in zip(boxes, boxes[1:]):
            self.assertEqual(above[1] + size[1], below[1])

    def test_the_view_scrolls_over_all_of_them(self):
        self.assertEqual((200, 1500),
                         tuple(self.window.page_area.get_content_size()))
        self.assertEqual(
            (200, 1500), tuple(self.window.layout.get_union_box().get_size()))

    def test_as_many_page_widgets_show_as_pages_are_stacked(self):
        self.assertEqual(3, self.window.displayed_page_count())
        self.assertEqual(3, len(self._shown()))
        self.assertEqual([1, 2, 3], self.window.displayed_pages())
        with unittest.mock.patch.object(
                self.window, 'get_visible_area_size',
                return_value=(100, 700)):
            self._redraw()
            # 100 wide the pages are 300, 300, 150, 300, 300, 300, 300
            # high: below the first, the seventh passes two screens,
            # 1400.
            self.assertEqual(7, self.window.displayed_page_count())
            self.assertEqual(7, len(self._shown()))
            self.assertEqual(
                [0, 300, 600, 750, 1050, 1350, 1650],
                [position[1] for position, _size in self._boxes()])
        self._redraw()
        self.assertEqual(3, len(self._shown()),
                         'widgets of pages no longer stacked still show')

    def test_a_turn_starts_the_strip_at_the_page_turned_to(self):
        self.window.set_page(3)
        self._redraw()
        self.assertEqual([3, 4, 5], self.window.displayed_pages())
        self.assertEqual([((0, 0), (200, 300)), ((0, 300), (200, 600)),
                          ((0, 900), (200, 600))], self._boxes())
        self.assertEqual((0, 0), tuple(self.window.page_area.get_position()))

    def test_the_last_pages_are_a_shorter_strip(self):
        self.window.set_page(len(self.PAGES))
        self._redraw()
        self.assertEqual([len(self.PAGES)], self.window.displayed_pages())
        self.assertEqual([((0, 0), (200, 600))], self._boxes())

    def test_short_pages_are_not_stacked_without_end(self):
        with unittest.mock.patch.object(
                self.window, 'get_visible_area_size',
                return_value=(10, 4000)), \
                unittest.mock.patch.object(constants, 'CONTINUOUS_MAX_PAGES', 3):
            self._redraw()
            self.assertEqual(3, self.window.displayed_page_count())

    def test_a_long_strip_is_not_turned_on_its_side(self):
        """Pages are turned by their shape where the preference asks,
        and a strip's shape is not a page's."""
        prefs['auto rotate depending on size'] = constants.AUTOROTATE_HEIGHT_90
        self._redraw()
        self.assertEqual([(200, 600), (200, 600), (200, 300)],
                         [size for _position, size in self._boxes()])

    def test_two_pages_are_not_shown_side_by_side(self):
        prefs['default double page'] = True
        self._redraw()
        self.assertFalse(self.window.displayed_double())
        self.assertEqual([0, 0, 0], [position[0]
                                     for position, _size in self._boxes()])

    def test_manga_mode_does_not_turn_the_strip_round(self):
        self.window.is_manga_mode = True
        self._redraw()
        self.assertEqual([1, 2, 3], self.window.displayed_pages())
        self.assertEqual([0, 600, 1200],
                         [position[1] for position, _size in self._boxes()])

    def test_manga_mode_is_back_when_the_strip_is_left(self):
        self.window.is_manga_mode = True
        self.assertFalse(self.window.is_manga_mode)
        prefs['continuous mode'] = False
        self.assertTrue(self.window.is_manga_mode)

    def test_the_resolution_shown_is_the_first_pages(self):
        with unittest.mock.patch.object(
                self.window.statusbar, 'set_resolution') as shown:
            self._redraw()
        resolutions = shown.call_args.args[0]
        self.assertEqual(1, len(resolutions))
        self.assertEqual([100, 300], list(resolutions[0][:2]))


class GrowingStripTest(_StripTest):

    """Pages that are not there yet are not waited for: the strip is
    drawn with the ones that are, and grows as the rest arrive."""

    def test_only_pages_that_are_there_are_stacked(self):
        handler = self.window.imagehandler
        there = handler._available_images
        gone = {index for index in there if index >= 1}
        there.difference_update(gone)
        try:
            self._redraw()
            self.assertEqual([((0, 0), (200, 600))], self._boxes())
        finally:
            there.update(gone)

    def test_a_page_that_arrives_goes_below_what_is_being_read(self):
        handler = self.window.imagehandler
        there = handler._available_images
        gone = {index for index in there if index >= 1}
        there.difference_update(gone)
        try:
            self._redraw()
            self.assertEqual(1, self.window.displayed_page_count())
            self.window.scroll(0, 150)
            pump()
            self.assertFalse(self.window._waiting_for_redraw)
            there.add(1)
            self.window._page_available(2)
            # Asked for at once; drawn when the main loop next turns.
            self.assertTrue(self.window._waiting_for_redraw)
            self.assertEqual(1, self.window.displayed_page_count())
            self.assertTrue(wait_for(
                lambda: self.window.displayed_page_count() == 2))
            pump()
            self.assertEqual([((0, 0), (200, 600)), ((0, 600), (200, 600))],
                             self._boxes())
            self.assertEqual(
                (0, 150), tuple(self.window.page_area.get_position()))
        finally:
            there.update(gone)


    def test_a_page_further_down_asks_for_nothing(self):
        self.window._page_available(len(self.PAGES))
        self.assertFalse(self.window._waiting_for_redraw)


class DoublePageSetTest(_StripTest):

    """Double page mode left on: in a strip it says nothing, wherever
    it is asked."""

    def setUp(self):
        super().setUp()
        prefs['default double page'] = True
        self._redraw()

    def test_no_pages_are_paired(self):
        self.assertFalse(self.window.is_double_page)
        self.assertFalse(self.window.displayed_double())
        handler = self.window.imagehandler
        # From the second: an archive's first page is called a title
        # page whatever the mode, which only double page mode reads.
        for page in range(2, len(self.PAGES) + 1):
            self.assertFalse(handler.get_virtual_double_page(page), page)

    def test_a_book_opened_at_its_end_opens_at_its_last_page(self):
        self.assertEqual(9, self.window.filehandler._get_index_for_page(
            -1, 10, self.book))
        prefs['continuous mode'] = False
        self.assertEqual(8, self.window.filehandler._get_index_for_page(
            -1, 10, self.book))

    def test_no_page_is_offered_to_stand_alone(self):
        self.window.uimanager.set_sensitivities()
        action = self.window.actiongroup.get_action('page_alone_popup')
        self.assertFalse(action.get_sensitive())


class CacheTest(_StripTest):

    """The decoded pages kept are at least the ones on screen."""

    def _kept(self):
        handler = self.window.imagehandler
        return sorted(handler._cache_window(handler.get_current_page()))

    def test_with_no_cacheing_the_strip_is_still_kept(self):
        prefs['max pages to cache'] = 0
        self.assertEqual([0, 1, 2], self._kept())
        with unittest.mock.patch.object(
                self.window, 'get_visible_area_size',
                return_value=(100, 700)):
            self._redraw()
            self.assertEqual(7, self.window.displayed_page_count())
            self.assertEqual([0, 1, 2, 3, 4, 5, 6], self._kept())

    def test_out_of_the_strip_one_page_is_enough(self):
        prefs['max pages to cache'] = 0
        prefs['continuous mode'] = False
        self._redraw()
        self.assertEqual([0], self._kept())


class ToggleTest(_StripTest):

    """The mode is a toggle in the View menu, with a key."""

    CONTINUOUS = False

    def _toggle(self):
        self.window.actiongroup.get_action('continuous_mode').activate()
        self.assertTrue(self.window._waiting_for_redraw)
        self.assertTrue(wait_for(
            lambda: not self.window._waiting_for_redraw))
        pump()

    def test_it_stacks_the_pages_and_unstacks_them(self):
        self.window.set_page(3)
        self._redraw()
        self.assertEqual(1, len(self._boxes()))
        self._toggle()
        self.assertTrue(prefs['continuous mode'])
        self.assertEqual([3, 4, 5], self.window.displayed_pages())
        self.assertEqual([((0, 0), (200, 300)), ((0, 300), (200, 600)),
                          ((0, 900), (200, 600))], self._boxes())
        self._toggle()
        self.assertFalse(prefs['continuous mode'])
        self.assertEqual([3], self.window.displayed_pages())
        self.assertEqual(1, len(self._shown()))

    def test_the_page_read_is_shown_from_its_top(self):
        """Fitted to the view's width a page is 600 high and scrolls;
        how far it was scrolled says nothing about a strip of another
        width, so the strip starts at the page's top."""
        prefs['zoom mode'] = constants.ZoomMode.WIDTH
        prefs['stretch'] = True
        self.window.change_zoom_mode()
        self._redraw()
        self.assertEqual([((0, 0), (200, 600))], self._boxes())
        self.assertTrue(self.window.scroll(0, 150))
        self.assertGreater(self.window.page_area.get_position()[1], 0)
        self._toggle()
        self.assertEqual(0, self.window.page_area.get_position()[1])
        self.assertTrue(self.window.scroll(0, 250))
        self.assertGreater(self.window.page_area.get_position()[1], 0)
        self._toggle()
        self.assertEqual(0, self.window.page_area.get_position()[1])

    def test_double_page_and_manga_mode_are_not_offered_in_a_strip(self):
        actions = self.window.actiongroup
        names = ('double_page', 'title_page_alone', 'manga_mode')
        self.assertEqual([True] * 3, [actions.get_action(name).get_sensitive()
                                      for name in names])
        self._toggle()
        self.assertEqual([False] * 3, [actions.get_action(name).get_sensitive()
                                       for name in names])
        self._toggle()
        self.assertEqual([True] * 3, [actions.get_action(name).get_sensitive()
                                      for name in names])

    def test_what_they_were_set_to_comes_back(self):
        actions = self.window.actiongroup
        actions.get_action('double_page').activate()
        actions.get_action('manga_mode').activate()
        self._toggle()
        self.assertFalse(self.window.is_double_page)
        self.assertFalse(self.window.is_manga_mode)
        self.assertTrue(actions.get_action('double_page').get_active())
        self.assertTrue(actions.get_action('manga_mode').get_active())
        self._toggle()
        self.assertTrue(self.window.is_double_page)
        self.assertTrue(self.window.is_manga_mode)

    def test_it_is_in_the_view_menus_and_has_a_key(self):
        def items_of(menu, table):
            """The items of the menu called <menu>, wherever in <table>
            it is nested."""
            for entry in table:
                if isinstance(entry, tuple):
                    if entry[0] == menu:
                        return entry[1]
                    found = items_of(menu, entry)
                    if found is not None:
                        return found
            return None

        self.assertIn('continuous_mode', items_of('menu_view', ui._MENUBAR))
        self.assertIn('continuous_mode',
                      items_of('menu_view_popup', ui._POPUP))
        manager = keybindings.keybinding_manager(self.window)
        self.assertTrue(manager.get_bindings_for_action('continuous_mode'))


class StartsOnTest(_StripTest):

    def test_a_window_opened_with_the_mode_on_shows_it_ticked(self):
        action = self.window.actiongroup.get_action('continuous_mode')
        self.assertTrue(action.get_active())
        self.assertTrue(prefs['continuous mode'])
        self.assertFalse(
            self.window.actiongroup.get_action('manga_mode').get_sensitive())


class WidthTest(_StripTest):

    """The strip is drawn at a share of the view's width, which zooming
    changes (upstream feature request 126)."""

    def setUp(self):
        super().setUp()
        prefs['continuous width'] = 50
        self._redraw()

    def _widths(self):
        return [size[0] for _position, size in self._boxes()]

    def test_it_starts_at_half_the_view(self):
        self.assertEqual(50, constants.CONTINUOUS_WIDTH_DEFAULT)
        self.assertEqual(50, preferences._DEFAULTS['continuous width'])

    def test_every_page_is_that_wide_and_the_strip_is_centred(self):
        """Half of 200: the pages are 300, 300, 150, 300 and 300 high,
        the fifth passing two screens below the first."""
        self.assertEqual(
            [((50, 0), (100, 300)), ((50, 300), (100, 300)),
             ((50, 600), (100, 150)), ((50, 750), (100, 300)),
             ((50, 1050), (100, 300))],
            self._boxes())

    def test_zooming_changes_the_share(self):
        self.window.manual_zoom_in()
        self._redraw()
        self.assertEqual(60, prefs['continuous width'])
        self.assertEqual({120}, set(self._widths()))
        self.window.manual_zoom_out()
        self.window.manual_zoom_out()
        self._redraw()
        self.assertEqual(40, prefs['continuous width'])
        self.assertEqual({80}, set(self._widths()))
        self.window.manual_zoom_original()
        self._redraw()
        self.assertEqual(50, prefs['continuous width'])
        self.assertEqual({100}, set(self._widths()))

    def test_the_share_stops_at_its_ends(self):
        prefs['continuous width'] = constants.CONTINUOUS_WIDTH_MAX
        self.window.manual_zoom_in()
        self.assertEqual(constants.CONTINUOUS_WIDTH_MAX,
                         prefs['continuous width'])
        prefs['continuous width'] = constants.CONTINUOUS_WIDTH_MIN
        self.window.manual_zoom_out()
        self.assertEqual(constants.CONTINUOUS_WIDTH_MIN,
                         prefs['continuous width'])

    def test_a_share_out_of_range_in_the_preferences_is_drawn_within_it(self):
        for kept, drawn in ((0, 20), (-5, 20), (100000, 400)):
            with self.subTest(kept=kept):
                prefs['continuous width'] = kept
                self._redraw()
                self.assertEqual({drawn}, set(self._widths()))

    def test_a_strip_wider_than_the_view_scrolls_sideways(self):
        prefs['continuous width'] = 200
        self._redraw()
        self.assertEqual({400}, set(self._widths()))
        self.assertEqual(400, self.window.page_area.get_content_size()[0])
        self.assertEqual({0}, {position[0]
                               for position, _size in self._boxes()})

    def test_the_zoom_of_other_books_is_left_alone(self):
        before = self.window.zoom._user_zoom_log
        self.window.manual_zoom_in()
        self.window.manual_zoom_in()
        self.assertEqual(before, self.window.zoom._user_zoom_log)
        prefs['continuous mode'] = False
        self.window.manual_zoom_in()
        self.assertEqual(before + 1, self.window.zoom._user_zoom_log)
        self.assertEqual(70, prefs['continuous width'])

    def test_what_is_being_read_stays_at_the_top_through_a_zoom(self):
        prefs['continuous width'] = 100
        self._redraw()
        self.window.scroll(0, 100)
        self.assertEqual(100, self.window.page_area.get_position()[1])
        prefs['continuous width'] = 50
        self._redraw()
        self.assertEqual(50, self.window.page_area.get_position()[1])
        self.window.manual_zoom_in()
        self._redraw()
        self.assertEqual(60, self.window.page_area.get_position()[1])

    def test_control_and_the_wheel_keep_the_part_under_the_pointer(self):
        prefs['continuous width'] = 50
        self._redraw()
        self.window.scroll(0, 100)
        self.window.manual_zoom_in(anchor=(10, 150))
        self._redraw()
        self.assertEqual(60, prefs['continuous width'])
        # 250 of the strip under the pointer, 300 of it at 1.2 times.
        self.assertEqual(150, self.window.page_area.get_position()[1])

    def test_the_fit_modes_are_not_offered_in_a_strip(self):
        self.window.uimanager.set_sensitivities()
        actions = self.window.actiongroup
        names = ('best_fit_mode', 'fit_width_mode', 'fit_height_mode',
                 'fit_size_mode', 'fit_manual_mode')
        self.assertEqual([False] * 5, [actions.get_action(name).get_sensitive()
                                       for name in names])
        actions.get_action('continuous_mode').activate()
        self.assertEqual([True] * 5, [actions.get_action(name).get_sensitive()
                                      for name in names])


class ScrollTest(_StripTest):

    """Scrolling goes on from one page into the next: the strip moves on
    under the view, and what is on screen stays where it is (upstream
    feature request 123).

    From the first page the strip is 600, 600 and 300 high; from the
    third 300, 600 and 600.
    """

    def _page(self):
        return self.window.imagehandler.get_current_page()

    def _down(self):
        return self.window.page_area.get_position()[1]

    def _drawn(self):
        self.assertTrue(wait_for(
            lambda: not self.window._waiting_for_redraw))
        pump()

    def _on_screen(self, page):
        """How far below the top of the view <page> begins."""
        index = self.window.displayed_pages().index(page)
        return self._boxes()[index][0][1] - self._down()

    def test_within_the_first_page_nothing_moves_on(self):
        self.assertTrue(self.window.scroll(0, 500))
        self.assertEqual(1, self._page())
        self.assertIsNone(self.window._strip_shift)
        self.assertFalse(self.window._waiting_for_redraw)
        self.assertEqual(500, self._down())

    def test_scrolled_off_the_first_page_the_next_is_the_current_one(self):
        self.assertTrue(self.window.scroll(0, 700))
        # At once: the page, and the move the next draw makes.
        self.assertEqual(2, self._page())
        self.assertEqual((0, -600), self.window._strip_shift)
        self.assertTrue(self.window._waiting_for_redraw)
        self._drawn()
        self.assertIsNone(self.window._strip_shift)
        self.assertEqual([2, 3, 4], self.window.displayed_pages())
        self.assertEqual([((0, 0), (200, 600)), ((0, 600), (200, 300)),
                          ((0, 900), (200, 600))], self._boxes())
        self.assertEqual(100, self._down())

    def test_what_is_on_screen_stays_where_it_is(self):
        self.assertEqual(600, self._boxes()[1][0][1])
        self.window.scroll(0, 700)
        # Until the strip is drawn again the second page is where the
        # first draw put it, 600 down, and the view 700.
        self.assertEqual(700, self._down())
        self._drawn()
        self.assertEqual(600 - 700, self._on_screen(2))

    def test_every_page_scrolled_past_is_left(self):
        self.window.set_page(3)
        self._redraw()
        self.assertTrue(self.window.scroll(0, 1000))
        self.assertEqual(5, self._page())
        self._drawn()
        self.assertEqual(100, self._down())
        self.assertEqual(5, self.window.displayed_pages()[0])

    def test_scrolling_up_from_the_top_brings_the_page_before(self):
        self.window.set_page(3)
        self._redraw()
        self.assertTrue(self.window.scroll(0, -50))
        self.assertEqual(2, self._page())
        self.assertEqual((1, -50), self.window._strip_shift)
        self.assertEqual(0, self._down())
        self._drawn()
        self.assertEqual([2, 3, 4], self.window.displayed_pages())
        self.assertEqual(550, self._down())
        # Page three has moved down by what was scrolled, and no more.
        self.assertEqual(50, self._on_screen(3))

    def test_the_first_page_has_none_before_it(self):
        self.assertFalse(self.window.scroll(0, -50))
        self.assertEqual(1, self._page())
        self.assertIsNone(self.window._strip_shift)

    def test_a_page_before_that_is_not_there_yet_is_not_waited_for(self):
        self.window.set_page(3)
        self._redraw()
        there = self.window.imagehandler._available_images
        there.discard(1)
        try:
            self.assertFalse(self.window.scroll(0, -50))
            self.assertEqual(3, self._page())
        finally:
            there.add(1)

    def test_one_move_at_a_time(self):
        self.window.scroll(0, 700)
        self.window.scroll(0, 300)
        self.assertEqual(2, self._page())
        self.assertEqual((0, -600), self.window._strip_shift)
        self._drawn()
        self.assertEqual(400, self._down())
        self.assertEqual([2, 3, 4], self.window.displayed_pages())

    def test_a_page_just_turned_to_is_not_moved_on_from(self):
        """Until it is drawn, the pages laid out are those of the page
        turned from: 700 down them is not 700 down the new strip."""
        self.window.set_page(5)
        self.assertTrue(self.window._waiting_for_redraw)
        self.window.scroll(0, 700)
        self.assertEqual(5, self._page())
        self.assertIsNone(self.window._strip_shift)
        self._drawn()
        self.assertEqual(5, self._page())
        self.assertEqual(0, self._down())

    def test_a_page_before_that_is_not_there_is_not_the_previous_book(self):
        self.window.set_page(3)
        self._redraw()
        there = self.window.imagehandler._available_images
        there.discard(1)
        try:
            with unittest.mock.patch.object(
                    self.window, 'previous_book') as opened:
                self.window.flip_page(-1)
                opened.assert_not_called()
        finally:
            there.add(1)

    def test_a_scroll_bar_dragged_down_moves_the_strip_on_too(self):
        bar = self.window.page_area.get_vadjustment()
        # Once the page area has been allocated, the bar spans the strip.
        self.window.scroll(0, 50)
        self.assertTrue(wait_for(lambda: bar.get_upper() == 1500))
        # The first allocation announces a new size, which draws the
        # strip again; nothing moves on while a draw is on its way.
        self._drawn()
        self.assertEqual(1, self._page())
        self.assertTrue(wait_for(lambda: bar.get_upper() == 1500))
        bar.set_value(650)
        self.assertEqual(650, self._down())
        self.assertEqual(2, self._page())
        self._drawn()
        self.assertEqual(50, self._down())

    def test_a_turn_of_the_page_scrolls_a_screen(self):
        self.window.flip_page(1)
        self.assertEqual(400, self._down())
        self.assertEqual(1, self._page())
        self.window.flip_page(1)
        self.assertEqual(2, self._page())
        self._drawn()
        self.assertEqual(200, self._down())
        self.window.flip_page(-1)
        self.assertEqual(1, self._page())
        self._drawn()
        self.assertEqual(400, self._down())

    def test_past_the_last_page_the_next_book_opens(self):
        self.window.set_page(len(self.PAGES))
        self._redraw()
        with unittest.mock.patch.object(self.window, 'next_book') as opened:
            self.window.flip_page(1)
            self.assertEqual(200, self._down())
            opened.assert_not_called()
            self.window.flip_page(1)
            opened.assert_called_once_with()

    def test_before_the_first_page_the_previous_book_opens(self):
        with unittest.mock.patch.object(
                self.window, 'previous_book') as opened:
            self.window.flip_page(-1)
            opened.assert_called_once_with()

    def test_the_end_of_a_strip_still_growing_is_not_the_books_end(self):
        there = self.window.imagehandler._available_images
        gone = {index for index in there if index >= 1}
        there.difference_update(gone)
        try:
            self._redraw()
            self.assertEqual(1, self.window.displayed_page_count())
            with unittest.mock.patch.object(
                    self.window, 'next_book') as opened:
                self.window.flip_page(1)
                self.window.flip_page(1)
                opened.assert_not_called()
        finally:
            there.update(gone)

    def test_a_jump_of_several_pages_is_still_a_jump(self):
        self.window.scroll(0, 300)
        self.window.flip_page(4)
        self._drawn()
        self.assertEqual(5, self._page())
        self.assertEqual(0, self._down())

    def test_smart_scrolling_goes_straight_down(self):
        prefs['smart scroll percentage'] = 0.5
        handler = self.window.event_handler
        with unittest.mock.patch.object(
                self.window.layout, 'scroll_smartly') as smartly:
            handler._smart_scrolling(None, False)
            smartly.assert_not_called()
        self.assertEqual(200, self._down())
        handler._smart_scrolling(90, True)
        self.assertEqual(110, self._down())

    def test_smart_scrolling_at_the_end_asks_for_the_next_book(self):
        self.window.set_page(len(self.PAGES))
        self._redraw()
        self.window.scroll(0, 200)
        handler = self.window.event_handler
        with unittest.mock.patch.object(
                handler, '_next_page_with_protection') as turn:
            handler._smart_scrolling(None, False)
            turn.assert_called_once_with()

    def test_the_bars_follow_the_page_scrolled_to(self):
        changed = []
        self.window.page_changed += lambda: changed.append(self._page())
        self.window.scroll(0, 700)
        self.assertEqual([2], changed)

    def test_a_move_and_a_zoom_drawn_together_keep_the_place(self):
        # 100 into the second page, which starts 600 down; then, before
        # the strip is drawn again, it is made half as wide.
        self.window.scroll(0, 700)
        self.assertTrue(self.window._waiting_for_redraw)
        prefs['continuous width'] = 50
        self.window.draw_image()
        self._drawn()
        self.assertEqual(2, self._page())
        self.assertEqual(50, self._down())

    def test_a_move_up_and_a_zoom_drawn_together_keep_the_place(self):
        self.window.set_page(2)
        self._redraw()
        # 100 above the second page, 500 into the first, 600 high.
        self.window.scroll(0, -100)
        self.assertTrue(self.window._waiting_for_redraw)
        prefs['continuous width'] = 50
        self.window.draw_image()
        self._drawn()
        self.assertEqual(1, self._page())
        self.assertEqual(250, self._down())

    def test_a_strip_turned_on_its_side_scrolls_along(self):
        prefs['rotation'] = 90
        prefs['keep transformation'] = True
        self._redraw()
        self.assertEqual(0, self.window._strip_axis)
        self.window.flip_page(1)
        across, down = self.window.page_area.get_position()
        self.assertEqual((200, 0), (across, down))


class TurnedStripTest(_StripTest):

    """A strip turned on its side runs across a view wider than high:
    each page is 600 along it and 200 across, and the strip reaches
    two screens past the page being read as it does down."""

    VIEW = (1000, 200)

    def setUp(self):
        super().setUp()
        prefs['rotation'] = 90
        prefs['keep transformation'] = True
        self._redraw()

    def test_the_strip_reaches_two_screens_past_the_page_read(self):
        self.assertEqual([1, 2, 3, 4, 5], self.window.displayed_pages())

    def test_scrolling_along_moves_the_strip_on(self):
        self.window.scroll(700, 0)
        self.assertTrue(wait_for(
            lambda: not self.window._waiting_for_redraw))
        pump()
        self.assertEqual(2, self.window.imagehandler.get_current_page())


class ScaledOnceTest(_StripTest):

    """A page of the strip is scaled once for as long as it stays in
    the strip at the same width: a move of the strip scales only the
    pages that come into it."""

    def _scaled(self, draw):
        """The pages <draw> scales, by their height as scaled."""
        with unittest.mock.patch(
                'mcomix.image_tools.fit_pixbuf_to_rectangle',
                wraps=image_tools.fit_pixbuf_to_rectangle) as fit:
            draw()
            self.assertTrue(wait_for(
                lambda: not self.window._waiting_for_redraw))
            pump()
        return [call.args[1][1] for call in fit.call_args_list]

    def test_a_move_of_the_strip_scales_the_page_that_came_into_it(self):
        self.assertEqual([1, 2, 3], self.window.displayed_pages())
        self.assertEqual([600], self._scaled(
            lambda: self.window.scroll(0, 700)))
        self.assertEqual([2, 3, 4], self.window.displayed_pages())

    def test_drawn_again_nothing_is_scaled(self):
        self.assertEqual([], self._scaled(self.window.draw_image))

    def test_another_scaling_quality_scales_every_page_again(self):
        prefs['scaling quality'] = 0
        self.assertEqual([600, 600, 300], self._scaled(self.window.draw_image))

    def test_at_another_width_every_page_is_scaled_again(self):
        prefs['continuous width'] = 50
        self.assertEqual([300, 300, 150, 300, 300], self._scaled(
            self.window.draw_image))

    def test_out_of_a_strip_nothing_is_kept(self):
        prefs['continuous mode'] = False
        self._redraw()
        self.assertEqual({}, self.window._strip_fitted)

    def test_a_book_closed_keeps_nothing(self):
        self.assertTrue(self.window._strip_fitted)
        self.window.filehandler.close_file()
        self._redraw()
        self.assertEqual({}, self.window._strip_fitted)


class ExifTest(_StripTest):

    """A page turned by its Exif tag is a page of the strip as it is
    shown: the second is stored on its side, 3000 high and 100 wide,
    and shown 3000 wide, which at the strip's width is 7 high."""

    PAGES = ((100, 300), (100, 3000)) + ((100, 300),) * 6
    EXIF = {2: 6}

    def setUp(self):
        prefs['auto rotate from exif'] = True
        super().setUp()

    def test_it_is_laid_out_as_it_is_shown(self):
        self.assertEqual([((0, 0), (200, 600)), ((0, 600), (200, 7))],
                         self._boxes()[:2])

    def test_the_strip_reaches_two_screens_below_the_page_read(self):
        self.assertEqual([1, 2, 3, 4], self.window.displayed_pages())

    def test_scrolling_down_moves_the_strip_on(self):
        # Past the first page and the second, which ends at 607.
        self.window.scroll(0, 700)
        self.assertTrue(wait_for(
            lambda: not self.window._waiting_for_redraw))
        pump()
        self.assertEqual(3, self.window.imagehandler.get_current_page())


class ReadTest(_StripTest):

    """The page at the top of the view is the one being read: what the
    bars and the title name, and what Copy and Save act on, of the
    several a strip has on screen."""

    def test_it_is_the_first_of_the_pages_on_screen(self):
        self.assertEqual([1, 2, 3], self.window.displayed_pages())
        self.assertEqual([1], self.window.pages_read())
        self.window.scroll(0, 700)
        self.assertEqual([2], self.window.pages_read())

    def test_out_of_a_strip_it_is_every_page_on_screen(self):
        prefs['continuous mode'] = False
        prefs['default double page'] = True
        self.window.set_page(4)
        self._redraw()
        self.assertEqual(self.window.displayed_pages(),
                         self.window.pages_read())
        self.assertEqual(2, len(self.window.pages_read()))

    def test_the_status_bar_names_it_as_the_view_scrolls(self):
        with unittest.mock.patch.object(
                self.window.statusbar, 'set_page_number') as named:
            self.window.scroll(0, 700)
        named.assert_called_with([2], len(self.PAGES))

    def test_the_title_names_it(self):
        with unittest.mock.patch.object(
                main.status, 'format_page_number',
                wraps=main.status.format_page_number) as named:
            self.window.update_title()
        named.assert_called_once_with([1], len(self.PAGES))

    def test_the_page_number_over_a_fullscreen_strip_is_its_alone(self):
        prefs['page counter'] = osd.PageCounter.ALWAYS
        counter = self.window.page_counter
        with unittest.mock.patch.object(self.window, 'is_fullscreen',
                                        return_value=True):
            counter.update()
            self.assertEqual('1 / %d' % len(self.PAGES), counter.text())
            self.window.scroll(0, 700)
            self.assertEqual('2 / %d' % len(self.PAGES), counter.text())

    def test_copy_takes_it_alone(self):
        copied = []
        clipboard = self.window.clipboard
        with unittest.mock.patch.object(
                clipboard, 'copy',
                side_effect=lambda path, pixbuf: copied.append(
                    (pixbuf.get_width(), pixbuf.get_height()))):
            clipboard.copy_page()
        self.assertEqual([(100, 300)], copied)

    def test_save_takes_it_alone(self):
        actions = self.window.file_actions
        with unittest.mock.patch.object(actions, '_save_pages') as saved:
            actions.extract_page()
            actions.extract_popup_page()
        self.assertEqual([unittest.mock.call([1])] * 2, saved.call_args_list)

    def test_a_turn_by_hand_turns_the_strip_and_is_not_one_pages(self):
        self.window.rotate_90()
        self._redraw()
        self.assertEqual(90, prefs['rotation'])
        self.assertEqual(0, self.window._strip_axis)
        for page in (1, 2, 3):
            identity = self.window.filehandler.page_identity(page)
            self.assertEqual(0, page_rotations.rotation(*identity), page)

    def test_a_turned_strip_still_reads_from_its_first_page_on(self):
        for turn, along in ((90, 0), (180, 1), (270, 0)):
            with self.subTest(turn=turn):
                prefs['rotation'] = turn
                prefs['keep transformation'] = True
                self._redraw()
                places = [position[along]
                          for position, _size in self._boxes()]
                self.assertEqual(sorted(places), places)
                self.assertEqual(0, places[0])
                self.assertGreater(places[1], 0)

    def test_a_turn_remembered_for_a_page_does_not_turn_the_strip(self):
        identity = self.window.filehandler.page_identity(5)
        page_rotations.remember(*identity, 90)
        self.window.set_page(5)
        self._redraw()
        self.assertEqual(0, prefs['rotation'])
        self.assertEqual(1, self.window._strip_axis)
        prefs['continuous mode'] = False
        self.window.set_page(4)
        self.window.set_page(5)
        self.assertEqual(90, prefs['rotation'])

    def test_scrolling_into_a_page_leaves_a_turn_by_hand(self):
        self.window.rotate_180()
        self._redraw()
        self.window.scroll(0, 700)
        self.assertEqual(2, self.window.imagehandler.get_current_page())
        self.assertEqual(180, prefs['rotation'])

    def test_a_page_arrived_at_from_behind_shows_its_end(self):
        self.window.set_page(len(self.PAGES), at_bottom=True)
        self._redraw()
        self.assertEqual(600 - 400, self.window.page_area.get_position()[1])

    def test_the_page_under_the_pointer_is_found_down_the_strip(self):
        # The scroll bars are what page_at() reads, and they span the
        # strip only once the page area has been allocated.
        with unittest.mock.patch.object(
                self.window, 'scroll_offset', return_value=(0, 0)):
            self.assertEqual(1, self.window.page_at(10, 599))
            self.assertEqual(2, self.window.page_at(10, 600))
            self.assertEqual(3, self.window.page_at(10, 1250))
            self.assertIsNone(self.window.page_at(10, 1600))
        with unittest.mock.patch.object(
                self.window, 'scroll_offset', return_value=(0, 300)):
            self.assertEqual(2, self.window.page_at(10, 300))


class SkippedPageTest(_StripTest):

    """A page marked "Skip this page" is left out of the strip: the
    pages either side of it meet, and scrolling passes it either way."""

    def setUp(self):
        super().setUp()
        identity = self.window.filehandler.page_identity(2)
        page_marks.mark(*identity, page_marks.SKIP, True)
        self._redraw()

    def _page(self):
        return self.window.imagehandler.get_current_page()

    def _drawn(self):
        self.assertTrue(wait_for(
            lambda: not self.window._waiting_for_redraw))
        pump()

    def test_it_takes_no_room_and_is_not_shown(self):
        """Below the first page two screens are 800: the third page's
        300 and the fourth's 600, the second counting for nothing."""
        self.assertEqual(
            [((0, 0), (200, 600)), ((0, 600), (200, 0)),
             ((0, 600), (200, 300)), ((0, 900), (200, 600))],
            self._boxes())
        self.assertEqual([True, False, True, True],
                         [image.get_visible()
                          for image in self.window.images[:4]])

    def test_scrolling_down_goes_past_it(self):
        self.window.scroll(0, 700)
        self.assertEqual(3, self._page())
        self._drawn()
        self.assertEqual(100, self.window.page_area.get_position()[1])

    def test_scrolling_up_goes_past_it_too(self):
        self.window.set_page(3)
        self._redraw()
        self.assertTrue(self.window.scroll(0, -50))
        self.assertEqual(1, self._page())
        self.assertEqual((2, -50), self.window._strip_shift)
        self._drawn()
        self.assertEqual(550, self.window.page_area.get_position()[1])

    def test_a_jump_to_it_goes_on_to_the_next_page(self):
        self.window.set_page(2)
        self.assertTrue(wait_for(lambda: self._page() == 3))
        self._drawn()
        self.assertEqual(3, self.window.displayed_pages()[0])

    def test_the_page_under_the_pointer_is_never_it(self):
        with unittest.mock.patch.object(
                self.window, 'scroll_offset', return_value=(0, 0)):
            self.assertEqual(1, self.window.page_at(10, 599))
            self.assertEqual(3, self.window.page_at(10, 600))

    def test_the_lens_passes_over_it(self):
        """The lens draws from every page's box, and this one's has no
        height to scale by."""
        lens = self.window.lens._get_lens_pixbuf(100, 600, (120, 120), 1,
                                                 (0, 0))
        self.assertEqual((122, 122), (lens.get_width(), lens.get_height()))

    def test_out_of_a_strip_nothing_is_left_out(self):
        prefs['continuous mode'] = False
        self._redraw()
        self.assertEqual([True, False],
                         [image.get_visible()
                          for image in self.window.images[:2]])
        self.assertEqual(1, len(self._boxes()))


class DetectTest(_StripTest):

    """A book of long strips is told by its first pages and shown in
    continuous mode by itself (upstream feature request 126); the
    reader's standing choice is not changed by it."""

    CONTINUOUS = False
    DETECT = True

    def _ticked(self):
        return self.window.actiongroup.get_action(
            'continuous_mode').get_active()

    def _toggle(self):
        self.window.actiongroup.get_action('continuous_mode').activate()
        self.assertTrue(wait_for(
            lambda: not self.window._waiting_for_redraw))
        pump()

    def _open(self, path, pages):
        self.window.filehandler.open_file(path)
        handler = self.window.imagehandler
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.file_loaded
            and handler.get_number_of_pages() == pages
            and all(handler.page_is_available(page)
                    for page in range(1, pages + 1)), seconds=20))
        self._redraw()

    def _book_of(self, name, sizes, orientation=None):
        path = os.path.join(self.tmp_dir, name)
        exif = Image.Exif()
        if orientation is not None:
            exif[0x0112] = orientation
        with zipfile.ZipFile(path, 'w') as archive:
            for number, size in enumerate(sizes, 1):
                page = os.path.join(self.tmp_dir, 'page.png')
                Image.new('RGB', size, (0, number * 20, 0)).save(
                    page, exif=exif)
                archive.write(page, '%02d.png' % number)
        return path

    def test_a_book_of_long_pages_is_shown_as_a_strip(self):
        """Five of its first six pages are three times as high as wide."""
        self.assertTrue(self.window._strip_detected)
        self.assertTrue(self.window.is_continuous)
        self.assertGreater(len(self._boxes()), 1)
        self.assertTrue(self._ticked())

    def test_the_standing_choice_is_left_as_it_was(self):
        self.assertFalse(prefs['continuous mode'])

    def test_double_page_and_manga_mode_are_not_offered_for_it(self):
        self.assertFalse(
            self.window.actiongroup.get_action('manga_mode').get_sensitive())

    def test_turned_off_by_hand_it_is_off_for_this_book_only(self):
        self._toggle()
        self.assertFalse(self.window.is_continuous)
        self.assertFalse(self._ticked())
        self.assertFalse(prefs['continuous mode'])
        self.assertEqual(1, len(self._boxes()))
        self._toggle()
        self.assertTrue(self.window.is_continuous)
        self.assertFalse(prefs['continuous mode'],
                         'a strip put back in its mode set it for every book')
        other = self._book_of('other.zip', [(100, 400)] * 3)
        self._toggle()
        self._open(other, 3)
        self.assertTrue(self.window.is_continuous,
                        'the next strip was kept out of the mode')

    def test_long_pages_stored_on_their_side_are_a_strip(self):
        """Stored three times as wide as high, turned upright by their
        Exif tags."""
        prefs['auto rotate from exif'] = True
        book = self._book_of('turned.zip', [(400, 100)] * 4, orientation=6)
        self._open(book, 4)
        self.assertTrue(self.window._strip_detected)

    def test_a_book_of_ordinary_pages_is_left_as_it_is(self):
        book = self._book_of('pages.zip', [(200, 300)] * 4)
        self._open(book, 4)
        self.assertFalse(self.window._strip_detected)
        self.assertFalse(self.window.is_continuous)
        self.assertFalse(self._ticked())
        self.assertEqual(1, len(self._boxes()))
        self.assertTrue(
            self.window.actiongroup.get_action('manga_mode').get_sensitive())

    def test_half_the_pages_are_not_most_of_them(self):
        book = self._book_of('half.zip', [(100, 300), (200, 300)] * 2)
        self._open(book, 4)
        self.assertFalse(self.window.is_continuous)

    def test_twice_as_high_is_long_and_a_little_less_is_not(self):
        self._open(self._book_of('twice.zip', [(100, 200)] * 3), 3)
        self.assertTrue(self.window.is_continuous)
        self._open(self._book_of('less.zip', [(100, 199)] * 3), 3)
        self.assertFalse(self.window.is_continuous)

    def test_only_the_first_pages_are_looked_at(self):
        sizes = [(200, 300)] * constants.CONTINUOUS_SAMPLE_PAGES \
            + [(100, 300)] * 20
        self._open(self._book_of('late.zip', sizes), len(sizes))
        self.assertFalse(self.window.is_continuous)

    def test_a_book_is_looked_at_once_its_first_pages_are_there(self):
        self.window._forget_strip()
        there = self.window.imagehandler._available_images
        there.discard(3)
        try:
            self.window._page_available(2)
            self.assertFalse(self.window._strip_looked)
            self.assertFalse(self.window.is_continuous)
        finally:
            there.add(3)
        self.window._page_available(4)
        self.assertTrue(self.window._strip_looked)
        self.assertTrue(self.window.is_continuous)
        self.assertTrue(self._ticked())

    def test_the_pictures_are_not_decoded_to_look(self):
        self.window._forget_strip()
        with unittest.mock.patch.object(
                self.window.imagehandler, 'get_pixbufs') as decoded:
            self.window._look_for_strip()
        decoded.assert_not_called()
        self.assertTrue(self.window._strip_detected)

    def test_a_book_that_is_closed_takes_its_mode_with_it(self):
        self.window.filehandler.close_file()
        self.assertFalse(self.window._strip_detected)
        self.assertFalse(self.window.is_continuous)
        self.assertFalse(self._ticked())

    def test_a_strip_opened_at_its_end_shows_the_end(self):
        book = self._book_of('end.zip', [(100, 400)] * 3)
        self.window.filehandler.open_file(book, -1)
        handler = self.window.imagehandler
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.file_loaded
            and handler.get_number_of_pages() == 3
            and all(map(handler.page_is_available, (1, 2, 3)))
            and not self.window._waiting_for_redraw, seconds=20))
        pump()
        self.assertTrue(self.window.is_continuous)
        self.assertEqual(3, handler.get_current_page())
        # As wide as the view the page is 800 high, and the view 400.
        self.assertEqual(800 - 400, self.window.page_area.get_position()[1])
        self.window.filehandler.open_file(self.book, -1)
        self.assertTrue(wait_for(
            lambda: self.window.filehandler.file_loaded
            and handler.get_number_of_pages() == len(self.PAGES)
            and all(handler.page_is_available(page)
                    for page in range(1, len(self.PAGES) + 1))
            and not self.window._waiting_for_redraw, seconds=20))
        pump()
        self.assertEqual(len(self.PAGES), handler.get_current_page())
        self.assertEqual(600 - 400, self.window.page_area.get_position()[1])


class DetectOffTest(_StripTest):

    """With the preference off, a book of long pages opens as any other."""

    CONTINUOUS = False

    def test_nothing_is_looked_at(self):
        self.assertFalse(self.window._strip_looked)
        self.assertFalse(self.window.is_continuous)
        self.assertEqual(1, len(self._boxes()))

    def test_the_preference_has_a_box_to_tick(self):
        from mcomix import preferences_dialog
        import inspect
        self.assertIn("'continuous for long strips'",
                      inspect.getsource(preferences_dialog))
        self.assertTrue(preferences._DEFAULTS['continuous for long strips'])


class StandingChoiceTest(_StripTest):

    """The mode chosen for every book, and a book of long strips."""

    DETECT = True

    def test_turned_off_for_a_strip_it_stays_on_for_other_books(self):
        self.assertTrue(self.window._strip_detected)
        self.window.actiongroup.get_action('continuous_mode').activate()
        self.assertFalse(self.window.is_continuous)
        self.assertTrue(prefs['continuous mode'])


class OffTest(_StripTest):

    """With the mode off the window shows a page at a time, as before."""

    CONTINUOUS = False

    def test_one_page_is_shown(self):
        self.assertFalse(self.window.is_continuous)
        self.assertEqual(1, self.window.displayed_page_count())
        self.assertEqual(1, len(self._boxes()))
        self.assertEqual(1, len(self._shown()))
        self.assertEqual(2, len(self.window.images))
