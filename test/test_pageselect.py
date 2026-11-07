"""The page selector, which previews the page it would go to.

The preview is made on a worker thread and comes back through a
callback, and the thumbnail it comes back with is None for a page the
extractor has not reached yet.
"""

import os
import zipfile
from unittest import mock

from gi.repository import Gdk, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants
from mcomix import icons
from mcomix import main
from mcomix import pageselect
from mcomix.dialog import Response
from mcomix.preferences import prefs


class PageselectTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() > 0,
            seconds=20))
        self.dialog = pageselect.Pageselector(self.window)
        pump()

    def tearDown(self):
        self.dialog._stop_thumbnailing()
        # Not the main window, which is stopped before it is destroyed:
        # destroyed first, its menus let go of their actions, and closing
        # the book then reached for them ("There is no action named").
        for window in Gtk.Window.list_toplevels():
            if window.get_visible() and window is not self.window:
                window.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def test_the_selector_covers_every_page(self):
        adjustment = self.dialog._selector_adjustment
        self.assertEqual(adjustment.get_lower(), 1)
        self.assertEqual(adjustment.get_upper(),
                         self.window.imagehandler.get_number_of_pages())

    def test_the_preview_is_not_enlarged_past_its_own_size(self):
        self.assertEqual(Gtk.ContentFit.SCALE_DOWN,
                         self.dialog._image_preview.get_content_fit())

    def test_a_page_that_is_not_available_leaves_the_preview_empty(self):
        """A page the extractor has not reached has no thumbnail, and
        handing None to Gdk.Texture raised instead of showing nothing."""
        self.dialog._thumbnail_page = 1
        self.dialog._thumbnail_finished(1, None)
        self.assertIsNone(self.dialog._image_preview.get_paintable())

    def test_a_thumbnail_that_was_made_is_shown(self):
        pixbuf = self.window.imagehandler.get_thumbnail(1, width=64,
                                                        height=64)
        self.assertIsNotNone(pixbuf)
        self.dialog._thumbnail_page = 1
        self.dialog._thumbnail_finished(1, pixbuf)
        self.assertIsNotNone(self.dialog._image_preview.get_paintable())

    def test_closing_the_selector_stops_the_worker(self):
        """The worker is not a daemon, so a dialog that leaves it
        running leaves terminate_program() waiting for it at exit.  It
        was stopped from the window's 'destroy' signal, which GTK4 emits
        when the last reference to the window goes rather than when it
        is destroyed - and the handler is a method of the window, so the
        closure held a reference and the signal never came."""
        self.dialog._update_thumbnail(1)
        self.assertTrue(wait_for(
            lambda: self.dialog._thread._threads,
            seconds=20))
        self.dialog.response(Response.CANCEL)
        pump()
        self.assertEqual(self.dialog._thread._threads, [],
                         'the preview worker is still running')

    def test_a_thumbnail_for_a_page_left_behind_is_dropped(self):
        """The preview is asked for again on every change, and an answer
        for the page before it must not overwrite the one on screen."""
        pixbuf = self.window.imagehandler.get_thumbnail(1, width=64,
                                                        height=64)
        self.dialog._thumbnail_page = 2
        self.dialog._thumbnail_finished(2, pixbuf)
        shown = self.dialog._image_preview.get_paintable()
        self.assertIsNotNone(shown)
        self.dialog._thumbnail_finished(1, None)
        self.assertIs(self.dialog._image_preview.get_paintable(), shown)


    def _type(self, text):
        spinner = self.dialog._page_spinner
        spinner.set_text(text)
        spinner.emit('changed')

    def test_a_page_number_typed_is_previewed_at_once(self):
        self._type('3')
        self.assertEqual(3, self.dialog._selector_adjustment.get_value())
        self.assertEqual(3, self.dialog._thumbnail_page)

    def test_a_number_past_the_last_page_or_not_a_number_is_left(self):
        for text in ('9', '0', 'x'):
            with self.subTest(text=text):
                self._type(text)
                self.assertEqual(
                    1, self.dialog._selector_adjustment.get_value())

    def _press(self, keyval):
        """Press <keyval> in the page number, as GTK hands it over:
        to the controllers that look before the number's own text does."""
        spinner = self.dialog._page_spinner
        for controller in spinner.observe_controllers():
            if isinstance(controller, Gtk.EventControllerKey) and \
                    controller.get_propagation_phase() == \
                    Gtk.PropagationPhase.CAPTURE:
                return controller.emit('key-pressed', keyval, 0, 0)
        self.fail('nothing on the page number looks at its keys')

    def test_one_enter_goes_to_the_page_typed(self):
        """GTK 4.24's spin button took the first Enter after typing for
        itself, and Go answered only a second one."""
        for keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            with self.subTest(key=Gdk.keyval_name(keyval)):
                self.dialog = pageselect.Pageselector(self.window)
                with mock.patch.object(self.window, 'set_page') as set_page:
                    self.dialog._page_spinner.set_text('3')
                    self.assertTrue(self._press(keyval))
                set_page.assert_called_once_with(3)

    def test_enter_on_a_number_past_the_last_page_goes_to_the_last(self):
        with mock.patch.object(self.window, 'set_page') as set_page:
            self.dialog._page_spinner.set_text('99')
            self._press(Gdk.KEY_Return)
        set_page.assert_called_once_with(
            self.window.imagehandler.get_number_of_pages())

    def test_other_keys_are_left_to_the_page_number(self):
        with mock.patch.object(self.window, 'set_page') as set_page:
            self.assertFalse(self._press(Gdk.KEY_Up))
        set_page.assert_not_called()

    def test_moving_the_selector_previews_the_page_it_is_moved_to(self):
        self.dialog._selector_adjustment.set_value(2)
        self.assertEqual(2, self.dialog._thumbnail_page)

    def test_it_opens_large_enough_for_a_preview(self):
        """With no size remembered it came up 154 pixels wide, around a
        preview a thumbnail across."""
        self.assertTrue(wait_for(lambda: self.dialog.get_width() > 0,
                                 seconds=5))
        self.assertGreaterEqual(self.dialog.get_width(), 320)
        self.assertGreaterEqual(self.dialog.get_height(), 420)

    def test_cancel_comes_before_go(self):
        labels = []
        child = self.dialog._button_row.get_first_child()
        while child is not None:
            labels.append(child.get_label())
            child = child.get_next_sibling()
        self.assertEqual(['_Cancel', '_Go'], labels)

    def test_the_size_it_is_given_is_remembered(self):
        self.dialog.set_default_size(420, 360)
        self.assertTrue(wait_for(
            lambda: prefs['pageselector width'] == self.dialog.get_width()
            and self.dialog.get_width() > 0, seconds=5))
        self.assertEqual(self.dialog.get_height(),
                         prefs['pageselector height'])


# vim: expandtab:sw=4:ts=4


class ChapterTest(MComixTest):

    """A book whose ComicInfo.xml names chapters is gone through by them
    in Go to page."""

    _COMICINFO = (
        '<ComicInfo><PageCount>4</PageCount><Pages>'
        '<Page Image="0" Bookmark="Prologue"/><Page Image="1"/>'
        '<Page Image="2" Bookmark="The Night"/><Page Image="3"/>'
        '</Pages></ComicInfo>')

    def _open(self, comicinfo_xml):
        path = os.path.join(self.tmp_dir, 'book.cbz')
        with zipfile.ZipFile(get_testfile_path(
                'archives', '01-ZIP-Normal.zip')) as source, \
                zipfile.ZipFile(path, 'w') as book:
            for name in source.namelist():
                if name.endswith(('.jpg', '.png')):
                    book.writestr(name, source.read(name))
            if comicinfo_xml is not None:
                book.writestr('ComicInfo.xml', comicinfo_xml)
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow(open_path=path)
        main.set_main_window(self.window)
        self.assertTrue(wait_for(
            lambda: self.window.imagehandler.get_number_of_pages() == 4,
            seconds=20))
        self.assertTrue(wait_for(
            lambda: all(self.window.filehandler.file_is_available(member)
                        for member in self.window.filehandler.get_member_names()),
            seconds=20))
        self.dialog = pageselect.Pageselector(self.window)
        pump()

    def tearDown(self):
        self.dialog._stop_thumbnailing()
        for window in Gtk.Window.list_toplevels():
            if window.get_visible() and window is not self.window:
                window.destroy()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _titles(self):
        listed = self.dialog._chapter_list
        return [listed.get_string(index) for index in range(listed.get_n_items())]

    def test_the_chapters_are_listed_and_choosing_one_goes_to_its_page(self):
        self._open(self._COMICINFO)
        selector = self.dialog._chapter_selector
        self.assertTrue(selector.get_visible())
        self.assertEqual(['Prologue', 'The Night'], self._titles())
        selector.set_selected(1)
        self.assertEqual(3, self.dialog._selector_adjustment.get_value())
        self.dialog.response(Response.OK)
        pump()
        self.assertEqual(3, self.window.imagehandler.get_current_page())

    def test_the_list_shows_the_chapter_of_the_page_chosen(self):
        self._open(self._COMICINFO)
        selector = self.dialog._chapter_selector
        adjustment = self.dialog._selector_adjustment
        for page, chapter in ((4, 1), (2, 0), (3, 1), (1, 0)):
            adjustment.set_value(page)
            self.assertEqual(chapter, selector.get_selected(), page)
            self.assertEqual(page, adjustment.get_value(),
                             'following the page moved it')

    def test_a_book_without_a_comicinfo_shows_no_list(self):
        self._open(None)
        self.assertFalse(self.dialog._chapter_selector.get_visible())

    def test_a_comicinfo_without_bookmarks_shows_no_list(self):
        self._open('<ComicInfo><Title>T</Title></ComicInfo>')
        self.assertFalse(self.dialog._chapter_selector.get_visible())

    def test_the_chapters_wait_for_a_comicinfo_not_out_yet(self):
        with mock.patch.object(main.MainWindow, '_look_for_direction'):
            self._open(self._COMICINFO)
        self.dialog.destroy()
        pump()
        filehandler = self.window.filehandler
        path = next(path for path, name in filehandler.get_member_names().items()
                    if name == 'ComicInfo.xml')
        with mock.patch.object(filehandler, 'file_is_available',
                               return_value=False), \
                mock.patch.object(filehandler, 'ask_for_files') as asked:
            self.dialog = pageselect.Pageselector(self.window)
        asked.assert_called_once_with([path])
        self.assertFalse(self.dialog._chapter_selector.get_visible())
        filehandler.file_available([path])
        self.assertTrue(self.dialog._chapter_selector.get_visible())
