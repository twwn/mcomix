"""The library's cover area, and the black it is painted on."""

import contextlib
import datetime
import os
import shutil
import sqlite3
import types
import unittest.mock
import warnings
import zipfile

import PIL.Image

from gi.repository import Gdk, Gio, GLib, Gtk

from . import (MComixTest, NORMAL_ZIP, children, copy_rar_set,
               get_testfile_path, hold_open, menu_keys, prompts_over, pump,
               solid_pixbuf, take_activation_from, wait_for)
from .test_theme import background_of

from mcomix import bookmark_backend
from mcomix import bookmark_menu_item
from mcomix import constants
from mcomix import file_actions
from mcomix import message_dialog
from mcomix import process
from mcomix import image_tools
from mcomix import preview
from mcomix import thumbnail_list
from mcomix import thumbnail_tools
from mcomix.dialog import Response
from mcomix.library import backend, backend_types
from mcomix.library import book_area
from mcomix.preferences import prefs


def _contrast_with_black(colour):
    """How far <colour>, laid over black, stands out from it: the WCAG
    contrast ratio of the two, from 1 to 21."""
    def linear(channel):
        channel *= colour.alpha
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4
    luminance = (0.2126 * linear(colour.red) + 0.7152 * linear(colour.green)
                 + 0.0722 * linear(colour.blue))
    return (luminance + 0.05) / 0.05


class _Event:

    """Stands in for the observable the backend exposes."""

    def __iadd__(self, handler):
        return self

    def __isub__(self, handler):
        return self


class _Backend:

    book_added = _Event()
    book_added_to_collection = _Event()
    book_cover_changed = _Event()
    book_moved = _Event()

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

    def get_sized_book_cover(self, path, made_for):
        # No cover is kept as it was drawn: each is drawn anew.
        return None

    def keep_sized_book_cover(self, path, pixbuf, made_for, thumbnail):
        pass

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
    #: A library window's cover area: books are dragged, dropped and
    #: searched for.
    manages = True
    window = None


class _Recent:

    """Stands in for the recent files, remembering what they forgot."""

    def __init__(self):
        #: The paths remove_path() was given, in order.
        self.removed = []

    def remove_path(self, path):
        self.removed.append(path)


class _OpenBook(file_actions.FileActions):

    """Stands in for the main window's file handler and file actions:
    the book it has open, and whether its unwritten changes were
    forgotten.  The offer to delete what the trash refused is the real
    one; the library gives its own window as the parent."""

    def __init__(self):
        super().__init__(None)
        self.path = None
        self.forgotten = False

    def get_path_to_base(self):
        return self.path

    def forget_changes(self):
        self.forgotten = True

    def release_archive(self):
        """What the library calls on Windows before it deletes the
        open book."""


class _LibraryWindow(Gtk.Window):

    """A library that is a real window, which a dialog can be transient for."""

    def __init__(self):
        super().__init__()
        self.manages = True
        self.window = self
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
        self.assertTrue(wait_for(lambda: self.area._covers.get_width() > 0))
        self.assertEqual('rgb(0,0,0)', background_of(self.area._covers))

    def test_a_selected_cover_stands_out_from_the_black(self):
        """The theme marks a selected cell with a quarter of its accent
        colour, which is meant for the light or grey ground of a list:
        on black it was rgb(13,33,57), 1.3 to 1 against it, and the book
        picked out was hard to find.  A part of the interface wants 3 to
        1 (WCAG 2.1, 1.4.11)."""
        # libadwaita's rule, which the suite's plain GTK does not load:
        # plain GTK marks the cell in the solid accent colour.
        libadwaita = Gtk.CssProvider()
        libadwaita.load_from_string('gridview > child:selected'
                                    ' { background-color:'
                                    ' rgba(53, 132, 228, 0.25); }')
        display = self.window.get_display()
        Gtk.StyleContext.add_provider_for_display(
            display, libadwaita, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display,
                        display, libadwaita)
        # The rule the area gave the display, on a view of the covers'
        # class with no library behind it to tell about the selection.
        covers = thumbnail_list.ThumbnailGridView()
        self.addCleanup(covers.stop_update)
        covers.add_css_class(book_area._BookArea._BLACK_CSS_CLASS)
        covers.set_thumbnail_size(64)
        covers.generate_thumbnail = lambda uid: None
        self.window.set_child(covers)
        covers.set_items([thumbnail_list.ThumbnailItem(1)])
        self.window.present()
        self.assertTrue(wait_for(
            lambda: next(covers._each_cell(), None) is not None))
        covers.select_positions([0])
        painted = background_of(next(covers._each_cell()).get_parent())
        colour = Gdk.RGBA()
        self.assertTrue(colour.parse(painted or ''), painted)
        self.assertGreaterEqual(_contrast_with_black(colour), 3, painted)

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

    def __init__(self, id, path, size=0, added='2000-01-01', pages=1,
                 format=constants.ZIP):
        self.id = id
        self.path = path
        self.size = size
        self.added = added
        self.pages = pages
        self.format = format


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

    def get_book_thumbnail(self, path, size=constants.MAX_LIBRARY_COVER_SIZE):
        self.asked_for = size
        return thumbnail_tools.Thumbnailer(
            dst_dir=self._store, store_on_disk=True, archive_support=True,
            size=(constants.MAX_LIBRARY_COVER_SIZE,) * 2,
            cover_orientation_required=True).thumbnail(path)


class _KeepingBackend(_CoverBackend):

    """One that keeps each cover as it was drawn, as the library's
    does."""

    def _covers(self):
        return thumbnail_tools.Thumbnailer(dst_dir=self._store)

    def get_sized_book_cover(self, path, made_for):
        return self._covers().sized(path, made_for)

    def keep_sized_book_cover(self, path, pixbuf, made_for, thumbnail):
        self._covers().keep_sized(path, pixbuf, made_for, thumbnail)


class _CoverAreaTest(MComixTest):

    """A book area of its own over a library of one book, whose pages
    are shown as they are read, closed after the test."""

    def _open_area(self, backend):
        """Build self.area over <backend>, with no cover in memory."""
        self.library = _Library()
        self.library.backend = backend
        self.library.main_window = types.SimpleNamespace(
            enhancer=types.SimpleNamespace(enhance=lambda pixbuf: pixbuf))
        self.area = book_area._BookArea(self.library)
        self.area._cache.invalidate_all()

    def _open_over_a_page(self, page, member):
        """Build self.area over a library of self.archive, a book of
        the one picture <page> as <member>, whose covers self.backend
        keeps."""
        self.archive = os.path.join(self.tmp_dir, 'book.cbz')
        with zipfile.ZipFile(self.archive, 'w') as book:
            book.write(page, member)
        self.backend = _KeepingBackend(
            self.archive, os.path.join(self.tmp_dir, 'covers'))
        self._open_area(self.backend)

    def tearDown(self):
        self.area.close()
        self.area._cache.invalidate_all()
        super().tearDown()


class KeptCoverTest(_CoverAreaTest):

    """A cover is kept on disk as it was drawn, and read back as that.

    The cover stored is 500 pixels high, for the largest size there is;
    drawn 125 high it was decoded whole and scaled down, 5 ms a cover,
    for every cover in view each time the program started."""

    def setUp(self):
        super().setUp()
        # Three times the picture's size, its Exif kept: large enough
        # for the cover stored to be 500 pixels across.
        page = os.path.join(self.tmp_dir, '01.jpg')
        with PIL.Image.open(get_testfile_path(
                'images', 'landscape-exif-270-rotation.jpg')) as picture:
            picture.resize((picture.width * 3, picture.height * 3)).save(
                page, exif=picture.info['exif'])
        self._open_over_a_page(page, '01.jpg')
        prefs['library cover size'] = constants.SIZE_NORMAL
        self.first = self.area._get_pixbuf(1)
        # As after a start of the program: nothing in memory.
        self.area._cache.invalidate_all()

    def _again(self):
        """The cover asked for again, and whether the cover stored at
        its largest was read for it."""
        with unittest.mock.patch.object(
                self.backend, 'get_book_thumbnail',
                wraps=self.backend.get_book_thumbnail) as read:
            pixbuf = self.area._get_pixbuf(1)
        return pixbuf, read.called

    def test_it_is_the_cover_drawn_before(self):
        again, read = self._again()
        self.assertFalse(read, 'the cover stored was decoded again')
        self.assertEqual(
            (self.first.get_width(), self.first.get_height()),
            (again.get_width(), again.get_height()))
        self.assertEqual(self.first.get_pixels(), again.get_pixels())

    def test_another_size_is_drawn_from_the_cover_stored(self):
        prefs['library cover size'] = constants.SIZE_LARGE
        again, read = self._again()
        self.assertTrue(read)
        self.assertGreater(again.get_width(), self.first.get_width())
        # And is what is kept from then on.
        self.area._cache.invalidate_all()
        self.assertFalse(self._again()[1])

    def test_none_is_kept_at_the_size_the_cover_is_stored_at(self):
        """Its pixels would weigh about ten times the cover stored, and
        drawing it means little more than decoding that."""
        prefs['library cover size'] = constants.SIZE_HUGE
        self.assertTrue(self._again()[1])
        self.assertEqual(
            [], os.listdir(os.path.join(self.tmp_dir, 'covers_sized')))
        self.area._cache.invalidate_all()
        self.assertTrue(self._again()[1])

    def test_what_the_drawing_depends_on_is_part_of_what_it_was_kept_for(self):
        """The cover is turned as its Exif orientation says only where
        the preference says so, and scaled by the filter chosen."""
        for name, value in (('auto rotate from exif', False),
                            ('scaling quality', 0),
                            ('checkered bg for transparent images', False)):
            with self.subTest(preference=name):
                self.assertNotEqual(value, prefs[name])
                was, prefs[name] = prefs[name], value
                try:
                    self.area._cache.invalidate_all()
                    self.assertTrue(self._again()[1])
                finally:
                    prefs[name] = was
                    self.area._cache.invalidate_all()
                    self._again()

    def test_a_changed_book_has_its_cover_drawn_anew(self):
        later = os.stat(self.archive).st_mtime + 10
        os.utime(self.archive, (later, later))
        self.assertTrue(self._again()[1])

    def test_the_cover_is_read_as_large_as_the_screen_draws_the_largest(self):
        """In the screen's own pixels: on one of twice the scale, the
        largest cover size is drawn twice as many pixels high."""
        largest = preview.scaled(constants.MAX_LIBRARY_COVER_SIZE, self.area)
        self.assertEqual(largest, self.backend.asked_for)
        self.area._covers.device_scale = 2.0
        self.area._cache.invalidate_all()
        self.assertTrue(self._again()[1])
        self.assertEqual(2 * largest, self.backend.asked_for)

    def test_a_cover_that_cannot_be_kept_is_shown_all_the_same(self):
        prefs['library cover size'] = constants.SIZE_NORMAL * 2
        with unittest.mock.patch.object(
                self.backend, 'keep_sized_book_cover',
                side_effect=OSError('no room')), \
            unittest.mock.patch.object(
                self.backend, 'get_sized_book_cover',
                side_effect=OSError('unreadable')):
            again, read = self._again()
        self.assertTrue(read)
        self.assertGreater(again.get_width(), self.first.get_width())

    def test_the_missing_image_is_not_kept(self):
        """It is drawn, not read, and a book whose cover could not be
        read once is tried again."""
        with zipfile.ZipFile(self.archive, 'w') as book:
            book.writestr('01.jpg', b'not an image')
        # Written within the second the first was, by the clock a
        # stored cover goes by.
        later = os.stat(self.archive).st_mtime + 10
        os.utime(self.archive, (later, later))
        directory = os.path.join(self.tmp_dir, 'covers_sized')
        (name,) = os.listdir(directory)
        with open(os.path.join(directory, name), 'rb') as file:
            kept = file.read()
        for _attempt in range(2):
            self.area._cache.invalidate_all()
            self.assertTrue(self._again()[1])
        # What is there is the cover of the book as it was, which is
        # not used for the book as it is.
        with open(os.path.join(directory, name), 'rb') as file:
            self.assertEqual(kept, file.read())
        self.assertEqual([name], os.listdir(directory))


class CoverAtHandTest(_CoverAreaTest):

    """The cover a cell is bound to is handed over at once where the
    memory cache holds it, dressed as a worker dresses it, and only
    then: anything else is read on a worker."""

    def setUp(self):
        super().setUp()
        prefs['library cover size'] = constants.SIZE_NORMAL
        self._open_over_a_page(
            get_testfile_path('images', 'landscape-no-exif.jpg'), '01.jpg')
        self.item = book_area._BookItem(self.backend.get_book_by_id(1))

    def test_it_is_what_the_view_asks_at_bind(self):
        self.assertEqual(self.area._cover_at_hand,
                         self.area._covers.thumbnail_at_hand)

    def test_a_cover_not_in_memory_is_not_read_for_it(self):
        with unittest.mock.patch.object(
                self.backend, 'get_sized_book_cover') as kept, \
            unittest.mock.patch.object(
                self.backend, 'get_book_thumbnail') as read:
            self.assertIsNone(self.area._cover_at_hand(self.item))
        self.assertFalse(kept.called)
        self.assertFalse(read.called)

    def test_a_cover_in_memory_is_the_one_a_worker_hands_over(self):
        made = self.area._get_pixbuf(1)
        at_hand = self.area._cover_at_hand(self.item)
        self.assertIsNotNone(at_hand)
        self.assertEqual((made.get_width(), made.get_height()),
                         (at_hand.get_width(), at_hand.get_height()))
        self.assertEqual(made.get_pixels(), at_hand.get_pixels())
        # Framed, as the cover in the cache is not.
        cached = self.area._cache.get(self.archive)
        self.assertEqual(cached.get_width() + 2, at_hand.get_width())

    def test_a_book_gone_from_the_library_has_no_cover_at_hand(self):
        self.area._get_pixbuf(1)
        with unittest.mock.patch.object(self.backend, 'get_book_by_id',
                                        return_value=None):
            self.assertIsNone(self.area._cover_at_hand(self.item))


class AbsentBookTest(_CoverAreaTest):

    """A book whose file is not there, as on a drive not connected,
    looked like any other in the library until it was opened."""

    def setUp(self):
        super().setUp()
        page = os.path.join(self.tmp_dir, '01.png')
        # In colour, to be seen turned grey.
        PIL.Image.new('RGB', (200, 300), (200, 60, 30)).save(page)
        prefs['library cover size'] = constants.SIZE_NORMAL
        self._open_over_a_page(page, '01.png')
        self.item = book_area._BookItem(self.backend.get_book_by_id(1))
        # Drawn while the file is there: the cover is in memory.
        self.present = self.area._get_pixbuf(1)
        self.away = os.path.join(self.tmp_dir, 'away.cbz')

    @staticmethod
    def _middle(pixbuf):
        return image_tools.pixbuf_to_pil(pixbuf).convert('RGBA').getpixel(
            (pixbuf.get_width() // 2, pixbuf.get_height() // 2))

    @staticmethod
    def _coloured(pixbuf):
        """How many pixels of <pixbuf> are not grey."""
        data = image_tools.pixbuf_to_pil(pixbuf).convert('RGB').tobytes()
        return sum(1 for red, green, blue
                   in zip(data[0::3], data[1::3], data[2::3])
                   if not red == green == blue)

    def test_the_cover_of_a_book_not_there_is_grey_and_faded(self):
        self.assertEqual(255, self._middle(self.present)[3])
        self.assertGreater(self._coloured(self.present), 1000)
        os.rename(self.archive, self.away)
        absent = self.area._get_pixbuf(1)
        self.assertEqual(0, self._coloured(absent))
        self.assertLess(self._middle(absent)[3], 128)

    def test_a_cover_in_memory_is_drawn_as_a_worker_last_found_it(self):
        """A cell is bound on the main thread, which does not look."""
        os.rename(self.archive, self.away)
        self.assertEqual(255, self._middle(
            self.area._cover_at_hand(self.item))[3])
        self.area._get_pixbuf(1)
        self.assertLess(self._middle(
            self.area._cover_at_hand(self.item))[3], 128)
        os.rename(self.away, self.archive)
        self.area._get_pixbuf(1)
        self.assertEqual(255, self._middle(
            self.area._cover_at_hand(self.item))[3])

    def test_showing_the_covers_draws_again_those_whose_files_went(self):
        with unittest.mock.patch.object(
                self.area._covers, 'redraw_item') as redraw:
            self.area._look_for_files([self.item])
            self.assertFalse(wait_for(lambda: redraw.called, seconds=0.3),
                             'a cover drawn as it is was drawn again')
            os.rename(self.archive, self.away)
            self.area._look_for_files([self.item])
            self.assertTrue(wait_for(lambda: redraw.called, seconds=10))
        redraw.assert_called_once_with(self.item)


class TurnedCoverTest(_CoverAreaTest):

    """A cover is drawn turned as the page it is shows when the book is
    read: its Exif orientation, where 'auto rotate from exif' says so."""

    def setUp(self):
        super().setUp()
        archive = os.path.join(self.tmp_dir, 'turned.cbz')
        with zipfile.ZipFile(archive, 'w') as book:
            book.write(get_testfile_path(
                'images', 'landscape-exif-270-rotation.jpg'), '01.jpg')
        self._open_area(_CoverBackend(
            archive, os.path.join(self.tmp_dir, 'covers')))

    def test_the_cover_of_a_turned_page_is_turned(self):
        """The picture is 210 pixels wide and 297 high, and shown the
        other way round; the cover was drawn as it is stored."""
        prefs['auto rotate from exif'] = True
        prefs['library cover size'] = constants.SIZE_NORMAL
        pixbuf = self.area._get_pixbuf(1)
        self.assertGreater(pixbuf.get_width(), pixbuf.get_height())


class UnreadableCoverTest(_CoverAreaTest):

    """A book with no page that will load is shown as the missing image.
    That was the theme's 24 pixel icon scaled up to the size of a
    cover, and came out blurred."""

    def setUp(self):
        super().setUp()
        archive = os.path.join(self.tmp_dir, 'unreadable.cbz')
        with zipfile.ZipFile(archive, 'w') as book:
            book.writestr('01.jpg', b'not an image')
        self._open_area(_CoverBackend(
            archive, os.path.join(self.tmp_dir, 'covers')))

    def test_the_missing_image_is_drawn_at_the_size_of_a_cover(self):
        prefs['library cover size'] = constants.SIZE_NORMAL
        width, height = self.area._pixbuf_size(framed=False)
        icon = image_tools.missing_image_icon(width, height)
        self.assertEqual(width, icon.get_width())

        cover = self.area._get_pixbuf(1)
        # Inside the one pixel frame every cover has by default.
        self.assertEqual((icon.get_width() + 2, icon.get_height() + 2),
                         (cover.get_width(), cover.get_height()))
        drawn = image_tools.pixbuf_to_pil(cover).crop(
            (1, 1, icon.get_width() + 1, icon.get_height() + 1))
        self.assertEqual(image_tools.pixbuf_to_pil(icon).tobytes(),
                         drawn.tobytes())
        self.assertEqual((255, 255, 255, 255),
                         image_tools.pixbuf_to_pil(cover).getpixel((0, 0)))

    def test_the_frame_is_as_wide_as_the_thumbnails_frame(self):
        """The white frame round each cover stood out on the black they
        are shown on; it is the thumbnails' frame, which can be none."""
        prefs['library cover size'] = constants.SIZE_NORMAL
        width, height = self.area._pixbuf_size(framed=False)
        icon = image_tools.missing_image_icon(width, height)
        for frame in (0, 3):
            with self.subTest(frame=frame):
                prefs['thumbnail border width'] = frame
                self.area._cache.invalidate_all()
                cover = self.area._get_pixbuf(1)
                inner =(icon.get_width(), icon.get_height())
                self.assertEqual((inner[0] + 2 * frame, inner[1] + 2 * frame),
                                 (cover.get_width(), cover.get_height()))
                self.assertEqual(
                    tuple(side + 2 * frame for side in
                          self.area._pixbuf_size(framed=False)),
                    self.area._pixbuf_size())
                drawn = image_tools.pixbuf_to_pil(cover).crop(
                    (frame, frame, inner[0] + frame, inner[1] + frame))
                self.assertEqual(image_tools.pixbuf_to_pil(icon).tobytes(),
                                 drawn.tobytes())

    def test_the_tick_of_a_finished_book_leaves_the_cover_as_it_was(self):
        """The cache's covers are drawn again and again, so the tick
        goes on a copy, which without a frame nothing else makes."""
        prefs['library cover size'] = constants.SIZE_NORMAL
        prefs['thumbnail border width'] = 0
        cover = solid_pixbuf(100, 150, 0x336699FF, has_alpha=True)
        before = image_tools.pixbuf_to_pil(cover).tobytes()
        book = unittest.mock.Mock(pages=3)
        book.get_last_read_page.return_value = 3

        dressed = self.area._dressed(book, cover, 1)

        self.assertEqual(before, image_tools.pixbuf_to_pil(cover).tobytes())
        self.assertEqual((100, 150), (dressed.get_width(), dressed.get_height()))
        self.assertNotEqual(before,
                            image_tools.pixbuf_to_pil(dressed).tobytes())


class CoverOrderTest(MComixTest):

    """What order the covers are shown in.

    The view was a Gtk.IconView over a six column Gtk.ListStore, which
    sorted itself by a column number - which is why the SORT_ constants
    had to match the column layout. A Gtk.Sorter is handed the two items
    instead, so the two are no longer tied together.
    """

    BOOKS = (_Book(1, '/b/zeta.cbz', size=30, added='2003', pages=5),
             _Book(2, '/a/alpha.cbz', size=10, added='2001', pages=40),
             _Book(3, '/c/mid.cbz', size=20, added='2002', pages=12))

    def _area_by_name(self, control_area=None):
        """An area of its own over BOOKS, sorted by name and closed
        after the test; <control_area>, where given, is told of every
        change of selection."""
        prefs['lib sort key'] = constants.SORT_NAME
        prefs['lib sort order'] = constants.SORT_ASCENDING
        # Held here: an area holds its library window only weakly.
        self.library = _Library()
        if control_area is not None:
            self.library.control_area = control_area
        area = book_area._BookArea(self.library)
        self.addCleanup(area.close)
        area._covers.set_items(
            book_area._BookItem(book) for book in self.BOOKS)
        area.set_sort_order()
        return area

    def _order(self, key, ascending=True, read=None, books=None):
        prefs['lib sort key'] = key
        prefs['lib sort order'] = (constants.SORT_ASCENDING if ascending
                                   else constants.SORT_DESCENDING)
        self.library = _Library()
        area = book_area._BookArea(self.library)
        items = [book_area._BookItem(book) for book in books or self.BOOKS]
        for item in items:
            item.read = (read or {}).get(item.uid)
        area._covers.set_items(items)
        area.set_sort_order()
        order = [item.uid for item in area._covers.each_item()]
        # The order display_covers() hands the covers over in, for the
        # sorter to find them sorted already: GTK's sort then compares
        # each cover once, where a library of 10000 books in the
        # database's order took 58409 calls into Python.
        self.assertEqual(order, [item.uid for item in area._in_order(items)])
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

    def test_by_pages(self):
        self.assertEqual(self._order(constants.SORT_PAGES), [1, 3, 2])

    def _files_changed_at(self, *times):
        """Three books whose files were last changed at <times>, the
        third's file missing when its time is None."""
        books = []
        for uid, when in enumerate(times, 1):
            path = os.path.join(self.tmp_dir, 'book%d.cbz' % uid)
            if when is not None:
                with open(path, 'wb'):
                    pass
                os.utime(path, (when, when))
            books.append(_Book(uid, path))
        return books

    def test_by_the_date_the_file_was_modified(self):
        """Not the date the book was added: the file's own date."""
        books = self._files_changed_at(2_000_000_000, 1_000_000_000,
                                       1_500_000_000)
        self.assertEqual(
            self._order(constants.SORT_FILE_MODIFIED, books=books),
            [2, 3, 1])
        self.assertEqual(
            self._order(constants.SORT_FILE_MODIFIED, ascending=False,
                        books=books),
            [1, 3, 2])

    def test_a_book_whose_file_is_gone_comes_last_either_way(self):
        books = self._files_changed_at(2_000_000_000, None, 1_000_000_000)
        self.assertEqual(
            self._order(constants.SORT_FILE_MODIFIED, books=books),
            [3, 1, 2])
        self.assertEqual(
            self._order(constants.SORT_FILE_MODIFIED, ascending=False,
                        books=books),
            [1, 3, 2])

    def test_by_last_read_newest_first_descending(self):
        read = {1: '2026-10-01 10:00:00', 2: '2026-10-29 09:00:00'}
        self.assertEqual(
            self._order(constants.SORT_LAST_READ, ascending=False, read=read),
            [2, 1, 3])

    def test_a_book_never_read_comes_last_either_way(self):
        read = {1: '2026-10-01 10:00:00', 2: '2026-10-29 09:00:00'}
        self.assertEqual(
            self._order(constants.SORT_LAST_READ, read=read), [1, 2, 3])

    def test_descending_is_the_other_way_round(self):
        self.assertEqual(self._order(constants.SORT_SIZE, ascending=False),
                         [1, 3, 2])

    def test_the_menu_sorts_the_covers_again(self):
        """The popup menu's "Sort by" and ascending/descending choices
        are one stateful action each; picking one keeps the choice and
        puts the covers on show in the new order."""
        area = self._area_by_name()

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


    def test_the_covers_selected_stay_selected_in_the_new_order(self):
        """A sort from the menu hands the covers over again, in the new
        order, for GTK's sort to find them sorted: 10000 books took 81
        ms to sort by name, 45 since.  The selection goes with the
        covers, not with the places they were at."""
        # Told of every change of selection.
        area = self._area_by_name(control_area=_ControlArea())
        # alpha, mid, zeta: zeta and alpha selected.
        area._covers.select_positions([0, 2])
        prefs['lib sort key'] = constants.SORT_PATH
        area.set_sort_order()
        self.assertEqual([2, 1, 3],
                         [item.uid for item in area._covers.each_item()])
        self.assertEqual(
            [2, 1], [item.uid for item in area._covers.get_selected_items()])

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
        self.assertEqual(1, sum(1 for child in children(dialogs[0].get_content_area())
                                if isinstance(child, Gtk.Scale)))


    def _answer_custom(self, value, response):
        """Pick "Custom", move its scale to <value> and answer the dialog
        with <response>; give back the action the menu shows."""
        action = self._Action()
        self.area._book_size_changed(action, GLib.Variant('i', 0))
        dialog = self._opened_dialogs()[0]
        scale = next(child for child in children(dialog.get_content_area())
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

    manages = True
    window = None

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
        for dialog in prompts_over(self.library):
            dialog.destroy()
        self.library.destroy()
        self.area.close()
        super().tearDown()

    def test_it_defaults_to_the_answer_that_deletes_nothing(self):
        """The books go from the disk as well as from the library, so
        Enter must not be what does it."""
        self.area._completely_remove_book()
        dialogs = prompts_over(self.library)
        self.assertEqual(1, len(dialogs), 'nothing asked before deleting')
        dialog = dialogs[0]
        keeps = dialog.get_widget_for_response(Response.NO)
        deletes = dialog.get_widget_for_response(Response.YES)
        self.assertIsNotNone(keeps, 'the dialog offers no way out')
        self.assertIs(dialog.get_default_widget(), keeps,
                      'Enter would delete the books')
        self.assertTrue(deletes.has_css_class('suggested-action'),
                        'the deleting button is drawn as an ordinary one')
        self.assertFalse(deletes.has_css_class('destructive-action'),
                         'what goes to the trash is drawn as lost for good')

    def _deletable(self):
        """A file that is no book, deletable.cbz in the test's folder,
        shown as the one cover and selected."""
        path = os.path.join(self.tmp_dir, 'deletable.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'not really a book')
        self.area._covers.set_items([book_area._BookItem(_Book(1, path))])
        self.area._covers.selection.select_all()
        return path

    def _asked_where_the_trash_refuses(self):
        with unittest.mock.patch.object(book_area.tools, 'trash_refuses',
                                        return_value=True):
            self.area._completely_remove_book()
            pump()
        dialogs = prompts_over(self.library)
        self.assertEqual(1, len(dialogs), 'nothing asked before deleting')
        return dialogs[0]

    def test_where_the_trash_refuses_it_asks_to_delete_for_good(self):
        """It asked to move the books to the trash, and offered to
        delete them for good only once the trash had refused."""
        self._deletable()
        dialog = self._asked_where_the_trash_refuses()
        self.assertEqual('The selected books will be removed from the '
                         'library. Any in a folder with no trash is deleted '
                         'permanently and cannot be restored.',
                         dialog._secondary.get_text())
        keeps = dialog.get_widget_for_response(Response.CANCEL)
        deletes = dialog.get_widget_for_response(Response.OK)
        self.assertEqual(('_Cancel', '_Delete Permanently'),
                         (keeps.get_label(), deletes.get_label()))
        self.assertIs(dialog.get_default_widget(), keeps,
                      'Enter would delete the books')
        self.assertTrue(deletes.has_css_class('destructive-action'))
        self.assertIsNone(dialog.dialog_id,
                          'the answer could be given for good')

    def test_where_the_trash_refuses_yes_deletes_without_trying_it(self):
        path = self._deletable()
        dialog = self._asked_where_the_trash_refuses()
        with unittest.mock.patch.object(book_area.tools, 'trash_refuses',
                                        return_value=True), \
                unittest.mock.patch.object(book_area.tools,
                                           'move_to_trash') as trash:
            dialog.get_widget_for_response(Response.OK).emit('clicked')
            pump()
        trash.assert_not_called()
        self.assertFalse(os.path.exists(path))
        self.assertEqual([], prompts_over(self.library),
                         'a second question followed the first')
        self.assertIn(path, self.library.recent.removed)

    def test_shift_delete_asks_to_delete_for_good(self):
        """As in a file manager and the main window: the library had no
        way to delete a book without the trash."""
        path = self._deletable()
        self.assertEqual(Gdk.EVENT_STOP, self.area._key_press(
            None, Gdk.KEY_Delete, 0, Gdk.ModifierType.SHIFT_MASK))
        pump()
        dialogs = prompts_over(self.library)
        self.assertEqual(1, len(dialogs), 'nothing asked before deleting')
        dialog = dialogs[0]
        self.assertEqual('Delete "deletable.cbz" permanently?',
                         dialog._primary.get_text())
        keeps = dialog.get_widget_for_response(Response.CANCEL)
        self.assertIs(dialog.get_default_widget(), keeps,
                      'Enter would delete the books')
        self.assertIsNone(dialog.dialog_id,
                          'the answer could be given for good')
        with unittest.mock.patch.object(book_area.tools,
                                        'move_to_trash') as trash:
            dialog.get_widget_for_response(Response.OK).emit('clicked')
            pump()
        trash.assert_not_called()
        self.assertFalse(os.path.exists(path))
        self.assertIn(path, self.library.recent.removed)

    def test_delete_permanently_names_how_many_books(self):
        self.area._covers.set_items(
            [book_area._BookItem(_Book(1, '/books/1.cbz')),
             book_area._BookItem(_Book(2, '/books/2.cbz'))])
        self.area._covers.selection.select_all()
        self.area.delete_permanently()
        pump()
        dialog, = prompts_over(self.library)
        self.assertEqual('Delete 2 books permanently?',
                         dialog._primary.get_text())
        dialog.get_widget_for_response(Response.CANCEL).emit('clicked')
        pump()
        self.assertEqual([], self.library.backend.removed,
                         'Cancel took the books out of the library')

    def test_a_remembered_yes_still_asks_where_the_trash_refuses(self):
        """The answer given for good was to move books to the trash."""
        prefs['stored dialog choices'][message_dialog.RememberedDialog
                                       .LIBRARY_REMOVE_BOOK_FROM_DISK] = \
            Response.YES
        self.addCleanup(prefs['stored dialog choices'].pop,
                        message_dialog.RememberedDialog
                        .LIBRARY_REMOVE_BOOK_FROM_DISK)
        path = self._deletable()
        self._asked_where_the_trash_refuses()
        self.assertTrue(os.path.isfile(path), 'the book went unasked')


    def test_on_windows_the_open_book_lets_go_of_its_archive_first(self):
        """Windows neither trashes nor deletes a file that is open, and
        the main window holds the open book's archive open until every
        member is out: the trash refused it, and then the delete for
        good the reader was offered.  The window's own delete lets go of
        the archive first; the library's did not."""
        path = self._deletable()
        released = []
        self.library.open_book.path = path
        self.library.open_book.release_archive = \
            lambda: released.append(os.path.exists(path))
        with unittest.mock.patch.object(book_area.sys, 'platform', 'win32'):
            self.area._remove_answered(Response.YES)
        pump()
        self.assertEqual([True], released,
                         'the archive was not let go of before it went')

    def test_a_book_that_is_not_open_leaves_the_open_one_alone(self):
        path = self._deletable()
        self.library.open_book.path = os.path.join(self.tmp_dir, 'other.cbz')
        released = []
        self.library.open_book.release_archive = lambda: released.append(path)
        with unittest.mock.patch.object(book_area.sys, 'platform', 'win32'):
            self.area._remove_answered(Response.YES)
        pump()
        self.assertEqual([], released)

    def test_a_book_that_could_not_be_deleted_from_disk_says_so(self):
        """The book leaves the library before the file goes to the
        trash, so a move that fails is the only thing that can tell the
        reader the file is still there.  The fixture's path is not a
        file, so the trash refuses it as it would a file on a file
        system with no trash."""
        self.area._remove_answered(Response.YES)
        pump()
        offers = prompts_over(self.library)
        self.assertEqual(1, len(offers), 'nothing was offered')
        offers[0].get_widget_for_response(Response.CANCEL).emit('clicked')
        pump()
        self.assertTrue(self.library.messages, 'the library said nothing')
        self.assertEqual('1 book could not be moved to the trash.',
                         self.library.messages[-1])

    def test_a_book_the_trash_refuses_can_be_deleted_for_good(self):
        """GLib keeps no trash on a bind-mounted folder, and the library
        could then only say the book had not gone."""
        path = self._deletable()

        def refuse(path):
            raise GLib.Error('Trashing on system internal mounts is not '
                             'supported')

        with unittest.mock.patch.object(book_area.tools, 'move_to_trash',
                                        refuse):
            self.area._remove_answered(Response.YES)
        pump()
        offers = prompts_over(self.library)
        self.assertEqual(1, len(offers), 'nothing was offered')
        self.assertTrue(os.path.isfile(path), 'the book went unasked')
        self.assertEqual('Could not move "deletable.cbz" to the trash',
                         offers[0]._primary.get_text())
        offers[0].get_widget_for_response(Response.OK).emit('clicked')
        pump()
        self.assertFalse(os.path.exists(path))
        self.assertEqual([], [message for message in self.library.messages
                              if 'trash' in message])
        self.assertIn(path, self.library.recent.removed)

    def _bookmark_store(self):
        # MComixTest redirects DATA_DIR without creating it, and the
        # store writes its file as soon as a bookmark is added.
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        return bookmark_backend.BookmarksStore

    def _bookmark(self, path):
        return bookmark_menu_item._Bookmark(
            None, None, os.path.basename(path), path, 2, 20, None,
            datetime.datetime(2026, 1, 1))

    def test_deleting_a_bookmarked_book_asks_about_its_bookmarks(self):
        """The window's own delete asks; the library deleted the file
        and left the bookmark pointing at nothing."""
        path = self._deletable()
        store = self._bookmark_store()
        store.add_bookmark(self._bookmark(path))

        self.area._remove_answered(Response.YES)
        pump()

        dialogs = [window for window in prompts_over(self.library)
                   if window.dialog_id == message_dialog.RememberedDialog
                   .REMOVE_BOOKMARKS_OF_DELETED_FILE]
        self.assertEqual(len(dialogs), 1, 'nothing asked about the bookmark')
        self.assertEqual(len(store.get_bookmarks()), 1,
                         'the bookmark went without being asked about')
        dialogs[0].emit('response', Response.YES)
        pump()
        self.assertEqual(store.get_bookmarks(), [])

    def test_deleting_a_book_nobody_bookmarked_asks_nothing(self):
        self._deletable()
        self._bookmark_store()

        self.area._remove_answered(Response.YES)
        pump()

        self.assertEqual(prompts_over(self.library), [])

    def test_a_book_that_was_deleted_says_nothing_of_the_kind(self):
        path = self._deletable()

        self.area._remove_answered(Response.YES)

        self.assertFalse(os.path.exists(path))
        self.assertTrue(all('could not be moved' not in message
                            for message in self.library.messages),
                        self.library.messages)

    def test_a_deleted_book_goes_to_the_trash(self):
        """It was removed for good (upstream feature request 107)."""
        self._deletable()

        self.area._remove_answered(Response.YES)

        self.assertEqual(['deletable.cbz'],
                         [name.split('-', 1)[1]
                          for name in os.listdir(self.trash_dir)])

    def _volume_set_selected(self):
        """The three volumes of Multivolume.rar in a folder of their
        own, the first selected as the book; the folder."""
        folder = os.path.join(self.tmp_dir, 'set')
        first = copy_rar_set(folder)[0]
        self.area._covers.set_items([book_area._BookItem(_Book(1, first))])
        self.area._covers.selection.select_all()
        return folder

    def test_a_deleted_rar_set_goes_to_the_trash_whole(self):
        """The later volumes are not books of the library, nor listed
        anywhere else: left behind, they were never seen again."""
        folder = self._volume_set_selected()
        self.area._remove_answered(Response.YES)
        self.assertEqual([], os.listdir(folder))
        self.assertEqual(['Set.part1.rar', 'Set.part2.rar', 'Set.part3.rar'],
                         sorted(name.split('-', 1)[1]
                                for name in os.listdir(self.trash_dir)))

    def test_a_rar_set_deleted_for_good_goes_whole(self):
        folder = self._volume_set_selected()
        self.area._remove_answered(Response.YES, permanently=True,
                                   everything=True)
        self.assertEqual([], os.listdir(folder))

    def test_a_deleted_book_leaves_the_recent_files(self):
        """The window's own delete forgets the path there; the library
        deleted the file and the recent files went on offering it."""
        path = self._deletable()

        self.area._remove_answered(Response.YES)

        self.assertEqual([path], self.library.recent.removed)

    def test_deleting_the_open_book_forgets_its_unwritten_changes(self):
        """Otherwise closing it offers to write the archive back where
        it was just deleted from, and Enter there saves."""
        path = self._deletable()
        self.library.open_book.path = path

        self.area._remove_answered(Response.YES)

        self.assertTrue(self.library.open_book.forgotten)

    def test_deleting_another_book_keeps_the_open_ones_changes(self):
        self._deletable()
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

    def test_the_keypad_delete_does_it_too(self):
        area, library = self._area(refuse=False)
        self.assertEqual(Gdk.EVENT_STOP, area._key_press(
            None, Gdk.KEY_KP_Delete, 0, Gdk.ModifierType(0)))
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

    manages = True
    window = None

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

    def setUp(self):
        super().setUp()
        #: Every library an area was made over: an area holds its
        #: library only weakly, and is closed when the test is over.
        self.libraries = []

    def _area(self, books):
        self.library = _CoverlessLibrary()
        self.libraries.append(self.library)
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

    def _dragged_from(self, area, position):
        """What a drag beginning over the cover at <position> offers,
        or None if it offers nothing."""
        with unittest.mock.patch.object(
                Gdk.ContentProvider, 'new_for_value',
                wraps=Gdk.ContentProvider.new_for_value) as made, \
                unittest.mock.patch.object(area._covers, 'position_at',
                                           return_value=position):
            if area._drag_prepare(None, 5.0, 5.0) is None:
                return None
        return made.call_args.args[0]

    def test_a_drag_from_a_cover_not_selected_is_of_that_cover(self):
        """GTK selects a cover when the button is let go, not when it
        is pressed: with nothing selected the drag offered nothing, and
        with other covers selected it took those and left the one under
        the pointer behind."""
        area = self._area(3)
        area._covers.unselect_all()
        self.assertEqual('%s:1' % constants.LIBRARY_DRAG_BOOKS,
                         self._dragged_from(area, 1))
        self.assertEqual([1], area._covers.get_selected_positions())
        self.assertEqual('%s:2' % constants.LIBRARY_DRAG_BOOKS,
                         self._dragged_from(area, 2))
        self.assertEqual([2], area._covers.get_selected_positions())

    def test_a_drag_from_a_selected_cover_takes_the_others_along(self):
        area = self._area(3)
        self.assertEqual('%s:0,1,2' % constants.LIBRARY_DRAG_BOOKS,
                         self._dragged_from(area, 1))
        self.assertEqual([0, 1, 2], area._covers.get_selected_positions())

    def test_a_drag_from_between_the_covers_is_of_the_selection(self):
        area = self._area(3)
        area._covers.select_only(2)
        self.assertEqual('%s:2' % constants.LIBRARY_DRAG_BOOKS,
                         self._dragged_from(area, -1))
        area._covers.unselect_all()
        self.assertIsNone(self._dragged_from(area, -1))

    def test_a_cover_a_pixel_across_still_has_an_icon(self):
        """Half of one pixel is none, and a pixbuf cannot be scaled to
        no width: the icon was not made and the drag began with an
        AssertionError.  A page a pixel across has such a cover."""
        for width, height in ((1, 1), (1, 300), (300, 1)):
            for books in (1, 3):
                with self.subTest(width=width, height=height, books=books):
                    thin = solid_pixbuf(width, height, 0x336699FF,
                                        has_alpha=True)
                    with unittest.mock.patch.object(
                            _CoverlessBackend, 'get_book_cover',
                            return_value=thin):
                        icons = self._icon_for(books)
                    self.assertEqual(1, len(icons))
                    self.assertIsInstance(icons[0], Gdk.Texture)

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

    manages = True
    window = None

    def __init__(self):
        self.backend = _PathBackend()
        self.control_area = _ControlArea()


class _AreaOnScreenTest(MComixTest):

    """self.area, a book area the test builds, shown in a window of its
    own; its menu, the area and the window are closed after the test."""

    def _present(self, size=None):
        self.window = self.window_holding(self.area, size)

    def tearDown(self):
        self.area._book_menu.popdown()
        self.area.close()
        super().tearDown()


class _FourCoversTest(_AreaOnScreenTest):

    """Four covers of _PathLibrary's books, in a window 600 by 400 and
    laid out, so that a point can be turned into a cover's position.
    The thumbnailer thread starts as soon as there are items, and parks
    on a condition if nobody stops it: tearDown closes the area."""

    def setUp(self):
        super().setUp()
        self.library = _PathLibrary()
        self.area = book_area._BookArea(self.library)
        self.area._covers.set_items(
            book_area._BookItem(_Book(index, '/books/%d.cbz' % index))
            for index in range(4))
        self._present((600, 400))
        self.assertTrue(wait_for(
            lambda: self.area._covers.position_at(60, 60) >= 0))


class SelectBooksTest(_FourCoversTest):

    """The covers' "Select books" submenu picks out the books on show
    that need the same thing done to them."""

    def _popped_up(self):
        self.library.collection_area = _CollectionArea()
        self.library.main_window = _main_window()
        with unittest.mock.patch.object(book_area.widgets, 'popup_at'):
            self.area._popup_book_menu()

    def _activate(self, name):
        self.area._popup_actions.lookup_action(name).activate(None)
        return self.area._covers.get_selected_positions()

    def test_books_with_no_pages_are_selected_and_nothing_else(self):
        """An archive of videos the library added before it refused
        such books could only be found by its empty cover."""
        self.area._covers.get_item(1).pages = 0
        self.area._covers.get_item(3).pages = 0
        self.area._covers.select_positions([0, 2])
        self._popped_up()
        self.assertTrue(self.area._popup_actions.lookup_action(
            'select-no-pages').get_enabled())
        self.assertEqual([1, 3], list(self._activate('select-no-pages')))

    def test_it_is_not_offered_where_every_book_has_pages(self):
        self._popped_up()
        self.assertFalse(self.area._popup_actions.lookup_action(
            'select-no-pages').get_enabled())

    def test_all_books(self):
        self.assertEqual([0, 1, 2, 3], list(self._activate('select-all')))

    def test_books_whose_file_is_not_there(self):
        """Looked for when picked, not only the covers drawn faded."""
        for index in range(4):
            path = os.path.join(self.tmp_dir, '%d.cbz' % index)
            self.area._covers.get_item(index).path = path
            if index in (0, 3):
                shutil.copy2(NORMAL_ZIP, path)
        self.assertEqual([1, 2], list(self._activate('select-absent')))


class StorePagesAsWebpEntryTest(_FourCoversTest):

    def test_offered_only_for_a_book_mcomix_can_write_back(self):
        """A PDF, or a RAR where no rar is installed, would only be
        counted as left alone after the question and the pass."""
        self.library.collection_area = _CollectionArea()
        self.library.main_window = _main_window()
        actions = [self.area._popup_actions.lookup_action(name)
                   for name in ('store-webp', 'shrink-pages')]
        self.area._covers.get_item(0).format = constants.PDF
        self.area._covers.get_item(1).format = constants.RAR
        with unittest.mock.patch.object(book_area.widgets, 'popup_at'), \
                unittest.mock.patch.object(
                    book_area.archive_packer, 'rar_executable',
                    return_value=None):
            for selected, offered in (([0], False), ([0, 1], False),
                                      ([0, 1, 2], True), ([3], True),
                                      ([], False)):
                with self.subTest(selected=selected):
                    self.area._covers.select_positions(selected)
                    self.area._popup_book_menu()
                    self.assertEqual([offered, offered],
                                     [action.get_enabled()
                                      for action in actions])

    def test_it_has_a_section_of_its_own(self):
        """It writes every book selected again; it sat among Rename and
        Properties, which only name or describe one.  "Shrink oversized
        pages" beside it does too, and "Find duplicates" goes through
        many books."""
        model = self.area._book_menu.get_menu_model()
        sections = [model.get_item_link(index, Gio.MENU_LINK_SECTION)
                    for index in range(model.get_n_items())]
        actions = [[section.get_item_attribute_value(
                        index, 'action', None).get_string()
                    for index in range(section.get_n_items())
                    if section.get_item_attribute_value(
                        index, 'action', None) is not None]
                   for section in sections if section is not None]
        self.assertIn(['books.store-webp', 'books.shrink-pages',
                       'books.find-duplicates'], actions)


class BooksOnShowEntriesTest(_FourCoversTest):

    """"Find duplicates..." and "Select books > Books that cannot be
    read in full..." look among the books on show, so they are offered
    whatever is selected, where any are shown."""

    ACTIONS = ('find-duplicates', 'select-unreadable')

    def test_offered_where_books_are_shown(self):
        self.library.collection_area = _CollectionArea()
        self.library.main_window = _main_window()
        actions = [self.area._popup_actions.lookup_action(name)
                   for name in self.ACTIONS]
        with unittest.mock.patch.object(book_area.widgets, 'popup_at'):
            self.area._covers.select_positions([])
            self.area._popup_book_menu()
            self.assertEqual([True, True],
                             [action.get_enabled() for action in actions])
            self.area._covers.remove_items(list(self.area._each_item()))
            self.area._popup_book_menu()
            self.assertEqual([False, False],
                             [action.get_enabled() for action in actions])

    def test_the_check_is_in_select_books(self):
        def submenus(model):
            for index in range(model.get_n_items()):
                label = model.get_item_attribute_value(index, 'label', None)
                links = model.iterate_item_links(index)
                while links.next():
                    if links.get_name() == 'submenu':
                        yield label.get_string(), links.get_value()
                    yield from submenus(links.get_value())

        select, = [menu for label, menu in
                   submenus(self.area._book_menu.get_menu_model())
                   if label == 'Select books']
        self.assertEqual(
            'books.select-unreadable',
            select.get_item_attribute_value(
                select.get_n_items() - 1, 'action', None).get_string())


class MiddleClickTest(_FourCoversTest):

    """The middle button over a cover opens that book on its own.

    It means here what it means in the recent and bookmark menus: the
    book goes into an MComix of its own and neither the book being read
    nor the library window moves. The cover under the pointer is what it
    acts on, so the coordinates have to be turned into a position, which
    needs the view laid out - hence the window.
    """

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

    def test_the_menu_entry_opens_the_book_selected_so(self):
        self.area._covers.select_only(2)
        with unittest.mock.patch.object(process, 'launch_mcomix') as launch:
            self.area.open_selected_book_in_new_window()
        launch.assert_called_once_with('/books/2.cbz')

    def test_the_menu_entry_leaves_a_book_without_a_path_alone(self):
        self.area._covers.select_only(2)
        self.library.backend.missing = self.area.get_book_at_path(2)
        with unittest.mock.patch.object(process, 'launch_mcomix') as launch:
            self.area.open_selected_book_in_new_window()
        launch.assert_not_called()

    def test_the_menu_offers_it_for_one_book_only(self):
        # One MComix per book picked out would start as many programs
        # as covers were selected, at one click.
        self.library.collection_area = _CollectionArea()
        self.library.main_window = _main_window()
        action = self.area._popup_actions.lookup_action('open-new-window')
        with unittest.mock.patch.object(book_area.widgets, 'popup_at'):
            self.area._covers.select_only(1)
            self.area._popup_book_menu()
            self.assertTrue(action.get_enabled())
            self.area._covers.selection.select_all()
            self.area._popup_book_menu()
            self.assertFalse(action.get_enabled())
            self.area._covers.selection.unselect_all()
            self.area._popup_book_menu()
            self.assertFalse(action.get_enabled())


class _FilteredLibrary:

    """A library showing all books through <filter_string>."""

    manages = True
    window = None
    backend = _Backend()

    def __init__(self, filter_string,
                 read_state=backend_types.ReadState.ANY):
        self.filter_string = filter_string
        self.read_state = read_state
        self.collection_area = self

    def get_current_collection(self):
        return constants.COLLECTION_ALL


class NewBookUnderAFilterTest(MComixTest):

    """A book added while the covers are filtered is drawn if the filter
    lets it through - by name or by path, as the covers drawn from the
    database are."""

    def _drawn(self, filter_string, name, path,
               read_state=backend_types.ReadState.ANY):
        library = _FilteredLibrary(filter_string, read_state)
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

    def test_a_new_book_is_unread(self):
        """A book just added was never opened: it belongs among all
        books and the unread ones, not the started or finished ones."""
        states = backend_types.ReadState
        for state, drawn in ((states.ANY, True), (states.UNREAD, True),
                             (states.STARTED, False),
                             (states.FINISHED, False)):
            with self.subTest(state=state):
                self.assertEqual(drawn, self._drawn(
                    'batman', 'Batman 01', '/books/Batman 01.cbz', state))

    def test_a_name_that_matches_in_another_script(self):
        self.assertTrue(self._drawn(
            '\u0432\u043e\u0439\u043d\u0430', '\u0412\u043e\u0439\u043d\u0430 01',
            '/books/\u0412\u043e\u0439\u043d\u0430 01.cbz'))

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


def _main_window(**more):
    """A main window as far as the covers' menu reads it: the recent
    files "Move to" offers the folders of."""
    return types.SimpleNamespace(uimanager=types.SimpleNamespace(
        recent=types.SimpleNamespace(paths=lambda: [])), **more)


class _MenuLibrary:

    manages = True
    window = None
    backend = _Backend()
    collection_area = _CollectionArea()
    main_window = _main_window()


class MenuKeyTest(_AreaOnScreenTest):

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
        self._present((400, 300))

    def _press(self, keyval, state):
        return self.area._key_press(None, keyval, 0, state)

    def test_both_keys_open_the_menu(self):
        hold_open(self.area._book_menu)
        for keyval, state in ((Gdk.KEY_Menu, Gdk.ModifierType(0)),
                              (Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK)):
            self.assertFalse(self.area._book_menu.get_visible())
            self.assertEqual(Gdk.EVENT_STOP, self._press(keyval, state))
            self.assertTrue(wait_for(self.area._book_menu.get_visible),
                            'the menu did not open for %s'
                            % Gdk.keyval_name(keyval))
            self.area._book_menu.popdown()

    def test_f10_on_its_own_is_left_to_gtk(self):
        self.assertEqual(Gdk.EVENT_PROPAGATE,
                         self._press(Gdk.KEY_F10, Gdk.ModifierType(0)))
        self.assertFalse(self.area._book_menu.get_visible())

    def test_control_c_copies_the_selected_book(self):
        """The menu's "Copy" had no key; CTRL+C is the one every
        file manager gives it."""
        with unittest.mock.patch.object(self.area, '_copy_selected') \
                as copied, unittest.mock.patch.object(
                    self.area, '_type_into_search') as typed:
            self.assertEqual(Gdk.EVENT_STOP, self._press(
                Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK))
            # A plain c begins a search instead.
            self._press(Gdk.KEY_c, Gdk.ModifierType(0))
        copied.assert_called_once_with()
        typed.assert_called_once_with(Gdk.KEY_c, Gdk.ModifierType(0))

    def test_the_menu_shows_the_keys_the_area_answers(self):
        accels = menu_keys(self.area._book_menu.get_menu_model())
        self.assertEqual({'books.open-by-hand': '<Control>Return',
                          'books.remove-from-collection': 'Delete',
                          'books.delete-permanently': '<Shift>Delete',
                          'books.copy-to-clipboard': '<Control>c',
                          'books.rename': 'F2',
                          'books.properties': '<Alt>Return'}, accels)


class OpenAndClickTest(_AreaOnScreenTest):

    """Opening the books picked out, with the library left open or not,
    and what a right click picks out before the menu opens."""

    class _Gesture:

        def get_widget(self):
            return None

    def setUp(self):
        super().setUp()
        # Held here: an area holds its library window only weakly.
        self.library = _MenuLibrary()
        self.library.control_area = _ControlArea()
        self.opened = []
        #: Each open's among_shown, beside self.opened.
        self.among_shown = []
        self.library.open_book = (
            lambda books, keep_library_open, among_shown=True: (
                self.opened.append((books, keep_library_open)),
                self.among_shown.append(among_shown)))
        self.area = book_area._BookArea(self.library)
        self.area._covers.set_items(
            book_area._BookItem(_Book(index, '/books/%d.cbz' % index))
            for index in range(3))
        self._present()

    def test_the_books_picked_out_open_with_the_library_closing(self):
        self.area._covers.select_only(1)
        self.area.open_selected_book()
        self.assertEqual([([1], False)], self.opened)

    def test_enter_on_one_of_several_picked_out_opens_them_all(self):
        self.area._covers.selection.select_all()
        self.area._covers.emit('activate', 1)
        self.assertEqual([([0, 1, 2], False)], self.opened)

    def test_enter_on_a_cover_not_picked_out_opens_that_one(self):
        self.area._covers.select_only(2)
        self.area._covers.emit('activate', 0)
        self.assertEqual([([0], False)], self.opened)

    def test_or_among_its_folder_s_books_as_ctrl_enter_does(self):
        self.area._covers.select_only(1)
        self.area.open_selected_book_by_hand()
        self.assertEqual([([1], False)], self.opened)
        self.assertEqual([False], self.among_shown)

    class _DoubleClick:

        """Stands in for the gesture that hears the covers' clicks
        first, as one pressed with <state> held."""

        def __init__(self, state):
            self.state = state
            self.claimed = False

        def get_current_event_state(self):
            return self.state

        def set_state(self, state):
            self.claimed = state == Gtk.EventSequenceState.CLAIMED

    def _double_click(self, state, n_press=2, position=2):
        gesture = self._DoubleClick(state)
        with unittest.mock.patch.object(self.area._covers, 'position_at',
                                        return_value=position):
            self.area._control_double_click(gesture, n_press, 5.0, 5.0)
        return gesture

    def test_ctrl_and_a_double_click_open_the_cover_as_ctrl_enter_does(self):
        self.area._covers.select_only(0)
        gesture = self._double_click(Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual([([2], False)], self.opened)
        self.assertEqual([False], self.among_shown)
        # Claimed, so the covers do not open it once more among those
        # shown.
        self.assertTrue(gesture.claimed)

    def test_other_double_clicks_are_left_to_the_covers(self):
        for state, n_press, position in (
                (Gdk.ModifierType(0), 2, 2),
                (Gdk.ModifierType.CONTROL_MASK, 1, 2),
                (Gdk.ModifierType.CONTROL_MASK
                 | Gdk.ModifierType.SHIFT_MASK, 2, 2),
                (Gdk.ModifierType.CONTROL_MASK, 2, -1)):
            gesture = self._double_click(state, n_press, position)
            self.assertFalse(gesture.claimed)
        self.assertEqual([], self.opened)

    def test_or_with_it_left_open(self):
        self.area._covers.select_only(2)
        self.area.open_selected_book_noclose()
        self.assertEqual([([2], True)], self.opened)

    def test_nothing_picked_out_opens_nothing(self):
        self.area._covers.selection.unselect_all()
        self.area.open_selected_book()
        self.assertEqual([], self.opened)

    def test_a_right_click_picks_out_the_cover_under_it(self):
        hold_open(self.area._book_menu)
        self.area._covers.select_only(0)
        with unittest.mock.patch.object(self.area._covers, 'position_at',
                                        return_value=2):
            self.area._button_press(self._Gesture(), 1, 5.0, 5.0)
        self.assertEqual([2], self.area._covers.get_selected_positions())
        self.assertTrue(wait_for(self.area._book_menu.get_visible))

    def test_a_right_click_on_one_already_picked_keeps_the_others(self):
        hold_open(self.area._book_menu)
        self.area._covers.selection.select_all()
        with unittest.mock.patch.object(self.area._covers, 'position_at',
                                        return_value=1):
            self.area._button_press(self._Gesture(), 1, 5.0, 5.0)
        self.assertEqual([0, 1, 2], self.area._covers.get_selected_positions())


def assert_offered_once_a_book_is_selected(test, area, name):
    """<area>'s book menu has its <name> entry off while nothing is
    selected, and on once every book is."""
    action = area._popup_actions.lookup_action(name)
    with unittest.mock.patch.object(book_area.widgets, 'popup_at'):
        area._popup_book_menu()
        test.assertFalse(action.get_enabled())
        area._covers.selection.select_all()
        area._popup_book_menu()
        test.assertTrue(action.get_enabled())


class _MarkingLibrary:

    """A library window over the real backend, for what the menu
    writes into it."""

    manages = True
    window = None
    main_window = _main_window()

    def __init__(self):
        self.backend = backend.LibraryBackend()
        self.control_area = _ControlArea()
        self.collection_area = _CollectionArea()


class _OneBookAreaTest(MComixTest):

    """A cover area over a library of <library_class>, showing
    NORMAL_ZIP alone: self.book, its self.item, and self.area."""

    library_class = _MarkingLibrary

    def setUp(self):
        super().setUp()
        self.library = self.library_class()
        self.addCleanup(self.library.backend.close)
        self.assertTrue(self.library.backend.add_book(NORMAL_ZIP))
        self.book = self.library.backend.get_book_by_path(NORMAL_ZIP)
        self.area = book_area._BookArea(self.library)
        self.addCleanup(self.area.close)
        self.item = book_area._BookItem(self.book)
        self.area._covers.set_items([self.item])


class MarkReadTest(_OneBookAreaTest):

    """"Mark as read" and "Mark as unread" in the covers' menu (upstream
    feature request 59).  A book is shown read, with a tick, when the
    page it was left at is its last."""

    def setUp(self):
        super().setUp()
        self.area._covers.selection.select_all()
        self.redrawn = []
        patcher = unittest.mock.patch.object(
            self.area._covers, 'redraw_item',
            side_effect=lambda item: self.redrawn.append(item.uid))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _page(self):
        return self.library.backend.get_book_by_id(
            self.book.id).get_last_read_page()

    def test_marking_read_stores_the_last_page_and_redraws_the_cover(self):
        self.assertGreater(self.book.pages, 1)
        self.area._mark_read()
        self.assertEqual(self.book.pages, self._page())
        self.assertEqual([self.book.id], self.redrawn)

    def test_marking_unread_forgets_the_page(self):
        self.book.set_last_read_page(2)
        self.area._mark_unread()
        self.assertIsNone(self._page())
        self.assertEqual([self.book.id], self.redrawn)

    def test_the_entries_need_a_book_selected(self):
        self.area._covers.selection.unselect_all()
        with unittest.mock.patch('mcomix.widgets.popup_at'):
            self.area._popup_book_menu()
        for name in ('mark-read', 'mark-unread'):
            self.assertFalse(self.area._popup_actions.lookup_action(name)
                             .get_enabled(), name)


class RightClickFocusTest(_FourCoversTest):

    """A right click on a cover selects it and gives it the keyboard
    focus.  It used to leave the focus on the cover clicked before, and
    Enter, after the menu, opened that book rather than the one shown
    selected."""

    def _focused(self):
        """The position of the cover that holds the keyboard focus."""
        covers = self.area._covers
        cell = self.window.get_focus()
        while cell is not None and cell.get_parent() is not covers:
            cell = cell.get_parent()
        if cell is None:
            return None
        bounds = cell.compute_bounds(covers)[1]
        return covers.position_at(
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2)

    def test_the_cover_right_clicked_takes_the_focus(self):
        self._right_click_on_the_third_cover()

    def test_so_it_does_in_a_window_not_active(self):
        """GTK moves the focus by itself only in the active window: the
        selection moved and the focus stayed, also once the window was
        active again."""
        self._right_click_on_the_third_cover(take_activation=True)
        self.window.present()
        wait_for(self.window.is_active)
        self.assertEqual(2, self._focused())

    def _right_click_on_the_third_cover(self, take_activation=False):
        covers = self.area._covers
        covers.grab_focus()
        covers.select_and_focus(0)
        # The focus moves to a cell once the cell has been laid out,
        # which on a loaded machine takes more turns of the main loop
        # than a few turns give.
        wait_for(lambda: self._focused() == 0)
        self.assertEqual(0, self._focused())
        if take_activation:
            self.assertTrue(take_activation_from(self, self.window))
        x = next(x for x in range(10, 600, 10)
                 if covers.position_at(x, 60) == 2)
        gesture = types.SimpleNamespace(get_widget=lambda: covers)
        with unittest.mock.patch.object(self.area, '_popup_book_menu'):
            self.area._button_press(gesture, 1, x, 60)
        wait_for(lambda: self._focused() == 2)
        self.assertEqual([2], covers.get_selected_positions())
        self.assertEqual(2, self._focused())


class _RenamingLibrary(_MarkingLibrary):

    """A library whose main window's rename is only watched."""

    def __init__(self):
        super().__init__()
        self.main_window = _main_window(file_actions=unittest.mock.Mock())


class RenameFromLibraryTest(_OneBookAreaTest):

    """"Rename" in the covers' menu, and F2."""

    library_class = _RenamingLibrary

    def setUp(self):
        super().setUp()
        self.ask = self.library.main_window.file_actions.ask_to_rename_book

    def test_the_book_selected_is_renamed(self):
        self.area._covers.selection.select_all()
        self.area.rename_selected()
        path, parent = self.ask.call_args.args
        self.assertEqual(self.book.path, path)

    def test_a_book_moved_is_shown_where_it_went(self):
        """Whichever window moved it: the main window renames and moves
        the book being read with the library open over it."""
        renamed = os.path.join(os.path.dirname(self.book.path), 'Renamed.cbz')
        self.assertTrue(self.library.backend.update_book_path(
            self.book.path, renamed))
        self.assertEqual(renamed, self.item.path)

    def test_with_nothing_selected_nothing_is_renamed(self):
        self.area.rename_selected()
        self.ask.assert_not_called()

    def test_f2_renames(self):
        with unittest.mock.patch.object(self.area,
                                        'rename_selected') as rename:
            self.assertEqual(Gdk.EVENT_STOP, self.area._key_press(
                None, Gdk.KEY_F2, 0, Gdk.ModifierType(0)))
        rename.assert_called_once_with()

    def test_the_menu_offers_it_for_one_book_only(self):
        assert_offered_once_a_book_is_selected(self, self.area, 'rename')


class MoveFromLibraryTest(MComixTest):

    """"Move to" in the covers' menu: the main window's submenu, for the
    books selected."""

    def setUp(self):
        super().setUp()
        self.library = _RenamingLibrary()
        self.addCleanup(self.library.backend.close)
        self.items = []
        for name in ('01-ZIP-Normal.zip', '02-TAR-Normal.tar'):
            path = get_testfile_path('archives', name)
            self.assertTrue(self.library.backend.add_book(path))
            self.items.append(book_area._BookItem(
                self.library.backend.get_book_by_path(path)))
        self.area = book_area._BookArea(self.library)
        self.addCleanup(self.area.close)
        self.area._covers.set_items(self.items)
        self.move = self.library.main_window.file_actions.move_books

    def test_the_books_selected_are_moved(self):
        self.area._covers.selection.select_all()
        self.area._move_selected_to('/elsewhere')
        paths, directory, parent = self.move.call_args.args
        self.assertEqual(sorted(item.path for item in self.items),
                         sorted(paths))
        self.assertEqual('/elsewhere', directory)

    def test_the_menu_offers_it_for_a_selection_only(self):
        actions = self.area._move_to._actions
        with unittest.mock.patch.object(book_area.widgets, 'popup_at'):
            self.area._popup_book_menu()
            self.assertFalse(actions.get_action_enabled('other'))
            self.area._covers.selection.select_all()
            self.area._popup_book_menu()
            self.assertTrue(actions.get_action_enabled('other'))

    def test_the_menu_holds_the_submenu(self):
        labels = []
        model = self.area._book_menu.get_menu_model()
        for i in range(model.get_n_items()):
            section = model.get_item_link(i, Gio.MENU_LINK_SECTION)
            for j in range(section.get_n_items() if section else 0):
                if section.get_item_link(j, Gio.MENU_LINK_SUBMENU) \
                        is self.area._move_to.model:
                    labels.append(section.get_item_attribute_value(
                        j, Gio.MENU_ATTRIBUTE_LABEL,
                        GLib.VariantType('s')).get_string())
        self.assertEqual(['Move _to'], labels)

# vim: expandtab:sw=4:ts=4
