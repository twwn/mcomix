"""The library's cover area, and the black it is painted on."""

import contextlib
import sqlite3
import warnings

from gi.repository import Gdk, GLib, Gtk

from . import MComixTest, wait_for
from .test_theme import background_of

from mcomix import constants
from mcomix import message_dialog
from mcomix.dialog import Response
from mcomix.library import book_area
from mcomix.preferences import prefs


def _children(widget):
    """Every direct child of <widget>, in order."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


class _Event:

    """Stands in for the observable the backend exposes."""

    def __iadd__(self, handler):
        return self


class _Backend:

    book_added_to_collection = _Event()


class _Library:

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
        super().setUp()
        self.area = book_area._BookArea(_Library())
        self.window = Gtk.Window()
        self.window.set_default_size(200, 200)
        self.window.set_child(self.area)

    def tearDown(self):
        # A window left on screen is answered by whatever looks for one
        # next.
        self.window.destroy()
        super().tearDown()

    def test_the_covers_are_painted_on_black(self):
        self.window.present()
        wait_for(lambda: self.area._covers.get_width() > 0)
        self.assertEqual('rgb(0,0,0)', background_of(self.area._covers))

    def test_the_view_carries_the_class_the_rule_is_written_against(self):
        self.assertTrue(self.area._covers.has_css_class(
            book_area._BookArea._BLACK_CSS_CLASS))


class _Book:

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
        super().setUp()
        self.area = book_area._BookArea(_Library())
        self.area._covers.set_items(
            book_area._BookItem(_Book(index, '/books/%d.cbz' % index))
            for index in range(5))

    def tearDown(self):
        self.area.close()
        super().tearDown()

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

    class _Action:

        """Enough of a Gio.SimpleAction for the handler to set a state."""

        def __init__(self):
            self.state = None

        def set_state(self, state):
            self.state = state

    def setUp(self):
        super().setUp()
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
        super().tearDown()

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


class _RecordingBackend(_Backend):

    """A backend that counts the transaction it is put into.

    transaction() is _LibraryBackend.transaction() with the connection
    left out: a caller that leaves the block, however it leaves it, ends
    the transaction it opened.
    """

    def __init__(self, refuse=False):
        self.begun = 0
        self.ended = 0
        self.removed = []
        self._refuse = refuse

    @contextlib.contextmanager
    def transaction(self):
        self.begin_transaction()
        try:
            yield
        finally:
            self.end_transaction()

    def begin_transaction(self):
        self.begun += 1

    def end_transaction(self):
        self.ended += 1

    def remove_book(self, uid):
        if self._refuse:
            raise sqlite3.OperationalError('database is locked')
        self.removed.append(uid)

    def remove_book_from_collection(self, uid, collection):
        if self._refuse:
            raise sqlite3.OperationalError('database is locked')
        self.removed.append((uid, collection))

    def get_collection_name(self, collection):
        return 'Collection'


class _RecordingLibrary:

    def __init__(self, refuse=False):
        self.backend = _RecordingBackend(refuse)
        self.messages = []
        self.collection_area = self

    def set_status_message(self, message):
        self.messages.append(message)

    def get_current_collection(self):
        return 7


class DeleteFromDiskTest(MComixTest):

    """The confirmation that deletes books from the disk."""

    def setUp(self):
        super().setUp()
        self.library = _LibraryWindow()
        self.area = book_area._BookArea(self.library)
        self.area._covers.set_items(
            [book_area._BookItem(_Book(1, '/books/1.cbz'))])
        self.area._covers.selection.select_all()

    def tearDown(self):
        for dialog in self._dialogs():
            dialog.destroy()
        self.library.destroy()
        self.area.close()
        super().tearDown()

    def _dialogs(self):
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_transient_for() is self.library]

    def test_it_defaults_to_the_answer_that_deletes_nothing(self):
        """The books go from the disk as well as from the library, so
        Enter must not be what does it."""
        self.area._completely_remove_book()
        dialogs = self._dialogs()
        self.assertEqual(1, len(dialogs), 'nothing asked before deleting')
        dialog = dialogs[0]
        keeps = dialog.get_widget_for_response(Response.NO)
        deletes = dialog.get_widget_for_response(Response.YES)
        self.assertIsNotNone(keeps, 'the dialog offers no way out')
        self.assertIs(dialog.get_default_widget(), keeps,
                      'Enter would delete the books')
        self.assertTrue(deletes.has_css_class('destructive-action'),
                        'the deleting button is drawn as an ordinary one')


class RemovalTransactionTest(MComixTest):

    """The library stops committing if a removal leaves the transaction open.

    begin_transaction() puts the connection into IMMEDIATE mode and only
    end_transaction() takes it out again, so a statement that raises
    between the two - a locked database, most plausibly, since the main
    window holds the library open as well - left every later write
    waiting for a commit that never came, and held a write lock on the
    file meanwhile.  What these check is that the removals reach the
    backend through something that ends the transaction whatever
    happens, which is _LibraryBackend.transaction().
    """

    def _area(self, refuse):
        library = _RecordingLibrary(refuse)
        area = book_area._BookArea(library)
        area._covers.set_items(
            book_area._BookItem(_Book(index, '/books/%d.cbz' % index))
            for index in range(3))
        area._covers.selection.select_all()
        self.addCleanup(area.close)
        return area, library

    def test_removing_from_the_library_ends_the_transaction(self):
        area, library = self._area(refuse=False)
        area._remove_books_from_library()
        self.assertEqual((1, 1), (library.backend.begun, library.backend.ended))

    def test_a_removal_that_raises_ends_it_too(self):
        area, library = self._area(refuse=True)
        with self.assertRaises(sqlite3.OperationalError):
            area._remove_books_from_library()
        self.assertEqual(1, library.backend.ended,
                         'the connection was left in transactional mode')

    def test_removing_from_a_collection_ends_the_transaction(self):
        area, library = self._area(refuse=False)
        area._remove_books_from_collection()
        self.assertEqual((1, 1), (library.backend.begun, library.backend.ended))

    def test_a_collection_removal_that_raises_ends_it_too(self):
        area, library = self._area(refuse=True)
        with self.assertRaises(sqlite3.OperationalError):
            area._remove_books_from_collection()
        self.assertEqual(1, library.backend.ended,
                         'the connection was left in transactional mode')


class _CoverlessBackend(_Backend):

    """A backend with no covers, so the drag icon is the missing-image
    placeholder rather than a thumbnail read off disk."""

    def get_book_cover(self, book):
        return None


class _CoverlessLibrary:

    def __init__(self):
        self.backend = _CoverlessBackend()


class DragIconTest(MComixTest):

    """The icon the pointer carries while books are dragged.

    Nothing else in the suite runs _drag_begin(), which is why the
    deprecation census - which only sees what the suite executes - did
    not notice that this was the last caller of
    Gdk.Texture.new_for_pixbuf(), deprecated in GTK 4.20.
    """

    def _area(self, books):
        area = book_area._BookArea(_CoverlessLibrary())
        area._covers.set_items(
            book_area._BookItem(_Book(index, '/books/%d.cbz' % index))
            for index in range(books))
        area._covers.selection.select_all()
        self.addCleanup(area.close)
        return area

    def _icon_for(self, books):
        """What _drag_begin() hands to Gtk.DragSource.set_icon().

        Gtk.DragSource has a set_icon() and no get_icon(), so the call
        is recorded rather than read back.
        """
        area = self._area(books)
        source = Gtk.DragSource()
        icons = []
        source.set_icon = lambda paintable, x, y: icons.append(paintable)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            area._drag_begin(source, None)
        deprecations = [str(w.message) for w in caught
                        if issubclass(w.category, DeprecationWarning)]
        self.assertEqual([], deprecations,
                         'building the drag icon called a deprecated API')
        return icons

    def test_one_book_has_an_icon(self):
        icons = self._icon_for(1)
        self.assertEqual(1, len(icons))
        self.assertIsInstance(icons[0], Gdk.Texture)

    def test_several_books_have_an_icon_with_the_count_on_it(self):
        # The branch that composites the number badge onto the cover.
        icons = self._icon_for(3)
        self.assertEqual(1, len(icons))
        self.assertIsInstance(icons[0], Gdk.Texture)

    def test_nothing_selected_sets_no_icon(self):
        self.assertEqual([], self._icon_for(0))

# vim: expandtab:sw=4:ts=4
