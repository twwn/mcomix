"""webp_dialog.py - The library's "Store PNG pages as WebP...".

The command may be given a few books or the whole of a large library,
which takes hours.  So it asks first, saying how many books will be
written again; shows how far it is over all of them and within the one
being written, how much room it has saved and about how long is left;
can be stopped, which keeps every book already done and leaves the one
being written as it was; and ends with a summary that counts the books
left alone by reason rather than naming thousands of them.  Each book
it leaves alone or cannot write is named in the log.

The books are written one at a time on a thread of their own, each
with its pages encoded in parallel (mcomix.webp_books).  What is kept
by the name of a page - bookmarks, marks, turns, the chosen cover, the
page a book was left at - follows each book on the main thread as soon
as it is written, so a stop or a crash later loses none of it.
"""

import math
import os
import threading
import time

from gi.repository import GLib, Gtk, Pango

from mcomix import archive_packer
from mcomix import file_actions
from mcomix import i18n
from mcomix import log
from mcomix import message_dialog
from mcomix import webp_books
from mcomix import widgets
from mcomix.dialog import Dialog, Response
from mcomix.i18n import _

from collections.abc import Callable, Sequence

#: How often the progress is brought up to date, in milliseconds.
_TICK_MS = 250

#: How long the books must have been worked on before a time left is
#: guessed, in seconds: the first books say little about the rest.
_GUESS_AFTER = 10.0

#: The most books named in the summary as not written for a failure.
_FAILURES_NAMED = 10


def offer(parent: Gtk.Window, books: Sequence[str],
          open_book: Callable[[], "str | None"],
          written: Callable[[str], None]) -> None:
    """Ask whether to store the PNG pages of <books> as WebP, and do it
    if the reader says yes.

    <open_book> answers with the path of the book the main window has
    open, which is left alone: its archive is the one it reads from.
    <written> is called on the main thread with the path of each book
    written again.
    """
    count = len(books)
    if not count:
        return
    dialog = message_dialog.MessageDialog(parent, modal=True)
    dialog.set_text(
        i18n.get_translation().ngettext(
            'Store the PNG pages of %d book as WebP?',
            'Store the PNG pages of %d books as WebP?', count) % count,
        _('Each book with PNG pages is written again, with every page '
          'that is smaller as a lossless WebP. Some other comic readers '
          'cannot show WebP pages.'))
    dialog.add_confirmation_buttons(_('_Cancel'), Response.CANCEL,
                                    _('_Store as WebP'), Response.OK)

    def answered(response: int) -> None:
        if response == Response.OK:
            _ProgressDialog(parent, list(books), open_book, written)
    dialog.run_async(answered)


class _ProgressDialog(Dialog):

    """How far the books are, with a Stop button; the summary once
    they are done."""

    def __init__(self, parent: Gtk.Window, books: list[str],
                 open_book: Callable[[], "str | None"],
                 written: Callable[[str], None]) -> None:
        super().__init__(title=_('Storing PNG pages as WebP'),
                         transient_for=parent, modal=True,
                         destroy_with_parent=True)
        self._books = books
        self._open_book = open_book
        self._written = written
        self._stop = threading.Event()
        # Written by the thread, read by the tick; a read between two
        # writes is a moment out of date, nothing worse.
        self._index = 0
        self._fraction = 0.0
        # Kept on the main thread, from what the thread hands over.
        self._converted = 0
        self._saved = 0
        self._left: dict[str, list[str]] = {}
        self._failed: list[str] = []
        self._started = time.monotonic()
        #: Whether the books are done, or stopped, and the summary shown.
        self.finished = False

        self.add_buttons(_('_Stop'), Response.CANCEL)
        self.set_default_response(Response.CANCEL)
        self.set_size_request(480, -1)
        self.set_resizable(False)
        self.connect('response', self._response)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        widgets.set_border(box, 12)
        self._book = Gtk.Label(xalign=0)
        self._book.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._bar = Gtk.ProgressBar(show_text=True)
        self._status = Gtk.Label(xalign=0)
        for widget in (self._book, self._bar, self._status):
            box.append(widget)
        widgets.pack(self.get_content_area(), box, True, True, 0)

        self._tick = GLib.timeout_add(_TICK_MS, self._show_progress)
        self._show_progress()
        # Closed with the library: stop.  On unrealize, not destroy, which
        # GTK 4 emits again where the wrapper is finally collected - at
        # the interpreter's exit, which a Python handler then crashes.
        self.connect('unrealize', lambda dialog: dialog._stop.set())
        self._thread = threading.Thread(target=self._run,
                                        name='webp-books')
        self._thread.start()
        self.set_visible(True)

    def _run(self) -> None:
        """Write the books, one after another; on the thread."""
        for index, path in enumerate(self._books):
            if self._stop.is_set():
                break
            self._index, self._fraction = index, 0.0
            # The book written, why it was left alone, or None where
            # it could not be written.
            outcome: "webp_books.Converted | str | None"
            try:
                open_book = self._open_book()
                if open_book is not None and \
                        os.path.abspath(open_book) == os.path.abspath(path):
                    raise webp_books.Skipped(_('open in the main window'))
                outcome = webp_books.convert(path, self._stop,
                                             self._progress)
            except archive_packer.Cancelled:
                break
            except webp_books.Skipped as reason:
                outcome = str(reason)
                log.info('Left "%s" as it was: %s',
                         i18n.to_display_string(path), reason)
            except OSError as error:
                outcome = None
                log.warning(_('! Could not save the archive %(archivefile)s: '
                              '%(error)s'),
                            {'archivefile': path, 'error': error})
            GLib.idle_add(self._book_done, path, outcome)
        GLib.idle_add(self._finished)

    def _progress(self, fraction: float) -> None:
        self._fraction = fraction

    def _book_done(self, path: str,
                   outcome: "webp_books.Converted | str | None") -> bool:
        if isinstance(outcome, webp_books.Converted):
            file_actions.follow_pages(path, outcome.renamed)
            self._written(path)
            self._converted += 1
            self._saved += outcome.before - outcome.after
        elif outcome is not None:
            self._left.setdefault(outcome, []).append(path)
        else:
            self._failed.append(path)
        return GLib.SOURCE_REMOVE

    def _done_line(self) -> str:
        return i18n.get_translation().ngettext(
            '%(count)d book stored with WebP pages, %(size)s smaller',
            '%(count)d books stored with WebP pages, %(size)s smaller',
            self._converted) % {'count': self._converted,
                                'size': GLib.format_size(self._saved)}

    def _show_progress(self) -> bool:
        count = len(self._books)
        index = min(self._index, count - 1)
        self._book.set_text('%d / %d · %s' % (
            index + 1, count, i18n.to_display_string(
                os.path.basename(self._books[index]))))
        done = (self._index + self._fraction) / count
        self._bar.set_fraction(done)
        status = self._done_line()
        elapsed = time.monotonic() - self._started
        if elapsed >= _GUESS_AFTER and done > 0:
            minutes = math.ceil(elapsed * (1 - done) / done / 60)
            status += '\n' + i18n.get_translation().ngettext(
                'About %d minute left', 'About %d minutes left',
                minutes) % minutes
        self._status.set_text(status)
        return GLib.SOURCE_CONTINUE

    def _response(self, dialog: Dialog, response: int) -> None:
        if self._thread.is_alive():
            self._stop.set()
            self.set_response_sensitive(Response.CANCEL, False)
        else:
            self.destroy()

    def _closed(self, *args: object) -> bool:
        self.emit('response', Response.DELETE_EVENT)
        # True: the window stays until the thread has stopped.
        return True

    def _finished(self) -> bool:
        """Put the summary up in the progress' place, once the thread
        is done."""
        GLib.source_remove(self._tick)
        self._thread.join()
        lines = [self._done_line()]
        for reason, paths in sorted(self._left.items(),
                                    key=lambda item: -len(item[1])):
            lines.append(i18n.get_translation().ngettext(
                '%(count)d book left as it was: %(reason)s',
                '%(count)d books left as they were: %(reason)s',
                len(paths)) % {'count': len(paths), 'reason': reason})
        if self._failed:
            names = [i18n.to_display_string(os.path.basename(path))
                     for path in self._failed[:_FAILURES_NAMED]]
            if len(self._failed) > _FAILURES_NAMED:
                names.append('…')
            lines.append(_('Could not be written: %s') % ', '.join(names))
        left = len(self._books) - self._converted - len(self._failed) \
            - sum(len(paths) for paths in self._left.values())
        if left:
            lines.append(i18n.get_translation().ngettext(
                'Stopped with %d book not yet looked at',
                'Stopped with %d books not yet looked at', left) % left)
        self._book.set_visible(False)
        self.finished = True
        self._bar.set_fraction(1.0 if not left else self._bar.get_fraction())
        self._status.set_text('\n'.join(lines))
        stop = self.get_widget_for_response(Response.CANCEL)
        if stop is not None:
            stop.set_label(_('_Close'))
            stop.set_use_underline(True)
        self.set_response_sensitive(Response.CANCEL, True)
        return GLib.SOURCE_REMOVE

# vim: expandtab:sw=4:ts=4
