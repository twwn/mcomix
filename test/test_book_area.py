"""The library's cover area, and the black it is painted on."""

import contextlib
import datetime
import os
import sqlite3
import types
import unittest.mock
import warnings

from gi.repository import Gdk, GLib, Gtk

from . import MComixTest, hold_open, pump, wait_for
from .test_theme import background_of

from mcomix import bookmark_backend
from mcomix import bookmark_menu_item
from mcomix import constants
from mcomix import message_dialog
from mcomix import process
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

    def __isub__(self, handler):
        return self


class _Backend:

    book_added = _Event()
    book_added_to_collection = _Event()

    def __init__(self):
        #: The book ids remove_book() was given.
        self.removed = []

    @contextlib.contextmanager
    def transaction(self):
        yield

    def remove_book(self, book):
        self.removed.append(book)

    def get_book_by_id(self, book):
        # No book is found, so a cover is drawn as the missing image.
        return None

    #: Which collection each collection is filed under, where any is.
    supercollections: dict = {}

    def collection_is_within(self, collection, ancestor):
        if ancestor in (None, constants.COLLECTION_ALL):
            return True
        while collection is not None:
            if collection == ancestor:
                return True
            collection = self.supercollections.get(collection)
        return False


class _ControlArea:

    """Stands in for the pane the cover area tells of every change of
    selection."""

    def update_info(self, selected):
        pass


class _Library:

    backend = _Backend()


class _Recent:

    """Stands in for the recent files, remembering what they forgot."""

    def __init__(self):
        #: The paths remove_path() was given, in order.
        self.removed = []

    def remove_path(self, path):
        self.removed.append(path)


class _OpenBook:

    """Stands in for the main window's file handler and file actions:
    the book it has open, and whether its unwritten changes were
    forgotten."""

    def __init__(self):
        self.path = None
        self.forgotten = False

    def get_path_to_base(self):
        return self.path

    def forget_changes(self):
        self.forgotten = True


class _LibraryWindow(Gtk.Window):

    """A library that is a real window, which a dialog can be transient for."""

    def __init__(self):
        super().__init__()
        self.backend = _Backend()
        self.recent = _Recent()
        self.open_book = _OpenBook()
        self.main_window = types.SimpleNamespace(
            uimanager=types.SimpleNamespace(recent=self.recent),
            filehandler=self.open_book, file_actions=self.open_book)
        self.control_area = _ControlArea()
        #: What set_status_message() was told, in order.
        self.messages = []

    def set_status_message(self, message):
        self.messages.append(message)


class BlackBackgroundTest(MComixTest):

    """Covers are shown on black whatever the theme's base colour is.

    A style provider belongs to a display in GTK4 rather than to a
    widget, so the rule reaches this view through a class rather than by
    being attached to it. Nothing about that is visible until something
    is painted, which is what this measures.
    """

    def setUp(self):
        super().setUp()
        # Held here: an area holds its library window only weakly.
        self.library = _Library()
        self.area = book_area._BookArea(self.library)
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

    def test_the_rule_goes_to_the_display_once(self):
        """Every library window opened added a provider of its own to the
        display, where it stayed after the window had closed."""
        add = unittest.mock.Mock(
            wraps=Gtk.StyleContext.add_provider_for_display)
        with unittest.mock.patch.object(
                Gtk.StyleContext, 'add_provider_for_display', add):
            for _ in range(3):
                library = _Library()
                book_area._BookArea(library).close()
        self.assertLessEqual(add.call_count, 1)


class _Book:

    """Enough of a library book for a cover to be made from it."""

    def __init__(self, id, path, size=0, added='2000-01-01'):
        self.id = id
        self.path = path
        self.size = size
        self.added = added


class _CoverBackend(_Backend):

    """A backend holding one book, whose cover the real thumbnailer
    makes."""

    def __init__(self, path, store):
        super().__init__()
        self._book = _Book(1, path)
        self._book.get_last_read_page = lambda: None
        self._store = store

    def get_book_by_id(self, book):
        return self._book if book == 1 else None

    def get_book_thumbnail(self, path):
        from mcomix import thumbnail_tools
        return thumbnail_tools.Thumbnailer(
            dst_dir=self._store, store_on_disk=True, archive_support=True,
            size=(constants.MAX_LIBRARY_COVER_SIZE,) * 2,
            cover_orientation_required=True).thumbnail(path)


class TurnedCoverTest(MComixTest):

    """A cover is drawn turned as the page it is shows when the book is
    read: its Exif orientation, where 'auto rotate from exif' says so."""

    def setUp(self):
        super().setUp()
        import zipfile
        from . import get_testfile_path
        archive = os.path.join(self.tmp_dir, 'turned.cbz')
        with zipfile.ZipFile(archive, 'w') as book:
            book.write(get_testfile_path(
                'images', 'landscape-exif-270-rotation.jpg'), '01.jpg')
        self.library = _Library()
        self.library.backend = _CoverBackend(
            archive, os.path.join(self.tmp_dir, 'covers'))
        self.library.main_window = types.SimpleNamespace(
            enhancer=types.SimpleNamespace(enhance=lambda pixbuf: pixbuf))
        self.area = book_area._BookArea(self.library)
        self.area._cache.invalidate_all()

    def tearDown(self):
        self.area.close()
        self.area._cache.invalidate_all()
        super().tearDown()

    def test_the_cover_of_a_turned_page_is_turned(self):
        """The picture is 210 pixels wide and 297 high, and shown the
        other way round; the cover was drawn as it is stored."""
        prefs['auto rotate from exif'] = True
        prefs['library cover size'] = constants.SIZE_NORMAL
        pixbuf = self.area._get_pixbuf(1)
        self.assertGreater(pixbuf.get_width(), pixbuf.get_height())


class UnreadableCoverTest(MComixTest):

    """A book with no page that will load is shown as the missing image.
    That was the theme's 24 pixel icon scaled up to the size of a
    cover, and came out blurred."""

    def setUp(self):
        super().setUp()
        import zipfile
        archive = os.path.join(self.tmp_dir, 'unreadable.cbz')
        with zipfile.ZipFile(archive, 'w') as book:
            book.writestr('01.jpg', b'not an image')
        self.library = _Library()
        self.library.backend = _CoverBackend(
            archive, os.path.join(self.tmp_dir, 'covers'))
        self.library.main_window = types.SimpleNamespace(
            enhancer=types.SimpleNamespace(enhance=lambda pixbuf: pixbuf))
        self.area = book_area._BookArea(self.library)
        self.area._cache.invalidate_all()

    def tearDown(self):
        self.area.close()
        self.area._cache.invalidate_all()
        super().tearDown()

    def test_the_missing_image_is_drawn_at_the_size_of_a_cover(self):
        from mcomix import image_tools
        prefs['library cover size'] = constants.SIZE_NORMAL
        width, height = self.area._pixbuf_size(border_size=0)
        icon = image_tools.missing_image_icon(width, height)
        self.assertEqual(width, icon.get_width())

        cover = self.area._get_pixbuf(1)
        # Inside the one pixel border every cover has.
        self.assertEqual((icon.get_width() + 2, icon.get_height() + 2),
                         (cover.get_width(), cover.get_height()))
        drawn = image_tools.pixbuf_to_pil(cover).crop(
            (1, 1, icon.get_width() + 1, icon.get_height() + 1))
        self.assertEqual(image_tools.pixbuf_to_pil(icon).tobytes(),
                         drawn.tobytes())


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
        self.library = _Library()
        area = book_area._BookArea(self.library)
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

    def test_the_menu_sorts_the_covers_again(self):
        """The popup menu's "Sort by" and ascending/descending choices
        are one stateful action each; picking one keeps the choice and
        puts the covers on show in the new order."""
        prefs['lib sort key'] = constants.SORT_NAME
        prefs['lib sort order'] = constants.SORT_ASCENDING
        # Held here: an area holds its library window only weakly.
        self.library = _Library()
        area = book_area._BookArea(self.library)
        self.addCleanup(area.close)
        area._covers.set_items(
            book_area._BookItem(book) for book in self.BOOKS)
        area.set_sort_order()

        def order():
            return [item.uid for item in area._covers.each_item()]

        self.assertEqual([2, 3, 1], order())
        actions = area._popup_actions
        actions.change_action_state('sort-key',
                                    GLib.Variant('i', constants.SORT_PATH))
        self.assertEqual(constants.SORT_PATH, prefs['lib sort key'])
        self.assertEqual(constants.SORT_PATH,
                         actions.get_action_state('sort-key').get_int32())
        self.assertEqual([2, 1, 3], order())
        actions.change_action_state(
            'sort-order', GLib.Variant('i', constants.SORT_DESCENDING))
        self.assertEqual(constants.SORT_DESCENDING, prefs['lib sort order'])
        self.assertEqual(constants.SORT_DESCENDING,
                         actions.get_action_state('sort-order').get_int32())
        self.assertEqual([3, 1, 2], order())


    def _order_of(self, books, key):
        self.BOOKS = books
        return self._order(key)

    def test_covers_a_key_cannot_tell_apart_go_by_their_path(self):
        """Books added in one go share the date they were added, and
        books of one name in two folders - each series' "Volume 1" -
        share their name: they came in whatever order the view held
        them, which is the order they were added or last shown in."""
        for key, books in (
                (constants.SORT_LAST_MODIFIED,
                 [_Book(1, '/b/one.cbz', added='2001'),
                  _Book(2, '/a/two.cbz', added='2001')]),
                (constants.SORT_SIZE,
                 [_Book(1, '/b/one.cbz', size=5),
                  _Book(2, '/a/two.cbz', size=5)]),
                (constants.SORT_NAME,
                 [_Book(1, '/b/Volume 1.cbz'),
                  _Book(2, '/a/Volume 1.cbz')])):
            for listed in (books, books[::-1]):
                with self.subTest(key=key, listed=[b.id for b in listed]):
                    self.assertEqual([2, 1], self._order_of(listed, key))

class CoverRemovalTest(MComixTest):

    """Removing covers by book id rather than one position at a time.

    Taking one cover out moves every one after it, so removing several
    by position - which is what the collection area's drop handler did -
    took the wrong books.
    """

    def setUp(self):
        super().setUp()
        # Held here: an area holds its library window only weakly.
        self.library = _Library()
        self.area = book_area._BookArea(self.library)
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


    def _answer_custom(self, value, response):
        """Pick "Custom", move its scale to <value> and answer the dialog
        with <response>; give back the action the menu shows."""
        action = self._Action()
        self.area._book_size_changed(action, GLib.Variant('i', 0))
        dialog = self._opened_dialogs()[0]
        scale = next(child for child in _children(dialog.get_content_area())
                     if isinstance(child, Gtk.Scale))
        scale.set_value(value)
        dialog.response(response)
        pump()
        return action

    def test_a_custom_size_is_taken_from_the_scale_on_ok(self):
        prefs['library cover size'] = 125
        action = self._answer_custom(210, Response.OK)
        self.assertEqual(210, prefs['library cover size'])
        self.assertEqual(1, len(self.reloaded))
        self.assertEqual(self.area._current_cover_size(),
                         action.state.get_int32())
        self.assertEqual([], self._opened_dialogs())

    def test_a_custom_size_given_up_changes_nothing(self):
        prefs['library cover size'] = 125
        action = self._answer_custom(210, Response.DELETE_EVENT)
        self.assertEqual(125, prefs['library cover size'])
        self.assertEqual([], self.reloaded)
        # The menu goes back to the size there is, from "Custom".
        self.assertEqual(self.area._current_cover_size(),
                         action.state.get_int32())


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

    #: The ids of the books still among the collection's own after a
    #: removal - those filed in a collection under it as well.
    still_filed: set = set()

    def get_collection_by_id(self, collection):
        return types.SimpleNamespace(get_books=lambda: [
            types.SimpleNamespace(id=uid) for uid in self.still_filed])


class _RecordingLibrary:

    def __init__(self, refuse=False):
        self.backend = _RecordingBackend(refuse)
        self.control_area = _ControlArea()
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


    def test_a_book_that_could_not_be_deleted_from_disk_says_so(self):
        """The book leaves the library before the file is deleted, so a
        deletion that fails is the only thing that can tell the reader
        the file is still there.  The fixture's path is not a file, so
        os.remove() raises as it would on a folder that cannot be
        written to."""
        self.area._remove_answered(Response.YES)
        self.assertTrue(self.library.messages, 'the library said nothing')
        self.assertEqual('1 book could not be deleted from disk.',
                         self.library.messages[-1])

    def _bookmark_store(self):
        # MComixTest redirects DATA_DIR without creating it, and the
        # store writes its file as soon as a bookmark is added.
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        store = bookmark_backend.BookmarksStore
        store._initialized = False
        store._bookmarks = []
        self.addCleanup(setattr, store, '_bookmarks', [])
        return store

    def _bookmark(self, path):
        return bookmark_menu_item._Bookmark(
            None, None, os.path.basename(path), path, 2, 20, None,
            datetime.datetime(2026, 1, 1))

    def test_deleting_a_bookmarked_book_asks_about_its_bookmarks(self):
        """The window's own delete asks; the library deleted the file
        and left the bookmark pointing at nothing."""
        path = os.path.join(self.tmp_dir, 'deletable.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'not really a book')
        self.area._covers.set_items([book_area._BookItem(_Book(1, path))])
        self.area._covers.selection.select_all()
        store = self._bookmark_store()
        store.add_bookmark(self._bookmark(path))

        self.area._remove_answered(Response.YES)
        pump()

        dialogs = [window for window in self._dialogs()
                   if window.dialog_id == message_dialog.RememberedDialog
                   .REMOVE_BOOKMARKS_OF_DELETED_FILE]
        self.assertEqual(len(dialogs), 1, 'nothing asked about the bookmark')
        self.assertEqual(len(store.get_bookmarks()), 1,
                         'the bookmark went without being asked about')
        dialogs[0].emit('response', Response.YES)
        pump()
        self.assertEqual(store.get_bookmarks(), [])

    def test_deleting_a_book_nobody_bookmarked_asks_nothing(self):
        path = os.path.join(self.tmp_dir, 'deletable.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'not really a book')
        self.area._covers.set_items([book_area._BookItem(_Book(1, path))])
        self.area._covers.selection.select_all()
        self._bookmark_store()

        self.area._remove_answered(Response.YES)
        pump()

        self.assertEqual(self._dialogs(), [])

    def test_a_book_that_was_deleted_says_nothing_of_the_kind(self):
        path = os.path.join(self.tmp_dir, 'deletable.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'not really a book')
        self.area._covers.set_items([book_area._BookItem(_Book(1, path))])
        self.area._covers.selection.select_all()

        self.area._remove_answered(Response.YES)

        self.assertFalse(os.path.exists(path))
        self.assertTrue(all('could not be deleted' not in message
                            for message in self.library.messages),
                        self.library.messages)

    def test_a_deleted_book_leaves_the_recent_files(self):
        """The window's own delete forgets the path there; the library
        deleted the file and the recent files went on offering it."""
        path = os.path.join(self.tmp_dir, 'deletable.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'not really a book')
        self.area._covers.set_items([book_area._BookItem(_Book(1, path))])
        self.area._covers.selection.select_all()

        self.area._remove_answered(Response.YES)

        self.assertEqual([path], self.library.recent.removed)

    def test_deleting_the_open_book_forgets_its_unwritten_changes(self):
        """Otherwise closing it offers to write the archive back where
        it was just deleted from, and Enter there saves."""
        path = os.path.join(self.tmp_dir, 'deletable.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'not really a book')
        self.area._covers.set_items([book_area._BookItem(_Book(1, path))])
        self.area._covers.selection.select_all()
        self.library.open_book.path = path

        self.area._remove_answered(Response.YES)

        self.assertTrue(self.library.open_book.forgotten)

    def test_deleting_another_book_keeps_the_open_ones_changes(self):
        path = os.path.join(self.tmp_dir, 'deletable.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'not really a book')
        self.area._covers.set_items([book_area._BookItem(_Book(1, path))])
        self.area._covers.selection.select_all()
        self.library.open_book.path = os.path.join(self.tmp_dir, 'open.cbz')

        self.area._remove_answered(Response.YES)

        self.assertFalse(self.library.open_book.forgotten)

    def test_an_open_book_that_would_not_go_keeps_its_changes(self):
        """The fixture's path is not a file, so it is not deleted, and
        the changes still have an archive to go into."""
        self.library.open_book.path = '/books/1.cbz'

        self.area._remove_answered(Response.YES)

        self.assertFalse(self.library.open_book.forgotten)

    def test_a_book_that_would_not_go_stays_in_the_recent_files(self):
        """The fixture's path is not a file, so it is not deleted."""
        self.area._remove_answered(Response.YES)

        self.assertEqual([], self.library.recent.removed)


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

    def test_the_delete_key_takes_the_books_out_of_the_collection(self):
        """Out of the collection on show, not out of the library."""
        area, library = self._area(refuse=False)
        self.assertEqual(Gdk.EVENT_STOP, area._key_press(
            None, Gdk.KEY_Delete, 0, Gdk.ModifierType(0)))
        self.assertEqual([(0, 7), (1, 7), (2, 7)],
                         sorted(library.backend.removed))

    def test_a_book_still_filed_under_the_collection_keeps_its_cover(self):
        """The covers of a collection include the books of the ones
        under it, so a book taken out of it but filed in one of those as
        well is still one of its books; its cover went all the same."""
        area, library = self._area(refuse=False)
        library.backend.still_filed = {1}
        area._remove_books_from_collection()
        self.assertEqual([item.uid for item in area._each_item()], [1])
        self.assertEqual(sorted(uid for uid, _ in library.backend.removed),
                         [0, 1, 2])

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
        self.control_area = _ControlArea()


class DragIconTest(MComixTest):

    """The icon the pointer carries while books are dragged.

    Nothing else in the suite runs _drag_begin(), which is why the
    deprecation census - which only sees what the suite executes - did
    not notice that this was the last caller of
    Gdk.Texture.new_for_pixbuf(), deprecated in GTK 4.20.
    """

    def _area(self, books):
        self.library = _CoverlessLibrary()
        area = book_area._BookArea(self.library)
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

    def test_the_drag_offers_the_positions_of_the_selected_covers(self):
        """What a drop on the collection list reads back: the kind of
        drag, and the positions of the covers dragged."""
        area = self._area(3)
        area._covers.select_only(0)
        area._covers.selection.select_item(2, False)
        # A Gdk.ContentProvider's value cannot be read back through
        # PyGObject, so what it is made from is recorded instead.
        with unittest.mock.patch.object(
                Gdk.ContentProvider, 'new_for_value',
                wraps=Gdk.ContentProvider.new_for_value) as made:
            content = area._drag_prepare(None, 0.0, 0.0)
        self.assertIsInstance(content, Gdk.ContentProvider)
        made.assert_called_once_with(
            '%s:0,2' % constants.LIBRARY_DRAG_BOOKS)
        area._covers.selection.unselect_all()
        self.assertIsNone(area._drag_prepare(None, 0.0, 0.0))

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


class _PathBackend(_Backend):

    """A backend that knows where its books are, and can lose one."""

    def __init__(self):
        self.missing = None

    def get_book_path(self, book):
        return None if book == self.missing else '/books/%d.cbz' % book


class _PathLibrary:

    def __init__(self):
        self.backend = _PathBackend()
        self.control_area = _ControlArea()


class MiddleClickTest(MComixTest):

    """The middle button over a cover opens that book on its own.

    It means here what it means in the recent and bookmark menus: the
    book goes into an MComix of its own and neither the book being read
    nor the library window moves. The cover under the pointer is what it
    acts on, so the coordinates have to be turned into a position, which
    needs the view laid out - hence the window.
    """

    def setUp(self):
        super().setUp()
        self.library = _PathLibrary()
        self.area = book_area._BookArea(self.library)
        self.area._covers.set_items(
            book_area._BookItem(_Book(index, '/books/%d.cbz' % index))
            for index in range(4))
        self.window = Gtk.Window()
        self.window.set_default_size(600, 400)
        self.window.set_child(self.area)
        self.window.present()
        wait_for(lambda: self.area._covers.position_at(*self.FIRST) >= 0)

    def tearDown(self):
        # The thumbnailer thread starts as soon as there are items, and
        # parks on a condition if nobody stops it.
        self.area.close()
        self.window.destroy()
        super().tearDown()

    #: A point inside the first cover, and one past the last one.
    FIRST = (60, 60)
    EMPTY = (580, 380)

    def _click(self, x, y):
        launched = []
        with unittest.mock.patch.object(
                process, 'launch_mcomix',
                side_effect=lambda name, page=0: launched.append((name, page))):
            self.area._middle_click(None, 1, x, y)
        return launched

    def test_it_opens_the_book_under_the_pointer(self):
        self.assertEqual(0, self.area._covers.position_at(*self.FIRST))
        self.assertEqual([('/books/0.cbz', 0)], self._click(*self.FIRST))

    def test_nothing_is_opened_where_there_is_no_cover(self):
        self.assertEqual(-1, self.area._covers.position_at(*self.EMPTY))
        self.assertEqual([], self._click(*self.EMPTY))

    def test_a_book_the_library_no_longer_has_a_path_for_is_left_alone(self):
        self.library.backend.missing = self.area.get_book_at_path(0)
        self.assertEqual([], self._click(*self.FIRST))

    def test_the_selection_is_left_as_it_was(self):
        self.area._covers.select_only(3)
        self._click(*self.FIRST)
        self.assertEqual([3], self.area._covers.get_selected_positions())


# vim: expandtab:sw=4:ts=4


class _FilteredLibrary:

    """A library showing all books through <filter_string>."""

    backend = _Backend()

    def __init__(self, filter_string):
        self.filter_string = filter_string
        self.collection_area = self

    def get_current_collection(self):
        return constants.COLLECTION_ALL


class NewBookUnderAFilterTest(MComixTest):

    """A book added while the covers are filtered is drawn if the filter
    lets it through - by name or by path, as the covers drawn from the
    database are."""

    def _drawn(self, filter_string, name, path):
        library = _FilteredLibrary(filter_string)
        area = book_area._BookArea(library)
        try:
            book = _Book(1, path)
            book.name = name
            with unittest.mock.patch.object(area, 'add_books') as added:
                area._new_book_added(book, None)
            return added.called
        finally:
            area.close()

    def test_a_name_that_matches(self):
        self.assertTrue(self._drawn('batman', 'Batman 01', '/books/Batman 01.cbz'))

    def test_a_book_filed_under_the_collection_on_show_is_drawn(self):
        """The covers of a collection include the books of the ones
        under it, but a book filed in one of those while it was on show
        was drawn only once the covers were drawn again."""
        library = _FilteredLibrary('')
        library.get_current_collection = lambda: 1
        library.backend = _Backend()
        library.backend.supercollections = {3: 1}
        area = book_area._BookArea(library)
        try:
            filed_under, filed_elsewhere = (_Book(7, '/books/7.cbz'),
                                            _Book(8, '/books/8.cbz'))
            filed_under.name, filed_elsewhere.name = '7', '8'
            with unittest.mock.patch.object(area, 'add_books') as added:
                area._new_book_added(filed_under, 3)
                self.assertTrue(added.called, 'filed under it, not drawn')
                area._new_book_added(filed_elsewhere, 2)
                self.assertEqual(added.call_count, 1,
                                 'drawn though filed elsewhere')
        finally:
            area.close()

    def test_a_path_that_matches(self):
        """The name alone was asked, so a book filed under a matching
        folder was left out until the covers were drawn again."""
        self.assertTrue(self._drawn('dc', 'Batman 01', '/books/DC/Batman 01.cbz'))

    def test_neither_matches(self):
        self.assertFalse(self._drawn('marvel', 'Batman 01', '/books/DC/Batman 01.cbz'))


class _CollectionArea:

    """Stands in for the sidebar the cover area asks which collection is
    being shown."""

    @staticmethod
    def get_current_collection():
        return constants.COLLECTION_ALL


class _MenuLibrary:

    backend = _Backend()
    collection_area = _CollectionArea()


class MenuKeyTest(MComixTest):

    """The keys that ask the cover area for its popup menu.

    A GTK3 widget was told by its popup-menu signal, which GTK emitted
    for the menu key and for Shift+F10 alike; the port heard only the
    menu key, leaving a keyboard without one with no way to the menu.
    """

    def setUp(self):
        super().setUp()
        # Held here: an area holds its library window only weakly.
        self.library = _MenuLibrary()
        self.area = book_area._BookArea(self.library)
        self.window = Gtk.Window()
        self.window.set_default_size(400, 300)
        self.window.set_child(self.area)
        self.window.present()

    def tearDown(self):
        self.area._book_menu.popdown()
        self.area.close()
        self.window.destroy()
        super().tearDown()

    def _press(self, keyval, state):
        return self.area._key_press(None, keyval, 0, state)

    def test_both_keys_open_the_menu(self):
        hold_open(self.area._book_menu)
        for keyval, state in ((Gdk.KEY_Menu, Gdk.ModifierType(0)),
                              (Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK)):
            self.assertFalse(self.area._book_menu.get_visible())
            self.assertEqual(Gdk.EVENT_STOP, self._press(keyval, state))
            self.assertTrue(self.area._book_menu.get_visible(),
                            'the menu did not open for %s'
                            % Gdk.keyval_name(keyval))
            self.area._book_menu.popdown()

    def test_f10_on_its_own_is_left_to_gtk(self):
        self.assertEqual(Gdk.EVENT_PROPAGATE,
                         self._press(Gdk.KEY_F10, Gdk.ModifierType(0)))
        self.assertFalse(self.area._book_menu.get_visible())
