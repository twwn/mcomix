# -*- coding: utf-8 -*-

"""The library's cover area, and the black it is painted on."""

from gi.repository import GLib, Gtk

from . import MComixTest, wait_for
from .test_theme import background_of

from mcomix import constants
from mcomix import message_dialog
from mcomix.library import book_area
from mcomix.preferences import prefs


def _children(widget):
    """Every direct child of <widget>, in order."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


class _Event(object):

    """Stands in for the observable the backend exposes."""

    def __iadd__(self, handler):
        return self


class _Backend(object):

    book_added_to_collection = _Event()


class _Library(object):

    backend = _Backend()


class _LibraryWindow(Gtk.Window):

    """A library that is a real window, which a dialog can be transient for."""

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
        wait_for(lambda: self.area._covers.get_width() > 0)
        self.assertEqual('rgb(0,0,0)', background_of(self.area._covers))

    def test_the_view_carries_the_class_the_rule_is_written_against(self):
        self.assertTrue(self.area._covers.has_css_class(
            book_area._BookArea._BLACK_CSS_CLASS))


class _Book(object):

    """Enough of a library book for a cover to be made from it."""

    def __init__(self, id, path, size=0, added='2000-01-01'):
        self.id = id
        self.path = path
        self.size = size
        self.added = added


class CoverOrderTest(MComixTest):

    """What order the covers are shown in.

    The view was a Gtk.IconView over a six column Gtk.ListStore, which
    sorted itself by a column number - which is why the SORT_ constants
    had to match the column layout. A Gtk.Sorter is handed the two items
    instead, so the two are no longer tied together.
    """

    BOOKS = (_Book(1, '/b/zeta.cbz', size=30, added='2003'),
             _Book(2, '/a/alpha.cbz', size=10, added='2001'),
             _Book(3, '/c/mid.cbz', size=20, added='2002'))

    def _order(self, key, ascending=True):
        prefs['lib sort key'] = key
        prefs['lib sort order'] = (constants.SORT_ASCENDING if ascending
                                   else constants.SORT_DESCENDING)
        area = book_area._BookArea(_Library())
        area._covers.set_items(
            book_area._BookItem(book) for book in self.BOOKS)
        area.set_sort_order()
        order = [item.uid for item in area._covers.each_item()]
        area.close()
        return order

    def test_by_book_name_ignores_the_directory(self):
        self.assertEqual(self._order(constants.SORT_NAME), [2, 3, 1])

    def test_by_full_path_does_not(self):
        self.assertEqual(self._order(constants.SORT_PATH), [2, 1, 3])

    def test_by_size(self):
        self.assertEqual(self._order(constants.SORT_SIZE), [2, 3, 1])

    def test_by_date_added(self):
        self.assertEqual(self._order(constants.SORT_LAST_MODIFIED), [2, 3, 1])

    def test_descending_is_the_other_way_round(self):
        self.assertEqual(self._order(constants.SORT_SIZE, ascending=False),
                         [1, 3, 2])


class CoverRemovalTest(MComixTest):

    """Removing covers by book id rather than one position at a time.

    Taking one cover out moves every one after it, so removing several
    by position - which is what the collection area's drop handler did -
    took the wrong books.
    """

    def setUp(self):
        super(CoverRemovalTest, self).setUp()
        self.area = book_area._BookArea(_Library())
        self.area._covers.set_items(
            book_area._BookItem(_Book(index, '/books/%d.cbz' % index))
            for index in range(5))

    def tearDown(self):
        self.area.close()
        super(CoverRemovalTest, self).tearDown()

    def _ids(self):
        return [item.uid for item in self.area._covers.each_item()]

    def test_removing_several_books_removes_those_and_no_others(self):
        self.area.remove_books([0, 2, 4])
        self.assertEqual(self._ids(), [1, 3])

    def test_removing_a_book_that_is_not_shown_is_ignored(self):
        self.area.remove_books([99])
        self.assertEqual(self._ids(), [0, 1, 2, 3, 4])

    def test_a_position_answers_with_the_book_shown_there(self):
        self.assertEqual(self.area.get_book_at_path(3), 3)
        self.assertIsNone(self.area.get_book_at_path(99))


class CoverSizeDialogTest(MComixTest):

    """The dialog behind the library's "Custom" cover size.

    Its scale is packed into the dialog by hand, and the method that
    holds it went with Gtk.MessageDialog: this one is a Gtk.Window
    carrying its own content area.
    """

    class _Action(object):

        """Enough of a Gio.SimpleAction for the handler to set a state."""

        def __init__(self):
            self.state = None

        def set_state(self, state):
            self.state = state

    def setUp(self):
        super(CoverSizeDialogTest, self).setUp()
        self.library = _LibraryWindow()
        self.area = book_area._BookArea(self.library)
        # Redrawing the covers needs a whole library behind it; that a
        # new size asks for one is what matters here.
        self.reloaded = []
        self.area.load_covers = lambda: self.reloaded.append(True)
        self._before = set(Gtk.Window.list_toplevels())

    def tearDown(self):
        # A dialog left on screen is answered by whatever looks for one
        # next.
        for window in set(Gtk.Window.list_toplevels()) - self._before:
            window.destroy()
        self.area.close()
        self.library.destroy()
        super(CoverSizeDialogTest, self).tearDown()

    def _opened_dialogs(self):
        return [window for window in
                set(Gtk.Window.list_toplevels()) - self._before
                if isinstance(window, message_dialog.MessageDialog)]

    def test_a_named_size_is_taken_without_asking(self):
        prefs['library cover size'] = 125
        self.area._book_size_changed(self._Action(), GLib.Variant('i', 64))
        self.assertEqual(64, prefs['library cover size'])
        self.assertEqual([], self._opened_dialogs())
        self.assertEqual(1, len(self.reloaded))

    def test_a_custom_size_asks_with_a_scale_in_the_dialog(self):
        # The scale used to be packed into get_message_area(), which
        # Gtk.MessageDialog had and this dialog never did, so choosing
        # "Custom" raised AttributeError instead of opening anything.
        self.area._book_size_changed(self._Action(), GLib.Variant('i', 0))

        dialogs = self._opened_dialogs()
        self.assertEqual(1, len(dialogs))
        self.assertEqual(1, sum(1 for child in _children(dialogs[0].get_content_area())
                                if isinstance(child, Gtk.Scale)))


# vim: expandtab:sw=4:ts=4
