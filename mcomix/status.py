"""status.py - Statusbar for main window."""

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from mcomix import i18n
from mcomix import widgets
from mcomix import constants
from mcomix.preferences import prefs
from mcomix.i18n import _

from collections.abc import Sequence


def format_page_number(pages: Sequence[int], total: int) -> str:
    """"1,2 / 10": the pages on screen out of the whole book.

    <pages> are listed in the order they read in, which is right to
    left in manga mode, so that they line up with the file names and
    the resolutions the same screen is described by.
    """
    return '%s / %d' % (','.join('%d' % page for page in pages), total)


class _Field(Gtk.Label):

    """One field of the status bar.

    It asks for at least the room of the widest text it has been told
    to hold, so that a page whose number, size or name is shorter than
    the last one's does not move the fields after it.  It only asks:
    where the window is too narrow for the whole bar, it gives way and
    is ellipsized.
    """

    __gtype_name__ = 'MComixStatusField'

    def __init__(self, name: bool, tabular: bool) -> None:
        """A field holding a <name>, cut short in the middle where it
        does not fit so that its end stays, or a number, aligned to its
        end so that the digits that change are the ones that move;
        <tabular> gives every digit the same width."""
        super().__init__()
        if tabular:
            attributes = Pango.AttrList()
            attributes.insert(Pango.attr_font_features_new('tnum=1'))
            self.set_attributes(attributes)
        self.set_xalign(0 if name else 1)
        self.set_ellipsize(Pango.EllipsizeMode.MIDDLE if name
                           else Pango.EllipsizeMode.END)
        self._held = 0

    def hold(self, text: str) -> None:
        """Keep room for <text>, from now until let_go()."""
        layout = self.create_pango_layout(text)
        layout.set_attributes(self.get_attributes())
        width = layout.get_pixel_size()[0]
        if width > self._held:
            self._held = width
            self.queue_resize()

    def let_go(self) -> None:
        """Forget the room held, for a book whose texts are new."""
        if self._held:
            self._held = 0
            self.queue_resize()

    def do_measure(self, orientation: Gtk.Orientation,
                   for_size: int) -> tuple[int, int, int, int]:
        minimum, natural, minimum_baseline, natural_baseline = (
            Gtk.Label.do_measure(self, orientation, for_size))
        if orientation == Gtk.Orientation.HORIZONTAL:
            natural = max(natural, self._held)
        return minimum, natural, minimum_baseline, natural_baseline


class Statusbar(Gtk.Box, widgets.Releasable):

    """The status bar along the bottom of the window.

    One label per field, rather than one line joining them with "|":
    the line moved every field after one whose text changed width, and
    cut off the last fields first where it was too long.  Each field
    now keeps the width of the widest text it has shown in the book,
    and the window gives way in the longest of them.
    """

    #: The room, in pixels, at either end of the bar and either side
    #: of a separator.
    SPACING = 16

    def __init__(self) -> None:
        super().__init__()

        self._loading = True

        # Gtk.Statusbar is deprecated as of GTK 4.10, and its message
        # stack was never used here.  A message, such as an error,
        # takes the place of the fields until they are next updated.
        self.message = Gtk.Label()
        self.message.set_xalign(0)
        self.message.set_hexpand(True)
        self.message.set_ellipsize(Pango.EllipsizeMode.END)
        self.message.set_margin_start(self.SPACING)
        self.message.set_margin_end(self.SPACING)
        self.message.set_visible(False)
        self.append(self.message)

        #: The label of each field, and the separator before it, by
        #: the field's bit.
        self._fields: dict[int, _Field] = {}
        self._separators: dict[int, Gtk.Separator] = {}
        fields = Gtk.Box()
        fields.set_hexpand(True)
        fields.set_margin_start(self.SPACING)
        fields.set_margin_end(self.SPACING)
        for name, label, bit in self.FIELDS:
            separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            separator.set_margin_start(self.SPACING)
            separator.set_margin_end(self.SPACING)
            separator.set_visible(False)
            fields.append(separator)
            self._separators[bit] = separator
            field = _Field(name in self._NAMES, name in self._TABULAR)
            field.set_visible(False)
            fields.append(field)
            self._fields[bit] = field
        self._field_box = fields
        self.append(fields)
        self.connect('realize', self._keep_one_height)

        # Create popup menu for enabling/disabling status boxes.
        #: The action behind each field's tick, by field name.  Kept
        #: rather than looked up again: Gio.ActionMap.lookup_action()
        #: answers with the Gio.Action interface, which has no way to
        #: set a state, and with None for a name that was never added.
        self._field_toggles: dict[str, Gio.SimpleAction] = {}
        self._fields_menu = self._create_fields_menu()

        # Hook mouse release event
        clicks = Gtk.GestureClick()
        clicks.set_button(0)
        clicks.connect('released', self._button_released)
        self.add_controller(clicks)

        # Default status information
        self._page_info = ''
        #: The widest text the page field can hold in this book.
        self._page_widest = ''
        self._file_info = ''
        self._file_widest = ''
        self._resolution = ''
        self._root = ''
        self._filename = ''
        self._filesize = ''
        self._date = ''
        #: The full path of the file being read, which no field shows
        #: whole; "Copy path" copies it.
        self._path = ''
        self._update_sensitivity()
        self.set_visible(True)

        self._loading = False

    #: Text in the scripts whose fallback fonts set the tallest lines,
    #: measured for the height every line of the status bar is given.
    _TALLEST_LINE = 'Ag \u6f22\u5b57 \ud55c\uae00 \u0639\u0631\u0628\u064a'

    def _keep_one_height(self, bar: Gtk.Widget) -> None:
        """Make the status bar as tall as its tallest script needs.

        Pango takes a character the interface font lacks from a fallback
        font, whose lines can be taller: a file name in Japanese or
        Korean made the bar 22 pixels high instead of 18, and the page
        area above it moved and rescaled the page at every file whose
        name was in another script (upstream bug 148).
        """
        layout = bar.create_pango_layout(self._TALLEST_LINE)
        bar.set_size_request(-1, layout.get_pixel_size()[1])

    def release(self) -> None:
        """Let go of the field actions once the window has closed.

        Each holds this statusbar's method in C, where the collector
        cannot see it, and the group and the dictionary here hold the
        actions: the statusbar outlived its window.
        """
        widgets.empty_action_group(self._field_actions)
        self._field_toggles.clear()

    def set_message(self, message: str) -> None:
        """Show <message> (such as an error message) in place of the
        fields, replacing whatever was there earlier.
        """
        self.message.set_text(message)
        self.message.set_visible(True)
        self._field_box.set_visible(False)

    def set_page_number(self, pages: Sequence[int], total: int) -> None:
        """Update the page number, from the pages on screen."""
        self._page_info = format_page_number(pages, total)
        # Every digit is as wide as any other, so the widest number of
        # this many pages is the total's.
        self._page_widest = format_page_number([total] * len(pages), total)

    def get_page_number(self) -> str:
        """Returns the bar's page information."""
        return self._page_info

    def set_file_number(self, fileno: int, total: int) -> None:
        """Updates the file number (i.e. number of current file/total
        files loaded)."""
        if total > 0:
            self._file_info = '(%d / %d)' % (fileno, total)
            self._file_widest = '(%d / %d)' % (total, total)
        else:
            self._file_info = self._file_widest = ''

    def get_file_number(self) -> str:
        """ Returns the bar's file information."""
        return self._file_info

    def set_resolution(
            self,
            dimensions: Sequence[Sequence[float]]) -> None:  # 2D only
        """Update the resolution data.

        Takes an iterable of tuples, (x, y, scale, distorted), describing the
        original resolution of an image as well as the currently displayed
        scale and whether scaling was done irrespective of aspect ratio,
        resulting in a distorted image.
        """
        self._resolution = ', '.join(
            '%dx%d (%.1f%%%s)' % (width, height, scale * 100.0,
                                  '*' if distorted else '')
            for width, height, scale, distorted in dimensions)

    def set_root(self, root: str) -> None:
        """Set the name of the root (directory or archive).

        Another root is another book, whose fields hold widths of their
        own.
        """
        root = i18n.to_display_string(i18n.to_unicode(root))
        if root != self._root:
            for field in self._fields.values():
                field.let_go()
        self._root = root

    def set_filename(self, filename: str) -> None:
        """Update the filename."""
        self._filename = i18n.to_display_string(i18n.to_unicode(filename))

    def set_path(self, path: str | None) -> None:
        """Note the full path of the file being read: the archive, or
        the picture on screen in a folder."""
        self._path = path or ''

    def set_date(self, date: str) -> None:
        """Update the date the file being read was last modified."""
        self._date = date

    def set_filesize(self, size: str | None) -> None:
        """Update the filesize."""
        if size is None:
            size = ""
        self._filesize = size

    def update(self) -> None:
        """Set the statusbar to display the current state."""
        self.message.set_visible(False)
        self._field_box.set_visible(True)
        widest = {constants.STATUS_PAGE: self._page_widest,
                  constants.STATUS_FILENUMBER: self._file_widest}
        # Only the fields that have something to say: before a book is
        # open none of them has, and the bar was a row of bare
        # separators; a file whose size is not known left one in the
        # middle of the line.
        shown_before = False
        for bit, text in self._field_texts():
            field = self._fields[bit]
            shown = bool(prefs['statusbar fields'] & bit and text)
            field.set_text(text if shown else '')
            field.set_visible(shown)
            self._separators[bit].set_visible(shown and shown_before)
            if shown:
                field.hold(text)
                if bit in widest:
                    field.hold(widest[bit])
            shown_before = shown_before or shown

    def _field_texts(self) -> list[tuple[int, str]]:
        """The text of every field, by its bit, in the bar's order."""
        return [(constants.STATUS_PAGE, self._page_info),
                (constants.STATUS_FILENUMBER, self._file_info),
                (constants.STATUS_RESOLUTION, self._resolution),
                (constants.STATUS_PATH, self._root),
                (constants.STATUS_FILENAME, self._filename),
                (constants.STATUS_FILESIZE, self._filesize),
                (constants.STATUS_DATE, self._date)]

    #: The fields the popup offers, and the bit each one stands for.
    FIELDS = (('pagenumber', _('Show page numbers'), constants.STATUS_PAGE),
              ('filenumber', _('Show file numbers'), constants.STATUS_FILENUMBER),
              ('resolution', _('Show resolution'), constants.STATUS_RESOLUTION),
              ('rootpath', _('Show path'), constants.STATUS_PATH),
              ('filename', _('Show filename'), constants.STATUS_FILENAME),
              ('filesize', _('Show filesize'), constants.STATUS_FILESIZE),
              ('date', _('Show date modified'), constants.STATUS_DATE))

    #: The fields that hold a name rather than a number.
    _NAMES = ('rootpath', 'filename')
    #: The fields whose digits are set all as wide as one another: in
    #: the interface font "1111" was 24 pixels wide and "8888" 37, so
    #: the page number grew and shrank as it counted.  Not the names
    #: or the date: the font's tabular forms space out the hyphens and
    #: colons too, and the date, last on the line, moves nothing.
    _TABULAR = ('pagenumber', 'filenumber', 'resolution', 'filesize')

    def _create_fields_menu(self) -> Gtk.PopoverMenu:
        """Build the right-click menu that picks which fields are shown."""
        self._field_actions = Gio.SimpleActionGroup()
        fields = Gio.Menu()
        for name, label, bit in self.FIELDS:
            action = Gio.SimpleAction.new_stateful(
                name, None, GLib.Variant('b', bool(prefs['statusbar fields'] & bit)))
            action.connect('change-state', self.toggle_status_visibility, bit)
            self._field_actions.add_action(action)
            self._field_toggles[name] = action
            fields.append(label, 'statusbar.%s' % name)
        # What the bar shows, to paste elsewhere (upstream feature
        # request 14).
        copies = Gio.Menu()
        for name, label in self.COPIES:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', self._copy, name)
            self._field_actions.add_action(action)
            copies.append(label, 'statusbar.%s' % name)
        model = Gio.Menu()
        model.append_section(None, fields)
        model.append_section(None, copies)
        self.insert_action_group('statusbar', self._field_actions)
        return Gtk.PopoverMenu.new_from_model(model)

    #: The entries that copy what the bar knows of the file being read.
    COPIES = (('copy-filename', _('Copy file name')),
              ('copy-path', _('Copy path')))

    def _copied_text(self, name: str) -> str:
        """What the entry <name> of COPIES copies: the file name as the
        bar shows it, both of a double page's, or the full path."""
        return self._filename if name == 'copy-filename' else self._path

    def _copy(self, action: Gio.SimpleAction, parameter: object,
              name: str) -> None:
        self._put_on_clipboard(self._copied_text(name))

    @staticmethod
    def _put_on_clipboard(text: str) -> None:
        widgets.display().get_clipboard().set_content(
            Gdk.ContentProvider.new_for_value(text))

    def toggle_status_visibility(self, action: Gio.SimpleAction,
                                 value: GLib.Variant, bit: int) -> None:
        """ Called when status entries visibility is to be changed. """
        action.set_state(value)

        # Ignore events as long as control is still loading.
        if self._loading:
            return

        if value.get_boolean():
            prefs['statusbar fields'] |= bit
        else:
            prefs['statusbar fields'] &= ~bit

        self.update()

    def _button_released(self, gesture: Gtk.GestureClick, n_press: int,
                         x: float, y: float) -> None:
        """ Triggered when a mouse button is released to open the context
        menu. """
        if gesture.get_current_button() == 3:
            for name, label in self.COPIES:
                widgets.simple_action(self._field_actions, name).set_enabled(
                    bool(self._copied_text(name)))
            widgets.popup_at(self._fields_menu, self, x, y)

    def _update_sensitivity(self) -> None:
        """ Brings the popup's ticks in line with the preferences. """
        for name, label, bit in self.FIELDS:
            self._field_toggles[name].set_state(
                GLib.Variant('b', bool(prefs['statusbar fields'] & bit)))


# vim: expandtab:sw=4:ts=4
