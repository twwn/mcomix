"""properties_dialog.py - Properties dialog that displays information about the archive/file."""

from gi.repository import Gtk
import os
import time
import stat
try:
    import pwd
    _has_pwd = True
except ImportError:
    # Running on non-Unix machine.
    _has_pwd = False

from mcomix.dialog import Dialog
from mcomix import i18n
from mcomix import log
from mcomix import strings
from mcomix import properties_page
from mcomix import widgets
from mcomix import tools
from mcomix.i18n import _
from mcomix.dialog import Response

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


class _PropertiesDialog(Dialog):

    def __init__(self, window: "main.MainWindow") -> None:

        super().__init__(title=_('Properties'), transient_for=window)
        self.add_buttons(_('_Close'), Response.CLOSE)

        self._window = window
        self.set_default_size(500, 430)
        self.set_resizable(True)
        self.set_default_response(Response.CLOSE)
        notebook = Gtk.Notebook()
        widgets.set_border(self, 4)
        widgets.set_border(notebook, 6)
        widgets.pack(self.get_content_area(), notebook, True, True, 0)

        self._notebook = notebook
        self._archive_page = properties_page._Page()
        self._image_page = properties_page._Page()
        notebook.append_page(self._image_page, Gtk.Label(label=_('Image')))
        self._update_archive_page()
        self._window.page_changed += self._on_page_change
        self._window.filehandler.file_opened += self._on_book_change
        self._window.filehandler.file_closed += self._on_book_change
        self._window.imagehandler.page_available += self._on_page_available

        self.set_visible(True)

    def _on_page_change(self) -> None:
        self._update_image_page()

    def _on_book_change(self) -> None:
        self._update_archive_page()

    def _on_page_available(self, page_number: int) -> None:
        if page_number == 1:
            self._update_page_image(self._archive_page, 1)
        current_page_number = self._window.imagehandler.get_current_page()
        if current_page_number == page_number:
            self._update_image_page()

    def _offer_archive_page(self, offer: bool) -> None:
        """Show or hide the Archive tab, and the tabs with it.

        A loose image is in no archive, so the page stood empty; with
        only the Image page left there is nothing to choose between, so
        the tabs go as well and the dialog is what it is about.
        """
        shown = self._notebook.page_num(self._archive_page)
        if offer and shown == -1:
            self._notebook.insert_page(self._archive_page,
                                       Gtk.Label(label=_('Archive')), 0)
        elif not offer and shown != -1:
            self._notebook.remove_page(shown)
        self._notebook.set_show_tabs(self._notebook.get_n_pages() > 1)

    def _update_archive_page(self) -> None:
        self._update_image_page()
        page = self._archive_page
        page.reset()
        window = self._window
        self._offer_archive_page(window.filehandler.archive_type is not None)
        if window.filehandler.archive_type is None:
            return
        # In case it's not ready yet, bump the cover extraction
        # in front of the queue.
        path = window.imagehandler.get_path_to_page(1)
        if path is not None:
            window.filehandler.ask_for_files([path])
        self._update_page_image(page, 1)
        filename = window.filehandler.get_pretty_current_filename()
        page.set_filename(filename)
        path = window.filehandler.get_path_to_base()
        main_info = (
            _('%d pages') % window.imagehandler.get_number_of_pages(),
            _('%d comments')
            % window.filehandler.get_number_of_comments(),
            strings.ARCHIVE_DESCRIPTIONS[window.filehandler.archive_type]
        )
        page.set_main_info(main_info)
        if path is not None:
            self._update_page_secondary_info(page, path)
        page.set_visible(True)

    def _update_image_page(self) -> None:
        page = self._image_page
        page.reset()
        window = self._window
        if not window.imagehandler.page_is_available():
            return
        self._update_page_image(page)
        path = window.imagehandler.get_path_to_page()
        if path is None:
            # A page that is available has a file behind it; this is
            # what says so to a reader as well as to the checker.
            return
        filename = os.path.basename(path)
        page.set_filename(filename)
        width, height = window.imagehandler.get_size()
        main_info = (
            '%dx%d px' % (width, height),
            window.imagehandler.get_mime_name() or '',
        )
        page.set_main_info(main_info)
        self._update_page_secondary_info(page, path)
        page.set_visible(True)

    def _update_page_image(self, page: properties_page._Page,
                           page_number: int | None = None) -> None:
        if not self._window.imagehandler.page_is_available(page_number):
            return
        thumb = self._window.imagehandler.get_thumbnail(page_number, width=128, height=128)
        if thumb is None:
            # The page is there but its thumbnail could not be made.
            return
        page.set_thumbnail(thumb)

    def _update_page_secondary_info(self, page: properties_page._Page,
                                    location: str) -> None:
        secondary_info = [
            (_('Location'), i18n.to_display_string(i18n.to_unicode(os.path.dirname(location)))),
        ]
        try:
            stats = os.stat(location)
        except OSError as error:
            log.debug('Could not stat "%s": %s', location, error)
            page.set_secondary_info(secondary_info)
            return
        if _has_pwd:
            uid = pwd.getpwuid(stats.st_uid)[0]
        else:
            uid = str(stats.st_uid)
        secondary_info.extend((
            (_('Size'), tools.format_byte_size(stats.st_size)),
            (_('Accessed'), time.strftime('%Y-%m-%d, %H:%M:%S',
                                          time.localtime(stats.st_atime))),
            (_('Modified'), time.strftime('%Y-%m-%d, %H:%M:%S',
                                          time.localtime(stats.st_mtime))),
            (_('Permissions'), oct(stat.S_IMODE(stats.st_mode))),
            (_('Owner'), uid)
        ))
        page.set_secondary_info(secondary_info)

# vim: expandtab:sw=4:ts=4
