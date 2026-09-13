"""filechooser_chooser_base_dialbg.py - Custom FileChooserDialog implementations."""

import os
import mimetypes
import fnmatch
from gi.repository import GLib, Gtk, Pango

from mcomix.preferences import prefs
from mcomix import image_tools
from mcomix import archive_tools
from mcomix import labels
from mcomix import widgets
from mcomix import constants
from mcomix import log
from mcomix import thumbnail_tools
from mcomix import message_dialog
from mcomix import file_provider
from mcomix import tools
from mcomix.i18n import _

mimetypes.init()

class _BaseFileChooserDialog(Gtk.Dialog):

    """We roll our own FileChooserDialog because the one in GTK seems
    buggy with the preview widget. The <action> argument dictates what type
    of filechooser dialog we want (i.e. it is Gtk.FileChooserAction.OPEN
    or Gtk.FileChooserAction.SAVE).

    This is a base class for the _MainFileChooserDialog, the
    _LibraryFileChooserDialog and the SimpleFileChooserDialog.

    Subclasses should implement a method files_chosen(paths) that will be
    called once the filechooser has done its job and selected some files.
    If the dialog was closed or Cancel was pressed, <paths> is the empty list.
    """

    _last_activated_file = None

    def __init__(self, action=Gtk.FileChooserAction.OPEN):
        self._action = action
        self._destroyed = False

        if action == Gtk.FileChooserAction.OPEN:
            title = _('Open')
            buttons = (_('_Cancel'), Gtk.ResponseType.CANCEL,
                _('_Open'), Gtk.ResponseType.OK)

        else:
            title = _('Save')
            buttons = (_('_Cancel'), Gtk.ResponseType.CANCEL,
                _('_Save'), Gtk.ResponseType.OK)

        # GTK4's Gtk.Dialog takes properties, not the title, parent
        # and flags GTK3 let it be constructed from.
        super(_BaseFileChooserDialog, self).__init__(title=title)
        self.add_buttons(*buttons)
        self.set_default_response(Gtk.ResponseType.OK)

        #: What each filter was built to match, by filter.
        self._filter_rules = {}
        self.filechooser = Gtk.FileChooserWidget(action=action)
        self.filechooser.set_size_request(680, 420)
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

        preview_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 10)
        preview_box.set_size_request(130, 0)
        # A Gtk.Image draws whatever it is given at an icon size in
        # GTK4; a picture draws it at its own.
        self._preview_image = Gtk.Picture()
        self._preview_image.set_size_request(130, 130)
        widgets.pack(preview_box, self._preview_image, False, False, 0)

        pango_scale_small = (1 / 1.2)

        self._namelabel = labels.FormattedLabel(weight=Pango.Weight.BOLD,
            scale=pango_scale_small)
        self._namelabel.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        widgets.pack(preview_box, self._namelabel, False, False, 0)

        self._sizelabel = labels.FormattedLabel(scale=pango_scale_small)
        self._sizelabel.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        widgets.pack(preview_box, self._sizelabel, False, False, 0)
        preview_box.set_visible(True)
        widgets.pack(chooser_row, preview_box, False, False, 0, end=True)

        # And no update-preview to hear either - a GTK4
        # Gtk.FileChooserWidget has no signals at all - so ask it what is
        # selected every so often.  It is one property read; the timer
        # goes when the dialog does.
        self._previewed = None
        self._preview_timer = GLib.timeout_add(200, self._poll_preview)
        self.connect('destroy', self._stop_previewing)

        self._all_files_filter = self.add_filter( _('All files'), [], ['*'])

        try:
            current_file = self._current_file()
            last_file = self.__class__._last_activated_file

            # If a file is currently open, use its path
            if current_file and os.path.exists(current_file):
                self.filechooser.set_current_folder(os.path.dirname(current_file))
            # If no file is open, use the last stored file
            elif (last_file and os.path.exists(last_file)):
                self.filechooser.set_filename(last_file)
            # If no file was stored yet, fall back to preferences
            elif os.path.isdir(prefs['path of last browsed in filechooser']):
                if prefs['store recent file info']:
                    self.filechooser.set_current_folder(
                        prefs['path of last browsed in filechooser'])
                else:
                    self.filechooser.set_current_folder(
                        constants.HOME_DIR)

        except Exception as ex: # E.g. broken prefs values.
            log.debug(ex)

        self.set_visible(True)

    def list_filters(self):
        """The filters the chooser offers, in the order they were added.

        Gtk.FileChooser.list_filters() is get_filters() in GTK4, and it
        answers with a Gio.ListModel rather than a list.
        """
        model = self.filechooser.get_filters()
        return [model.get_item(index) for index in range(model.get_n_items())]

    def add_filter(self, name, mimes, patterns=()):
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
        """Add archive filters to the filechooser.
        """
        ffilter = Gtk.FileFilter()
        ffilter.set_name(_('All archives'))
        self.filechooser.add_filter(ffilter)
        all_mimes, all_patterns = [], []
        supported_formats = archive_tools.get_supported_formats()
        for name in sorted(supported_formats):
            mime_types, extensions = supported_formats[name]
            patterns = ['*.%s' % ext for ext in extensions]
            self.add_filter(_('%s archives') % name, mime_types, patterns)
            all_mimes.extend(mime_types)
            all_patterns.extend(patterns)
            for mime in mime_types:
                ffilter.add_mime_type(mime)
            for pat in patterns:
                ffilter.add_pattern(pat)
        self._filter_rules[ffilter] = (tuple(all_patterns), tuple(all_mimes))

    def add_image_filters(self) -> None:
        """Add images filters to the filechooser.
        """
        ffilter = Gtk.FileFilter()
        ffilter.set_name(_('All images'))
        self.filechooser.add_filter(ffilter)
        all_mimes, all_patterns = [], []
        supported_formats = image_tools.get_supported_formats()
        for name in sorted(supported_formats):
            mime_types, extensions = supported_formats[name]
            patterns = ['*.%s' % ext for ext in extensions]
            self.add_filter(_('%s images') % name, mime_types, patterns)
            all_mimes.extend(mime_types)
            all_patterns.extend(patterns)
            for mime in mime_types:
                ffilter.add_mime_type(mime)
            for pat in patterns:
                ffilter.add_pattern(pat)
        self._filter_rules[ffilter] = (tuple(all_patterns), tuple(all_mimes))

    def _matches(self, ffilter, path, mime_type):
        """Whether <path> passes <ffilter>, by the rules it was built from."""
        match_patterns, match_mimes = self._filter_rules.get(ffilter, ((), ()))
        if mime_type in match_mimes:
            return True
        return any(fnmatch.fnmatch(path, pattern)
                   for pattern in match_patterns)

    def collect_files_from_subdir(self, path, filter, recursive=False):
        """ Finds archives within C{path} that match the
        L{Gtk.FileFilter} passed in C{filter}. """

        for root, dirs, files in os.walk(path):
            for file in files:
                full_path = os.path.join(root, file)
                mimetype = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'

                if (filter == self._all_files_filter
                        or self._matches(filter, full_path, mimetype)):
                    yield full_path

            if not recursive:
                break

    def set_save_name(self, name):
        self.filechooser.set_current_name(name)

    def set_current_directory(self, path):
        self.filechooser.set_current_folder(path)

    def should_open_recursive(self) -> bool:
        return False

    def _activated(self, gesture, n_press, x, y) -> None:
        """Confirm the dialog when a file is double clicked."""
        if n_press == 2 and self.filechooser.get_file() is not None:
            self._response(self, Gtk.ResponseType.OK)

    def _response(self, widget, response):
        """Return a list of the paths of the chosen files, or None if the
        event only changed the current directory.
        """
        if response == Gtk.ResponseType.OK:
            if not self.filechooser.get_filenames():
                return

            # Collect files, if necessary also from subdirectories
            filter = self.filechooser.get_filter()
            paths = [ ]
            for path in self.filechooser.get_filenames():
                if os.path.isdir(path):
                    subdir_files = list(self.collect_files_from_subdir(path, filter,
                        self.should_open_recursive()))
                    file_provider.FileProvider.sort_files(subdir_files)
                    paths.extend(subdir_files)
                else:
                    paths.append(path)

            # FileChooser.set_do_overwrite_confirmation() doesn't seem to
            # work on our custom dialog, so we use a simple alternative.
            first_path = self.filechooser.get_filenames()[0]
            if (self._action == Gtk.FileChooserAction.SAVE and
                not os.path.isdir(first_path) and
                os.path.exists(first_path)):

                overwrite_dialog = message_dialog.MessageDialog(None, 0,
                    Gtk.MessageType.QUESTION, Gtk.ButtonsType.OK_CANCEL)
                overwrite_dialog.set_text(
                    _("A file named '%s' already exists. Do you want to replace it?") %
                        os.path.basename(first_path),
                    _('Replacing it will overwrite its contents.'))
                # Declining leaves this dialog standing, which is what
                # stopping the response signal used to achieve; the answer
                # now arrives too late to veto a signal that has been
                # emitted, so finish the job from the answer instead.
                overwrite_dialog.run_async(
                    lambda answer: answer == Gtk.ResponseType.OK
                    and self._files_accepted(paths, first_path))
                return

            self._files_accepted(paths, first_path)

        else:
            self.files_chosen([])
            self._destroyed = True

    def _files_accepted(self, paths: list[str], first_path: str) -> None:
        """Hand the chosen <paths> on, once nothing is left to confirm."""
        # Do not store path if the user chose not to keep a file history
        if prefs['store recent file info']:
            prefs['path of last browsed in filechooser'] = \
                self.filechooser.get_current_folder()
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

    def _stop_previewing(self, *args) -> None:
        if self._preview_timer is not None:
            GLib.source_remove(self._preview_timer)
            self._preview_timer = None

    def _update_preview(self, *args):
        path = self._previewed

        if path and os.path.isfile(path):
            thumbnailer = thumbnail_tools.Thumbnailer(size=(128, 128),
                                                      archive_support=True)
            thumbnailer.thumbnail_finished += self._preview_thumbnail_finished
            thumbnailer.thumbnail(path, threaded=True)
        else:
            self._preview_image.set_paintable(None)
            self._namelabel.set_text('')
            self._sizelabel.set_text('')

    def _preview_thumbnail_finished(self, filepath, pixbuf):
        """ Called when the thumbnailer has finished creating
        the thumbnail for <filepath>. """

        if self._destroyed:
            return

        current_path = self.filechooser.get_preview_filename()
        if current_path and current_path == filepath:

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

    def _current_file(self):
        # XXX: This method defers the import of main to avoid cyclic imports
        # during startup.

        from mcomix import main
        return main.main_window().filehandler.get_path_to_base()

# vim: expandtab:sw=4:ts=4
