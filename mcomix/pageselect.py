"""pageselect.py - The dialog window for the page selector."""

from gi.repository import Gtk

from mcomix.dialog import Dialog
from mcomix import image_tools
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix.worker_thread import WorkerThread
from mcomix import callback
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gi.repository import GdkPixbuf
    from mcomix import main


class Pageselector(Dialog):

    """The Pageselector takes care of the popup page selector
    """

    def __init__(self, window: "main.MainWindow") -> None:
        self._window = window
        super().__init__(
            title=_('Go to page...'), transient_for=window,
            modal=True, destroy_with_parent=True)
        self.add_buttons(_('_Go'), Response.OK,
                         _('_Cancel'), Response.CANCEL,)
        self.set_default_response(Response.OK)
        self.connect('response', self._response)
        self.set_resizable(True)

        self._number_of_pages = self._window.imagehandler.get_number_of_pages()

        self._selector_adjustment = Gtk.Adjustment(value=self._window.imagehandler.get_current_page(),
                                                   lower=1, upper=self._number_of_pages,
                                                   step_increment=1, page_increment=1)

        self._page_selector = Gtk.Scale.new(Gtk.Orientation.VERTICAL,
                                            self._selector_adjustment)
        self._page_selector.set_draw_value(False)
        self._page_selector.set_digits(0)

        self._page_spinner = Gtk.SpinButton.new(self._selector_adjustment, 0.0, 0)
        self._page_spinner.connect('changed', self._page_text_changed)
        self._page_spinner.set_activates_default(True)
        self._page_spinner.set_numeric(True)
        self._pages_label = Gtk.Label(label=_(' of %s') % self._number_of_pages)
        self._pages_label.set_xalign(0)
        self._pages_label.set_yalign(0.5)

        # A Gtk.Image draws whatever it is given at an icon size; a
        # picture draws it at its own.
        self._image_preview = Gtk.Picture()
        self._image_preview.set_size_request(
            prefs['thumbnail size'], prefs['thumbnail size'])

        self.set_size_request(prefs['pageselector width'],
                              prefs['pageselector height'])

        # Group preview image and page selector next to each other
        preview_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.set_border(preview_box, 5)
        preview_box.set_spacing(5)
        widgets.pack(preview_box, self._image_preview, True, True, 0)
        widgets.pack(preview_box, self._page_selector, False, False, 0, end=True)
        # Below them, group selection spinner and current page label
        selection_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        widgets.set_border(selection_box, 5)
        widgets.pack(selection_box, self._page_spinner, True, True, 0)
        widgets.pack(selection_box, self._pages_label, False, False, 0, end=True)

        widgets.pack(self.get_content_area(), preview_box, True, True, 0)
        widgets.pack(self.get_content_area(), selection_box, False, False, 0, end=True)
        self.set_visible(True)

        self.connect_while_open(self._selector_adjustment, 'value-changed',
                                self._cb_value_changed)

        # Set focus on the input box.
        self._page_spinner.select_region(0, -1)
        self._page_spinner.grab_focus()

        # Currently displayed thumbnail page.
        self._thumbnail_page = 0
        self._thread = WorkerThread(self._generate_thumbnail, name='preview')
        # The worker is not a daemon, so whatever ends this dialog has to
        # stop it - not only the buttons.  Anything else leaves a thread
        # that terminate_program() then waits for at exit.  'unrealize',
        # not 'destroy': GTK4 emits the latter when the last reference to
        # the window goes rather than when it is destroyed, and the
        # worker holds one for as long as it runs, so 'destroy' would
        # not come before it had stopped.  Nothing here hides the dialog,
        # which is the other thing that unrealizes a window.
        self.connect('unrealize', self._stop_thumbnailing)
        # A window says how large it is through its default size
        # properties.  Connected last, after everything the handler
        # reaches has been built.
        self.connect('notify::default-width', self._size_changed_cb)
        self.connect('notify::default-height', self._size_changed_cb)
        self._update_thumbnail(int(self._selector_adjustment.props.value))
        self._window.imagehandler.page_available += self._page_available

    def _cb_value_changed(self, *args: object) -> None:
        """ Called whenever the spinbox value changes. Updates the preview thumbnail. """
        page = int(self._selector_adjustment.props.value)
        if page != self._thumbnail_page:
            self._update_thumbnail(page)

    def _size_changed_cb(self, *args: object) -> None:
        # Window cannot be scaled down unless the size request is reset
        self.set_size_request(-1, -1)
        # Store dialog size
        prefs['pageselector width'] = self.get_width() or prefs['pageselector width']
        prefs['pageselector height'] = self.get_height() or prefs['pageselector height']

        self._update_thumbnail(int(self._selector_adjustment.props.value))

    def _page_text_changed(self, control: Gtk.SpinButton,
                           *args: object) -> None:
        """ Called when the page selector has been changed. Used to instantly update
            the preview thumbnail when entering page numbers by hand. """
        if control.get_text().isdigit():
            page = int(control.get_text())
            if page > 0 and page <= self._number_of_pages:
                control.set_value(page)

    def _stop_thumbnailing(self, *args: object) -> None:
        self._thread.stop()

    def _response(self, widget: Gtk.Widget, event: int,
                  *args: object) -> None:
        if event == Response.OK:
            self._window.set_page(int(self._selector_adjustment.props.value))

        self._window.imagehandler.page_available -= self._page_available
        self.destroy()

    def _update_thumbnail(self, page: int) -> None:
        """ Trigger a thumbnail update. """
        width = self._image_preview.get_width()
        height = self._image_preview.get_height()
        self._thumbnail_page = page
        self._thread.clear_orders()
        self._thread.append_order((page, width, height))

    def _generate_thumbnail(self, params: tuple[int, int, int]) -> None:
        """ Generate the preview thumbnail for the page selector.
        A page that is not available yet has no thumbnail, and the
        preview is then left empty. """
        page, width, height = params

        pixbuf = self._window.imagehandler.get_thumbnail(page,
                                                         width=width, height=height, nowait=True)
        self._thumbnail_finished(page, pixbuf)

    @callback.Callback
    def _thumbnail_finished(self, page: int,
                            pixbuf: "GdkPixbuf.Pixbuf | None") -> None:
        # Don't bother if we changed page in the meantime.
        if page == self._thumbnail_page:
            # get_thumbnail() answers None for a page that has not been
            # extracted yet, which is nothing to make a texture of.
            self._image_preview.set_paintable(
                image_tools.pixbuf_to_texture(pixbuf)
                if pixbuf is not None else None)

    def _page_available(self, page: int) -> None:
        if page == int(self._selector_adjustment.props.value):
            self._update_thumbnail(page)

# vim: expandtab:sw=4:ts=4
