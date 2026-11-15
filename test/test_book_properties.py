"""Tests for the properties of the books selected in the library."""

import datetime
import os
import shutil
import unittest.mock

from gi.repository import Gdk, Gtk

from . import MComixTest, get_testfile_path, pump
from .test_book_area import _MarkingLibrary

from mcomix import image_tools
from mcomix.library import book_area
from mcomix.library import book_properties


def _texts(widget):
    """Every label's text under <widget>, depth first."""
    texts = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            texts.append(child.get_text())
        texts.extend(_texts(child))
        child = child.get_next_sibling()
    return texts


class BookPropertiesTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.library = _MarkingLibrary()
        self.backend = self.library.backend
        self.addCleanup(self.backend.close)
        self.paths = []
        for name in ('First.cbz', 'Second.cbz'):
            path = os.path.join(self.tmp_dir, name)
            shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                        path)
            self.assertTrue(self.backend.add_book(path))
            self.paths.append(path)
        self.books = [self.backend.get_book_by_path(path)
                      for path in self.paths]
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.destroy()
        pump()
        super().tearDown()

    def _open(self, books, cover=None):
        dialog = book_properties.BookPropertiesDialog(
            None, self.backend, books, cover)
        self.dialogs.append(dialog)
        return dialog

    def test_one_book_is_described_by_its_file_and_the_library(self):
        book = self.books[0]
        self.backend.add_collection('Westerns')
        self.backend.add_book_to_collection(
            book.id, self.backend.get_collection_by_name('Westerns').id)
        book.set_last_read_page(2, datetime.datetime(2026, 3, 4, 5, 6, 7))

        texts = _texts(self._open([book]).page)

        self.assertIn('First.cbz', texts)
        self.assertIn('%d pages' % book.pages, texts)
        self.assertIn('ZIP archive', texts)
        self.assertIn(self.tmp_dir, texts)
        for row in ('Location:', 'Size:', 'Modified:', 'Date added:',
                    'Last read:', 'Collection:'):
            self.assertIn(row, texts)
        self.assertIn('Page 2/%d, 2026-03-04, 05:06:07' % book.pages, texts)
        self.assertIn('Westerns', texts)

    def test_a_book_never_read_and_filed_nowhere_says_neither(self):
        texts = _texts(self._open([self.books[0]]).page)
        self.assertNotIn('Last read:', texts)
        self.assertNotIn('Collection:', texts)

    def test_a_book_whose_file_is_gone_keeps_the_size_recorded(self):
        os.remove(self.paths[0])
        texts = _texts(self._open([self.books[0]]).page)
        self.assertIn('Size:', texts)
        self.assertNotIn('Modified:', texts)

    def test_the_cover_shown_in_the_library_is_shown(self):
        cover = image_tools.missing_image_icon(300, 400)
        dialog = self._open([self.books[0]], cover)
        paintable = dialog.page._thumb.get_paintable()
        self.assertIsNotNone(paintable)
        # Brought down to the page's 128 pixels, and a border round it.
        self.assertLessEqual(paintable.get_intrinsic_height(), 130)

    def test_several_books_are_summed_up(self):
        first, second = self.books
        first.set_last_read_page(first.pages)
        texts = _texts(self._open(self.books).page)
        self.assertIn('2 books', texts)
        self.assertIn('%d pages' % (first.pages + second.pages), texts)
        self.assertIn('Started: 0, finished: 1', texts)
        # Both lie in the same folder, which is said once.
        self.assertIn(self.tmp_dir, texts)

    def test_books_in_several_folders_name_none(self):
        elsewhere = os.path.join(self.tmp_dir, 'elsewhere')
        os.makedirs(elsewhere)
        moved = os.path.join(elsewhere, 'Second.cbz')
        shutil.move(self.paths[1], moved)
        self.assertTrue(self.backend.update_book_path(self.paths[1], moved))
        books = [self.backend.get_book_by_path(self.paths[0]),
                 self.backend.get_book_by_path(moved)]
        texts = _texts(self._open(books).page)
        self.assertNotIn('Location:', texts)


class _PropertiesLibrary(_MarkingLibrary):

    manages = True


class BookAreaPropertiesTest(MComixTest):

    """Reaching the properties from the covers."""

    def setUp(self):
        super().setUp()
        self.library = _PropertiesLibrary()
        self.addCleanup(self.library.backend.close)
        self.assertTrue(self.library.backend.add_book(
            get_testfile_path('archives', '01-ZIP-Normal.zip')))
        self.book = self.library.backend.get_book_by_path(
            get_testfile_path('archives', '01-ZIP-Normal.zip'))
        self.area = book_area._BookArea(self.library)
        self.area._covers.set_items([book_area._BookItem(self.book)])

    def tearDown(self):
        self.area.close()
        super().tearDown()

    def test_alt_return_describes_the_selection(self):
        with unittest.mock.patch.object(self.area,
                                        'show_properties') as shown:
            self.assertEqual(Gdk.EVENT_STOP, self.area._key_press(
                None, Gdk.KEY_Return, 0, Gdk.ModifierType.ALT_MASK))
        shown.assert_called_once_with()

    def test_the_selected_books_are_described(self):
        self.area._covers.selection.select_all()
        with unittest.mock.patch.object(
                book_properties, 'BookPropertiesDialog') as dialog:
            self.area.show_properties()
        books = dialog.call_args.args[2]
        self.assertEqual([self.book.id], [book.id for book in books])

    def test_a_cover_the_cache_let_go_is_read_again(self):
        # A full-width library at a small cover size asks for more
        # covers than the cache holds; the one picked out was gone, and
        # the Properties showed none.
        self.area._cache.invalidate_all()
        self.area._covers.selection.select_all()
        with unittest.mock.patch.object(
                book_properties, 'BookPropertiesDialog') as dialog:
            self.area.show_properties()
        self.assertIsNotNone(dialog.call_args.args[3])

    def test_with_nothing_selected_nothing_is_described(self):
        with unittest.mock.patch.object(
                book_properties, 'BookPropertiesDialog') as dialog:
            self.area.show_properties()
        dialog.assert_not_called()

    def test_the_menu_offers_it_for_a_selection_only(self):
        action = self.area._popup_actions.lookup_action('properties')
        with unittest.mock.patch.object(book_area.widgets, 'popup_at'):
            self.area._popup_book_menu()
            self.assertFalse(action.get_enabled())
            self.area._covers.selection.select_all()
            self.area._popup_book_menu()
            self.assertTrue(action.get_enabled())

# vim: expandtab:sw=4:ts=4
