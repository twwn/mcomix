"""clipboard.py - Clipboard handler"""

from gi.repository import Gdk

from mcomix import image_tools


class Clipboard(object):

    """The Clipboard takes care of all necessary copy-paste functionality
    """

    def __init__(self, window):
        # Gtk.Clipboard and Gdk.Atom are both gone in GTK4; a clipboard
        # belongs to the display and is asked for by name.
        self._clipboard = Gdk.Display.get_default().get_clipboard()
        self._window = window

    def copy(self, text, pixbuf):
        """ Copies C{text} and C{pixbuf} to clipboard. """
        # A GTK4 clipboard holds one content provider rather than a set
        # of targets set one at a time, so offer both and leave whoever
        # pastes to take the one it understands.
        self._clipboard.set_content(Gdk.ContentProvider.new_union([
            Gdk.ContentProvider.new_for_value(text),
            Gdk.ContentProvider.new_for_value(
                image_tools.pixbuf_to_texture(image_tools.static_image(pixbuf))),
        ]))

    def copy_page(self, *args):
        """ Copies the currently opened page and pixbuf to clipboard. """

        if self._window.filehandler.file_loaded:
            # Get pixbuf for current page
            current_page_pixbufs = self._window.imagehandler.get_pixbufs(
                2 if self._window.displayed_double() else 1) # XXX limited to at most 2 pages

            if len(current_page_pixbufs) == 1:
                pixbuf = current_page_pixbufs[ 0 ]
            else:
                pixbuf = image_tools.combine_pixbufs(
                        current_page_pixbufs[ 0 ],
                        current_page_pixbufs[ 1 ],
                        self._window.is_manga_mode )

            path = self._window.imagehandler.get_path_to_page()
            self.copy(path, pixbuf)

# vim: expandtab:sw=4:ts=4
