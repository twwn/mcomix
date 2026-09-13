"""edit_image_area.py - The area of the editing archive window that displays images."""

import os
from gi.repository import Gdk, GdkPixbuf, Gio, Gtk

from mcomix import widgets
from mcomix import image_tools
from mcomix import preview
from mcomix import i18n
from mcomix import thumbnail_tools
from mcomix import thumbnail_view
from mcomix.i18n import _

from typing import Any

class _ImageArea(Gtk.ScrolledWindow):

    """The area used for displaying and handling image files."""

    def __init__(self, edit_dialog, window):
        super(_ImageArea, self).__init__()

        self._window = window
        self._edit_dialog = edit_dialog
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # The ListStore layout is (thumbnail, basename, full path, thumbnail status).
        # Basename is used as image tooltip.
        self._liststore = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, bool)
        self._iconview = thumbnail_view.ThumbnailIconView(
            self._liststore,
            2, # UID
            0, # pixbuf
            3, # status
        )
        self._iconview.generate_thumbnail = self._generate_thumbnail
        self._iconview.set_tooltip_column(1)
        self._iconview.set_reorderable(True)
        self._iconview.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        clicks = Gtk.GestureClick()
        clicks.set_button(3)
        clicks.connect('pressed', self._button_press)
        self._iconview.add_controller(clicks)

        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_press)
        self._iconview.add_controller(keys)
        self.set_child(self._iconview)

        # As every other preview in MComix, as large as this screen
        # wants it.
        self._thumbnail_size = preview.scaled(128, self)
        self._thumbnailer = thumbnail_tools.Thumbnailer(store_on_disk=False,
                                                        size=(self._thumbnail_size,
                                                              self._thumbnail_size))

        self._filler = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                            has_alpha=True, bits_per_sample=8,
                                            width=self._thumbnail_size,
                                            height=self._thumbnail_size)
        # Make the pixbuf transparent.
        self._filler.fill(0)

        self._window.imagehandler.page_available += self._on_page_available

        self._popup_menu = self._create_popup_menu()

    def _create_popup_menu(self) -> Any:
        """Build the right-click menu for the page list."""
        actions = Gio.SimpleActionGroup()
        remove = Gio.SimpleAction.new('remove', None)
        remove.connect('activate', self._remove_pages)
        actions.add_action(remove)
        self.insert_action_group('imagearea', actions)

        model = Gio.Menu()
        model.append(_('Remove from archive'), 'imagearea.remove')
        return Gtk.PopoverMenu.new_from_model(model)

    def fetch_images(self) -> None:
        """Load all the images in the archive or directory."""
        for page in range(1, self._window.imagehandler.get_number_of_pages() + 1):
            path = self._window.imagehandler.get_path_to_page(page)
            encoded_path = i18n.to_unicode(os.path.basename(path))
            encoded_path = encoded_path.replace('&', '&amp;')
            self._liststore.append([self._filler, encoded_path, path, False])

    def _generate_thumbnail(self, uid):
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

    def add_extra_image(self, path):
        """Add an imported image (at <path>) to the end of the image list."""
        self._liststore.append([self._filler, os.path.basename(path), path, False])

    def get_file_listing(self):
        """Return a list with the full paths to all the images, in order."""
        return [row[2] for row in self._liststore]

    def _remove_pages(self, *args):
        """Remove the currently selected pages from the list."""
        paths = self._iconview.get_selected_items()

        for path in paths:
            iterator = self._liststore.get_iter(path)
            self._liststore.remove(iterator)

    def _button_press(self, gesture, n_press, x, y) -> None:
        """Handle mouse button presses on the thumbnail area."""
        iconview = self._iconview
        path = iconview.get_path_at_pos(int(x), int(y))

        if path is None:
            return

        if not iconview.path_is_selected(path):
            iconview.unselect_all()
            iconview.select_path(path)

        widgets.popup_at(self._popup_menu, iconview, x, y)

    def _key_press(self, controller, keyval, keycode, state):
        """Handle key presses on the thumbnail area."""
        if keyval == Gdk.KEY_Delete:
            self._remove_pages()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    # The pages are reordered by dragging, which Gtk.IconView does for
    # itself.  A drag_begin hook used to move the drag icon's hotspot to
    # its top left corner; GTK4 gives no such signal on the widget, and
    # the icon it draws for a reorder is its own.

    def cleanup(self) -> None:
        self._iconview.stop_update()

    def _on_page_available(self, page):
        """ Called whenever a new page is ready for display. """
        self._iconview.draw_thumbnails_on_screen()

# vim: expandtab:sw=4:ts=4
