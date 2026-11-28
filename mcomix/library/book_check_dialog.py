"""book_check_dialog.py - "Select books > Books that cannot be read in
full...", in the library.

Reads every file of each book the library shows (mcomix.library.
book_check), a few books at once, with how far it is in a bar and a
Stop button.  It then lists the books that cannot be read in full, each
with why: damaged, encrypted, not an archive at all, or in a format
nothing installed reads.  "Select in Library" selects them there, to
move, repair or remove together.  Stop lists what was found so far.
"""

import concurrent.futures
import os
import threading

from gi.repository import GLib, Gtk, Pango

from mcomix import i18n
from mcomix import log
from mcomix import tools
from mcomix import widgets
from mcomix.dialog import Dialog, Response
from mcomix.i18n import _
from mcomix.library import book_check
from mcomix.preferences import prefs

from collections.abc import Callable, Mapping

#: How often the progress is brought up to date, in milliseconds.
_TICK_MS = 250

#: How large the window opens, in pixels.
_SIZE = (520, 460)

#: What answers "Select in Library".
_SELECT = Response.ACCEPT


class BookCheckDialog(Dialog):

    """How far the check is, with a Stop button; the books that cannot
    be read in full once it is done."""

    stays_until_destroyed = True

    def __init__(self, parent: Gtk.Window, books: Mapping[int, str],
                 select: Callable[[list[str]], None]) -> None:
        """Check <books> (id to path); <select> selects books in the
        library by their paths."""
        super().__init__(title=_('Books that cannot be read in full'),
                         transient_for=parent, destroy_with_parent=True)
        self._paths = list(books.values())
        self._select = select
        self._stop = threading.Event()
        #: Written by the thread, read by the tick.
        self._done = 0
        #: The books found, to how, in the order they are shown.
        self.found: dict[str, book_check.Checked] = {}
        #: The books that could not be checked, to why: the disk's
        #: errors, not the book's.
        self.unchecked: dict[str, str] = {}
        #: Whether the check is done, or stopped, and its end shown.
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
        self.connect('unrealize', lambda dialog: dialog._stop.set())
        self._thread = threading.Thread(target=self._run, name='book check')
        self._thread.start()
        self.set_visible(True)

    def _run(self) -> None:
        """Check every book, a few at once; on the thread."""
        found: dict[str, book_check.Checked] = {}
        unchecked: dict[str, str] = {}
        threads = tools.thread_count(prefs['max threads'])
        with concurrent.futures.ThreadPoolExecutor(
                threads, thread_name_prefix='book check') as pool:
            checks = {pool.submit(self._check, path): path
                      for path in self._paths}
            for check in concurrent.futures.as_completed(checks):
                path = checks[check]
                try:
                    checked = check.result()
                except book_check.Stopped:
                    continue
                except OSError as error:
                    log.warning('"%s" could not be checked: %s',
                                i18n.to_display_string(path), error)
                    unchecked[path] = str(error)
                else:
                    if checked is not None:
                        found[path] = checked
                self._done += 1
        GLib.idle_add(self._finished, found, unchecked)

    def _check(self, path: str) -> book_check.Checked | None:
        """Check the book at <path>, unless Stop came first; on a thread
        of the pool."""
        if self._stop.is_set():
            raise book_check.Stopped()
        return book_check.check(path, self._stop)

    def _show_progress(self) -> bool:
        count = len(self._paths)
        self._status.set_text(i18n.get_translation().ngettext(
            'Checking %(done)d of %(count)d book',
            'Checking %(done)d of %(count)d books',
            count) % {'done': self._done, 'count': count})
        self._bar.set_fraction(self._done / count if count else 1.0)
        return GLib.SOURCE_CONTINUE

    def _response(self, dialog: Dialog, response: int) -> None:
        if response == _SELECT:
            self._select(list(self.found))
            self.destroy()
        elif self._thread.is_alive():
            self._stop.set()
            self.set_response_sensitive(Response.CANCEL, False)
        else:
            self.destroy()

    def _finished(self, found: dict[str, book_check.Checked],
                  unchecked: dict[str, str]) -> bool:
        """Put the books found up in the progress' place, once the
        thread is done."""
        GLib.source_remove(self._tick)
        self._thread.join()
        order = {path: index for index, path in enumerate(self._paths)}
        self.found = dict(sorted(found.items(),
                                 key=lambda item: order[item[0]]))
        self.unchecked = unchecked
        self.finished = True
        self._bar.set_visible(False)
        ngettext = i18n.get_translation().ngettext
        if self.found:
            text = ngettext('%d book cannot be read in full.',
                            '%d books cannot be read in full.',
                            len(self.found)) % len(self.found)
        else:
            text = _('Every book can be read in full.')
        left = len(self._paths) - self._done
        if left:
            text += ' ' + ngettext('Stopped with %d book not yet read.',
                                   'Stopped with %d books not yet read.',
                                   left) % left
        if unchecked:
            text += ' ' + ngettext(
                '%d book could not be checked: see the log.',
                '%d books could not be checked: see the log.',
                len(unchecked)) % len(unchecked)
        self._status.set_text(text)

        if self.found:
            rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            for path, checked in self.found.items():
                rows.append(self._row(path, checked))
            scrolled = Gtk.ScrolledWindow(
                hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            scrolled.set_child(rows)
            self._box.append(scrolled)

        stop = self.get_widget_for_response(Response.CANCEL)
        if stop is not None:
            stop.set_label(_('_Close'))
            stop.set_use_underline(True)
            self.set_response_sensitive(Response.CANCEL, True)
            if self.found:
                button = self.add_button(_('_Select in Library'), _SELECT)
                row = stop.get_parent()
                if isinstance(row, Gtk.Box):
                    row.reorder_child_after(button, None)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _row(path: str, checked: book_check.Checked) -> Gtk.Widget:
        """A line for the book at <path>: its name, its folder, and
        why it cannot be read in full."""
        why = checked.fault.describe()
        if checked.unreadable:
            count = len(checked.unreadable)
            why += ' - ' + i18n.get_translation().ngettext(
                '%d file cannot be read', '%d files cannot be read',
                count) % count
        text = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE,
                         margin_top=4, margin_bottom=4)
        text.set_markup('<b>%s</b>\n%s\n%s' % tuple(
            GLib.markup_escape_text(part) for part in (
                i18n.to_display_string(os.path.basename(path)),
                i18n.to_display_string(os.path.dirname(path)), why)))
        text.set_tooltip_text('\n'.join(
            i18n.to_display_string(name)
            for name in list(checked.unreadable)[:20]) or None)
        return text
