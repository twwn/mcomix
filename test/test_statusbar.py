"""What the status bar puts on screen.

The bar used to hold a Gtk.Statusbar, deprecated as of GTK 4.10, whose
message stack it never used: every write popped context 0 and pushed the
whole line back.  It then was one label joining the fields with "|",
and now is a label per field.  These pin what the labels carry.
"""

from gi.repository import Gdk, Gsk, Gtk

from . import MComixTest, pump, wait_for

from mcomix import constants
from mcomix import status
from mcomix import theme
from mcomix.preferences import prefs


def shown_text(bar):
    """What <bar> shows: its message, or its fields joined by " | "."""
    if bar.message.get_visible():
        return bar.message.get_text()
    return ' | '.join(field.get_text() for field in bar._fields.values()
                      if field.get_visible())


class StatusbarTextTest(MComixTest):

    def setUp(self):
        super().setUp()
        prefs['statusbar fields'] = (constants.STATUS_PAGE |
                                     constants.STATUS_FILENAME)
        self.bar = status.Statusbar()
        self.window = Gtk.Window()
        self.window.set_child(self.bar)

    def tearDown(self):
        self.window.destroy()
        super().tearDown()

    def _text(self):
        return shown_text(self.bar)

    def test_a_message_is_shown_as_it_was_given(self):
        self.bar.set_message('Could not open the archive')
        self.assertEqual(self._text(), 'Could not open the archive')

    def test_a_message_replaces_the_one_before_it(self):
        self.bar.set_message('first')
        self.bar.set_message('second')
        self.assertEqual(self._text(), 'second')

    def test_an_empty_message_clears_the_bar(self):
        self.bar.set_message('something went wrong')
        self.bar.set_message('')
        self.assertEqual(self._text(), '')

    def test_the_date_is_shown_only_when_asked_for(self):
        self.bar.set_page_number([3], 12)
        self.bar.set_date('2024-05-06, 07:08:09')
        self.bar.update()
        self.assertNotIn('2024-05-06', self._text())
        prefs['statusbar fields'] |= constants.STATUS_DATE
        self.bar.update()
        self.assertIn('2024-05-06, 07:08:09', self._text())

    def test_update_shows_the_fields_the_preference_asks_for(self):
        self.bar.set_page_number([3], 12)
        self.bar.set_filename('page-003.jpg')
        self.bar.set_resolution(((800, 600, 1.0, False),))
        self.bar.update()
        text = self._text()
        self.assertIn('3 / 12', text)
        self.assertIn('page-003.jpg', text)
        self.assertNotIn('800x600', text,
                         'the resolution field is off but was shown')

    def test_a_field_with_nothing_to_say_takes_no_room(self):
        """Before a book is open every field is empty, and the bar was a
        row of bare separators; a file whose size is not known leaves one
        in the middle of the line."""
        self.bar.update()
        self.assertEqual('', self._text())
        self.bar.set_page_number([1], 10)
        self.bar.update()
        self.assertEqual('1 / 10', self._text())

    def test_the_page_field_lists_the_pages_in_the_order_it_was_given(self):
        """The pages on screen are handed over in reading order, which
        is right to left in manga mode, so the field lists them as they
        stand rather than sorting them."""
        self.bar.set_page_number([3, 2], 12)
        self.assertEqual('3,2 / 12', self.bar.get_page_number())
        self.bar.set_page_number([2, 3], 12)
        self.assertEqual('2,3 / 12', self.bar.get_page_number())

    def test_update_replaces_a_message_rather_than_stacking_on_it(self):
        self.bar.set_message('an error nobody cleared')
        self.bar.set_page_number([1], 1)
        self.bar.set_filename('only.jpg')
        self.bar.update()
        self.assertNotIn('an error nobody cleared', self._text())

# vim: expandtab:sw=4:ts=4


class StatusbarHeightTest(MComixTest):

    def test_a_name_in_another_script_does_not_change_the_height(self):
        """A fallback font's taller lines made the bar 22 pixels high for
        a Japanese or Korean file name and 18 for a Latin one, so the
        page area above it moved, and the page was scaled again, at every
        file whose name was in another script (upstream bug 148)."""
        bar = status.Statusbar()
        window = Gtk.Window()
        window.set_child(bar)
        self.addCleanup(window.destroy)
        window.present()
        pump()
        heights = set()
        for name in ('Volume 01 - page 003.jpg',
                     '\u9032\u6483\u306e\u5de8\u4eba 003.jpg',
                     '\ub098 \ud63c\uc790\ub9cc 003.jpg'):
            bar.set_filename(name)
            bar.update()
            heights.add(bar.measure(Gtk.Orientation.VERTICAL, -1)[1])
        self.assertEqual(1, len(heights), heights)


class StatusbarLayoutTest(MComixTest):

    """Where the fields stand.  Joined into one line, every field moved
    whenever one before it changed width: the page number gaining a
    digit, a shorter file name moving the size after it, and the
    interface font's digits are not all as wide as one another."""

    def setUp(self):
        super().setUp()
        prefs['statusbar fields'] = (constants.STATUS_PAGE
                                     | constants.STATUS_FILENAME
                                     | constants.STATUS_FILESIZE)
        self.bar = status.Statusbar()
        self.window = Gtk.Window()
        self.window.set_default_size(900, -1)
        self.window.set_child(self.bar)
        self.window.present()
        self.bar.set_root('Book.cbz')

    def tearDown(self):
        self.window.destroy()
        super().tearDown()

    def _show(self, pages, filename, size='1.2 MiB'):
        self.bar.set_page_number(pages, 120)
        self.bar.set_filename(filename)
        self.bar.set_filesize(size)
        self.bar.update()
        self.assertTrue(wait_for(self._laid_out, seconds=5))

    def _laid_out(self):
        """Whether every field shown has been given the room it asks
        for, which happens at the next frame."""
        return all(
            field.get_width() == field.measure(
                Gtk.Orientation.HORIZONTAL, -1)[1]
            for field in self.bar._fields.values() if field.get_visible())

    def _x(self, bit):
        found, bounds = self.bar._fields[bit].compute_bounds(self.bar)
        self.assertTrue(found)
        return bounds.get_x()

    def test_a_page_number_with_more_digits_moves_nothing(self):
        places = set()
        for page in (1, 9, 10, 88, 111):
            self._show([page], 'page.jpg')
            places.add(self._x(constants.STATUS_FILENAME))
        self.assertEqual(1, len(places), places)

    def test_a_shorter_file_name_does_not_move_the_size(self):
        places = set()
        for filename in ('a very long file name of a page.jpg', 'p.jpg',
                         'a very long file name of a page.jpg'):
            self._show([1], filename)
            places.add(self._x(constants.STATUS_FILESIZE))
        self.assertEqual(1, len(places), places)

    def test_another_book_lets_go_of_the_room_held(self):
        self._show([1], 'a very long file name of a page.jpg')
        self._show([1], 'p.jpg')
        held = self._x(constants.STATUS_FILESIZE)
        self.bar.set_root('Another book.cbz')
        self._show([1], 'p.jpg')
        self.assertLess(self._x(constants.STATUS_FILESIZE), held)

    def test_one_separator_stands_between_each_two_fields(self):
        self._show([1], 'page.jpg', size='')
        separators = [bit for bit, separator in self.bar._separators.items()
                      if separator.get_visible()]
        self.assertEqual([constants.STATUS_FILENAME], separators)

    def test_the_bar_does_not_hold_the_window_wide(self):
        """Each field gives way where the window is narrower than the
        bar, as the one line did."""
        prefs['statusbar fields'] = 127
        self.bar.set_resolution(((1200, 1800, 0.453, False),))
        self.bar.set_date('2024-05-06, 07:08:09')
        self.bar.set_page_number([1], 120)
        self.bar.set_filename('a very long file name of a page.jpg')
        self.bar.update()
        minimum, natural = self.bar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
        self.assertLess(minimum, natural / 2)

    def test_every_digit_is_as_wide_as_any_other(self):
        """In the interface font "1111" was 24 pixels wide and "8888"
        37, so a number grew and shrank as its digits changed."""
        field = self.bar._fields[constants.STATUS_PAGE]
        field.set_visible(True)
        widths = set()
        for text in ('1111', '8888', '0000'):
            field.set_text(text)
            widths.add(field.measure(Gtk.Orientation.HORIZONTAL, -1)[1])
            field.let_go()
        self.assertEqual(1, len(widths), widths)

    def test_a_field_s_text_is_centred_in_the_room_it_holds(self):
        """The page field holds the room of "120 / 120" from the first
        page; "1 / 120" stands in the middle of it, as wide a gap on
        either side."""
        self._show([1], 'page.jpg')
        field = self.bar._fields[constants.STATUS_PAGE]
        snapshot = Gtk.Snapshot()
        Gtk.WidgetPaintable(widget=field).snapshot(
            snapshot, field.get_width(), field.get_height())
        drawn = snapshot.to_node().get_bounds()
        before = drawn.get_x()
        after = field.get_width() - drawn.get_x() - drawn.get_width()
        # What is drawn is the glyphs' ink, whose edges stand a little
        # inside the text's own width.
        self.assertGreater(before, 3)
        self.assertLessEqual(abs(before - after), 2, (before, after))

    def test_the_line_between_two_fields_is_half_the_text_s_colour(self):
        """Adwaita draws a separator in 15 per cent of its text colour,
        which in a dark theme left nothing visible between the fields;
        half shows in light, dark and black."""
        theme.show_own_styles()
        self.addCleanup(self._remove_own_styles)
        self._show([1], 'page.jpg')
        separator = next(separator
                         for separator in self.bar._separators.values()
                         if separator.get_visible())
        snapshot = Gtk.Snapshot()
        Gtk.WidgetPaintable(widget=separator).snapshot(
            snapshot, separator.get_width(), separator.get_height())
        node = snapshot.to_node()
        self.assertIsInstance(node, Gsk.ColorNode)
        drawn = node.get_color()
        text = self.bar._fields[constants.STATUS_PAGE].get_color()
        self.assertEqual((text.red, text.green, text.blue),
                         (drawn.red, drawn.green, drawn.blue))
        self.assertAlmostEqual(text.alpha / 2, drawn.alpha, places=2)

    @staticmethod
    def _remove_own_styles():
        if theme._own_styles is not None:
            Gtk.StyleContext.remove_provider_for_display(
                Gdk.Display.get_default(), theme._own_styles)
            theme._own_styles = None
