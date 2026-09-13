"""file_chooser_base_dialog.py - Custom FileChooserDialog implementations."""

import os
import mimetypes
import fnmatch
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from collections.abc import Iterable, Iterator, Sequence
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from gi.repository import GdkPixbuf

from mcomix.preferences import prefs
from mcomix.dialog import Dialog
from mcomix import image_tools
from mcomix import archive_tools
from mcomix import labels
from mcomix import widgets
from mcomix import constants
from mcomix import log
from mcomix import preview
from mcomix import thumbnail_tools
from mcomix import message_dialog
from mcomix import file_provider
from mcomix import tools
from mcomix.i18n import _
from mcomix.dialog import Response

mimetypes.init()

#: How large a preview is on a screen that has nothing to say about it.
_PREVIEW_SIZE = 128
#: How wide the name and size under a preview are allowed to be.
_PREVIEW_LABEL_WIDTH = 18


def preview_size(widget: Gtk.Widget) -> tuple[int, int]:
    """Return how large a preview should be, and what to render it at.

    The size follows the screen, as every other preview in MComix does.
    What it is rendered at follows the scale factor as well: a picture
    drawn from more pixels than it is given is sharp, where one drawn
    from fewer is not.
    """
    size = preview.scaled(_PREVIEW_SIZE, widget)
    return size, size * max(1, widget.get_scale_factor())


#: How wide the places on the left are opened, which GTK4 leaves at
#: 140 - enough for "Zuletzt v..." but not for "Zuletzt verwendet".
_PLACES_WIDTH = 220

#: The formats a comic reader is asked for, before the rest.
_COMMON_ARCHIVES = ('ZIP', 'RAR', '7z', 'Tar', 'PDF')
_COMMON_IMAGES = ('JPEG', 'PNG', 'WEBP', 'GIF', 'AVIF', 'JXL', 'TIFF', 'BMP')


def _by_familiarity(names: Iterable[str], common: Sequence[str]) -> list[str]:
    """<names>, with the ones a reader expects first."""
    known = [name for name in common if name in names]
    return known + sorted(name for name in names if name not in known)


class _BaseFileChooserDialog(Dialog):

    """We roll our own FileChooserDialog because the one in GTK seems
    buggy with the preview widget. The <action> argument dictates what type
    of filechooser dialog we want (i.e. it is Gtk.FileChooserAction.OPEN
    or Gtk.FileChooserAction.SAVE).

    This is a base class for the _MainFileChooserDialog, the
    _LibraryFileChooserDialog and the SimpleFileChooserDialog.  It opens
    in <folder>, or wherever the last thing that was opened came from.

    Subclasses should implement a method files_chosen(paths) that will be
    called once the filechooser has done its job and selected some files.
    If the dialog was closed or Cancel was pressed, <paths> is the empty list.
    """

    _last_activated_file: str | None = None

    #: The name set_save_name() offered, which the chooser will not say
    #: again: Gtk.FileChooser.get_current_name() is deprecated with the
    #: rest of the interface.
    save_name: str | None = None

    def __init__(self, action: Gtk.FileChooserAction = Gtk.FileChooserAction.OPEN,
                 parent: "Gtk.Window | None" = None,
                 folder: str | None = None) -> None:
        self._action = action
        self._destroyed = False

        if action == Gtk.FileChooserAction.OPEN:
            title = _('Open')
            buttons = (_('_Cancel'), Response.CANCEL,
                       _('_Open'), Response.OK)

        else:
            title = _('Save')
            buttons = (_('_Cancel'), Response.CANCEL,
                       _('_Save'), Response.OK)

        if parent is None:
            # This dialog maps itself at the end of construction, so a
            # transient parent set afterwards comes too late: GTK warns
            # about the dialog it mapped without one.
            from mcomix import main
            parent = main.main_window()
        super().__init__(title=title, transient_for=parent)
        #: The buttons, wherever they ended up.
        self._buttons: list[Gtk.Button] = []
        #: What set_note() says under the file list, once there is one.
        self._note: "Gtk.Label | None" = None
        #: Whether the chooser's filter menu has been moved aside.
        self._filter_moved = False

        #: The search box and the list of files, where the arrow keys
        #: are made to lead from one into the other.
        self._search: "Gtk.SearchEntry | None" = None
        self._listing: "Gtk.ColumnView | None" = None
        #: What each filter was built to match, by filter.
        self._filter_rules: dict[Gtk.FileFilter,
                                 tuple[Sequence[str], Sequence[str]]] = {}
        #: One-format filters, held back so the groups can come first:
        #: the name, the mime types and the patterns each was built for.
        self._pending_filters: list[tuple[str, Iterable[str], Sequence[str]]] = []
        self.filechooser = Gtk.FileChooserWidget(action=action)
        # The preview sits beside the list rather than inside it, so the
        # dialog wants more height than width.
        self.filechooser.set_size_request(640, 560)
        # GTK4 has no set_preview_widget(): the chooser will not hold
        # anything of ours any more, so the preview goes beside it.
        chooser_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
        widgets.pack(chooser_row, self.filechooser, True, True, 0)
        widgets.pack(self.get_content_area(), chooser_row, True, True, 0)
        widgets.set_border(self, 4)
        widgets.set_border(self.filechooser, 6)
        self.connect('response', self._response)
        # GTK4's Gtk.FileChooserWidget has no signals at all, so a
        # double click no longer reaches file-activated; a click gesture
        # on the widget is what is left to hear it.
        activate = Gtk.GestureClick()
        activate.set_button(1)
        activate.connect('pressed', self._activated)
        self.filechooser.add_controller(activate)

        self._walk_from_search_into_the_list()

        self._preview_size, self._preview_pixels = preview_size(self)
        preview_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 10)
        preview_box.set_size_request(self._preview_size + 22, -1)
        # The preview and what it says about the file sit together in
        # the middle of the column, rather than filling it.
        preview_box.set_valign(Gtk.Align.CENTER)
        widgets.set_border(preview_box, 6)
        # A Gtk.Image draws whatever it is given at an icon size in
        # GTK4; a picture draws it at its own.
        self._preview_image = Gtk.Picture()
        self._preview_image.set_size_request(self._preview_size,
                                             self._preview_size)
        # A picture scales what it holds to whatever room it is given,
        # so a thumbnail came out blurred and grew and shrank with the
        # dialog.  SCALE_DOWN never draws above the real size, and the
        # alignments keep the box from handing it any more room.
        self._preview_image.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        self._preview_image.set_halign(Gtk.Align.CENTER)
        self._preview_image.set_valign(Gtk.Align.CENTER)
        widgets.pack(preview_box, self._preview_image, False, False, 0)

        pango_scale_small = (1 / 1.2)

        self._namelabel = labels.FormattedLabel(weight=Pango.Weight.BOLD,
                                                scale=pango_scale_small)
        self._namelabel.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        widgets.pack(preview_box, self._namelabel, False, False, 0)

        self._sizelabel = labels.FormattedLabel(scale=pango_scale_small)
        self._sizelabel.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        widgets.pack(preview_box, self._sizelabel, False, False, 0)

        # An ellipsized label still asks for room enough for all of its
        # text, so the column - and with it the file list beside it -
        # moved every time the name under the preview changed.  Holding
        # the labels to a width stops that.
        for label in (self._namelabel, self._sizelabel):
            label.set_max_width_chars(_PREVIEW_LABEL_WIDTH)
            label.set_width_chars(_PREVIEW_LABEL_WIDTH)
        preview_box.set_visible(True)
        widgets.pack(chooser_row, preview_box, False, False, 0, end=True)

        # And no update-preview to hear either - a GTK4
        # Gtk.FileChooserWidget has no signals at all - so ask it what is
        # selected every so often.  It is one property read; the timer
        # goes when the dialog does.
        self._previewed: str | None = None
        self._preview_timer: int | None = GLib.timeout_add(200, self._poll_preview)
        # 'unrealize', not 'destroy': GTK4 emits the latter when the last
        # reference to the window goes rather than when it is destroyed,
        # and the handler is a method of the window, so the closure held
        # one and the timer went on polling a destroyed chooser every
        # 200 ms for the rest of the session.  Nothing here hides the
        # dialog, which is the other thing that unrealizes a window.
        self.connect('unrealize', self._stop_previewing)

        self.place_buttons(buttons)
        # Only once the pane has been laid out; a position set before
        # that is forgotten.
        self.connect('map', self._widen_the_places)

        self._all_files_filter = self.add_filter(_('All files'), [], ['*'])

        try:
            current_file = self._current_file()
            last_file = self.__class__._last_activated_file

            # Where the caller said, if it said.  It has to be settled
            # here rather than afterwards: the chooser loads whatever
            # folder it was given asynchronously, and a folder set once
            # that is under way is lost when the load finishes.
            if folder is not None:
                widgets.set_chooser_folder(self.filechooser, folder)
            # If a file is currently open, use its path
            elif current_file and os.path.exists(current_file):
                widgets.set_chooser_folder(self.filechooser,
                                           os.path.dirname(current_file))
            # If no file is open, use the last stored file
            elif (last_file and os.path.exists(last_file)):
                widgets.set_chooser_file(self.filechooser, last_file)
            # If no file was stored yet, fall back to preferences
            elif os.path.isdir(prefs['path of last browsed in filechooser']):
                if prefs['store recent file info']:
                    widgets.set_chooser_folder(
                        self.filechooser,
                        prefs['path of last browsed in filechooser'])
                else:
                    widgets.set_chooser_folder(self.filechooser,
                                               constants.HOME_DIR)

        except Exception as ex:  # E.g. broken prefs values.
            log.debug(ex)

        self.set_visible(True)

    def _widen_the_places(self, *args: object) -> None:
        """Give the places on the left room for their own names.

        GTK4 puts the sidebar in a Gtk.Paned and opens it at a fixed
        position, which cuts "Zuletzt verwendet" down to "Zuletzt v...".
        The sidebar knows how wide it would like to be; the pane can be
        opened there instead, and dragged from there afterwards.
        """
        paned = cast('Gtk.Paned | None',
                     self._descendant(self.filechooser, Gtk.Paned))
        if paned is None:
            return
        places = paned.get_start_child()
        if places is None:
            return
        # Neither the sidebar nor the names in it say how wide they
        # would like to be - both ellipsize, so both ask for what they
        # can be squeezed to - so open the pane wide enough for a name
        # instead, and leave it draggable from there.
        if paned.get_position() < _PLACES_WIDTH:
            GLib.idle_add(paned.set_position, _PLACES_WIDTH)

    def place_buttons(self, buttons: "Sequence[str | int]") -> None:
        """Put <buttons> - label, response, label, response - in the row
        the chooser keeps its filter menu in.

        GTK4's Gtk.FileChooserWidget holds that menu in a Gtk.ActionBar
        of its own and a Gtk.Dialog holds its buttons in another, so the
        two came out on separate rows, one above the other.  That bar is
        an ordinary Gtk.ActionBar, so the buttons can join it and the
        filter can move to its other end, which is where a file dialog
        has always put the two.

        Nothing in the API promises that bar is there, so if it cannot
        be found the buttons go back in the dialog's own row.
        """
        for button in self._buttons:
            parent = button.get_parent()
            if parent is not None:
                bar = button.get_ancestor(Gtk.ActionBar)
                if bar is not None:
                    bar.remove(button)
                elif isinstance(parent, Gtk.Box):
                    parent.remove(button)
        self._buttons = []

        # The arguments come in pairs, which a sequence cannot say: to
        # the checker every one of them is a label or a response.
        pairs = [(label, response)
                 for label, response in zip(buttons[::2], buttons[1::2])
                 if isinstance(label, str) and isinstance(response, int)]
        bar = self._filter_action_bar()
        if bar is None:
            for label, response in pairs:
                self._buttons.append(self.add_button(label, response))
            self.set_default_response(Response.OK)
            return

        # pack_end() puts each new child nearer the start of the end
        # group, so the last one named ends up furthest left.
        for label, response in reversed(pairs):
            button = Gtk.Button(label=label, use_underline=True)
            button.connect('clicked', self._button_clicked, response)
            bar.pack_end(button)
            self._buttons.append(button)
            if response == Response.OK:
                button.add_css_class('suggested-action')
                self.set_default_widget(button)
        bar.set_revealed(True)

    def _button_clicked(self, _button: Gtk.Button, response: int) -> None:
        self.response(response)

    def _filter_action_bar(self) -> "Gtk.ActionBar | None":
        """The chooser's own action bar, with its filter moved aside."""
        menu = self._descendant(self.filechooser, Gtk.DropDown)
        if menu is None:
            return None
        bar = menu.get_ancestor(Gtk.ActionBar)
        packed = menu.get_parent()
        if bar is None or packed is None:
            return None
        if not self._filter_moved:
            # The filter is packed at the end, where the buttons belong;
            # move it to the other one, once.
            try:
                bar.remove(packed)
                bar.pack_start(packed)
            except Exception:
                return None
            self._filter_moved = True
        return bar

    @staticmethod
    def _descendant(widget: Gtk.Widget, kind: type) -> "Gtk.Widget | None":
        """The first child of <widget> that is a <kind>, at any depth.

        Not one inside a popover: what a menu or a dropdown holds hangs
        off the widget rather than standing in it, and the chooser has a
        search box and a list of its own inside the filter dropdown.
        """
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, kind):
                return child
            if not isinstance(child, Gtk.Popover):
                found = _BaseFileChooserDialog._descendant(child, kind)
                if found is not None:
                    return found
            child = child.get_next_sibling()
        return None

    def set_note(self, text: str) -> None:
        """Say <text> under the file list.

        Gtk.FileChooser.set_extra_widget() is what said it up to GTK3.
        GTK4 has no such thing - the call raised AttributeError rather
        than showing anything - so the note belongs to the dialog around
        the chooser instead.
        """
        if self._note is None:
            self._note = Gtk.Label()
            self._note.set_xalign(0)
            widgets.pack(self.get_content_area(), self._note,
                         False, False, 6, end=True)
        self._note.set_text(text)

    def _walk_from_search_into_the_list(self) -> None:
        """Let the arrow keys carry on from the search box into the list.

        Typing in a Gtk.FileChooserWidget searches, and what it finds is
        listed under the box being typed into - but the arrows stay in
        the box, so the only way to a result is the mouse.  Down goes to
        the first one, and up from there comes back to the box.
        """
        self._search = cast('Gtk.SearchEntry | None',
                            self._descendant(self.filechooser, Gtk.SearchEntry))
        self._listing = cast('Gtk.ColumnView | None',
                             self._descendant(self.filechooser, Gtk.ColumnView))
        if self._search is None or self._listing is None:
            return

        for widget, pressed in ((self._search, self._into_the_list),
                                (self._listing, self._back_to_the_search)):
            keys = Gtk.EventControllerKey()
            # Before the widget's own handling, which would otherwise
            # take the arrow key for itself.
            keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            keys.connect('key-pressed',
                         lambda _c, keyval, _code, _state, answer=pressed:
                         answer(keyval))
            widget.add_controller(keys)

    def _into_the_list(self, keyval: int) -> bool:
        """Down out of the search box: the first thing it found."""
        if self._listing is None or keyval not in (Gdk.KEY_Down,
                                                   Gdk.KEY_KP_Down):
            return False
        # A Gtk.SelectionModel is a Gio.ListModel as well, whatever the
        # introspection data says of it.
        model = cast("Gio.ListModel[GObject.Object] | None",
                     self._listing.get_model())
        if model is None or not model.get_n_items():
            return False
        self._listing.grab_focus()
        cast(Gtk.SelectionModel, model).select_item(0, True)
        return True

    def _back_to_the_search(self, keyval: int) -> bool:
        """Up off the top of the list: back to the search box."""
        if self._search is None or self._listing is None \
                or keyval not in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            return False
        model = self._listing.get_model()
        if model is None:
            return False
        # Only off the top: anywhere else up is the row above, which is
        # what the list does with it itself.
        selected = model.get_selection()
        if selected.is_empty() or selected.get_minimum() != 0:
            return False
        self._search.grab_focus()
        return True

    def list_filters(self) -> list[Gtk.FileFilter]:
        """The filters the chooser offers, in the order they were added.

        Gtk.FileChooser.list_filters() is get_filters() in GTK4, and it
        answers with a Gio.ListModel rather than a list.
        """
        model = self.filechooser.get_filters()
        return [filter for filter in
                (model.get_item(index) for index in range(model.get_n_items()))
                if filter is not None]

    def add_filter(self, name: str, mimes: Iterable[str],
                   patterns: Iterable[str] = ()) -> Gtk.FileFilter:
        """Add a filter, called <name>, for each mime type in <mimes> and
        each pattern in <patterns> to the filechooser.
        """
        # Gtk.FileFilter.add_custom() is gone in GTK4, and with it
        # Gtk.FileFilterInfo and Gtk.FileFilter.filter().  A filter built
        # from mime types and patterns matches a file that answers any
        # one of them, which is what the callback said.  What it matched
        # on is kept here as well, for the walk below that has no chooser
        # to ask.
        ffilter = Gtk.FileFilter()
        for mime in mimes:
            ffilter.add_mime_type(mime)
        for pattern in patterns:
            ffilter.add_pattern(pattern)
        self._filter_rules[ffilter] = (tuple(patterns), tuple(mimes))

        ffilter.set_name(name)
        self.filechooser.add_filter(ffilter)
        return ffilter

    def add_archive_filters(self) -> None:
        """Offer the archive formats, everything before one format."""
        self._add_group(_('All archives'), _('%s archives'),
                        archive_tools.get_supported_formats(),
                        _COMMON_ARCHIVES)

    def add_image_filters(self) -> None:
        """Offer the image formats, everything before one format."""
        self._add_group(_('All images'), _('%s images'),
                        image_tools.get_supported_formats(),
                        _COMMON_IMAGES)

    def _add_group(self, everything: str, one: str,
                   supported_formats: dict[str, tuple[set[str], set[str]]],
                   common: Sequence[str]) -> None:
        """Add a filter for all of <supported_formats> and one for each.

        The list was in alphabetical order, which put ANI, APM and APNG
        ahead of JPEG and PNG - true, and no use to anyone looking for a
        comic.  The formats a reader actually opens come first now, in
        the order below, and the rest follow alphabetically after them.
        """
        ffilter = Gtk.FileFilter()
        ffilter.set_name(everything)
        self.filechooser.add_filter(ffilter)
        all_mimes: list[str] = []
        all_patterns: list[str] = []
        for name in _by_familiarity(supported_formats, common):
            mime_types, extensions = supported_formats[name]
            patterns = ['*.%s' % ext for ext in extensions]
            self._pending_filters.append((one % name, mime_types, patterns))
            all_mimes.extend(mime_types)
            all_patterns.extend(patterns)
            for mime in mime_types:
                ffilter.add_mime_type(mime)
            for pat in patterns:
                ffilter.add_pattern(pat)
        self._filter_rules[ffilter] = (tuple(all_patterns), tuple(all_mimes))

    def add_pending_filters(self) -> None:
        """Add the one-format filters held back while the groups were
        being offered, so that every "All ..." comes first."""
        for name, mimes, patterns in self._pending_filters:
            self.add_filter(name, mimes, patterns)
        self._pending_filters = []

    def _matches(self, ffilter: "Gtk.FileFilter | None", path: str,
                 mime_type: str | None) -> bool:
        """Whether <path> passes <ffilter>, by the rules it was built from."""
        match_patterns, match_mimes = (self._filter_rules.get(ffilter, ((), ()))
                                       if ffilter is not None else ((), ()))
        if mime_type in match_mimes:
            return True
        return any(fnmatch.fnmatch(path, pattern)
                   for pattern in match_patterns)

    def collect_files_from_subdir(self, path: str, filter: "Gtk.FileFilter | None",
                                  recursive: bool = False) -> Iterator[str]:
        """Yield the files under <path> that <filter> accepts.

        Only the files directly in <path>, unless <recursive> is set.
        The "All files" filter is let through by identity before the
        rules are consulted, although the "*" it was built with would
        match everything anyway.
        """

        for root, dirs, files in os.walk(path):
            for file in files:
                full_path = os.path.join(root, file)
                mimetype = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'

                if (filter == self._all_files_filter
                        or self._matches(filter, full_path, mimetype)):
                    yield full_path

            if not recursive:
                break

    def set_save_name(self, name: str) -> None:
        """Offer <name> as the name to save under."""
        self.save_name = name
        self.filechooser.set_current_name(name)

    def should_open_recursive(self) -> bool:
        return False

    def _activated(self, gesture: Gtk.GestureClick, n_press: int,
                   x: float, y: float) -> None:
        """Confirm the dialog when a file is double clicked."""
        if n_press == 2 and self.filechooser.get_file() is not None:
            self._response(self, Response.OK)

    def _response(self, widget: Gtk.Widget, response: int) -> None:
        """Return a list of the paths of the chosen files, or None if the
        event only changed the current directory.
        """
        if response == Response.OK:
            chosen = widgets.chooser_paths(self.filechooser)
            if not chosen:
                return

            # Collect files, if necessary also from subdirectories
            filter = self.filechooser.get_filter()
            paths = []
            for path in chosen:
                if os.path.isdir(path):
                    subdir_files = list(self.collect_files_from_subdir(path, filter,
                                                                       self.should_open_recursive()))
                    file_provider.FileProvider.sort_files(subdir_files)
                    paths.extend(subdir_files)
                else:
                    paths.append(path)

            # FileChooser.set_do_overwrite_confirmation() doesn't seem to
            # work on our custom dialog, so we use a simple alternative.
            first_path = chosen[0]
            if (self._action == Gtk.FileChooserAction.SAVE and
                    not os.path.isdir(first_path) and
                    os.path.exists(first_path)):

                overwrite_dialog = message_dialog.MessageDialog(
                    None, buttons=Gtk.ButtonsType.OK_CANCEL)
                overwrite_dialog.set_text(
                    _("A file named '%s' already exists. Do you want to replace it?")
                    % os.path.basename(first_path),
                    _('Replacing it will overwrite its contents.'))

                # Declining leaves this dialog standing, which is what
                # stopping the response signal used to achieve; the answer
                # now arrives too late to veto a signal that has been
                # emitted, so finish the job from the answer instead.
                def overwrite_answered(answer: int) -> None:
                    if answer == Response.OK:
                        self._files_accepted(paths, first_path)

                overwrite_dialog.run_async(overwrite_answered)
                return

            self._files_accepted(paths, first_path)

        else:
            self.files_chosen([])
            self._destroyed = True

    def files_chosen(self, paths: list[str]) -> None:
        """Called with the paths that were chosen, or with an empty list
        when the dialog was cancelled.  Subclasses implement it."""
        raise NotImplementedError('Subclasses must override files_chosen.')

    def _files_accepted(self, paths: list[str], first_path: str) -> None:
        """Hand the chosen <paths> on, once nothing is left to confirm."""
        # Do not store path if the user chose not to keep a file history
        if prefs['store recent file info']:
            prefs['path of last browsed in filechooser'] = \
                widgets.chooser_folder(self.filechooser) or constants.HOME_DIR
        else:
            prefs['path of last browsed in filechooser'] = \
                constants.HOME_DIR

        self.__class__._last_activated_file = first_path
        self.files_chosen(paths)
        self._destroyed = True

    def _poll_preview(self) -> bool:
        """Notice a change of selection, which nothing announces."""
        selected = self.filechooser.get_file()
        path = selected.get_path() if selected is not None else None
        if path != self._previewed:
            self._previewed = path
            self._update_preview()
        return GLib.SOURCE_CONTINUE

    def _stop_previewing(self, *args: object) -> None:
        if self._preview_timer is not None:
            GLib.source_remove(self._preview_timer)
            self._preview_timer = None

    def _update_preview(self, *args: object) -> None:
        path = self._previewed

        if path and os.path.isfile(path):
            thumbnailer = thumbnail_tools.Thumbnailer(
                size=(self._preview_pixels, self._preview_pixels),
                archive_support=True)
            thumbnailer.thumbnail_finished += self._preview_thumbnail_finished
            thumbnailer.thumbnail(path, threaded=True)
        else:
            self._preview_image.set_paintable(None)
            self._namelabel.set_text('')
            self._sizelabel.set_text('')

    def _preview_thumbnail_finished(self, filepath: str,
                                    pixbuf: "GdkPixbuf.Pixbuf | None") -> None:
        """ Called when the thumbnailer has finished creating
        the thumbnail for <filepath>. """

        if self._destroyed:
            return

        # Gtk.FileChooser.get_preview_filename() went with the rest of
        # the preview API in GTK4; what is being previewed is what the
        # poll last saw selected.
        if self._previewed and self._previewed == filepath:

            if pixbuf is None:
                self._preview_image.set_paintable(None)
                self._namelabel.set_text('')
                self._sizelabel.set_text('')

            else:
                pixbuf = image_tools.add_border(pixbuf, 1)
                self._preview_image.set_paintable(
                    image_tools.pixbuf_to_texture(pixbuf))
                self._namelabel.set_text(os.path.basename(filepath))
                self._sizelabel.set_text(tools.format_byte_size(
                    os.stat(filepath).st_size))

    def _current_file(self) -> str | None:
        # XXX: This method defers the import of main to avoid cyclic imports
        # during startup.

        from mcomix import main
        window = main.main_window()
        return None if window is None else window.filehandler.get_path_to_base()

# vim: expandtab:sw=4:ts=4
