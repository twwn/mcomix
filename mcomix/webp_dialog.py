"""webp_dialog.py - "Make pages smaller without loss...", in the library and
the main window's File menu.

The library's command may be given a few books or the whole of a large library,
which takes hours.  So it asks first, saying how many books will be
written again; shows how far it is over all of them and within the one
being written, how much room it has saved and about how long is left;
can be stopped, which keeps every book already done and leaves the one
being written as it was; and ends with a summary that counts the books
left alone by reason rather than naming thousands of them.  "Save Log"
then writes out every book by what became of it, with the files left
out of a book for being damaged and why each failure failed.

It keeps one width whatever the name of the book being written, and
the summary wraps and scrolls, so that neither a long name nor a long
list of failures pushes the window, and its buttons, off the screen.

The books are written one at a time on a thread of their own, each
with its pages encoded in parallel (mcomix.webp_books).  What is kept
by the name of a page - bookmarks, marks, turns, the chosen cover, the
page a book was left at - is the caller's to bring along, on the main
thread as soon as each book is written, so a stop or a crash later loses
none of it.
"""

import math
import os
import threading
import time

from gi.repository import GLib, Gtk, Pango

from mcomix import archive_packer
from mcomix import file_chooser_simple_dialog
from mcomix import i18n
from mcomix import log
from mcomix import message_dialog
from mcomix import page_shrink
from mcomix import tools
from mcomix import webp_books
from mcomix import widgets
from mcomix.dialog import Dialog, Response
from mcomix.i18n import _
from mcomix.preferences import prefs

from collections.abc import Callable, Sequence

#: How often the progress is brought up to date, in milliseconds.
_TICK_MS = 250

#: How long the books must have been worked on before a time left is
#: guessed, in seconds: the first books say little about the rest.
_GUESS_AFTER = 10.0

#: The most books named in the summary as not written for a failure.
_FAILURES_NAMED = 10

#: How wide the window is, in pixels, and how many characters its text
#: asks for at most: what it holds wraps or is cut short to fit.
_WIDTH = 480
_CHARACTERS = 40

#: How high the summary grows before it scrolls, in pixels.
_SUMMARY_HEIGHT = 320

#: What answers "Save Log".
_SAVE_LOG = Response.APPLY

#: What answers "Select Books with Errors".
_SELECT = Response.ACCEPT


def offer(parent: Gtk.Window, books: Sequence[str],
          written: "Callable[[str, webp_books.Converted], None]",
          open_book: Callable[[], "str | None"] = lambda: None,
          start: "Callable[[Callable[[], None]], None]" = lambda run: run(),
          finished: Callable[[], None] = lambda: None,
          select: "Callable[[list[str]], None] | None" = None) -> None:
    """Ask whether to store the PNG pages of <books> as WebP, and do it
    if the reader says yes.

    <written> is called on the main thread with the path of each book
    written again and what was done to it.  <open_book> answers with
    the path of a book to leave alone - the one the main window reads,
    where the library asks.  Once the reader has said yes, <start> is
    given what starts the work, to call when the books are ready to be
    read, or never.  <finished> is called on the main thread once the
    work has ended, however it ended.  Where <select> is given, the
    summary offers to select the books it found faults in, and it is
    called with their paths.
    """
    count = len(books)
    if not count:
        return
    dialog = message_dialog.MessageDialog(parent, modal=True)
    dialog.set_text(
        i18n.get_translation().ngettext(
            'Make the pages of %d book smaller?',
            'Make the pages of %d books smaller?', count) % count,
        _('Each book is written again, with every PNG or GIF page that is '
          'smaller as a lossless WebP and every JPEG page optimised without '
          'loss. Some other comic readers cannot show WebP pages.'))
    dialog.add_confirmation_buttons(_('_Cancel'), Response.CANCEL,
                                    _('_Make Smaller'), Response.OK)

    def run() -> None:
        write(parent, list(books), open_book, written, finished, select)

    def answered(response: int) -> None:
        if response == Response.OK:
            start(run)
    dialog.run_async(answered)


def write(parent: Gtk.Window, books: list[str],
          open_book: Callable[[], "str | None"],
          written: "Callable[[str, webp_books.Converted], None]",
          finished: Callable[[], None],
          select: "Callable[[list[str]], None] | None" = None,
          shrink: "page_shrink.Shrink | None" = None) -> None:
    """Write <books> again, showing how far it is, as offer() does once
    the reader has said yes; with the pages over the limit of <shrink>
    shrunk, where it is given (mcomix.shrink_dialog), instead of made
    smaller without loss."""
    _ProgressDialog(parent, books, open_book, written, finished, select,
                    shrink)


def left_line(reason: str, count: int) -> str:
    """The summary's line for <count> books left alone for <reason>."""
    return i18n.get_translation().ngettext(
        '%(count)d book left as it was: %(reason)s',
        '%(count)d books left as they were: %(reason)s',
        count) % {'count': count, 'reason': reason}


def stopped_line(count: int) -> str:
    """The summary's line for <count> books a stop left unread."""
    return i18n.get_translation().ngettext(
        'Stopped with %d book not yet looked at',
        'Stopped with %d books not yet looked at', count) % count


class _ProgressDialog(Dialog):

    """How far the books are, with a Stop button; the summary once
    they are done."""

    stays_until_destroyed = True

    def __init__(self, parent: Gtk.Window, books: list[str],
                 open_book: Callable[[], "str | None"],
                 written: "Callable[[str, webp_books.Converted], None]",
                 finished: Callable[[], None],
                 select: "Callable[[list[str]], None] | None" = None,
                 shrink: "page_shrink.Shrink | None" = None
                 ) -> None:
        super().__init__(title=_('Making pages smaller') if shrink is None
                         else _('Shrinking pages'),
                         transient_for=parent, modal=True,
                         destroy_with_parent=True)
        self._shrink = shrink
        self._books = books
        self._open_book = open_book
        self._written = written
        self._finished_with = finished
        self._select = select
        self._stop = threading.Event()
        # Written by the thread, read by the tick; a read between two
        # writes is a moment out of date, nothing worse.
        self._index = 0
        self._fraction = 0.0
        # Kept on the main thread, from what the thread hands over.
        #: The books written, each with what was done to it.
        self._stored: list[tuple[str, webp_books.Converted]] = []
        self._saved = 0
        self._left: dict[str, list[str]] = {}
        #: The books left alone because their file could not be read.
        self._unreadable: set[str] = set()
        #: The books that could not be written, each with why.
        self._failed: list[tuple[str, str]] = []
        self._started = time.monotonic()
        #: Whether the books are done, or stopped, and the summary shown.
        self.finished = False

        self.add_buttons(_('_Stop'), Response.CANCEL)
        self.set_default_response(Response.CANCEL)
        # Not resizable, so that it takes the height of what it shows;
        # the width is held where it is by the text asking for no more.
        self.set_size_request(_WIDTH, -1)
        self.set_resizable(False)
        widgets.set_border(self, 12)
        self.connect('response', self._response)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._book = Gtk.Label(xalign=0, max_width_chars=_CHARACTERS)
        self._book.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._bar = Gtk.ProgressBar(show_text=True)
        self._status = Gtk.Label(xalign=0, yalign=0, wrap=True,
                                 wrap_mode=Pango.WrapMode.WORD_CHAR,
                                 max_width_chars=_CHARACTERS)
        summary = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=_SUMMARY_HEIGHT)
        summary.set_child(self._status)
        for widget in (self._book, self._bar, summary):
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
            # it could not be written, for the <error> that says why.
            outcome: "webp_books.Converted | str | None"
            error = ''
            unreadable = False
            try:
                open_book = self._open_book()
                if open_book is not None and \
                        os.path.abspath(open_book) == os.path.abspath(path):
                    raise webp_books.Skipped(_('open in the main window'))
                outcome = webp_books.convert(path, self._stop,
                                             self._progress, self._shrink)
            except archive_packer.Cancelled:
                break
            except webp_books.Skipped as reason:
                outcome = str(reason)
                unreadable = reason.damaged
                log.info('Left "%s" as it was: %s',
                         i18n.to_display_string(path), reason)
            except OSError as failure:
                outcome, error = None, str(failure)
                log.warning(_('! Could not save the archive %(archivefile)s: '
                              '%(error)s'),
                            {'archivefile': path, 'error': failure})
            GLib.idle_add(self._book_done, path, outcome, error, unreadable)
        GLib.idle_add(self._finished)

    def _progress(self, fraction: float) -> None:
        self._fraction = fraction

    def _book_done(self, path: str,
                   outcome: "webp_books.Converted | str | None",
                   error: str, unreadable: bool = False) -> bool:
        if isinstance(outcome, webp_books.Converted):
            self._written(path, outcome)
            self._stored.append((path, outcome))
            self._saved += outcome.before - outcome.after
        elif outcome is not None:
            self._left.setdefault(outcome, []).append(path)
            if unreadable:
                self._unreadable.add(path)
        else:
            self._failed.append((path, error))
        return GLib.SOURCE_REMOVE

    def _done_line(self) -> str:
        count = len(self._stored)
        ngettext = i18n.get_translation().ngettext
        if self._shrink is not None:
            line = ngettext('%(count)d book shrunk, %(size)s smaller',
                            '%(count)d books shrunk, %(size)s smaller', count)
        else:
            line = ngettext(
                '%(count)d book stored with WebP pages, %(size)s smaller',
                '%(count)d books stored with WebP pages, %(size)s smaller',
                count)
        return line % {'count': count, 'size': GLib.format_size(self._saved)}

    def _damaged(self) -> list[tuple[str, webp_books.Converted]]:
        """The books written without the files in them that could not
        be read."""
        return [(path, converted) for path, converted in self._stored
                if converted.left_out]

    def _damaged_line(self, count: int) -> str:
        return i18n.get_translation().ngettext(
            '%d book stored without its damaged files',
            '%d books stored without their damaged files', count) % count

    def faulty(self) -> list[str]:
        """The books found at fault, in the order they were given: those
        that could not be written, those written without their damaged
        files, and those that could not be read at all."""
        found = self._unreadable.union(
            path for path, _error in self._failed)
        found.update(path for path, _converted in self._damaged())
        return [path for path in self._books if path in found]

    def _not_looked_at(self) -> list[str]:
        """The books a stop left before they were looked at."""
        seen = {path for path, _converted in self._stored}
        seen.update(path for path, _error in self._failed)
        for paths in self._left.values():
            seen.update(paths)
        return [path for path in self._books if path not in seen]

    def _left_by_reason(self) -> list[tuple[str, list[str]]]:
        """The books left alone by why, the most common reason first."""
        return sorted(self._left.items(), key=lambda item: -len(item[1]))

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
        if response == _SAVE_LOG:
            self._ask_where_to_save_the_log()
        elif response == _SELECT and self._select is not None:
            self._select(self.faulty())
            self.destroy()
        elif self._thread.is_alive():
            self._stop.set()
            self.set_response_sensitive(Response.CANCEL, False)
        else:
            self.destroy()

    def _finished(self) -> bool:
        """Put the summary up in the progress' place, once the thread
        is done."""
        GLib.source_remove(self._tick)
        self._thread.join()
        lines = [self._done_line()]
        damaged = self._damaged()
        if damaged:
            lines.append(self._damaged_line(len(damaged)))
        for reason, paths in self._left_by_reason():
            lines.append(left_line(reason, len(paths)))
        # One to a line: joined, a few long names made one line wider
        # than the screen.
        for path, _error in self._failed[:_FAILURES_NAMED]:
            lines.append(_('Could not be written: %s')
                         % i18n.to_display_string(os.path.basename(path)))
        if len(self._failed) > _FAILURES_NAMED:
            lines.append('…')
        left = len(self._not_looked_at())
        if left:
            lines.append(stopped_line(left))
        self._book.set_visible(False)
        self.finished = True
        self._bar.set_fraction(1.0 if not left else self._bar.get_fraction())
        self._status.set_text('\n'.join(lines))
        stop = self.get_widget_for_response(Response.CANCEL)
        if stop is not None:
            stop.set_label(_('_Close'))
            stop.set_use_underline(True)
            # Before Close, which stays the button at the end.
            save = self.add_button(_('_Save Log…'), _SAVE_LOG)
            row = stop.get_parent()
            if isinstance(row, Gtk.Box):
                row.reorder_child_after(save, None)
            if self._select is not None and self.faulty():
                select = self.add_button(_('Select Books with _Errors'),
                                         _SELECT)
                if isinstance(row, Gtk.Box):
                    row.reorder_child_after(select, save)
        self.set_response_sensitive(Response.CANCEL, True)
        self._finished_with()
        return GLib.SOURCE_REMOVE

    def log_text(self) -> str:
        """Every book, under what became of it: the lines of the summary,
        each followed by the books it counts, in full, and with why a
        book could not be written or which of its files were left
        out."""
        def book(path: str) -> str:
            return '  ' + i18n.to_display_string(path)

        sections = [[self._done_line()]
                    + [book(path) for path, _converted in self._stored]]
        damaged = self._damaged()
        if damaged:
            section = [self._damaged_line(len(damaged))]
            for path, converted in damaged:
                section.append(book(path))
                section.extend(
                    '    - %s: %s' % (i18n.to_display_string(name), why)
                    for name, why in converted.left_out.items())
            sections.append(section)
        for reason, paths in self._left_by_reason():
            sections.append([left_line(reason, len(paths))]
                            + [book(path) for path in paths])
        for path, error in self._failed:
            sections.append([_('Could not be written: %s')
                             % i18n.to_display_string(path),
                             '    ' + error])
        left = self._not_looked_at()
        if left:
            sections.append([stopped_line(len(left))]
                            + [book(path) for path in left])
        return '\n\n'.join('\n'.join(section) for section in sections) + '\n'

    def _ask_where_to_save_the_log(self) -> None:
        chooser = file_chooser_simple_dialog.SimpleFileChooserDialog(
            Gtk.FileChooserAction.SAVE, self,
            folder=prefs['path of last saved in filechooser'])
        chooser.set_title(_('Save the log as'))
        chooser.set_save_name(time.strftime(
            'mcomix-webp-%Y-%m-%d-%H%M.txt' if self._shrink is None
            else 'mcomix-shrink-%Y-%m-%d-%H%M.txt'))

        def chosen(paths: list[str]) -> None:
            chooser.destroy()
            if paths:
                self.save_log(paths[0])
        chooser.run_async(chosen)

    def save_log(self, path: str) -> None:
        """Write log_text() to <path>, or say why it could not be."""
        try:
            with tools.atomic_write(path) as file:
                file.write(self.log_text())
        except OSError as error:
            dialog = message_dialog.MessageDialog(
                self, buttons=Gtk.ButtonsType.CLOSE)
            dialog.set_text(_('Could not save "%(file)s" to "%(directory)s"')
                            % {'file': os.path.basename(path),
                               'directory': os.path.dirname(path)},
                            str(error))
            dialog.run_async(lambda response: None)
            return
        prefs['path of last saved in filechooser'] = os.path.dirname(path)

# vim: expandtab:sw=4:ts=4
