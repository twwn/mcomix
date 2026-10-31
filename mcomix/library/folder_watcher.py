"""The watched folders, watched while the library window is open.

A scan of the watch list ran when the library was opened, and by hand;
a book copied into a watched folder while the library was on screen
appeared only at the next one.  While the library is open, and the scan
at its opening is on, the folders are watched for files now: a book
that has arrived - written and closed, or moved in - starts the same
scan, a moment after the last of a batch, and is added as that scan
adds books.
"""

import os
import threading
from collections.abc import Callable, Sequence

from gi.repository import Gio, GLib

from mcomix import archive_tools
from mcomix import log

#: The most folders watched at once.  Each is an inotify watch on Linux,
#: and those are counted per user, against every program the user runs
#: (8192 by default before Linux 5.11); a library deeper than this is
#: still found by the scan when the library is opened.
LIMIT = 1000

#: The seconds after the last book to arrive before the scan, so that a
#: batch of books copied in is one scan and not one each.
DELAY = 2.0

#: What a monitor reports of a file that has arrived whole: written and
#: closed, or moved or renamed into the folder.
_ARRIVED = (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.MOVED_IN,
            Gio.FileMonitorEvent.RENAMED)

#: And of a folder that has appeared, to be watched in its turn where
#: it is under a folder watched with its subfolders.
_APPEARED = (Gio.FileMonitorEvent.CREATED,
             Gio.FileMonitorEvent.MOVED_IN,
             Gio.FileMonitorEvent.RENAMED)


class FolderWatcher:

    """Gio monitors on the watched folders, and on their subfolders for
    the entries that take them in; scan() is called when a book has
    arrived in one of them."""

    def __init__(self, scan: Callable[[], None]) -> None:
        self._scan = scan
        self._monitors: dict[str, Gio.FileMonitor] = {}
        #: The folders watched with their subfolders.
        self._recursive: list[str] = []
        self._pending: int | None = None
        #: Bumped by stop(), so that the folders a walk started before it
        #: found are not watched after it.
        self._generation = 0

    @property
    def folders(self) -> list[str]:
        """The folders being watched."""
        return sorted(self._monitors)

    def start(self, entries: Sequence[tuple[str, bool]]) -> None:
        """Watch the folders of <entries>, (folder, with subfolders)
        each, in place of whatever was watched before.  The subfolders
        are found on a thread of their own, since a deep tree on a
        network share takes long to walk; the monitors are made on the
        main thread, which delivers their signals."""
        self.stop()
        generation = self._generation
        self._recursive = [os.path.normpath(folder) for folder, recursive
                           in entries if recursive]
        thread = threading.Thread(target=self._find_folders,
                                  args=(list(entries), generation), daemon=True)
        thread.name += '-watch_folders'
        thread.start()

    def stop(self) -> None:
        """Watch nothing, and scan for nothing that has arrived."""
        self._generation += 1
        for monitor in self._monitors.values():
            monitor.cancel()
        self._monitors.clear()
        if self._pending is not None:
            GLib.source_remove(self._pending)
            self._pending = None

    def _find_folders(self, entries: list[tuple[str, bool]],
                      generation: int) -> None:
        folders: list[str] = []
        for folder, recursive in entries:
            if not os.path.isdir(folder):
                continue
            if not recursive:
                folders.append(folder)
                continue
            for path, _subfolders, _files in os.walk(folder):
                folders.append(path)
                if len(folders) >= LIMIT:
                    break
            if len(folders) >= LIMIT:
                log.debug('Watching the first %d folders of the watch list', LIMIT)
                break
        GLib.idle_add(self._watch_all, folders[:LIMIT], generation)

    def _watch_all(self, folders: list[str], generation: int) -> bool:
        if generation == self._generation:
            for folder in folders:
                self._watch(folder)
        return GLib.SOURCE_REMOVE

    def _watch(self, folder: str) -> None:
        folder = os.path.normpath(folder)
        if folder in self._monitors or len(self._monitors) >= LIMIT:
            return
        try:
            monitor = Gio.File.new_for_path(folder).monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error as error:
            log.debug('Cannot watch %s: %s', folder, error.message)
            return
        monitor.connect('changed', self._changed)
        self._monitors[folder] = monitor

    def _changed(self, monitor: Gio.FileMonitor, file: Gio.File,
                 other: Gio.File | None, event: Gio.FileMonitorEvent) -> None:
        arrived = other if event == Gio.FileMonitorEvent.RENAMED else file
        path = arrived.get_path() if arrived is not None else None
        if path is None:
            return
        if event in _APPEARED and os.path.isdir(path):
            if any(path == root or path.startswith(root + os.sep)
                   for root in self._recursive):
                for subfolder, _subfolders, _files in os.walk(path):
                    self._watch(subfolder)
                # What was moved in with the folder is new as well.
                self._later()
            return
        if event in _ARRIVED and archive_tools.is_archive_file(path):
            self._later()

    def _later(self) -> None:
        """Scan DELAY seconds from now, after whatever arrives before."""
        if self._pending is not None:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(int(DELAY * 1000), self._due)

    def _due(self) -> bool:
        self._pending = None
        if self._monitors:
            self._scan()
        return GLib.SOURCE_REMOVE

# vim: expandtab:sw=4:ts=4
