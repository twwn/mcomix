"""shrink_dialog.py - "Shrink oversized pages...", in the library.

Unlike "Make pages smaller without loss...", this loses detail, so it
writes nothing the reader has not seen first.  The window asks for the
height limit and the WebP quality, says plainly what becomes of the
pages and of the books as they were, then reads the books
(webp_books.survey()) and lists those with pages over the limit, with
about how much room each would save, each ticked.  Only the books left
ticked are written, by "Shrink", with the progress, Stop and summary of
the lossless command (webp_dialog.write()); each goes to the trash as
it was.

The books are read one at a time on a thread of their own.  Stop, or
closing the window, ends the reading; what was found so far is listed.
"""

import os
import shutil
import threading

from gi.repository import GLib, Gtk, Pango

from mcomix import archive_packer
from mcomix import i18n
from mcomix import log
from mcomix import message_dialog
from mcomix import page_shrink
from mcomix import webp_books
from mcomix import webp_dialog
from mcomix import widgets
from mcomix.dialog import Dialog, Response
from mcomix.i18n import _
from mcomix.preferences import prefs

from collections.abc import Callable, Sequence

#: What answers "Find Books".
_FIND = Response.APPLY

#: The least the height limit can be set to, and the most: a WebP is
#: at most 16383 pixels high.
_LEAST_LIMIT = 600
_MOST_LIMIT = 16383

#: How often the progress is brought up to date, in milliseconds.
_TICK_MS = 250

#: How wide the window is, in pixels, and how many characters its text
#: asks for at most, as webp_dialog's.
_WIDTH = 480
_CHARACTERS = 40

#: How high the list of books grows before it scrolls, in pixels.
_LIST_HEIGHT = 320


class ShrinkDialog(Dialog):

    """The limit and the quality; how far the reading is, with Stop;
    then the books found, each ticked, and Shrink."""

    stays_until_destroyed = True

    def __init__(self, parent: Gtk.Window, books: Sequence[str],
                 written: "Callable[[str, webp_books.Converted], None]",
                 open_book: Callable[[], "str | None"] = lambda: None,
                 select: "Callable[[list[str]], None] | None" = None
                 ) -> None:
        """<written>, <open_book> and <select> are as webp_dialog.offer()
        takes them."""
        super().__init__(title=_('Shrink oversized pages'),
                         transient_for=parent, modal=True,
                         destroy_with_parent=True)
        self._parent = parent
        self._books = list(books)
        self._written = written
        self._open_book = open_book
        self._select = select
        self._stop = threading.Event()
        # Written by the thread, read by the tick; a read between two
        # writes is a moment out of date, nothing worse.
        self._index = 0
        self._fraction = 0.0
        self._thread: threading.Thread | None = None
        self._tick = 0
        #: The books with pages over the limit, as the reading found
        #: each, in the order they were given.
        self.found: list[tuple[str, webp_books.Surveyed]] = []
        #: The books left out of the list, by why.
        self._left: dict[str, list[str]] = {}
        #: The tick of each book listed, by its path.
        self.ticks: dict[str, Gtk.CheckButton] = {}
        #: Whether the reading is over and what it found listed.
        self.surveyed = False

        self.set_size_request(_WIDTH, -1)
        self.set_resizable(False)
        widgets.set_border(self, 12)
        self.connect('response', self._response)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        warning = self._text()
        warning.set_text(_(
            'Each page taller than the limit is made as high as the limit '
            'and stored as a WebP at the quality set here. Such pages lose '
            'detail. A long strip, far higher than wide, is judged by its '
            'width alone. Each book written goes to the trash as it was, '
            'from where it can be put back.'))
        self._grid = Gtk.Grid(row_spacing=6, column_spacing=12)
        self._limit = Gtk.SpinButton.new_with_range(_LEAST_LIMIT, _MOST_LIMIT,
                                                    100)
        self._limit.set_value(prefs['shrink page height'])
        self._quality = Gtk.SpinButton.new_with_range(1, 100, 1)
        self._quality.set_value(prefs['shrink page quality'])
        # A book whose pages would lose detail to save a small share of
        # it is listed but not ticked.
        self._least = Gtk.SpinButton.new_with_range(0, 99, 1)
        self._least.set_value(prefs['shrink least share'])
        for row, (text, spin) in enumerate((
                (_('Page _height limit, in pixels:'), self._limit),
                (_('WebP _quality:'), self._quality),
                (_('_Least saving to tick a book, in percent:'),
                 self._least))):
            label = Gtk.Label.new_with_mnemonic(text)
            label.set_xalign(0)
            label.set_mnemonic_widget(spin)
            self._grid.attach(label, 0, row, 1, 1)
            self._grid.attach(spin, 1, row, 1, 1)
        # The other two steps, in the same pass over each book.
        self._lossless = webp_dialog.lossless_tick()
        self._lossless.set_label(
            _('Also make the other pages smaller without loss'))
        self._repack = webp_dialog.repack_tick()
        self._book = Gtk.Label(xalign=0, max_width_chars=_CHARACTERS,
                               visible=False)
        self._book.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._bar = Gtk.ProgressBar(show_text=True, visible=False)
        self._status = self._text()
        self._status.set_visible(False)
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True, max_content_height=_LIST_HEIGHT,
            visible=False)
        self._scrolled.set_child(self._list)
        for widget in (warning, self._grid, self._lossless, self._repack,
                       self._book, self._bar,
                       self._status, self._scrolled):
            box.append(widget)
        widgets.pack(self.get_content_area(), box, True, True, 0)

        self.add_buttons(_('_Cancel'), Response.CANCEL,
                         _('_Find Books'), _FIND)
        self.set_default_response(_FIND)
        # Closed with the library: stop.  On unrealize, as webp_dialog's
        # window does.
        self.connect('unrealize', lambda dialog: dialog._stop.set())
        self.set_visible(True)

    @staticmethod
    def _text() -> Gtk.Label:
        return Gtk.Label(xalign=0, wrap=True,
                         wrap_mode=Pango.WrapMode.WORD_CHAR,
                         max_width_chars=_CHARACTERS)

    @property
    def shrink(self) -> page_shrink.Shrink:
        """The limit and the quality, as set."""
        return page_shrink.Shrink(self._limit.get_value_as_int(),
                                  self._quality.get_value_as_int())

    def _response(self, dialog: Dialog, response: int) -> None:
        if response == _FIND and self._thread is None:
            self._survey()
        elif response == Response.OK and self.surveyed:
            self._write()
        elif self._thread is not None and self._thread.is_alive():
            self._stop.set()
            self.set_response_sensitive(Response.CANCEL, False)
        else:
            self.destroy()

    def _survey(self) -> None:
        """Start reading the books, with what is set."""
        shrink = self.shrink
        prefs['shrink page height'] = shrink.limit
        prefs['shrink page quality'] = shrink.quality
        prefs['shrink least share'] = self._least.get_value_as_int()
        self._grid.set_sensitive(False)
        find = self.get_widget_for_response(_FIND)
        if find is not None:
            find.set_visible(False)
        self._relabel(Response.CANCEL, _('_Stop'))
        self.set_default_response(Response.CANCEL)
        for widget in (self._book, self._bar):
            widget.set_visible(True)
        self._thread = threading.Thread(target=self._run, args=(shrink,),
                                        name='shrink-survey')
        self._tick = GLib.timeout_add(_TICK_MS, self._show_progress)
        self._show_progress()
        self._thread.start()

    def _relabel(self, response: int, label: str) -> None:
        button = self.get_widget_for_response(response)
        if button is not None:
            button.set_label(label)
            button.set_use_underline(True)

    def _run(self, shrink: page_shrink.Shrink) -> None:
        """Read the books, one after another; on the thread."""
        for index, path in enumerate(self._books):
            if self._stop.is_set():
                break
            self._index, self._fraction = index, 0.0
            outcome: "webp_books.Surveyed | str"
            try:
                open_book = self._open_book()
                if open_book is not None and \
                        os.path.abspath(open_book) == os.path.abspath(path):
                    raise webp_books.Skipped(_('open in the main window'))
                outcome = webp_books.survey(path, shrink, self._stop,
                                            self._progress)
            except archive_packer.Cancelled:
                break
            except webp_books.Skipped as reason:
                outcome = str(reason)
            except OSError as failure:
                outcome = str(failure)
                log.warning('Could not read "%s": %s',
                            i18n.to_display_string(path), failure)
            GLib.idle_add(self._book_read, path, outcome)
        GLib.idle_add(self._read_all)

    def _progress(self, fraction: float) -> None:
        self._fraction = fraction

    def _book_read(self, path: str,
                   outcome: "webp_books.Surveyed | str") -> bool:
        if isinstance(outcome, webp_books.Surveyed):
            self.found.append((path, outcome))
        else:
            self._left.setdefault(outcome, []).append(path)
        return GLib.SOURCE_REMOVE

    def _show_progress(self) -> bool:
        count = len(self._books)
        index = min(self._index, count - 1)
        self._book.set_text('%d / %d · %s' % (
            index + 1, count, i18n.to_display_string(
                os.path.basename(self._books[index]))))
        self._bar.set_fraction((self._index + self._fraction) / count)
        return GLib.SOURCE_CONTINUE

    def _read_all(self) -> bool:
        """List what the reading found, once the thread is done."""
        GLib.source_remove(self._tick)
        assert self._thread is not None
        self._thread.join()
        self.surveyed = True
        ngettext = i18n.get_translation().ngettext
        least = self._least.get_value_as_int() / 100
        for path, surveyed in self.found:
            share = surveyed.saved / surveyed.size if surveyed.size else 0.0
            worth = share >= least and surveyed.saved > 0
            tick = Gtk.CheckButton(active=worth)
            label = self._text()
            label.set_text(ngettext(
                '%(book)s: %(pages)d page over the limit, about %(size)s '
                '(%(share)d%%) smaller',
                '%(book)s: %(pages)d pages over the limit, about %(size)s '
                '(%(share)d%%) smaller', surveyed.pages) % {
                    'book': i18n.to_display_string(os.path.basename(path)),
                    'pages': surveyed.pages,
                    'size': GLib.format_size(surveyed.saved),
                    'share': round(100 * share)})
            tick.set_child(label)
            if not worth:
                tick.set_tooltip_text(_(
                    'Shrinking it saves a smaller share of the book than the '
                    'least set for a book to be ticked.'))
            tick.connect('toggled', lambda _tick: self._ticks_changed())
            self.ticks[path] = tick
            self._list.append(tick)
        self._ticks_changed()
        for widget in (self._book, self._bar):
            widget.set_visible(False)
        self._status.set_visible(True)
        self._scrolled.set_visible(bool(self.found))
        self._relabel(Response.CANCEL, _('_Cancel') if self.found
                      else _('_Close'))
        self.set_response_sensitive(Response.CANCEL, True)
        if self.found:
            self.add_button(_('_Shrink'), Response.OK).add_css_class(
                'destructive-action')
            self.set_response_sensitive(Response.OK, bool(self.ticked()))
        return GLib.SOURCE_REMOVE

    def _ticks_changed(self) -> None:
        """Say how much the books left ticked would save, and offer
        Shrink only while there are some."""
        ngettext = i18n.get_translation().ngettext
        saved = sum(surveyed.saved for path, surveyed in self.found
                    if self.ticks[path].get_active())
        lines = [ngettext(
            '%(count)d book has pages over the limit, about %(size)s to save',
            '%(count)d books have pages over the limit, about %(size)s to '
            'save', len(self.found)) % {
                'count': len(self.found), 'size': GLib.format_size(saved)}]
        for reason, paths in sorted(self._left.items(),
                                    key=lambda item: -len(item[1])):
            lines.append(webp_dialog.left_line(reason, len(paths)))
        read = len(self.found) + sum(map(len, self._left.values()))
        if read < len(self._books):
            lines.append(webp_dialog.stopped_line(len(self._books) - read))
        self._status.set_text('\n'.join(lines))
        self.set_response_sensitive(Response.OK, bool(self.ticked()))

    def ticked(self) -> list[str]:
        """The books listed and left ticked, in the order given."""
        return [path for path, _surveyed in self.found
                if self.ticks[path].get_active()]

    def _write(self) -> None:
        """Shrink the books left ticked, in a window of their own; first
        asking, where the disk has no room to keep the books as they were
        in the trash, whether to delete them instead."""
        books = self.ticked()
        if not books:
            return
        short = self._short_of_room(books)
        if short is None:
            self._shrink_books(books, trash=True)
            return
        needed, free = short
        dialog = message_dialog.MessageDialog(self, modal=True)
        dialog.set_text(
            _('Not enough room to keep the books as they were'),
            _('The books shrunk take about %(needed)s on the disk, which '
              'has %(free)s free: the books as they were stay in the trash, '
              'and keep their room until it is emptied. Deleting them '
              'permanently instead frees their room as each book is '
              'written.') % {'needed': GLib.format_size(needed),
                             'free': GLib.format_size(free)})
        dialog.add_confirmation_buttons(
            _('_Cancel'), Response.CANCEL,
            _('_Delete Originals Permanently'), Response.OK)

        def answered(response: int) -> None:
            if response == Response.OK:
                self._shrink_books(books, trash=False)
        dialog.run_async(answered)

    def _short_of_room(self, books: list[str]) -> "tuple[int, int] | None":
        """Where the disk of any of <books> has less room free than the
        books shrunk will take beside the books as they were, kept in
        the trash, which is on the same disk: how much they take there,
        and how much is free.  None where every disk has room."""
        surveyed = dict(self.found)
        disks: dict[int, tuple[str, int]] = {}
        for path in books:
            folder = os.path.dirname(os.path.abspath(path))
            try:
                disk = os.stat(folder).st_dev
            except OSError:
                continue
            taken = surveyed[path].size - surveyed[path].saved
            disks[disk] = (folder, disks.get(disk, (folder, 0))[1] + taken)
        for folder, needed in disks.values():
            try:
                free = shutil.disk_usage(folder).free
            except OSError:
                continue
            if needed > free:
                return needed, free
        return None

    def _shrink_books(self, books: list[str], trash: bool) -> None:
        shrink = self.shrink
        lossless = self._lossless.get_active()
        repack = self._repack.get_active()
        self.destroy()
        webp_dialog.write(self._parent, books, self._open_book,
                          self._written, lambda: None, self._select, shrink,
                          trash=trash, lossless=lossless, repack=repack)

# vim: expandtab:sw=4:ts=4
