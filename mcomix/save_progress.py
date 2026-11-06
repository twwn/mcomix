"""save_progress.py - What is shown while a book is written out.

Writing a book back - from the window, or from the archive editor's
Save As - packs every page again, which takes seconds for a book of
large pages and minutes for a big one.  The Packer does it on a thread
of its own; waiting() is what the caller hands write_archive() to wait
on it with.  A save that is done within half a second shows nothing.
One that takes longer puts up a dialog with a progress bar and a Cancel
button. The windows stay drawn and the save can be stopped, while the
pages being packed stay where they are.
"""

import os

from gi.repository import GLib, Gtk

from mcomix import archive_packer
from mcomix import i18n
from mcomix import widgets
from mcomix.dialog import Dialog, Response
from mcomix.i18n import _

from collections.abc import Callable, Sequence

#: How long a save may take before the dialog comes up, in seconds.
#: Most edits are written in less, and a dialog flashing up and away
#: again tells the reader nothing.
QUIET_SECONDS = 0.5

#: How often the progress bar is brought up to date, in milliseconds.
_TICK_MS = 100

_saving = 0
_after_saving: "list[Callable[[], None]]" = []


def saving() -> bool:
    """Whether a book is being written out.

    The pages being packed are the files the open book was extracted
    to, and they go when it closes, so nothing may close it meanwhile:
    neither quitting nor another book opened from outside.  The windows
    take no input while the dialog is up, but the window manager's close
    button and a second MComix handing a book over still reach them.
    """
    return _saving > 0


def after_saving(callback: "Callable[[], None]") -> None:
    """Run <callback> once no book is being written out: from the main
    loop when the save is over, so that whoever saved has dealt with
    the result first, or now where nothing is being saved."""
    if not saving():
        callback()
        return
    _after_saving.append(callback)


def _run_after_saving() -> None:
    callbacks = list(_after_saving)
    _after_saving.clear()
    for callback in callbacks:
        GLib.idle_add(_once, callback)


def _once(callback: "Callable[[], None]") -> bool:
    callback()
    return GLib.SOURCE_REMOVE


def waiting(parent: Gtk.Window, archive_path: str,
            also: "Sequence[Gtk.Window]" = ()
            ) -> "Callable[[archive_packer.Packer], None]":
    """What write_archive() waits on its Packer with.

    The dialog is put up over <parent>; <parent> and the windows in
    <also> take no input until the save is over, since the main loop
    runs on while it lasts.
    """
    def wait(packer: archive_packer.Packer) -> None:
        if packer.finished(QUIET_SECONDS):
            return
        global _saving
        _saving += 1
        windows = [window for window in (parent, *also)
                   if window.get_sensitive()]
        for window in windows:
            window.set_sensitive(False)
        dialog = _SaveProgressDialog(parent, archive_path, packer)
        tick = GLib.timeout_add(_TICK_MS, dialog.show_progress)
        try:
            context = GLib.MainContext.default()
            while not packer.finished():
                # The timeout wakes this at least every tick, so the end
                # of the thread is not missed for want of an event.
                context.iteration(True)
        finally:
            GLib.source_remove(tick)
            dialog.destroy()
            for window in windows:
                window.set_sensitive(True)
            _saving -= 1
            if not _saving:
                _run_after_saving()
    return wait


class _SaveProgressDialog(Dialog):

    """A progress bar and Cancel, over the window that saves."""

    def __init__(self, parent: Gtk.Window, archive_path: str,
                 packer: archive_packer.Packer) -> None:
        super().__init__(
            title=_('Writing "%s"') % i18n.to_display_string(
                os.path.basename(archive_path)),
            transient_for=parent, modal=True)
        self._packer = packer
        self.add_buttons(_('_Cancel'), Response.CANCEL)
        self.set_default_response(Response.CANCEL)
        self.set_size_request(400, -1)
        self.set_resizable(False)
        # The close button and Escape answer as Cancel does; the dialog
        # goes when the thread has stopped, not before.
        self.connect('response', self._response)

        self._bar = Gtk.ProgressBar()
        # A percentage, which needs no words.
        self._bar.set_show_text(True)
        widgets.set_border(self._bar, 12)
        widgets.pack(self.get_content_area(), self._bar, True, True, 0)
        self.show_progress()
        self.set_visible(True)

    def show_progress(self) -> bool:
        written, total = self._packer.progress()
        self._bar.set_fraction(written / total if total else 0.0)
        return GLib.SOURCE_CONTINUE

    def _response(self, dialog: Dialog, response: int) -> None:
        self._packer.stop()
        self.set_response_sensitive(Response.CANCEL, False)

    def _closed(self, *args: object) -> bool:
        self.emit('response', Response.DELETE_EVENT)
        # True: the window stays until the thread has stopped.
        return True

# vim: expandtab:sw=4:ts=4
