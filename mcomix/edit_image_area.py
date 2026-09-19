"""edit_image_area.py - The area of the editing archive window that displays images."""

import os
from gi.repository import Gdk, GdkPixbuf, Gio, Gtk

from mcomix import widgets
from mcomix import image_tools
from mcomix import preview
from mcomix import i18n
from mcomix import thumbnail_list
from mcomix import thumbnail_tools
from mcomix.i18n import _

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import edit_dialog as edit_dialog_module
    from mcomix import main


class _ImageArea(Gtk.ScrolledWindow):

    """The area used for displaying and handling image files."""

    def __init__(self, edit_dialog: "edit_dialog_module._EditArchiveDialog",
                 window: "main.MainWindow") -> None:
        super().__init__()

        self._window = window
        self._edit_dialog = edit_dialog
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # As every other preview in MComix, as large as this screen
        # wants it.
        self._thumbnail_size = preview.scaled(128, self)

        # An entry's uid is the full path to its image, which is what
        # the thumbnailer takes; its tooltip is the basename.
        self._grid = thumbnail_list.ThumbnailGridView()
        self._grid.generate_thumbnail = self._generate_thumbnail
        self._grid.set_thumbnail_size(self._thumbnail_size)
        self._grid.set_reorderable(True)
        self._grid.about_to_reorder = edit_dialog.record_change
        clicks = Gtk.GestureClick()
        clicks.set_button(3)
        clicks.connect('pressed', self._button_press)
        self._grid.add_controller(clicks)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press)
        self._grid.add_controller(keys)
        self.set_child(self._grid)

        self._thumbnailer = thumbnail_tools.Thumbnailer(store_on_disk=False,
                                                        size=(self._thumbnail_size,
                                                              self._thumbnail_size))

        self._window.imagehandler.page_available += self._on_page_available

        self._popup_menu = self._create_popup_menu()

    def _create_popup_menu(self) -> Gtk.PopoverMenu:
        """Build the right-click menu for the page list.

        Selecting every page, undoing and redoing were the keyboard's
        alone - Ctrl+A is Gtk.GridView's own binding and Ctrl+Z and
        Ctrl+Y the dialog's - and this menu is the only place the editor
        has to name them, so nothing said they were there.
        """
        actions = Gio.SimpleActionGroup()
        for name, activated in (('remove', self._remove_pages),
                                ('select-all', self._select_all),
                                ('undo', self._undo),
                                ('redo', self._redo)):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', activated)
            actions.add_action(action)
        self.insert_action_group('imagearea', actions)

        model = Gio.Menu()
        pages = Gio.Menu()
        pages.append(_('Remove from archive'), 'imagearea.remove')
        pages.append(_('Select _All'), 'imagearea.select-all')
        model.append_section(None, pages)
        history = Gio.Menu()
        history.append(_('_Undo'), 'imagearea.undo')
        history.append(_('_Redo'), 'imagearea.redo')
        model.append_section(None, history)
        return Gtk.PopoverMenu.new_from_model(model)

    def _select_all(self, *args: object) -> None:
        self._grid.select_all()

    def _undo(self, *args: object) -> None:
        self._edit_dialog.undo()

    def _redo(self, *args: object) -> None:
        self._edit_dialog.redo()

    def fetch_images(self) -> None:
        """Load all the images in the archive or directory."""
        items = []
        for page in range(1, self._window.imagehandler.get_number_of_pages() + 1):
            path = self._window.imagehandler.get_path_to_page(page)
            # The page count is read once and the paths one at a time,
            # so a book that is closed in between - which empties the
            # list both of them answer from - leaves pages with no path
            # at all.  There is nothing to show for one of those.
            if path is not None:
                items.append(self._item_for(path))
        self._grid.set_items(items)

    @staticmethod
    def _item_for(path: str) -> thumbnail_list.ThumbnailItem:
        name = i18n.to_unicode(os.path.basename(path))
        return thumbnail_list.ThumbnailItem(path, tooltip=name)

    def _generate_thumbnail(self, uid: str) -> "GdkPixbuf.Pixbuf | None":
        assert isinstance(uid, str)
        path = uid
        try:
            if not self._window.filehandler.file_is_available(path):
                return None
        except KeyError:
            # Not a page from the current archive, ignore.
            pass
        pixbuf = self._thumbnailer.thumbnail(path)
        if pixbuf is None:
            # The icon that stands in for a page that would not load is
            # 24 pixels square; on its own in a cell many times that it
            # looks like the page came out tiny rather than missing.
            pixbuf = image_tools.fit_in_rectangle(
                image_tools.missing_image_icon(),
                self._thumbnail_size, self._thumbnail_size, scale_up=True)
        return pixbuf

    def add_extra_image(self, path: str) -> None:
        """Add an imported image (at <path>) to the end of the image list."""
        self._grid.append_item(self._item_for(path))

    def get_file_listing(self) -> list[str]:
        """Return a list with the full paths to all the images, in order."""
        return [item.uid for item in self._grid.each_item()]

    def selected_paths(self) -> list[str]:
        """The file of every page picked out here, in the order shown."""
        return [item.uid for item in self._grid.get_selected_items()]

    def select_paths(self, paths: "Iterable[str]") -> None:
        """Pick out the pages whose files are <paths>, and no others."""
        wanted = set(paths)
        self._grid.select_positions(
            position for position, item in enumerate(self._grid.each_item())
            if item.uid in wanted)

    def snapshot(self) -> list[thumbnail_list.ThumbnailItem]:
        """The entries as they stand, for the dialog's undo.

        The entries themselves rather than their paths: an entry carries
        the thumbnail that was made for it, so putting one back does not
        make it again.
        """
        return list(self._grid.each_item())

    def restore(self, items: list[thumbnail_list.ThumbnailItem]) -> None:
        """Show <items>, from a snapshot(), and nothing else."""
        self._grid.set_items(items)

    def _remove_pages(self, *args: object) -> None:
        """Remove the currently selected pages from the list."""
        positions = self._grid.get_selected_positions()
        if not positions:
            return
        self._edit_dialog.record_change()
        self._grid.remove_positions(positions)

    def _button_press(self, gesture: Gtk.GestureClick, n_press: int,
                      x: float, y: float) -> None:
        """Handle mouse button presses on the thumbnail area."""
        position = self._grid.position_at(x, y)
        if position < 0:
            return

        if position not in self._grid.get_selected_positions():
            self._grid.select_only(position)

        widgets.popup_at(self._popup_menu, self._grid, x, y)

    def _key_press(self, controller: Gtk.EventControllerKey, keyval: int,
                   keycode: int, state: Gdk.ModifierType) -> bool:
        """Handle key presses on the thumbnail area."""
        if keyval == Gdk.KEY_Delete:
            self._remove_pages()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    # The pages are reordered by dragging. Gtk.IconView did that for
    # itself; a Gtk.GridView does not, so every cell carries a drag
    # source and a drop target of its own. See ThumbnailGridView.

    def cleanup(self) -> None:
        """Stop making thumbnails, stop listening for pages, and drop
        the entries.

        A page extracted after the editor has closed would otherwise
        reach _on_page_available(), whose refresh() clears the flag
        stop_update() sets and puts the worker thread back to work for a
        dialog that is gone.

        Nothing here goes by itself, because a closed editor is never
        collected: GTK 4 no longer disposes the widgets of a destroyed
        window, and the Python handlers they hold keep the dialog alive.
        callback.CallbackList's weak reference to this area never dies,
        and the entries, each with its thumbnail, stayed with it - every
        editor opened kept a thumbnail of every page it had shown.
        """
        self._window.imagehandler.page_available -= self._on_page_available
        self._grid.clear()

    def _on_page_available(self, page: int) -> None:
        """ Called whenever a new page is ready for display. """
        self._grid.refresh()

# vim: expandtab:sw=4:ts=4
