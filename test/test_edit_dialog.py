"""The archive editor, and the Save As chooser it opens.

The note under the file list was a Gtk.FileChooser extra widget, which
GTK4 does not have: setting it raised AttributeError and took the whole
Save As branch with it.
"""

import os
import shutil
import unittest.mock
import zipfile

from gi.repository import Gdk, Gtk

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import archive_packer
from mcomix import constants
from mcomix import edit_dialog
from mcomix import file_chooser_simple_dialog
from mcomix import icons
from mcomix import main
from mcomix import message_dialog
from mcomix.dialog import Response
from mcomix.preferences import prefs


def _children(widget):
    """Every direct child of <widget>, in order."""
    children = []
    child = widget.get_first_child()
    while child is not None:
        children.append(child)
        child = child.get_next_sibling()
    return children


class EditArchiveDialogTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.window = main.MainWindow(
            open_path=get_testfile_path('archives', '01-ZIP-Normal.zip'))
        main.set_main_window(self.window)
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)
        self.dialog = edit_dialog._EditArchiveDialog(self.window)
        pump()

    def tearDown(self):
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, file_chooser_simple_dialog.
                          SimpleFileChooserDialog):
                window.destroy()
        self.dialog.destroy()
        edit_dialog._close_dialog()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _chooser(self):
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, file_chooser_simple_dialog.
                          SimpleFileChooserDialog):
                return window
        return None

    # -- The editor and the book it belongs to ----------------------------

    def _editors(self):
        """Every archive editor on screen."""
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, edit_dialog._EditArchiveDialog)
                and window.get_visible()]

    def _editors_listening(self):
        """How many editors are still told when a book closes.

        Read off the callback list itself: a destroyed dialog is not
        collected, so one that never unsubscribed goes on answering.
        """
        callbacks = self.window.filehandler.__dict__.get('file_closed')
        if callbacks is None:
            return 0
        held = getattr(callbacks, '_CallbackList__callbacks')
        return len([1 for reference, _function in held
                    if reference is not None
                    and isinstance(reference(),
                                   edit_dialog._EditArchiveDialog)])

    def test_the_editor_closes_with_the_book_it_edits(self):
        """Its lists are one book's pages and comment files, out of a
        temporary directory that goes when the book does: a save then
        fails on files that have been cleaned up, and Apply would hand
        the window a listing of them."""
        self.assertEqual(len(self._editors()), 1, 'no editor was open')
        self.window.filehandler.close_file()
        pump()
        self.assertEqual(self._editors(), [],
                         'the editor stood over a book that had gone')

    def test_the_editor_that_closed_is_not_the_one_the_menu_opens(self):
        """open_dialog() presents the editor it holds, so an editor that
        closed itself has to be let go of or the menu presents a window
        that is not there."""
        edit_dialog._dialog = self.dialog
        try:
            self.window.filehandler.close_file()
            pump()
            self.assertIsNone(edit_dialog._dialog)
        finally:
            edit_dialog._dialog = None

    def test_a_closed_editor_stops_hearing_about_books(self):
        self.assertEqual(self._editors_listening(), 1,
                         'the editor is not listening at all')
        self.dialog.destroy()
        pump()
        self.assertEqual(self._editors_listening(), 0,
                         'a closed editor would answer the next book too')

    def test_a_page_with_no_path_is_left_out_of_the_image_area(self):
        """The page count is read once and the paths one at a time, so a
        book closed in between leaves pages that answer with no path at
        all - and os.path.basename() does not take None."""
        area = self.dialog._image_area
        handler = self.window.imagehandler
        pages = handler.get_number_of_pages()
        self.assertGreater(pages, 1, 'the fixture archive has too few pages')
        real = handler.get_path_to_page

        def gone(page=None):
            return None if page == 1 else real(page)

        handler.get_path_to_page = gone
        try:
            area.fetch_images()
        finally:
            handler.get_path_to_page = real

        self.assertEqual(len(area.get_file_listing()), pages - 1,
                         'the page with no path was not left out')

    def _packing_dialogs(self):
        """Every message dialog standing over this window."""
        return [window for window in Gtk.Window.list_toplevels()
                if isinstance(window, message_dialog.MessageDialog)
                and window.get_transient_for() is self.window]

    def test_a_page_arriving_after_the_editor_closed_leaves_it_closed(self):
        """cleanup() stops the thumbnailing thread, and the
        page_available listener's refresh() starts it again: a page
        extracted afterwards put a destroyed editor back to work, for as
        long as Python had not collected it."""
        area = self.dialog._image_area
        self.dialog.destroy()
        pump()
        self.assertTrue(area._grid._updates_stopped,
                        'cleanup() left the thumbnailer running')

        handler = self.window.imagehandler
        # page_available() refuses a page it has already announced.
        handler._available_images.discard(0)
        handler.page_available(1)
        pump()

        self.assertTrue(area._grid._updates_stopped,
                        'a closed editor was put back to work')

    def test_a_failed_load_gives_the_window_its_cursor_back(self):
        """The wait cursor is set on the main window rather than on the
        editor, so anything getting out of the loading left the whole
        program pointing at it, with an editor that could neither save
        nor import."""
        def refuse():
            raise OSError(5, 'Input/output error')

        with unittest.mock.patch.object(self.dialog._image_area,
                                        'fetch_images', refuse):
            with self.assertRaises(OSError):
                self.dialog._load_original_files()
        pump()
        self.assertIsNone(self.window.page_area.get_cursor(),
                          'the window was left pointing at a wait cursor')
        self.assertTrue(self.dialog._save_button.get_sensitive())
        self.assertTrue(self.dialog._import_button.get_sensitive())

    def test_a_load_that_finishes_leaves_no_cursor_behind_either(self):
        self.dialog._load_original_files()
        pump()
        self.assertIsNone(self.window.page_area.get_cursor())
        self.assertTrue(self.dialog._save_button.get_sensitive())

    def test_a_save_that_will_not_fit_is_refused_before_it_starts(self):
        """The packer unwinds from a disk that fills up under it, but
        only after writing until it does.  All of the new archive has to
        fit beside the old one, which does not give its room up until it
        has been replaced."""
        target = os.path.join(self.tmp_dir, 'saved.cbz')
        standing = len(self._packing_dialogs())
        real = shutil.disk_usage

        def nearly_full(path):
            usage = real(path)
            return usage.__class__(usage.total, usage.used, 1)

        with unittest.mock.patch('shutil.disk_usage', nearly_full):
            self.dialog._pack_archive(target)
        pump()

        try:
            self.assertEqual(len(self._packing_dialogs()), standing + 1,
                             'the failure was not reported')
            self.assertFalse(os.path.exists(target))
            self.assertEqual([name for name in os.listdir(self.tmp_dir)
                              if name.startswith('tmp.')], [],
                             'a temporary archive was written anyway')
        finally:
            for dialog in self._packing_dialogs():
                dialog.destroy()
            pump()

    def test_a_save_that_fits_is_not_refused(self):
        target = os.path.join(self.tmp_dir, 'saved.cbz')
        self.dialog._load_original_files()
        pump()
        self.dialog._pack_archive(target)
        pump()
        self.assertTrue(os.path.exists(target), 'the archive was not written')

    def test_a_save_that_fails_partway_says_so_and_lets_go(self):
        """Only the temporary file was guarded.  A failure at the rename
        over the old archive, or at the permissions on the new one,
        escaped into the signal handler that asked for the save and left
        the dialog insensitive under a wait cursor."""
        target = os.path.join(self.tmp_dir, 'saved.cbz')
        standing = len(self._packing_dialogs())

        def refuse(*args, **kwargs):
            raise OSError(13, 'Permission denied')

        with unittest.mock.patch('os.rename', refuse):
            self.dialog._pack_archive(target)
        pump()

        try:
            self.assertEqual(len(self._packing_dialogs()), standing + 1,
                             'the failure was not reported')
            self.assertFalse(os.path.exists(target),
                             'a broken archive was left under the real name')
            self.assertEqual([name for name in os.listdir(self.tmp_dir)
                              if name.startswith('tmp.')], [],
                             'the temporary archive was left behind')
        finally:
            # A dialog left standing is answered by whichever test goes
            # looking for one next.
            for dialog in self._packing_dialogs():
                dialog.destroy()
            pump()

    # -- Applying the edited listing --------------------------------------

    def test_applying_shows_the_page_that_is_first_in_the_new_order(self):
        """The pixbufs the handler is holding stand against the page
        numbers of the listing that was there before, so a book whose
        pages have been reordered must not be drawn from them."""
        self.dialog._load_original_files()
        pump()
        listing = list(self.dialog._image_area.get_file_listing())
        self.assertGreater(len(listing), 1, 'the fixture has too few pages')
        handler = self.window.imagehandler
        # Every page of this archive is the same one-pixel picture, so
        # the pixbuf read for the old page 1 can only be told from a
        # fresh one by identity - which is the whole question here.
        stale = handler._get_pixbuf(0)

        reordered = list(reversed(listing))
        self.dialog._image_area.get_file_listing = lambda: reordered
        self.dialog._response(self.dialog, Response.APPLY)
        pump()

        self.assertEqual(handler._image_files, reordered)
        self.assertEqual(handler.get_current_page(), 1)
        self.assertIsNot(handler._get_pixbuf(0), stale,
                         'page 1 was drawn from the pixbuf read for the '
                         'page that used to be first')

    def test_applying_a_removal_redraws_the_book_it_shortened(self):
        """Applying went through set_page(1), which returns early when
        it is asked for the page that is current already - page 1, as
        often as not - so nothing was drawn or counted again and the
        window went on describing the book that had just been replaced.
        """
        self.dialog._load_original_files()
        pump()
        listing = list(self.dialog._image_area.get_file_listing())
        self.assertGreater(len(listing), 2, 'the fixture has too few pages')
        handler = self.window.imagehandler
        self.assertEqual(handler.get_current_page(), 1,
                         'the book does not start where this test needs it')

        kept = listing[:-1]
        self.dialog._image_area.get_file_listing = lambda: kept
        self.dialog._response(self.dialog, Response.APPLY)
        pump()

        self.assertEqual(handler.get_number_of_pages(), len(kept))
        self.assertIn('/ %d]' % len(kept), self.window.get_title(),
                      'the title still counts the pages that were removed')
        self.assertEqual(self.window.statusbar.get_page_number(),
                         '1 / %d' % len(kept))

    def test_applying_a_book_with_no_pages_left_leaves_the_window_alone(self):
        """There is no page to move to, and applying an edit was not
        asked to close the file."""
        self.dialog._load_original_files()
        pump()
        self.dialog._image_area.get_file_listing = list
        self.dialog._response(self.dialog, Response.APPLY)
        pump()
        self.assertEqual(self.window.imagehandler.get_number_of_pages(), 0)

    # -- Taking a change back ---------------------------------------------

    def _shortcut(self, accelerator):
        """The dialog's Gtk.Shortcut for <accelerator>, if it has one."""
        wanted = Gtk.ShortcutTrigger.parse_string(accelerator).to_string()
        for controller in self.dialog.observe_controllers():
            if not isinstance(controller, Gtk.ShortcutController):
                continue
            for index in range(controller.get_n_items()):
                shortcut = controller.get_item(index)
                if shortcut.get_trigger().to_string() == wanted:
                    return shortcut
        return None

    def _press(self, accelerator):
        """Do what pressing <accelerator> over the dialog does."""
        shortcut = self._shortcut(accelerator)
        self.assertIsNotNone(shortcut, '%s is not bound' % accelerator)
        return shortcut.get_action().activate(
            Gtk.ShortcutActionFlags(0), self.dialog, None)

    def _pages(self):
        return list(self.dialog._image_area.get_file_listing())

    def test_control_z_takes_a_removal_back(self):
        self.dialog._load_original_files()
        pump()
        before = self._pages()
        self.assertGreater(len(before), 1, 'the fixture has too few pages')
        grid = self.dialog._image_area._grid
        grid.select_only(0)
        self.dialog._image_area._remove_pages()
        self.assertEqual(self._pages(), before[1:])

        self._press('<Control>z')
        self.assertEqual(self._pages(), before)

    def test_control_y_makes_an_undone_removal_again(self):
        self.dialog._load_original_files()
        pump()
        before = self._pages()
        self.dialog._image_area._grid.select_only(0)
        self.dialog._image_area._remove_pages()
        self._press('<Control>z')

        self._press('<Control>y')
        self.assertEqual(self._pages(), before[1:])

    def test_control_shift_z_redoes_as_control_y_does(self):
        self.dialog._load_original_files()
        pump()
        before = self._pages()
        self.dialog._image_area._grid.select_only(0)
        self.dialog._image_area._remove_pages()
        self._press('<Control>z')

        self._press('<Control><Shift>z')
        self.assertEqual(self._pages(), before[1:])

    def _popup_actions(self, model):
        """Every action the popup <model> addresses, in order."""
        actions = []
        for index in range(model.get_n_items()):
            action = model.get_item_attribute_value(index, 'action', None)
            if action is not None:
                actions.append(action.get_string())
            section = model.get_item_link(index, 'section')
            if section is not None:
                actions.extend(self._popup_actions(section))
        return actions

    def test_the_page_menu_names_what_the_keyboard_could_already_do(self):
        """Selecting every page, undoing and redoing were reachable only
        by Ctrl+A, Ctrl+Z and Ctrl+Y, and the editor has no menu bar to
        name them on: nothing said they were there at all."""
        self.assertEqual(
            self._popup_actions(
                self.dialog._image_area._popup_menu.get_menu_model()),
            ['imagearea.rename', 'imagearea.remove', 'imagearea.select-all',
             'imagearea.undo', 'imagearea.redo'])

    def test_the_comment_menu_names_undo_and_redo_too(self):
        self.assertEqual(
            self._popup_actions(
                self.dialog._comment_area._popup_menu.get_menu_model()),
            ['commentarea.rename', 'commentarea.remove',
             'commentarea.undo', 'commentarea.redo'])

    def test_the_keyboard_opens_the_page_menu(self):
        """The editor has no menu bar, and its popup was reachable with
        the pointer alone.  A GTK4 widget has no popup-menu signal, so
        the two keys that asked for one through it are heard by the
        area itself, as the library's areas hear them."""
        area = self.dialog._image_area
        for keyval, state in ((Gdk.KEY_Menu, Gdk.ModifierType(0)),
                              (Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK)):
            self.assertFalse(area._popup_menu.get_visible())
            self.assertEqual(Gdk.EVENT_STOP,
                             area._key_press(None, keyval, 0, state))
            pump()
            self.assertTrue(area._popup_menu.get_visible(),
                            'the menu did not open for %s'
                            % Gdk.keyval_name(keyval))
            area._popup_menu.popdown()
            pump()

    def test_the_keyboard_opens_the_comment_menu(self):
        area = self.dialog._comment_area
        self.assertEqual(Gdk.EVENT_STOP,
                         area._key_press(None, Gdk.KEY_F10, 0,
                                         Gdk.ModifierType.SHIFT_MASK))
        pump()
        self.assertTrue(area._popup_menu.get_visible())
        area._popup_menu.popdown()
        pump()

    def test_f10_on_its_own_is_left_to_gtk_in_the_editor(self):
        area = self.dialog._image_area
        self.assertEqual(Gdk.EVENT_PROPAGATE,
                         area._key_press(None, Gdk.KEY_F10, 0,
                                         Gdk.ModifierType(0)))
        self.assertFalse(area._popup_menu.get_visible())

    def test_the_page_menu_offers_to_rename_a_page(self):
        self.assertIn(
            'imagearea.rename',
            self._popup_actions(
                self.dialog._image_area._popup_menu.get_menu_model()))

    def test_renaming_from_the_editor_names_the_page_the_window_holds(self):
        """The editor and the window are the same book: a name given
        here is the name the page is written under either way."""
        self.dialog._load_original_files()
        pump()
        grid = self.dialog._image_area._grid
        self.assertTrue(grid.model.get_n_items() > 1,
                        'the fixture has too few pages')
        grid.select_only(0)

        # The offer to write the archive again is another dialog, and
        # what it asks about is not this test's business.
        with unittest.mock.patch.object(self.window.file_actions,
                                        'offer_to_save'):
            self.dialog._image_area._rename_page()
            pump()

        dialogs = [window for window in Gtk.Window.list_toplevels()
                   if isinstance(window, message_dialog.MessageDialog)]
        self.assertEqual(len(dialogs), 1, 'nothing asked for a name')
        entries = [child for child in _children(dialogs[0].get_content_area())
                   if isinstance(child, Gtk.Entry)]
        self.assertEqual(len(entries), 1)
        entries[0].set_text('Cover.png')
        with unittest.mock.patch.object(self.window.file_actions,
                                        'offer_to_save'):
            dialogs[0].emit('response', Response.OK)
            pump()

        self.assertEqual(self.window.file_actions.page_name(1), 'Cover.png')
        self.assertEqual(grid.get_item(0).tooltip, 'Cover.png',
                         'the thumbnail still shows the old name')

    def test_f2_asks_for_a_name_for_the_page_selected(self):
        """The key a file manager renames with, on the list that shows
        the pages: the menu's rename was the only way to reach it."""
        self.dialog._load_original_files()
        pump()
        area = self.dialog._image_area
        area._grid.select_only(0)
        with unittest.mock.patch.object(area, '_rename_page') as asked:
            self.assertEqual(
                area._key_press(None, Gdk.KEY_F2, 0, Gdk.ModifierType(0)),
                Gdk.EVENT_STOP)
        asked.assert_called_once_with()

    def test_the_page_menu_selects_every_page(self):
        self.dialog._load_original_files()
        pump()
        grid = self.dialog._image_area._grid
        self.assertGreater(grid.model.get_n_items(), 1,
                           'the fixture has too few pages')
        grid.unselect_all()

        self.dialog._image_area._select_all()
        pump()

        self.assertEqual(grid.get_selected_positions(),
                         list(range(grid.model.get_n_items())))

    def test_the_page_menu_takes_a_removal_back(self):
        self.dialog._load_original_files()
        pump()
        before = self._pages()
        self.dialog._image_area._grid.select_only(0)
        self.dialog._image_area._remove_pages()
        self.assertEqual(self._pages(), before[1:])

        self.dialog._image_area._undo()

        self.assertEqual(self._pages(), before)

    def test_the_page_menu_makes_an_undone_removal_again(self):
        self.dialog._load_original_files()
        pump()
        before = self._pages()
        self.dialog._image_area._grid.select_only(0)
        self.dialog._image_area._remove_pages()
        self.dialog._image_area._undo()

        self.dialog._image_area._redo()

        self.assertEqual(self._pages(), before[1:])

    def test_undoing_what_was_never_changed_is_not_an_error(self):
        self.dialog._load_original_files()
        pump()
        before = self._pages()
        self.assertFalse(self.dialog.undo())
        self.assertFalse(self.dialog.redo())
        self.assertEqual(self._pages(), before)

    def test_a_change_after_an_undo_leaves_nothing_to_redo(self):
        """The undone change is not one the editor can arrive at any
        more: the listing went somewhere else instead."""
        self.dialog._load_original_files()
        pump()
        area = self.dialog._image_area
        area._grid.select_only(0)
        area._remove_pages()
        self.dialog.undo()

        area._grid.select_only(1)
        area._remove_pages()
        self.assertFalse(self.dialog.redo())

    def test_a_closed_editor_lets_go_of_its_thumbnails(self):
        """A closed editor is never collected - GTK 4 no longer disposes
        the widgets of a destroyed window, and the handlers they hold
        keep the dialog alive - so it has to drop its pages' entries,
        each with a thumbnail, and the undo snapshots that hold them."""
        self.dialog._load_original_files()
        pump()
        grid = self.dialog._image_area._grid
        self.assertGreater(grid.store.get_n_items(), 0)
        grid.select_only(0)
        self.dialog._image_area._remove_pages()
        self.dialog.undo()
        self.assertTrue(self.dialog._redone)
        self.dialog.destroy()
        self.assertEqual(grid.store.get_n_items(), 0)
        self.assertEqual((self.dialog._undone, self.dialog._redone), ([], []))

    def test_an_undone_page_keeps_the_thumbnail_that_was_made_for_it(self):
        """A snapshot is the entries themselves, not their paths."""
        self.dialog._load_original_files()
        pump()
        grid = self.dialog._image_area._grid
        first = grid.get_item(0)
        grid.select_only(0)
        self.dialog._image_area._remove_pages()
        self.dialog.undo()
        self.assertIs(grid.get_item(0), first)

    def test_a_reordering_drag_can_be_undone(self):
        self.dialog._load_original_files()
        pump()
        before = self._pages()
        self.assertGreater(len(before), 2, 'the fixture has too few pages')
        self.assertTrue(self.dialog._image_area._grid.move_item(0, 2))
        self.assertNotEqual(self._pages(), before)

        self.dialog.undo()
        self.assertEqual(self._pages(), before)

    def test_an_import_is_one_change_however_many_files_it_added(self):
        self.dialog._load_original_files()
        pump()
        pages = self._pages()
        added = []
        for name in ('imported-1.png', 'imported-2.png'):
            path = os.path.join(self.tmp_dir, name)
            with open(get_testfile_path('images', '03-PNG-RGB.png'), 'rb') \
                    as source, open(path, 'wb') as copy:
                copy.write(source.read())
            added.append(path)
        self.dialog._import_files(added)
        self.assertEqual(self._pages(), pages + added)

        self.assertTrue(self.dialog.undo())
        self.assertEqual(self._pages(), pages)

    def test_importing_nothing_is_not_a_change_to_undo(self):
        self.dialog._load_original_files()
        pump()
        self.dialog._import_files([os.path.join(self.tmp_dir, 'not there')])
        self.assertFalse(self.dialog.undo())

    def test_removing_a_comment_file_can_be_undone(self):
        area = self.dialog._comment_area
        before = area.get_file_listing()
        self.assertTrue(before, 'the fixture archive has no comment file')

        area._list.select_only(0)
        area._remove_file()
        self.assertEqual(area.get_file_listing(), before[1:])

        self._press('<Control>z')
        self.assertEqual(area.get_file_listing(), before)

    # -- The pages picked out in the window --------------------------------

    def test_the_editor_opens_with_the_windows_pages_picked_out(self):
        """The pages the reader picked out are the ones the editor was
        opened to do something about."""
        self.window.select_page(2)
        self.dialog._load_original_files()
        pump()
        listing = self.dialog._image_area.get_file_listing()
        self.assertEqual(self.dialog._image_area.selected_paths(),
                         [listing[1]])

    def test_closing_the_editor_picks_its_pages_out_in_the_window(self):
        self.dialog._load_original_files()
        pump()
        listing = list(self.dialog._image_area.get_file_listing())
        self.assertGreater(len(listing), 2, 'the fixture has too few pages')
        self.dialog._image_area._grid.select_positions([0, 2])
        self.dialog.destroy()
        pump()
        self.assertEqual(self.window.selected_pages, {1, 3})

    def test_applying_keeps_the_editors_pages_picked_out(self):
        """The listing is a new one, so the numbers are new too: what
        was picked out is carried over by its file rather than by where
        it stood."""
        self.dialog._load_original_files()
        pump()
        listing = list(self.dialog._image_area.get_file_listing())
        self.assertGreater(len(listing), 2, 'the fixture has too few pages')
        self.dialog._image_area._grid.select_positions([2])
        reordered = list(reversed(listing))
        self.dialog._image_area.get_file_listing = lambda: reordered
        self.dialog._response(self.dialog, Response.APPLY)
        pump()
        self.assertEqual(self.window.selected_page_paths(), [listing[2]])

    # -- Which format a save writes ---------------------------------------

    def test_a_save_is_a_cbz_unless_the_reader_asks_otherwise(self):
        self.assertEqual(self.dialog._save_format(),
                         (constants.ZIP, '.cbz'))

    def test_a_save_can_keep_the_format_the_book_was_opened_in(self):
        """A ZIP saved back as a ZIP keeps the extension it had, rather
        than being renamed to the one MComix would have given it."""
        prefs['keep archive format when saving'] = True
        self.assertEqual(self.dialog._save_format(),
                         (constants.ZIP, '.zip'))
        self.dialog._response(self.dialog, constants.RESPONSE_SAVE_AS)
        pump()
        chooser = self._chooser()
        self.assertEqual(chooser.save_name, '01-ZIP-Normal.zip')
        self.assertIsNone(chooser._note,
                          'the format is the one that was opened, so '
                          'there is nothing to say about it')

    def test_a_format_that_cannot_be_written_is_still_saved_as_a_cbz(self):
        """Nothing makes an LHA out of a book."""
        prefs['keep archive format when saving'] = True
        with unittest.mock.patch.object(self.dialog.file_handler,
                                        'archive_type', constants.LHA):
            self.assertEqual(self.dialog._save_format(),
                             (constants.ZIP, '.cbz'))

    def test_a_format_is_only_offered_where_its_program_is_installed(self):
        """A 7z needs 7-Zip and a RAR needs rar, neither of which
        MComix installs; unrar, which is what a RAR is read with, only
        ever reads."""
        prefs['keep archive format when saving'] = True
        for archive_type, finder, found in (
                (constants.SEVENZIP, 'szip_executable', '/usr/bin/7z'),
                (constants.RAR, 'rar_executable', '/usr/bin/rar')):
            with unittest.mock.patch.object(self.dialog.file_handler,
                                            'archive_type', archive_type):
                with unittest.mock.patch.object(archive_packer, finder,
                                                lambda: None):
                    self.assertEqual(self.dialog._save_format(),
                                     (constants.ZIP, '.cbz'))
                with unittest.mock.patch.object(archive_packer, finder,
                                                lambda found=found: found):
                    self.assertEqual(self.dialog._save_format(),
                                     (archive_type, '.zip'))

    def test_save_as_opens_a_chooser_saying_what_it_writes(self):
        self.dialog._response(self.dialog, constants.RESPONSE_SAVE_AS)
        pump()
        chooser = self._chooser()
        self.assertIsNotNone(chooser)
        self.assertEqual(chooser._note.get_text(),
                         'Archives are stored as ZIP files.')

    def test_save_as_offers_the_archive_under_a_name_of_its_own(self):
        self.dialog._response(self.dialog, constants.RESPONSE_SAVE_AS)
        pump()
        chooser = self._chooser()
        self.assertEqual(chooser.save_name, '01-ZIP-Normal.cbz')

    def test_import_opens_a_chooser_without_a_note(self):
        self.dialog._response(self.dialog, constants.RESPONSE_IMPORT)
        pump()
        chooser = self._chooser()
        self.assertIsNotNone(chooser)
        self.assertIsNone(chooser._note)


class SavedArchiveContentsTest(MComixTest):

    """What a saved archive holds besides its pages.

    An archive carries more than the pictures MComix draws and the
    comments it reads: a ComicInfo.xml, an OPF, a JSON sidecar.  The
    editor writes a new archive out of what it was given, so anything
    the file handler does not hand over is dropped the moment a book is
    saved.
    """

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        self.source = os.path.join(self.tmp_dir, 'Book.cbz')
        page = get_testfile_path('images', '03-PNG-RGB.png')
        with zipfile.ZipFile(self.source, 'w', zipfile.ZIP_DEFLATED) as book:
            for number in (1, 2, 3):
                book.write(page, 'pages/%02d.png' % number)
            book.writestr('ComicInfo.xml',
                          '<ComicInfo><Series>S</Series></ComicInfo>')
            book.writestr('metadata.json', '{"series": "S"}')
            book.writestr('info.txt', 'read me')
            book.writestr('extra/notes.md', 'notes')
            book.writestr('__MACOSX/._notes.md', 'junk')
        self.window = main.MainWindow(open_path=self.source)
        main.set_main_window(self.window)
        wait_for(lambda: self.window.imagehandler.get_number_of_pages() > 0,
                 seconds=20)
        self.dialog = edit_dialog._EditArchiveDialog(self.window)
        pump()

    def tearDown(self):
        self.dialog.destroy()
        edit_dialog._close_dialog()
        self.window.terminate_program()
        self.window.destroy()
        main.set_main_window(None)
        pump()
        super().tearDown()

    def _saved(self):
        """Save the book under a new name, and say what is in it."""
        target = os.path.join(self.tmp_dir, 'Saved.cbz')
        self.dialog._pack_archive(target)
        pump()
        with zipfile.ZipFile(target) as saved:
            return sorted(saved.namelist())

    def test_the_pages_are_there_under_the_names_the_editor_gives_them(self):
        self.assertEqual([name for name in self._saved()
                          if name.endswith('.png')],
                         ['1 - Saved.png', '2 - Saved.png', '3 - Saved.png'])

    def test_a_metadata_file_is_not_dropped(self):
        self.assertIn('metadata.json', self._saved())

    def test_a_carried_file_keeps_the_directory_it_was_in(self):
        self.assertIn('extra/notes.md', self._saved())

    def test_the_files_the_finder_leaves_behind_are_still_left_behind(self):
        """They are not part of the book, which is why they are left out
        of the pages as well."""
        self.assertEqual([name for name in self._saved()
                          if '__MACOSX' in name], [])

    def test_a_comment_file_is_written_once_and_not_carried_as_well(self):
        self.assertEqual(self._saved().count('ComicInfo.xml'), 1)

    def test_a_comment_file_is_saved_under_the_name_it_was_given(self):
        """The name a comment is renamed to in the editor is the name
        the save writes it under, as a page's is."""
        area = self.dialog._comment_area
        rows = [row.name for row in area._list.each_row()]
        self.assertIn('info.txt', rows, 'the fixture holds no comment file')
        area._list.select_only(rows.index('info.txt'))
        with unittest.mock.patch.object(
                edit_dialog.edit_comment_area.rename_dialog, 'ask') as asked:
            area._rename_file()
        asked.call_args.kwargs['answered'](Response.OK, 'Notes.txt')

        saved = self._saved()
        self.assertIn('Notes.txt', saved)
        self.assertNotIn('info.txt', saved)


# vim: expandtab:sw=4:ts=4
