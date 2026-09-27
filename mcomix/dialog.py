"""dialog.py - The window MComix' dialogs are built out of."""

from gi.repository import GLib, GObject, Gtk

from mcomix import widgets

import enum
import weakref
from collections.abc import Callable
from typing import Any


class Response(enum.IntEnum):

    """What a dialog answers with.

    These were Gtk.ResponseType, which GTK deprecated in 4.20 along with
    the Gtk.Dialog they belonged to.  The numbers are GTK's own and have
    to stay that way: an answer the user has asked to have remembered is
    written to the preferences file as its number, so renumbering them
    would turn every answer already stored into a different one.
    """

    NONE = -1
    REJECT = -2
    ACCEPT = -3
    DELETE_EVENT = -4
    OK = -5
    CANCEL = -6
    CLOSE = -7
    YES = -8
    NO = -9
    APPLY = -10
    HELP = -11


class Dialog(Gtk.Window):

    """A window with a content area and a row of buttons under it.

    This is what Gtk.Dialog was, which GTK deprecated in 4.10 without
    replacing: Gtk.AlertDialog answers for a message and two buttons,
    and everything else is meant to be an ordinary window that lays its
    own buttons out.  MComix has a dozen dialogs that are neither, so
    the shape they all shared lives here instead - the same
    add_button(), get_content_area(), response() and 'response' signal,
    over a Gtk.Window.

    A dialog is answered exactly once, whether by a button, by the
    escape key or by the window being closed.
    """

    __gtype_name__ = 'MComixDialog'

    __gsignals__ = {
        'response': (GObject.SignalFlags.RUN_LAST, None, (int,)),
    }

    #: What a Gtk.Dialog carried, and what a theme paints a dialog by:
    #: MComix' own stylesheet gives window.dialog the desktop's
    #: @dialog_bg_color, which is not the @window_bg_color a plain
    #: window gets, so without this every dialog MComix built was
    #: painted in a different colour from the ones GTK builds - its own
    #: file chooser beside the "save page as" one, say.
    _CSS_CLASS = 'dialog'

    # Any, because these go straight on to Gtk.Window's constructor,
    # which takes a value of the property's own type for each of the
    # hundred-odd properties a window has.
    def __init__(self, **kwargs: Any) -> None:  # type: ignore[explicit-any]  # straight on to Gtk.Window's own typed properties
        super().__init__(**kwargs)
        self.add_css_class(self._CSS_CLASS)
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                spacing=6)
        self._content.set_vexpand(True)
        self._button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                   spacing=6)
        self._button_row.set_halign(Gtk.Align.END)
        #: The button for each response.  Not _buttons: the file
        #: chooser keeps a list of its own under that name, and a base
        #: class has no business squatting on a plain one.
        self._response_buttons: dict[int, Gtk.Button] = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        widgets.pack(box, self._content, True, True, 0)
        widgets.pack(box, self._button_row, False, False, 0)
        super().set_child(box)
        # Closing the window answers the dialog, the way a Gtk.Dialog's
        # delete event did, so that whoever is waiting hears about it.
        self.connect('close-request', self._closed)
        escape = Gtk.ShortcutController()
        escape.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string('Escape'),
            Gtk.CallbackAction.new(_escaped)))
        self.add_controller(escape)
        #: What connect_while_open() connected, to disconnect on close.
        self._while_open: list[tuple[GObject.Object, int]] = []
        # After everything else that waits for it: nothing is left to
        # run once the dialog's widgets have let go of it.
        self.connect_after('unrealize', Dialog._release)
        # GTK 4.14 left a window it destroyed along with its parent still
        # pointing at that parent, which was then freed; freeing the
        # window afterwards disconnected its handlers from freed memory,
        # a segmentation fault.  The dialog lets go of the parent itself,
        # when the dialog is destroyed and when the parent is, after
        # GTK's own handler has run.
        self._parent_destroyed: int | None = None
        parent = self.get_transient_for()
        if parent is not None:
            dialog = weakref.ref(self)

            def parent_destroyed(parent: Gtk.Widget) -> None:
                still = dialog()
                if still is not None:
                    still._let_go_of_parent()

            self._parent_destroyed = parent.connect('destroy',
                                                    parent_destroyed)

    # -- What Gtk.Dialog offered ------------------------------------------

    def get_content_area(self) -> Gtk.Box:
        """The box a dialog puts what it is about into."""
        return self._content

    def add_button(self, label: str, response: int) -> Gtk.Button:
        """Add a button answering with <response>, and return it."""
        button = Gtk.Button.new_with_mnemonic(label)
        button.connect('clicked', lambda _button: self.response(response))
        self._button_row.append(button)
        self._response_buttons[response] = button
        return button

    def add_buttons(self, *args: "str | int") -> None:
        """Add several buttons, as label and response in turn."""
        for index in range(0, len(args) - 1, 2):
            label, response = args[index], args[index + 1]
            # The arguments come in pairs, which a variadic cannot say:
            # to the checker every one of them is a label or a response.
            assert isinstance(label, str) and isinstance(response, int)
            self.add_button(label, response)

    def add_action_widget(self, widget: Gtk.Widget, response: int) -> None:
        """Put <widget> in the button row, answering with <response>.

        Whatever it is, it answers when it is activated: a Gtk.Button
        when it is clicked, anything else through its 'activate' signal,
        which is what Gtk.Dialog did with it.
        """
        if isinstance(widget, Gtk.Button):
            widget.connect('clicked', lambda _w: self.response(response))
        else:
            widget.connect('activate', lambda _w: self.response(response))
        self._button_row.append(widget)

    def get_widget_for_response(self, response: int) -> "Gtk.Button | None":
        """The button that answers with <response>, if there is one."""
        return self._response_buttons.get(response)

    def set_default_response(self, response: int) -> None:
        """Make the button for <response> the one Enter presses."""
        button = self._response_buttons.get(response)
        if button is not None:
            self.set_default_widget(button)

    def set_response_sensitive(self, response: int, sensitive: bool) -> None:
        """Enable or disable the button for <response>."""
        button = self._response_buttons.get(response)
        if button is not None:
            button.set_sensitive(sensitive)

    def response(self, response: int) -> None:
        """Answer the dialog with <response>."""
        self.emit('response', response)

    def connect_while_open(self, instance: GObject.Object, signal: str, handler: Callable[..., object], *args: object) -> None:  # type: ignore[explicit-any]  # a handler takes what the signal hands over
        """Connect <handler> to <signal> on <instance> until the dialog
        is closed.

        For a handler on something that is not one of the dialog's own
        widgets - an adjustment, a selection, a model - and that closes
        over the dialog.  Whatever holds that object in C holds the
        handler where Python's collector cannot see it, and that would
        keep the closed dialog alive for good.
        """
        self._while_open.append(
            (instance, instance.connect(signal, handler, *args)))

    def _let_go_of_parent(self) -> None:
        """Stop pointing at the window the dialog was over."""
        parent = self.get_transient_for()
        if parent is not None and self._parent_destroyed is not None:
            parent.disconnect(self._parent_destroyed)
        self._parent_destroyed = None
        self.set_transient_for(None)

    def destroy(self) -> None:
        self._let_go_of_parent()
        super().destroy()

    def _release(self) -> None:
        """Let go of everything that would keep the closed dialog alive."""
        widgets.release(self)
        for instance, handler in self._while_open:
            instance.disconnect(handler)
        self._while_open.clear()

    # -- Where the answers come from --------------------------------------

    def _closed(self, *args: object) -> bool:
        self.emit('response', Response.DELETE_EVENT)
        # False: the window goes on closing, which is what a Gtk.Dialog
        # did with its delete event.
        return False

    def _escaped(self) -> bool:
        # DELETE_EVENT, not CANCEL: escape closed a Gtk.Dialog, which
        # answered with the response its delete event did, and that is
        # what MComix' dialogs are written against - the enhancement
        # dialog answers DELETE_EVENT and OK alike and did not close on
        # escape at all while this said CANCEL.
        self.emit('response', Response.DELETE_EVENT)
        return True


def _escaped(widget: Gtk.Widget, args: "GLib.Variant | None") -> bool:
    """Answer the dialog the escape key was pressed in.

    A function rather than the dialog's own method: GTK holds the
    callback of a Gtk.CallbackAction where Python's collector cannot
    see it, so a bound method there would keep the dialog alive for
    good.  GTK hands over the widget the shortcut belongs to instead.
    """
    assert isinstance(widget, Dialog)
    return widget._escaped()

# vim: expandtab:sw=4:ts=4
