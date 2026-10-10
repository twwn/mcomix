"""single_instance.py - One window for the books opened from outside.

MComix is one process per window: a book double-clicked in a file
manager starts another MComix, which takes as long to come up as the
first did.  With "Open files in the window that is already open" set,
the MComix that is started finds the one that is running, hands it the
files it was given and exits, and the running one opens them (upstream
feature request 130).

The two find each other on the session bus, through a Gio.Application
that is registered and never run: MComix keeps its own main loop, and
all that is wanted of the application is the name on the bus and the
call that carries the files.  Where there is no session bus the
registration fails or names nobody, and MComix starts as it always has.
On Windows the bus is one GLib starts itself, with the gdbus.exe that
comes with it.
"""

import json
import os
import sys

from collections.abc import Callable, Sequence

from gi.repository import Gio, GLib

from mcomix import log


def application_id() -> str:
    """The name MComix goes by on the session bus.

    In the Flatpak it has to be the app's own id, the only name the
    sandbox lets it take.
    """
    return os.environ.get('FLATPAK_ID') or 'net.sourceforge.mcomix'


class SingleInstance:

    """What an MComix that has just been started asks the bus with.

    hand_over() is the question: it answers True where another MComix
    took the files, and this one has nothing left to do.  Where it
    answers False this MComix is the one others will find from now on,
    and serve() says what it does with what they hand it.
    """

    def __init__(self, name: str | None = None) -> None:
        if sys.platform == 'win32':
            # Windows has no session bus.  GLib starts one of its own
            # there, for the programs of one user, but only where the
            # address asks for it: with none set it looks for no bus
            # at all, and every MComix found itself alone.
            os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', 'autolaunch:')
        self._application = Gio.Application(
            application_id=name or application_id(),
            flags=Gio.ApplicationFlags.HANDLES_OPEN)
        #: What to do with files handed over, and with a launch that
        #: named none; None until serve() has said.
        self._opened: "Callable[[list[str], int, str | None], None] | None" \
            = None
        self._raised: "Callable[[], None] | None" = None
        #: What arrived before serve() did: the name is taken before
        #: the window is built, and a call that came in between would
        #: otherwise have gone nowhere.
        self._waiting: "list[tuple[list[str], int, str | None] | None]" = []
        self._application.connect('open', self._on_open)
        self._application.connect('activate', self._on_activate)

    def hand_over(self, paths: Sequence[str], page: int = 0,
                  member: str | None = None) -> bool:
        """Hand <paths>, to be opened at <page> or at the file called
        <member>, to the MComix that is running, and say whether there
        was one.  With no paths the running window is only brought
        forward.

        A path is handed over as the command line gave it, made
        absolute here: the other process has a working directory of its
        own.
        """
        try:
            self._application.register(None)
        except GLib.Error as error:
            log.warning('! Could not look for a running MComix: %s',
                        error.message)
            return False
        if not self._application.get_is_remote():
            return False
        if paths:
            self._application.open(
                [Gio.File.new_for_commandline_arg(path) for path in paths],
                json.dumps({'page': page, 'member': member}))
        else:
            self._application.activate()
        # The call is sent from another thread, and this process is
        # about to end.
        connection = self._application.get_dbus_connection()
        if connection is not None:
            try:
                connection.flush_sync(None)
            except GLib.Error as error:
                log.warning('! Could not reach the running MComix: %s',
                            error.message)
                return False
        return True

    def serve(self, opened: "Callable[[list[str], int, str | None], None]",
              raised: "Callable[[], None]") -> None:
        """Answer the MComix started from now on: <opened> takes the
        files one was given, with the page and the file of that page,
        and <raised> is called for one that was given none."""
        self._opened, self._raised = opened, raised
        waiting, self._waiting = self._waiting, []
        for call in waiting:
            self._deliver(call)

    def _deliver(self, call: "tuple[list[str], int, str | None] | None"
                 ) -> None:
        if self._opened is None or self._raised is None:
            self._waiting.append(call)
        elif call is None:
            self._raised()
        else:
            self._opened(*call)

    def _on_open(self, application: Gio.Application, files: list[Gio.File],
                 count: int, hint: str) -> None:
        paths = [path for path in (file.get_path() for file in files)
                 if path is not None]
        page, member = 0, None
        try:
            said = json.loads(hint) if hint else {}
            if isinstance(said.get('page'), int):
                page = said['page']
            if isinstance(said.get('member'), str):
                member = said['member']
        except (ValueError, AttributeError):
            # Not from an MComix of this version: the files are opened
            # where the file handler would open them.
            pass
        if paths:
            self._deliver((paths, page, member))

    def _on_activate(self, application: Gio.Application) -> None:
        self._deliver(None)


# vim: expandtab:sw=4:ts=4
