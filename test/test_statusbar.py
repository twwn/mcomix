"""What the status bar puts on screen.

The bar used to hold a Gtk.Statusbar, deprecated as of GTK 4.10, whose
message stack it never used: every write popped context 0 and pushed the
whole line back. These pin the text a label now carries.
"""

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import constants
from mcomix import status
from mcomix.preferences import prefs


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
        return self.bar.status.get_text().strip()

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
