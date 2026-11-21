"""Tests for the properties of the books selected in the library."""

import datetime
import os
import shutil
import tempfile
import unittest.mock

from gi.repository import Gdk, Gtk

from . import (MComixTest, NORMAL_ZIP, described_book, descendants,
               label_texts, pump, wait_for)
from .test_book_area import (_MarkingLibrary, _OneBookAreaTest,
                             assert_offered_once_a_book_is_selected)

from mcomix import image_tools
from mcomix.archive import password as archive_password
from mcomix.library import book_properties


class BookPropertiesTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.library = _MarkingLibrary()
        self.backend = self.library.backend
        self.addCleanup(self.backend.close)
        self.paths = []
        for name in ('First.cbz', 'Second.cbz'):
            path = os.path.join(self.tmp_dir, name)
            shutil.copy(NORMAL_ZIP, path)
            self.assertTrue(self.backend.add_book(path))
            self.paths.append(path)
        self.books = [self.backend.get_book_by_path(path)
                      for path in self.paths]
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.destroy()
            if dialog.reading is not None:
                dialog.reading.join(10)
        pump()
        super().tearDown()

    def _described_book(self, comicinfo):
        """A book of the library whose ComicInfo.xml is <comicinfo>."""
        path = described_book(os.path.join(self.tmp_dir, 'Described.cbz'),
                              comicinfo)
        self.assertTrue(self.backend.add_book(path))
        return self.backend.get_book_by_path(path)

    def _open(self, books, cover=None):
        dialog = book_properties.BookPropertiesDialog(
            None, self.backend, books, cover)
        self.dialogs.append(dialog)
        return dialog

    def test_the_name_is_not_selected_as_it_opens(self):
        """The book's name at the top took the focus as the dialog was
        shown, which selected the whole of it."""
        dialog = self._open([self.books[0]])
        dialog.present()
        self.assertTrue(wait_for(lambda: dialog.get_mapped()))
        pump()
        selected = []
        widget = dialog.page
        for widget in (widget, *descendants(widget)):
            if isinstance(widget, Gtk.Label) and widget.get_selection_bounds()[0]:
                selected.append(widget.get_text())
        self.assertEqual([], selected)

    def test_one_book_is_described_by_its_file_and_the_library(self):
        book = self.books[0]
        self.backend.add_collection('Westerns')
        self.backend.add_book_to_collection(
            book.id, self.backend.get_collection_by_name('Westerns').id)
        book.set_last_read_page(2, datetime.datetime(2026, 3, 4, 5, 6, 7))

        texts = label_texts(self._open([book]).page)

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
        texts = label_texts(self._open([self.books[0]]).page)
        self.assertNotIn('Last read:', texts)
        self.assertNotIn('Collection:', texts)

    def test_a_book_whose_file_is_gone_keeps_the_size_recorded(self):
        os.remove(self.paths[0])
        texts = label_texts(self._open([self.books[0]]).page)
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
        texts = label_texts(self._open(self.books).page)
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
        texts = label_texts(self._open(books).page)
        self.assertNotIn('Location:', texts)

    # -- What the book's ComicInfo.xml says ---------------------------------

    def test_a_book_s_comicinfo_is_described(self):
        """The rows the main window's Archive tab shows, though the book
        is not open, above the file's own."""
        book = self._described_book(
            '<ComicInfo><Title>The Long Night</Title>'
            '<Series>Night Watch</Series><Number>3</Number>'
            '<Penciller>B. Artist</Penciller></ComicInfo>')
        dialog = self._open([book])
        # Read off the main thread: the dialog is up before it is.
        self.assertIsNotNone(dialog.reading)
        self.assertTrue(
            wait_for(lambda: 'Night Watch' in label_texts(dialog.page),
                     seconds=10),
            'the series never appeared: %r' % label_texts(dialog.page))
        texts = label_texts(dialog.page)
        for label, value in (('Series:', 'Night Watch'), ('Number:', '3'),
                             ('Title:', 'The Long Night'),
                             ('Artist:', 'B. Artist')):
            self.assertIn(label, texts)
            self.assertIn(value, texts)
        self.assertLess(texts.index('Series:'), texts.index('Location:'))
        self.assertIn('Date added:', texts)

    def test_a_book_without_comicinfo_names_no_series(self):
        dialog = self._open([self.books[0]])
        dialog.reading.join(10)
        pump()
        texts = label_texts(dialog.page)
        self.assertNotIn('Series:', texts)
        self.assertIn('Location:', texts)

    def test_a_dialog_closed_before_the_comicinfo_is_read_is_left_alone(self):
        book = self._described_book(
            '<ComicInfo><Series>Night Watch</Series></ComicInfo>')
        dialog = self._open([book])
        page = dialog.page
        dialog.destroy()
        dialog.reading.join(10)
        pump()
        self.assertNotIn('Night Watch', label_texts(page))

    def test_no_password_is_asked_for(self):
        """The library never asks for a password: the archive is opened
        with every request for one answered with none."""
        withheld = []

        def handler(*args, **kwargs):
            withheld.append(archive_password.withheld_here())
            return None

        with unittest.mock.patch(
                'mcomix.archive_tools.get_recursive_archive_handler',
                side_effect=handler):
            dialog = self._open([self.books[0]])
            dialog.reading.join(10)
        self.assertEqual(withheld, [True])

    def test_a_book_that_is_no_archive_describes_nothing(self):
        path = os.path.join(self.tmp_dir, 'Broken.cbz')
        with open(path, 'wb') as handle:
            handle.write(b'PK\x03\x04 not really')
        self.assertEqual(book_properties._comicinfo_of(path), [])
        # Nothing is left behind in the temporary folder.
        self.assertEqual(
            [name for name in os.listdir(tempfile.gettempdir())
             if name.startswith('mcomix_book_properties.')], [])


class BookAreaPropertiesTest(_OneBookAreaTest):

    """Reaching the properties from the covers."""

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
        assert_offered_once_a_book_is_selected(self, self.area, 'properties')

# vim: expandtab:sw=4:ts=4
