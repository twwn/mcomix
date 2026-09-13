"""clipboard.py - Clipboard handler"""

from gi.repository import Gdk, GdkPixbuf

from mcomix import widgets
from mcomix import image_tools

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


class Clipboard:

    """Copying the open page to the system clipboard.

    Nothing here reads the clipboard: MComix copies a page out of
    itself and never pastes one in.
    """

    def __init__(self, window: "main.MainWindow") -> None:
        # Gtk.Clipboard and Gdk.Atom are both gone in GTK4; a clipboard
        # belongs to the display and is asked for by name.
        self._clipboard = widgets.display().get_clipboard()
        self._window = window

    def copy(self, text: str, pixbuf: GdkPixbuf.Pixbuf) -> None:
        """Put <text> and <pixbuf> on the clipboard."""
        # A GTK4 clipboard holds one content provider rather than a set
        # of targets set one at a time, so offer both and leave whoever
        # pastes to take the one it understands.
        self._clipboard.set_content(Gdk.ContentProvider.new_union([
            Gdk.ContentProvider.new_for_value(text),
            Gdk.ContentProvider.new_for_value(
                image_tools.pixbuf_to_texture(pixbuf)),
        ]))

    def copy_page(self, *args: object) -> None:
        """Put the open page on the clipboard, as an image and as a path.

        Two pages shown side by side are copied as the single image
        they make on screen, in the order they are shown; the path is
        the current page's either way.
        """

        if self._window.filehandler.file_loaded:
            # Get pixbuf for current page
            current_page_pixbufs = self._window.imagehandler.get_pixbufs(
                self._window.displayed_page_count())

            if len(current_page_pixbufs) == 1:
                pixbuf = current_page_pixbufs[0]
            else:
                pixbuf = image_tools.combine_pixbufs(
                        current_page_pixbufs[0],
                        current_page_pixbufs[1],
                        self._window.is_manga_mode)

            path = self._window.imagehandler.get_path_to_page()
            # A page that is loaded has a file behind it; there is
            # nothing to name in the unlikely case that it has not.
            self.copy(path or '', pixbuf)

# vim: expandtab:sw=4:ts=4
