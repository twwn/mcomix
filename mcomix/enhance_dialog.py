"""enhance_dialog.py - Image enhancement dialog."""

from gi.repository import GdkPixbuf, Gio, Gtk
from . import histogram

from mcomix.dialog import Dialog
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix import image_tools
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main

_dialog: "_EnhanceImageDialog | None" = None

class _EnhanceImageDialog(Dialog):

    """A Gtk.Dialog which allows modification of the values belonging to
    an ImageEnhancer.
    """

    def __init__(self, window: "main.MainWindow") -> None:
        super(_EnhanceImageDialog, self).__init__(
            title=_('Enhance image'), transient_for=window)

        self._window = window

        reset = Gtk.Button.new_with_mnemonic(_('_Revert'))
        reset.set_tooltip_text(_('Reset to defaults.'))
        self.add_action_widget(reset, Response.REJECT)
        save = Gtk.Button.new_with_mnemonic(_('_Save'))
        save.set_tooltip_text(_('Save the selected values as default for future files.'))
        self.add_action_widget(save, Response.APPLY)
        self.add_button(_('_OK'), Response.OK)

        self.set_resizable(False)
        self.connect('response', self._response)
        self.set_default_response(Response.OK)

        self._enhancer = window.enhancer
        self._block = False

        vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 10)
        widgets.set_border(self, 4)
        widgets.set_border(vbox, 6)
        self.get_content_area().append(vbox)

        # A Gtk.Image draws whatever it is given at an icon size in
        # GTK4; a picture draws it at its own.
        self._hist_image = Gtk.Picture()
        self._hist_image.set_size_request(262, 170)
        widgets.pack(vbox, self._hist_image, True, True, 0)
        widgets.pack(vbox, Gtk.Separator.new(Gtk.Orientation.HORIZONTAL), True, True, 0)

        hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 4)
        widgets.pack(vbox, hbox, False, False, 2)
        vbox_left = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
        vbox_right = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
        widgets.pack(hbox, vbox_left, False, False, 2)
        widgets.pack(hbox, vbox_right, True, True, 2)

        def _create_scale(label_text: str) -> Gtk.Scale:
            label = Gtk.Label(label=label_text)
            label.set_xalign(1)
            label.set_yalign(0.5)
            label.set_use_underline(True)
            widgets.pack(vbox_left, label, True, False, 2)
            adj = Gtk.Adjustment.new(0.0, -1.0, 1.0, 0.01, 0.1, 0.0)
            scale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, adj)
            scale.set_digits(2)
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            scale.connect('value-changed', self._change_values)
            label.set_mnemonic_widget(scale)
            widgets.pack(vbox_right, scale, True, False, 2)
            return scale

        self._brightness_scale = _create_scale(_('_Brightness:'))
        self._contrast_scale = _create_scale(_('_Contrast:'))
        self._saturation_scale = _create_scale(_('S_aturation:'))
        self._sharpness_scale = _create_scale(_('S_harpness:'))

        widgets.pack(vbox, Gtk.Separator.new(Gtk.Orientation.HORIZONTAL), True, True, 0)

        self._autocontrast_button = \
            Gtk.CheckButton.new_with_mnemonic(_('_Automatically adjust contrast'))
        self._autocontrast_button.set_tooltip_text(
            _('Automatically adjust contrast (both lightness and darkness), separately for each colour band.'))
        widgets.pack(vbox, self._autocontrast_button, False, False, 2)
        self._autocontrast_button.connect('toggled', self._change_values)

        self._invert_color_button = \
            Gtk.CheckButton.new_with_mnemonic(_('_Invert image colors'))
        self._invert_color_button.set_tooltip_text(
            _('Invert (negate) image colors.'))
        widgets.pack(vbox, self._invert_color_button, False, False, 2)
        self._invert_color_button.connect('toggled', self._change_values)

        self._block = True
        self._brightness_scale.set_value(self._enhancer.brightness - 1)
        self._contrast_scale.set_value(self._enhancer.contrast - 1)
        self._saturation_scale.set_value(self._enhancer.saturation - 1)
        self._sharpness_scale.set_value(self._enhancer.sharpness - 1)
        self._autocontrast_button.set_active(self._enhancer.autocontrast)
        self._invert_color_button.set_active(self._enhancer.invert_color)
        self._block = False
        self._contrast_scale.set_sensitive(
            not self._autocontrast_button.get_active())

        self._window.imagehandler.page_available += self._on_page_available
        self._window.filehandler.file_closed += self._on_book_close
        self._window.page_changed += self._on_page_change
        self._on_page_change()

        self.set_visible(True)

    def _on_book_close(self) -> None:
        self.clear_histogram()

    def _on_page_change(self) -> None:
        if not self._window.imagehandler.page_is_available():
            self.clear_histogram()
            return
        # XXX transitional(double page limitation)
        pixbuf = self._window.imagehandler.get_pixbufs(1)[0]
        self.draw_histogram(pixbuf)

    def _on_page_available(self, page_number: int) -> None:
        current_page_number = self._window.imagehandler.get_current_page()
        if current_page_number == page_number:
            self._on_page_change()

    def draw_histogram(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        """Draw a histogram representing <pixbuf> in the dialog."""
        histogram_pixbuf = histogram.draw_histogram(pixbuf, text=False)
        self._hist_image.set_paintable(
            image_tools.pixbuf_to_texture(histogram_pixbuf))

    def clear_histogram(self) -> None:
        """Clear the histogram in the dialog."""
        self._hist_image.set_paintable(None)

    def _change_values(self, *args: Any) -> None:
        if self._block:
            return

        self._enhancer.brightness = self._brightness_scale.get_value() + 1
        self._enhancer.contrast = self._contrast_scale.get_value() + 1
        self._enhancer.saturation = self._saturation_scale.get_value() + 1
        self._enhancer.sharpness = self._sharpness_scale.get_value() + 1
        self._enhancer.autocontrast = self._autocontrast_button.get_active()
        self._contrast_scale.set_sensitive(
            not self._autocontrast_button.get_active())
        self._enhancer.invert_color = self._invert_color_button.get_active()
        self._enhancer.signal_update()

    def _response(self, dialog: Dialog, response: int) -> None:

        if response in [Response.OK, Response.DELETE_EVENT]:
            _close_dialog()

        elif response == Response.APPLY:
            self._change_values(self)
            prefs['brightness'] = self._enhancer.brightness
            prefs['contrast'] = self._enhancer.contrast
            prefs['saturation'] = self._enhancer.saturation
            prefs['sharpness'] = self._enhancer.sharpness
            prefs['auto contrast'] = self._enhancer.autocontrast
            prefs['invert color'] = self._enhancer.invert_color
            # The menu carries this one as a tick of its own, the only
            # enhancement that does; leaving it behind is what put the
            # two out of step.  The colours are already what the
            # enhancer says, so the tick moves without running the
            # menu item's own handler.
            self._window.actiongroup.get_action('invert_color').show_active(
                prefs['invert color'])

        elif response == Response.REJECT:
            self._block = True
            self._brightness_scale.set_value(prefs['brightness'] - 1.0)
            self._contrast_scale.set_value(prefs['contrast'] - 1.0)
            self._saturation_scale.set_value(prefs['saturation'] - 1.0)
            self._sharpness_scale.set_value(prefs['sharpness'] - 1.0)
            self._autocontrast_button.set_active(prefs['auto contrast'])
            self._invert_color_button.set_active(prefs['invert color'])
            self._block = False
            self._change_values(self)


def open_dialog(action: Gio.SimpleAction, window: "main.MainWindow") -> None:
    """Create and display the (singleton) image enhancement dialog."""
    global _dialog

    if _dialog is None:
        _dialog = _EnhanceImageDialog(window)
    else:
        _dialog.present()

def _close_dialog(*args: Any) -> None:
    """Destroy the image enhancement dialog."""
    global _dialog

    if _dialog is not None:
        _dialog.destroy()
        _dialog = None


# vim: expandtab:sw=4:ts=4
