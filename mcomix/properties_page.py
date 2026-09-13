"""properties_page.py - A page to put in the properties dialog window."""

from gi.repository import GdkPixbuf, Gtk

from collections.abc import Sequence

from mcomix import i18n
from mcomix import image_tools
from mcomix import labels
from mcomix import widgets


class _Page(Gtk.ScrolledWindow):

    """A page to put in the Gtk.Notebook. Contains info about a file (an
    image or an archive.)
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        widgets.set_border(self, 12)

        self._vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 12)
        self.set_child(self._vbox)

        topbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
        widgets.pack(self._vbox, topbox, True, True, 0)
        # A Gtk.Image draws what it is given at an icon size.
        self._thumb = Gtk.Picture()
        self._thumb.set_size_request(128, 128)
        widgets.pack(topbox, self._thumb, False, False, 0)
        borderbox = Gtk.Frame()
        borderbox.set_size_request(-1, 130)
        widgets.pack(topbox, borderbox, True, True, 0)
        self._insidebox = borderbox
        # The two boxes the page is written into.  They stand for its
        # whole life and reset() empties them; building another pair for
        # every book, and taking the old one off the page again, said
        # the same thing at more cost.
        self._mainbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 5)
        widgets.set_border(self._mainbox, 10)
        self._insidebox.set_child(self._mainbox)
        self._extrabox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
        widgets.pack(self._vbox, self._extrabox, False, False, 0)
        self.reset()

    def reset(self) -> None:
        """Take off what the book before this one was described with."""
        self._thumb.set_paintable(None)
        widgets.empty(self._mainbox)
        widgets.empty(self._extrabox)

    def set_thumbnail(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        pixbuf = image_tools.add_border(pixbuf, 1)
        self._thumb.set_paintable(image_tools.pixbuf_to_texture(pixbuf))

    def set_filename(self, filename: str) -> None:
        """Set the filename to be displayed to <filename>. Call this before
        set_main_info().
        """
        label = labels.BoldLabel(i18n.to_display_string(i18n.to_unicode(filename)))
        label.set_xalign(0)
        label.set_yalign(0.5)
        label.set_selectable(True)
        widgets.pack(self._mainbox, label, False, False, 0)

    def set_main_info(self, info: Sequence[str]) -> None:
        """Set the information in the main info box (below the filename) to
        the values in the sequence <info>.
        """
        for text in info:
            label = Gtk.Label(label=text)
            label.set_xalign(0)
            label.set_yalign(0.5)
            label.set_selectable(True)
            widgets.pack(self._mainbox, label, False, False, 0, end=True)

    def set_secondary_info(self, info: Sequence[tuple[str, str]]) -> None:
        """Set the information below the main info box to the values in the
        sequence <info>. Each entry in info should be a tuple (desc, value).
        """
        left_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 8)
        left_box.set_homogeneous(True)
        right_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 8)
        right_box.set_homogeneous(True)
        widgets.pack(self._extrabox, left_box, False, False, 0)
        widgets.pack(self._extrabox, right_box, False, False, 0)
        for desc, value in info:
            desc_label = labels.BoldLabel('%s:' % desc)
            desc_label.set_xalign(1.0)
            desc_label.set_yalign(1.0)
            widgets.pack(left_box, desc_label, True, True, 0)
            value_label = Gtk.Label(label=value)
            value_label.set_xalign(0)
            value_label.set_yalign(1.0)
            value_label.set_selectable(True)
            widgets.pack(right_box, value_label, True, True, 0)

# vim: expandtab:sw=4:ts=4
