"""properties_page.py - A page to put in the properties dialog window."""

from gi.repository import GdkPixbuf, Gtk, Pango

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
        # Never across: a long name or folder wraps instead (see
        # _wrapping()), and a page wider than the window would hide
        # the end of every row behind a scroll bar.
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        widgets.set_border(self, 12)

        self._vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 12)
        self.set_child(self._vbox)

        topbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
        widgets.pack(self._vbox, topbox, True, True, 0)
        # A Gtk.Image draws what it is given at an icon size.
        self._thumb = Gtk.Picture()
        # Not enlarged past its own size, as the thumbnail bar's are not.
        self._thumb.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
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

    def set_thumbnail(self, pixbuf: GdkPixbuf.Pixbuf, scale: float = 1) -> None:
        """Show <pixbuf>, made with <scale> of the screen's pixels to each
        of the window's, at the size it stands for."""
        pixbuf = image_tools.add_border(pixbuf, int(round(scale)))
        self._thumb.set_paintable(widgets.at_scale(
            image_tools.pixbuf_to_texture(pixbuf), scale))

    def set_filename(self, filename: str) -> None:
        """Set the filename to be displayed to <filename>. Call this before
        set_main_info().
        """
        label = labels.BoldLabel(i18n.to_display_string(i18n.to_unicode(filename)))
        _wrapping(label)
        label.set_xalign(0)
        label.set_selectable(True)
        widgets.pack(self._mainbox, label, False, False, 0)

    def set_main_info(self, info: Sequence[str]) -> None:
        """Set the information in the main info box (below the filename) to
        the values in the sequence <info>.
        """
        for text in info:
            label = Gtk.Label(label=text)
            _wrapping(label)
            label.set_xalign(0)
            label.set_selectable(True)
            widgets.pack(self._mainbox, label, False, False, 0)

    def set_secondary_info(self, info: Sequence[tuple[str, str]]) -> None:
        """Set the information below the main info box to the values in the
        sequence <info>. Each entry in info should be a tuple (desc, value).
        What an earlier call set is replaced.
        """
        widgets.empty(self._extrabox)
        # A row each, rather than a column of names beside a column of
        # values: a value that wraps onto a second line keeps its name
        # beside its first.  Not a Gtk.Grid, which reserves for a
        # wrapping label the height it would need at its narrowest,
        # several times what it takes at the width it is given.  The
        # size group keeps the names one column wide.
        rows = Gtk.Box.new(Gtk.Orientation.VERTICAL, 8)
        rows.set_hexpand(True)
        widgets.pack(self._extrabox, rows, True, True, 0)
        names = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)
        for desc, value in info:
            row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
            desc_label = labels.BoldLabel('%s:' % desc)
            desc_label.set_xalign(1.0)
            desc_label.set_valign(Gtk.Align.START)
            names.add_widget(desc_label)
            widgets.pack(row, desc_label, False, False, 0)
            value_label = Gtk.Label(label=value)
            _wrapping(value_label)
            value_label.set_xalign(0)
            value_label.set_valign(Gtk.Align.START)
            value_label.set_selectable(True)
            widgets.pack(row, value_label, True, True, 0)
            widgets.pack(rows, row, False, False, 0)

def _wrapping(label: Gtk.Label) -> None:
    """Have <label> break a long text over several lines, between
    words where it can and anywhere in a word that is too long by
    itself, as a file name without spaces often is."""
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    # Its natural width stays the whole text's, so a short one keeps
    # its line; a few characters is all it asks for at least.
    label.set_width_chars(1)


# vim: expandtab:sw=4:ts=4
