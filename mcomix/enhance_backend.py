"""enhance_backend.py - Image enhancement handler and dialog (e.g. contrast,
brightness etc.)
"""
from gi.repository import GdkPixbuf, GLib

from mcomix.preferences import prefs
from mcomix import callback
from mcomix import image_tools
from mcomix.library import main_dialog

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


class ImageEnhancer:

    """The ImageEnhancer keeps track of the "enhancement" values and performs
    these enhancements on pixbufs. Changes to the ImageEnhancer's values
    can be made using an _EnhanceImageDialog.
    """

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        self.brightness = prefs['brightness']
        self.contrast = prefs['contrast']
        self.saturation = prefs['saturation']
        self.sharpness = prefs['sharpness']
        self.gamma = prefs['gamma']
        self.autocontrast = prefs['auto contrast']
        self.invert_color = prefs['invert color']

    def enhance(self, pixbuf: GdkPixbuf.Pixbuf) -> GdkPixbuf.Pixbuf:
        """Return an "enhanced" version of <pixbuf>."""

        if (self.brightness != 1.0 or self.contrast != 1.0 or
                self.saturation != 1.0 or self.sharpness != 1.0 or
                self.gamma != 1.0 or self.autocontrast or self.invert_color):

            return image_tools.enhance(pixbuf, self.brightness, self.contrast,
                                       self.saturation, self.sharpness, self.autocontrast,
                                       self.invert_color, gamma=self.gamma)

        return pixbuf

    @callback.Callback
    def signal_update(self) -> None:
        """Signal to the main window that a change in the enhancement
        values has been made.

        A callback too, for the enhancement dialog: Ctrl+I changes a
        value behind its back, and a control left showing the old one
        would put it back the next time any control was moved.
        """
        self._window.draw_image()

        self._window.thumbnailsidebar.clear()
        GLib.idle_add(self._window.thumbnailsidebar.load_thumbnails)

        library = main_dialog.get_dialog()
        if library is not None:
            library.book_area.load_covers()

# vim: expandtab:sw=4:ts=4
