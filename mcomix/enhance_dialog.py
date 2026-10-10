"""enhance_dialog.py - Image enhancement dialog."""

import math

from gi.repository import GdkPixbuf, Gio, Gtk
from . import histogram

from mcomix.dialog import Dialog
from mcomix import widgets
from mcomix.preferences import prefs
from mcomix import image_tools
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main

_dialog: "_EnhanceImageDialog | None" = None


def _gamma_position(gamma: float) -> float:
    """Where the gamma scale stands for <gamma>: its logarithm, so that
    0.5 and 2 lie as far either side of 1, and within the scale's -1 to
    1 whatever a hand-edited preferences file holds."""
    return min(1.0, max(-1.0, math.log2(gamma))) if gamma > 0 else -1.0


class _EnhanceImageDialog(Dialog):

    """A Gtk.Dialog which allows modification of the values belonging to
    an ImageEnhancer.
    """

    #: The longest side of the page the histogram is counted on.
    _HISTOGRAM_SOURCE_SIZE = 512

    def __init__(self, window: "main.MainWindow") -> None:
        super().__init__(title=_('Enhance image'), transient_for=window)

        self._window = window

        neutral = Gtk.Button.new_with_mnemonic(_('R_eset'))
        neutral.set_tooltip_text(_('Show the pages as they are, without enhancement.'))
        neutral.connect('clicked', self._reset)
        self._button_row.append(neutral)
        revert = Gtk.Button.new_with_mnemonic(_('_Revert'))
        revert.set_tooltip_text(_('Go back to the saved values.'))
        self.add_action_widget(revert, Response.REJECT)
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

        # A Gtk.Image draws whatever it is given at an icon size; a
        # picture draws it at its own.
        self._hist_image = Gtk.Picture()
        # Drawn at its own size, however far the dialog is widened.
        self._hist_image.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        self._hist_image.set_size_request(262, 170)
        widgets.pack(vbox, self._hist_image, True, True, 0)
        self._logarithmic_button = \
            Gtk.CheckButton.new_with_mnemonic(_('_Logarithmic scale'))
        self._logarithmic_button.set_tooltip_text(
            _('Draw the histogram on a logarithmic scale, where colours few pixels have still show.'))
        self._logarithmic_button.set_active(prefs['histogram logarithmic'])
        self._logarithmic_button.connect('toggled', self._logarithmic_toggled)
        widgets.pack(vbox, self._logarithmic_button, False, False, 0)
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
        self._saturation_scale = _create_scale(_('Sat_uration:'))
        self._sharpness_scale = _create_scale(_('S_harpness:'))
        # Gamma is a ratio: the scale's -1 to 1 is 0.5 to 2, even steps
        # either side of 1.
        self._gamma_scale = _create_scale(_('_Gamma:'))

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
        self._gamma_scale.set_value(_gamma_position(self._enhancer.gamma))
        self._autocontrast_button.set_active(self._enhancer.autocontrast)
        self._invert_color_button.set_active(self._enhancer.invert_color)
        self._block = False
        self._contrast_scale.set_sensitive(
            not self._autocontrast_button.get_active())

        self._window.imagehandler.page_available += self._on_page_available
        self._window.filehandler.file_closed += self._on_book_close
        self._window.page_changed += self._on_page_change
        self._enhancer.signal_update += self._follow_enhancer
        # 'unrealize' rather than 'destroy', which GTK4 emits only when
        # the last reference to the window goes - whenever Python's
        # collector gets round to it, not when the window is closed.
        self.connect('unrealize', self._stop_following)
        self._on_page_change()

        self.set_visible(True)

    def _stop_following(self, *args: object) -> None:
        """Stop hearing about the book, which a closed dialog shows nothing of.

        The callbacks hold the dialog only weakly, but a destroyed dialog
        is not collected, and one left listening would go on drawing a
        histogram for every page turned, once for each time it had been
        opened.
        """
        self._window.imagehandler.page_available -= self._on_page_available
        self._window.filehandler.file_closed -= self._on_book_close
        self._window.page_changed -= self._on_page_change
        self._enhancer.signal_update -= self._follow_enhancer

    def _follow_enhancer(self) -> None:
        """Show what the enhancer holds, whoever changed it.

        Ctrl+I inverts the colours without the dialog; its checkbox
        would otherwise go on saying they were not, and the next move of
        any control would set them back from it.
        """
        self._block = True
        self._invert_color_button.set_active(self._enhancer.invert_color)
        self._block = False
        # The histogram is of the page as enhanced, which just changed.
        self._on_page_change()

    def _logarithmic_toggled(self, button: Gtk.CheckButton) -> None:
        prefs['histogram logarithmic'] = button.get_active()
        self._on_page_change()

    def _on_book_close(self) -> None:
        self.clear_histogram()

    def _on_page_change(self) -> None:
        if not self._window.imagehandler.page_is_available():
            self.clear_histogram()
            return
        # The histogram describes the current page alone, even when a
        # second one is shown beside it: the enhancements it drives are
        # applied to both, and two histograms would not say which.
        # And of the page as the enhancements leave it, which is what
        # the sliders are moved to judge (upstream feature request 70);
        # a page cut down to the histogram's own width first, since a
        # count of each colour hardly changes with the size and the
        # sliders redraw it as they move.
        pixbuf = image_tools.fit_in_rectangle(
            self._window.imagehandler.get_pixbufs(1)[0],
            self._HISTOGRAM_SOURCE_SIZE, self._HISTOGRAM_SOURCE_SIZE,
            scaling_quality=GdkPixbuf.InterpType.BILINEAR)
        self.draw_histogram(self._enhancer.enhanced(pixbuf))

    def _on_page_available(self, page_number: int) -> None:
        current_page_number = self._window.imagehandler.get_current_page()
        if current_page_number == page_number:
            self._on_page_change()

    def draw_histogram(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        """Draw a histogram representing <pixbuf> in the dialog."""
        histogram_pixbuf = histogram.draw_histogram(
            pixbuf, logarithmic=prefs['histogram logarithmic'])
        self._hist_image.set_paintable(
            image_tools.pixbuf_to_texture(histogram_pixbuf))

    def clear_histogram(self) -> None:
        """Clear the histogram in the dialog."""
        self._hist_image.set_paintable(None)

    def _change_values(self, *args: object) -> None:
        if self._block:
            return

        self._enhancer.brightness = self._brightness_scale.get_value() + 1
        self._enhancer.contrast = self._contrast_scale.get_value() + 1
        self._enhancer.saturation = self._saturation_scale.get_value() + 1
        self._enhancer.sharpness = self._sharpness_scale.get_value() + 1
        self._enhancer.gamma = 2 ** self._gamma_scale.get_value()
        self._enhancer.autocontrast = self._autocontrast_button.get_active()
        self._contrast_scale.set_sensitive(
            not self._autocontrast_button.get_active())
        self._enhancer.invert_color = self._invert_color_button.get_active()
        # Ctrl+I toggles the inversion through an action with a state of
        # its own, the only enhancement that has one; left behind, that
        # state would make the next Ctrl+I set the colours to what they
        # already are.  The colours are already what the enhancer says,
        # so the state moves without running the action's own handler.
        self._window.actiongroup.get_action('invert_color').show_active(
            self._enhancer.invert_color)
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
            prefs['gamma'] = self._enhancer.gamma
            prefs['auto contrast'] = self._enhancer.autocontrast
            prefs['invert color'] = self._enhancer.invert_color

        elif response == Response.REJECT:
            self._show_values(prefs['brightness'], prefs['contrast'],
                              prefs['saturation'], prefs['sharpness'],
                              prefs['auto contrast'], prefs['invert color'],
                              prefs['gamma'])

    def _reset(self, *args: object) -> None:
        """Take every enhancement off, without saving: "Revert" goes
        back to what was saved, which is not this once it has been."""
        self._show_values(1.0, 1.0, 1.0, 1.0, False, False, 1.0)

    def _show_values(self, brightness: float, contrast: float,
                     saturation: float, sharpness: float,
                     autocontrast: bool, invert_color: bool,
                     gamma: float) -> None:
        """Set the controls to these values, and the pages with them."""
        self._block = True
        self._gamma_scale.set_value(_gamma_position(gamma))
        self._brightness_scale.set_value(brightness - 1.0)
        self._contrast_scale.set_value(contrast - 1.0)
        self._saturation_scale.set_value(saturation - 1.0)
        self._sharpness_scale.set_value(sharpness - 1.0)
        self._autocontrast_button.set_active(autocontrast)
        self._invert_color_button.set_active(invert_color)
        self._block = False
        self._change_values(self)


def open_dialog(action: Gio.SimpleAction, window: "main.MainWindow") -> None:
    """Create and display the (singleton) image enhancement dialog."""
    global _dialog

    if _dialog is None:
        _dialog = _EnhanceImageDialog(window)
    else:
        _dialog.present()


def _close_dialog(*args: object) -> None:
    """Destroy the image enhancement dialog."""
    global _dialog

    if _dialog is not None:
        _dialog.destroy()
        _dialog = None


# vim: expandtab:sw=4:ts=4
