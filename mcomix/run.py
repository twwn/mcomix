
import argparse
import os
import signal
import sys
import types


if __name__ == '__main__':
    print('PROGRAM TERMINATED', file=sys.stderr)
    print('Please do not run this script directly! Use the mcomix script or mcomixstarter.py instead.', file=sys.stderr)
    sys.exit(1)

# These modules must not depend on GTK, Pillow,
# or any other optional libraries.
from mcomix import (
    constants,
    log,
    preferences,
)
from mcomix.version_tools import Version

#: Lowest Pillow release MComix starts with: the one pyproject.toml requires
#: and the suite is run against, which test_run.py checks agree.
PIL_VERSION_REQUIRED = '10.1.0'


def wait_and_exit() -> None:
    """ Wait for the user pressing ENTER before closing. This should help
    the user find possibly missing dependencies when starting, since the
    Python window will not close down immediately after the error. """
    if sys.platform == 'win32' and not sys.stdin.closed and not sys.stdout.closed:
        print()
        input("Press ENTER to continue...")
    sys.exit(1)


def parse_arguments(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """ Parse the command line passed in <argv>. Returns a tuple containing
    (options, arguments). Errors parsing the command line are handled in
    this function. """
    from mcomix.i18n import _

    parser = argparse.ArgumentParser(
            usage='%%(prog)s %s' % _('[OPTION...] [PATH]'),
            description=_('View images and comic book archives.'),
            add_help=False)
    parser.add_argument('--help', action='help',
                        help=_('Show this help and exit.'))
    parser.add_argument('-s', '--slideshow', dest='slideshow', action='store_true',
                        help=_('Start the application in slideshow mode.'))
    parser.add_argument('-l', '--library', dest='library', action='store_true',
                        help=_('Show the library on startup.'))
    parser.add_argument('-v', '--version', action='version',
                        version='%s %s' % (constants.APPNAME, constants.VERSION),
                        help=_('Show the version number and exit.'))
    parser.add_argument('--lang', dest='language_code',
                        help=_('Temporarily override the interface language.'))
    parser.add_argument('--page', dest='page', type=int, default=0,
                        help=_('Open the file at the given page.'))
    # The name within an archive of the file of that page, which finds
    # the page wherever the archive's sort order puts it: what a
    # bookmark opened with the middle button hands the MComix it
    # starts.  Not for a reader to type, so not in the help.
    parser.add_argument('--page-member', dest='page_member',
                        help=argparse.SUPPRESS)

    viewmodes = parser.add_argument_group(_('View modes'))
    viewmodes.add_argument('-f', '--fullscreen', dest='fullscreen', action='store_true',
                           help=_('Start the application in fullscreen mode.'))
    viewmodes.add_argument('-m', '--manga', dest='manga', action='store_true',
                           help=_('Start the application in manga mode.'))
    viewmodes.add_argument('-d', '--double-page', dest='doublepage', action='store_true',
                           help=_('Start the application in double page mode.'))

    fitmodes = parser.add_argument_group(_('Zoom modes'))
    fitmodes.add_argument('-b', '--zoom-best', dest='zoommode', action='store_const',
                          const=constants.ZoomMode.BEST,
                          help=_('Start the application with zoom set to best fit mode.'))
    fitmodes.add_argument('-w', '--zoom-width', dest='zoommode', action='store_const',
                          const=constants.ZoomMode.WIDTH,
                          help=_('Start the application with zoom set to fit width.'))
    fitmodes.add_argument('-h', '--zoom-height', dest='zoommode', action='store_const',
                          const=constants.ZoomMode.HEIGHT,
                          help=_('Start the application with zoom set to fit height.'))

    debugopts = parser.add_argument_group(_('Debug options'))
    debugopts.add_argument('-W', dest='loglevel', default='warn',
                           choices=('all', 'debug', 'info', 'warn', 'error'),
                           metavar='[ all | debug | info | warn | error ]',
                           help=_('Sets the desired output log level.'))
    # What a build without a console, MComix.exe on Windows, is read by.
    debugopts.add_argument('-o', dest='output', default='', metavar='FILE',
                           help=_('Writes the log to FILE as well.'))

    # The usage line above already names it; keep it out of --help.
    parser.add_argument('paths', nargs='*', help=argparse.SUPPRESS)

    opts = parser.parse_args(argv)

    # Fix up log level to use constants from log.
    opts.loglevel = {
        'all': log.DEBUG,
        'debug': log.DEBUG,
        'info': log.INFO,
        'warn': log.WARNING,
        'error': log.ERROR,
    }[opts.loglevel]

    return opts, opts.paths


def setup_dependencies() -> None:
    """Check for the PyGObject and PIL dependencies."""
    from mcomix.i18n import _

    try:
        from gi import require_version

        require_version('PangoCairo', '1.0')
        require_version('Gtk', '4.0')
        require_version('Gdk', '4.0')

        # require_version() only settles which typelib will be read;
        # importing is what fails when the libraries behind it are absent.
        from gi.repository import Gtk  # noqa

    except ValueError:
        log.error(_("You do not have the required versions of GTK 4.0 and PyGObject installed."))
        wait_and_exit()

    except ImportError:
        log.error(_('No version of GObject was found on your system.'))
        log.error(_('This error might be caused by missing GTK+ libraries.'))
        wait_and_exit()

    try:
        import PIL.Image  # noqa: F401

        if Version(PIL.__version__) < Version(PIL_VERSION_REQUIRED):
            log.error(_("You don't have the required version of the Python Imaging Library Fork (Pillow) installed."))
            log.error(_('Installed Pillow version is: %s') % PIL.__version__)
            log.error(_('Required Pillow version is: %s or higher') % PIL_VERSION_REQUIRED)
            wait_and_exit()

    except ImportError:
        log.error(_('Python Imaging Library Fork (Pillow) %s or higher is required.') % PIL_VERSION_REQUIRED)
        log.error(_('No version of the Python Imaging Library was found on your system.'))
        wait_and_exit()


def apply_layout_direction() -> None:
    """Lay the interface out right to left when it is being displayed in a
    language that reads that way. A widget takes the default direction when
    it is built, so this has to run before the main window does."""
    from gi.repository import Gtk
    from mcomix import i18n

    # Ask i18n which language it settled on rather than reading the
    # preference: the preference is one of three sources, and it holds
    # 'auto' by default.
    if i18n.is_rtl_language():
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)


def what_to_open(opts: argparse.Namespace, args: list[str]
                 ) -> "tuple[str | list[str] | None, int, str | None]":
    """The file or files to open at start, the page to open at, and the
    file of that page within an archive where it is known.

    The command line decides where it names anything; otherwise the
    last file viewed, where "auto load last file" says so and the file
    is still there.  A page of 0 leaves the choice to the file handler:
    the first page, or the last one read if there is one for the book.
    """
    open_path: "str | list[str] | None" = None
    open_page = 0
    open_member: "str | None" = None
    if len(args) == 1:
        open_path = args[0]
    elif len(args) > 1:
        open_path = args

    elif preferences.prefs['auto load last file'] \
            and preferences.prefs['path to last file'] \
            and os.path.isfile(preferences.prefs['path to last file']):
        open_path = preferences.prefs['path to last file']
        open_page = preferences.prefs['page of last file']
        open_member = preferences.prefs['member of last file'] or None

    # --page is about the book that was named, not about the one the
    # last session was left on: a page without a path is ignored.
    if args and opts.page:
        open_page = opts.page
    if args:
        open_member = opts.page_member
    return open_path, open_page, open_member


def make_directories() -> None:
    """Make the directories MComix keeps its data and settings in.

    Whether they are there is not asked first: MComix runs one process
    per window, and another one started at the same moment may make
    them between the question and the answer.
    """
    for directory in (constants.DATA_DIR, constants.CONFIG_DIR):
        os.makedirs(directory, 0o700, exist_ok=True)


def run() -> None:
    """Run the program."""

    # Load configuration and setup localisation.
    preferences.read_preferences_file()
    from mcomix import i18n
    i18n.install_gettext()

    # Retrieve and parse command line arguments.
    argv = sys.argv[1:]
    opts, args = parse_arguments(argv)

    # First things first: set the log level, and where the log goes.
    log.setLevel(opts.loglevel)
    if opts.output:
        try:
            log.log_to_file(opts.output)
        except OSError as error:
            log.error('! Could not write the log to %s: %s', opts.output, error)
    log.log_uncaught_exceptions()

    # Reconfigure stdout to replace characters that cannot be printed
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')

    if opts.language_code:
        i18n.install_gettext(opts.language_code)

    setup_dependencies()

    from gi.repository import GLib

    make_directories()

    # Before any widget is built: libadwaita restyles what already
    # exists, but only what it was started before.
    from mcomix import theme
    theme.follow_theme()

    from mcomix import icons
    icons.load_icons()

    open_path, open_page, open_member = what_to_open(opts, args)

    apply_layout_direction()

    # The window class is taken from the program name.
    GLib.set_prgname(constants.APPNAME)

    from mcomix import main
    window = main.MainWindow(fullscreen=opts.fullscreen, is_slideshow=opts.slideshow,
                             show_library=opts.library, manga_mode=opts.manga,
                             double_page=opts.doublepage, zoom_mode=opts.zoommode,
                             open_path=open_path, open_page=open_page,
                             open_member=open_member)
    main.set_main_window(window)

    if sys.platform != 'win32':
        # Add a SIGCHLD handler to reap zombie processes. Signals coalesce,
        # so one delivery can stand for several children having exited;
        # reap until there is nothing left to collect.
        def on_sigchld(signum: int, frame: "types.FrameType | None") -> None:
            try:
                while os.waitpid(-1, os.WNOHANG)[0] != 0:
                    pass
            except OSError:
                # No children left to wait for.
                pass
        signal.signal(signal.SIGCHLD, on_sigchld)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, stack: GLib.idle_add(window.terminate_program))
    try:
        main.main_loop().run()
    except KeyboardInterrupt:  # Will not always work because of threading.
        window.terminate_program()

# vim: expandtab:sw=4:ts=4
