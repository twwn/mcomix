"""duplicates_dialog.py - "Find duplicates...", in the library.

Looks for copies among the books the library shows - the whole library
under "All books", or a collection, or what a search found - and lists
them in groups, each with how sure it is that they are copies.

The books are read first, a few pages each (mcomix.library.fingerprint),
which in a large library takes minutes: what was read is kept in the
library, so that the next search reads only the books added or changed
since.  How far it is shows in a bar, and Stop ends the reading and
compares what was read; closing the window ends the comparing too.

Each book is shown with its cover, name, folder, size, pages and the
size of its first page.  In each group one copy is marked to keep - the
one of most pages, then of the largest pages, then the smallest file -
and the others are ticked, which the reader may change.  The books
ticked are then selected in the library, where every command for books
selected is at hand, or removed from it; a book is opened by activating
its row.  What a group's books are is left to the reader to see: none
is removed, let alone deleted, without being asked for.
"""

import os
import threading

from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from mcomix import i18n
from mcomix import image_tools
from mcomix import message_dialog
from mcomix import tools
from mcomix import widgets
from mcomix.dialog import Dialog, Response
from mcomix.i18n import _
from mcomix.library import duplicates
from mcomix.library import fingerprint
from mcomix.preferences import prefs

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library.backend import _LibraryBackend

#: How often the progress is brought up to date, in milliseconds.
_TICK_MS = 250

#: The side of the square a cover is shrunk to fit, in pixels.
_COVER_SIDE = 64

#: How large the window opens, in pixels.
_SIZE = (560, 520)

#: What answers "Select in Library".
_SELECT = Response.ACCEPT

#: What answers "Remove from Library".
_REMOVE = Response.REJECT

#: What each likeness is called over its group.
_LIKENESS = {
    duplicates.Likeness.SAME_FILE: lambda: _('The same file'),
    duplicates.Likeness.SAME_PAGES: lambda: _('The same pages packed again'),
    duplicates.Likeness.SIMILAR: lambda: _('Pages that look the same'),
}


class DuplicatesDialog(Dialog):

    """How far the reading of the books is, with a Stop button; the
    groups of copies once they are found."""

    def __init__(self, parent: Gtk.Window, backend: "_LibraryBackend",
                 books: Mapping[int, str],
                 open_book: Callable[[int], None],
                 select: Callable[[list[str]], None],
                 remove: Callable[[list[int]], None]) -> None:
        """Look for copies among <books> (id to path), with what is
        kept in <backend>.  <open_book> opens a book by its id,
        <select> selects books in the library by their paths, and
        <remove> removes books from it by their ids."""
        super().__init__(title=_('Duplicates'), transient_for=parent,
                         destroy_with_parent=True)
        self._backend = backend
        self._books = dict(books)
        self._open_book = open_book
        self._select = select
        self._remove = remove
        #: Set by Stop: no other book is read.
        self._stop = threading.Event()
        #: Set as the window goes: nothing more is done at all.
        self._closing = threading.Event()
        # Written by the thread, read by the tick.
        self._done = 0
        self._total = 0
        self._comparing = False
        #: The groups found, each book with its tick, once they are.
        self._ticks: dict[int, Gtk.CheckButton] = {}
        #: The book of each row listed.
        self._row_books: dict[Gtk.ListBoxRow, int] = {}
        #: Whether the search is done, or stopped, and the groups shown.
        self.finished = False

        self.add_buttons(_('_Stop'), Response.CANCEL)
        self.set_default_response(Response.CANCEL)
        self.set_default_size(*_SIZE)
        widgets.set_border(self, 12)
        self.connect('response', self._response)

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._status = Gtk.Label(xalign=0, wrap=True,
                                 wrap_mode=Pango.WrapMode.WORD_CHAR)
        self._bar = Gtk.ProgressBar(show_text=True)
        self._box.append(self._status)
        self._box.append(self._bar)
        widgets.pack(self.get_content_area(), self._box, True, True, 0)

        self._tick = GLib.timeout_add(_TICK_MS, self._show_progress)
        self._show_progress()
        # On unrealize, not destroy: see webp_dialog.
        self.connect('unrealize', lambda dialog: dialog._close())
        self._thread = threading.Thread(target=self._run,
                                        name='duplicates')
        self._thread.start()
        self.set_visible(True)

    def _close(self) -> None:
        self._stop.set()
        self._closing.set()

    def _run(self) -> None:
        """Read the books and compare them; on the thread."""
        found = fingerprint.update(
            self._books, self._backend.fingerprints(),
            self._backend.store_fingerprint, self._stop, self._progress,
            prefs['max threads'])
        self._comparing = True
        groups = duplicates.find(found, self._digest, self._closing)
        covers = {book: self._cover(book)
                  for group in groups for book in group.books
                  if not self._closing.is_set()}
        GLib.idle_add(self._finished, groups, found, covers)

    def _progress(self, done: int, total: int) -> None:
        self._done, self._total = done, total

    def _digest(self, book: int,
                made: fingerprint.Fingerprint) -> bytes | None:
        """The hash of the whole file of <book>, made and kept unless
        it was before; on the thread."""
        if made.digest is not None:
            return made.digest
        try:
            digest = fingerprint.digest(self._books[book], self._closing)
        except OSError:
            return None
        if digest is not None:
            self._backend.store_digest(book, made, digest)
        return digest

    def _cover(self, book: int) -> GdkPixbuf.Pixbuf | None:
        """The cover of <book> as small as a row shows it; on the
        thread, since it may read the book."""
        cover = self._backend.get_book_cover(book)
        if cover is None:
            return None
        return image_tools.fit_in_rectangle(cover, _COVER_SIDE, _COVER_SIDE)

    def _show_progress(self) -> bool:
        if self._comparing:
            self._status.set_text(_('Comparing the books...'))
            self._bar.pulse()
        else:
            count = self._total or len(self._books)
            self._status.set_text(i18n.get_translation().ngettext(
                'Reading %(done)d of %(count)d book',
                'Reading %(done)d of %(count)d books',
                count) % {'done': self._done, 'count': count})
            self._bar.set_fraction(self._done / count if count else 1.0)
        return GLib.SOURCE_CONTINUE

    def ticked(self) -> list[int]:
        """The books ticked, in the order they are listed."""
        return [book for book, tick in self._ticks.items()
                if tick.get_active()]

    def _response(self, dialog: Dialog, response: int) -> None:
        if response == _SELECT:
            self._select([self._books[book] for book in self.ticked()])
            self.destroy()
        elif response == _REMOVE:
            self._ask_to_remove()
        elif self._thread.is_alive():
            self._stop.set()
            self.set_response_sensitive(Response.CANCEL, False)
        else:
            self.destroy()

    def _closed(self, *args: object) -> bool:
        self.emit('response', Response.DELETE_EVENT)
        # True: the window stays until the thread has stopped.
        return True

    def _ask_to_remove(self) -> None:
        books = self.ticked()
        if not books:
            return
        prompt = message_dialog.MessageDialog(self, modal=True)
        prompt.set_text(
            i18n.get_translation().ngettext(
                'Remove %d book from the library?',
                'Remove %d books from the library?', len(books))
            % len(books),
            _('Their files are left where they are.'))
        prompt.add_confirmation_buttons(_('_Cancel'), Response.CANCEL,
                                        _('_Remove'), Response.OK)

        def answered(response: int) -> None:
            if response != Response.OK:
                return
            self._remove(books)
            for book in books:
                row = self._ticks.pop(book).get_ancestor(Gtk.ListBoxRow)
                if row is not None:
                    row.set_sensitive(False)
            self._update_buttons()
        prompt.run_async(answered)

    def _update_buttons(self) -> None:
        ticked = bool(self.ticked())
        for response in (_SELECT, _REMOVE):
            self.set_response_sensitive(response, ticked)

    def _finished(self, groups: Sequence[duplicates.Group],
                  found: Mapping[int, fingerprint.Fingerprint],
                  covers: Mapping[int, GdkPixbuf.Pixbuf | None]) -> bool:
        """Put the groups up in the progress' place, once the thread
        is done."""
        GLib.source_remove(self._tick)
        self._thread.join()
        self.finished = True
        self._bar.set_visible(False)
        stopped = len(found) < len(self._books)
        if not groups:
            text = _('No copies found.')
        else:
            text = i18n.get_translation().ngettext(
                '%d group of copies found.', '%d groups of copies found.',
                len(groups)) % len(groups)
        if stopped:
            text += ' ' + i18n.get_translation().ngettext(
                'Stopped with %d book not yet read.',
                'Stopped with %d books not yet read.',
                len(self._books) - len(found)) % (
                    len(self._books) - len(found))
        self._status.set_text(text)

        if groups:
            listed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                             spacing=12)
            for group in groups:
                listed.append(self._group(group, found, covers))
            scrolled = Gtk.ScrolledWindow(
                hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            scrolled.set_child(listed)
            self._box.append(scrolled)

        stop = self.get_widget_for_response(Response.CANCEL)
        if stop is not None:
            stop.set_label(_('_Close'))
            stop.set_use_underline(True)
            self.set_response_sensitive(Response.CANCEL, True)
            if groups:
                row = stop.get_parent()
                for label, response in (
                        (_('_Select in Library'), _SELECT),
                        (_('_Remove from Library'), _REMOVE)):
                    button = self.add_button(label, response)
                    if isinstance(row, Gtk.Box):
                        row.reorder_child_after(button, None)
                self._update_buttons()
        return GLib.SOURCE_REMOVE

    def _group(self, group: duplicates.Group,
               found: Mapping[int, fingerprint.Fingerprint],
               covers: Mapping[int, GdkPixbuf.Pixbuf | None]) -> Gtk.Widget:
        """The heading of <group> over a list of its books."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading = Gtk.Label(xalign=0)
        heading.set_markup('<b>%s</b>' % GLib.markup_escape_text(
            _LIKENESS[group.likeness]()))
        box.append(heading)
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        kept = duplicates.to_keep(group.books, found)
        for book in group.books:
            rows.append(self._row(book, found[book], covers.get(book),
                                  book == kept))
        rows.connect('row-activated', self._activated)
        box.append(rows)
        return box

    def _row(self, book: int, made: fingerprint.Fingerprint,
             cover: GdkPixbuf.Pixbuf | None, kept: bool) -> Gtk.ListBoxRow:
        """A row for <book>, ticked unless it is the one <kept>."""
        path = self._books[book]
        line = Gtk.Box(spacing=8)
        tick = Gtk.CheckButton(active=not kept, valign=Gtk.Align.CENTER)
        tick.connect('toggled', lambda button: self._update_buttons())
        self._ticks[book] = tick
        line.append(tick)
        picture = Gtk.Picture(can_shrink=False)
        picture.set_size_request(_COVER_SIDE, _COVER_SIDE)
        if cover is not None:
            picture.set_paintable(image_tools.pixbuf_to_texture(cover))
        line.append(picture)

        details = [i18n.get_translation().ngettext(
            '%d page', '%d pages', made.pages) % made.pages,
            tools.format_byte_size(made.size)]
        if made.samples and made.samples[0].width:
            details.append('%d × %d' % (made.samples[0].width,
                                        made.samples[0].height))
        if kept:
            details.append(_('the copy to keep'))
        text = Gtk.Label(xalign=0, hexpand=True,
                         ellipsize=Pango.EllipsizeMode.MIDDLE)
        text.set_markup('<b>%s</b>\n%s\n%s' % tuple(
            GLib.markup_escape_text(part) for part in (
                i18n.to_display_string(os.path.basename(path)),
                i18n.to_display_string(os.path.dirname(path)),
                ' · '.join(details))))
        line.append(text)
        row = Gtk.ListBoxRow(child=line, activatable=True)
        self._row_books[row] = book
        return row

    def _activated(self, rows: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self._open_book(self._row_books[row])
