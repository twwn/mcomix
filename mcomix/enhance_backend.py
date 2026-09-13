"""enhance_backend.py - Image enhancement handler and dialog (e.g. contrast,
brightness etc.)
"""
from gi.repository import GLib

from mcomix.preferences import prefs
from mcomix import image_tools
from mcomix.library import main_dialog

class ImageEnhancer(object):

    """The ImageEnhancer keeps track of the "enhancement" values and performs
    these enhancements on pixbufs. Changes to the ImageEnhancer's values
    can be made using an _EnhanceImageDialog.
    """

    def __init__(self, window):
        self._window = window
        self.brightness = prefs['brightness']
        self.contrast = prefs['contrast']
        self.saturation = prefs['saturation']
        self.sharpness = prefs['sharpness']
        self.autocontrast = prefs['auto contrast']
        self.invert_color = prefs['invert color']

    def enhance(self, pixbuf):
        """Return an "enhanced" version of <pixbuf>."""

        if (self.brightness != 1.0 or self.contrast != 1.0 or
          self.saturation != 1.0 or self.sharpness != 1.0 or
          self.autocontrast or self.invert_color):

            return image_tools.enhance(pixbuf, self.brightness, self.contrast,
                self.saturation, self.sharpness, self.autocontrast,
                self.invert_color)

        return pixbuf

    def signal_update(self) -> None:
        """Signal to the main window that a change in the enhancement
        values has been made.
        """
        self._window.draw_image()

        self._window.thumbnailsidebar.clear()
        GLib.idle_add(self._window.thumbnailsidebar.load_thumbnails)

        if main_dialog._dialog is not None:
            main_dialog._dialog.book_area.load_covers()

        self._window.update_icon(False)

# vim: expandtab:sw=4:ts=4
