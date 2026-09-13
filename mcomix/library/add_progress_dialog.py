"""library_add_progress_dialog.py - Progress bar for the library."""

from gi.repository import GLib, Gtk
from gi.repository import Pango

from mcomix.dialog import Dialog
from mcomix import labels
from mcomix import widgets
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main
    from mcomix.library import main_dialog

_dialog = None
# The "All books" collection is not a real collection stored in the library,
# but is represented by this ID in the library's TreeModels.
_COLLECTION_ALL = -1

class _AddLibraryProgressDialog(Dialog):

    """Dialog with a ProgressBar that adds books to the library."""

    def __init__(self, library: "main_dialog._LibraryDialog",
                 window: "main.MainWindow", paths: Sequence[str],
                 collection: int | None) -> None:
        """Adds the books at <paths> to the library, and also to the
        <collection>, unless it is None.
        """
        super(_AddLibraryProgressDialog, self).__init__(
            title=_('Adding books'), transient_for=library, modal=True)
        self.add_buttons(_('_Stop'), Response.CLOSE)

        self._window = window
        self._destroy = False
        self.set_size_request(400, -1)
        self.set_resizable(False)
        widgets.set_border(self, 4)
        self.connect('response', self._response)
        self.set_default_response(Response.CLOSE)

        main_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 5)
        widgets.set_border(main_box, 6)
        widgets.pack(self.get_content_area(), main_box, False, False, 0)
        hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
        widgets.pack(main_box, hbox, False, False, 5)
        left_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 5)
        left_box.set_homogeneous(True)
        right_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 5)
        right_box.set_homogeneous(True)
        widgets.pack(hbox, left_box, False, False, 0)
        widgets.pack(hbox, right_box, False, False, 0)

        label = labels.BoldLabel(_('Added books:'))
        label.set_xalign(1.0)
        label.set_yalign(1.0)
        widgets.pack(left_box, label, True, True, 0)
        number_label = Gtk.Label(label='0')
        number_label.set_xalign(0)
        number_label.set_yalign(1.0)
        widgets.pack(right_box, number_label, True, True, 0)

        bar = Gtk.ProgressBar()
        widgets.pack(main_box, bar, False, False, 0)

        added_label = labels.ItalicLabel()
        added_label.set_xalign(0)
        added_label.set_yalign(0.5)
        added_label.set_width_chars(64)
        added_label.set_max_width_chars(64)
        added_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        widgets.pack(main_box, added_label, False, False, 0)
        self.set_visible(True)

        total_paths_int = len(paths)
        total_paths_float = float(len(paths))
        total_added = 0

        for path in paths:

            if library.backend.add_book(path, collection):
                total_added += 1

                number_label.set_text('%d / %d' % (total_added, total_paths_int))

            added_label.set_text(_("Adding '%s'...") % path)
            bar.set_fraction(total_added / total_paths_float)

            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)

            if self._destroy:
                return

        self._response()

    def _response(self, *args: object) -> None:
        self._destroy = True
        self.destroy()

# vim: expandtab:sw=4:ts=4
