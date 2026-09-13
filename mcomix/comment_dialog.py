"""comment_dialog.py - The comment files an archive carries.

One window, which follows whichever book is open: the files in the
archive whose extensions matched the comment extensions preference,
each on a page of a notebook, in a text view of its own.  A comment
still being extracted has its page added when the file turns up.
"""

import os
from gi.repository import Gtk

from mcomix.dialog import Dialog
from mcomix import i18n
from mcomix import widgets
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import main


class _CommentsDialog(Dialog):

    def __init__(self, window: "main.MainWindow") -> None:
        super().__init__(title=_('Comments'), transient_for=window)
        self.add_buttons(_('_Close'), Response.CLOSE)

        self.set_resizable(True)
        self.set_default_response(Response.CLOSE)
        self.set_default_size(600, 550)
        widgets.set_border(self, 4)

        tag = Gtk.TextTag()
        tag.set_property('editable', False)
        tag.set_property('editable-set', True)
        tag.set_property('family', 'Monospace')
        tag.set_property('family-set', True)
        tag.set_property('scale', 0.9)
        tag.set_property('scale-set', True)
        tag_table = Gtk.TextTagTable()
        tag_table.add(tag)

        self._tag = tag
        self._tag_table = tag_table
        self._window = window
        #: The comment each extracted file holds, by path.
        self._comments: dict[str, int] = {}

        # One notebook for the life of the dialog, emptied and filled in
        # again whenever the book changes: taking it off the dialog and
        # packing another in its place said the same thing at more cost.
        self._notebook = Gtk.Notebook()
        self._notebook.set_scrollable(True)
        widgets.set_border(self._notebook, 6)
        widgets.pack(self.get_content_area(), self._notebook, True, True, 0)

        self._window.filehandler.file_available += self._on_file_available
        self._window.filehandler.file_opened += self._update_comments
        self._window.filehandler.file_closed += self._update_comments
        self._update_comments()
        self.set_visible(True)

    def _on_file_available(self, path_list: Sequence[str]) -> None:
        for path in path_list:
            if path in self._comments:
                self._add_comment(path, self._comments[path])
        self._notebook.set_visible(True)

    def _update_comments(self) -> None:

        # Out with the comments of the book before this one.
        while self._notebook.get_n_pages():
            self._notebook.remove_page(-1)
        self._comments = {}

        for num in range(1, self._window.filehandler.get_number_of_comments() + 1):
            path = self._window.filehandler.get_comment_name(num)
            if self._window.filehandler.file_is_available(path):
                self._add_comment(path, num)
            else:
                # In case it's not ready yet, bump it's
                # extraction in front of the queue.
                self._window.filehandler._ask_for_files([path])
            self._comments[path] = num

        self._notebook.set_visible(True)

    def _add_comment(self, path: str, num: int) -> None:

        name = os.path.basename(path)

        page = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        widgets.set_border(page, 8)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        widgets.pack(page, scrolled, True, True, 0)

        # The two Gtk.EventBoxes here only carried a background and a
        # margin, neither of which needs a widget of its own in GTK4.

        text = self._window.filehandler.get_comment_text(num)
        if text is None:
            text = _('Could not read %s') % name

        text_buffer = Gtk.TextBuffer(tag_table=self._tag_table)
        text_buffer.set_text(i18n.to_unicode(text))
        text_buffer.apply_tag(self._tag, *text_buffer.get_bounds())
        text_view = Gtk.TextView(buffer=text_buffer)
        widgets.set_border(text_view, 6)
        scrolled.set_child(text_view)

        # The comment used to be framed in the text view's background by
        # an event box carrying the 'view' style class; the view is the
        # scrolled window's own child now, and brings that class with it.
        tab_label = Gtk.Label(label=i18n.to_unicode(name))
        self._notebook.insert_page(page, tab_label, -1)


# vim: expandtab:sw=4:ts=4
