
import argparse
import os
import signal
import sys

if __name__ == '__main__':
    print('PROGRAM TERMINATED', file=sys.stderr)
    print('Please do not run this script directly! Use the mcomix script or mcomixstarter.py instead.', file=sys.stderr)
    sys.exit(1)

# These modules must not depend on GTK, Pillow,
# or any other optional libraries.
from mcomix import (
    constants,
    log,
    portability,
    preferences,
)
from mcomix.version_tools import Version

#: Lowest Pillow release providing the API MComix uses (Image.Transpose).
PIL_VERSION_REQUIRED = '9.1.0'

def wait_and_exit() -> None:
    """ Wait for the user pressing ENTER before closing. This should help
    the user find possibly missing dependencies when starting, since the
    Python window will not close down immediately after the error. """
    if sys.platform == 'win32' and not sys.stdin.closed and not sys.stdout.closed:
        print()
        input("Press ENTER to continue...")
    sys.exit(1)

def parse_arguments(argv):
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
    # This supresses an error when MComix is used with cProfile
    debugopts.add_argument('-o', dest='output', default='',
            help=argparse.SUPPRESS)

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
    """Check for PyGTK and PIL dependencies."""
    from mcomix.i18n import _

    try:
        from gi import require_version

        require_version('PangoCairo', '1.0')
        require_version('Gtk', '3.0')
        require_version('Gdk', '3.0')

        from gi.repository import Gdk, GLib, Gtk  # noqa

        # Older GLib requires initialization before using threads
        if GLib.check_version(2, 32, 0) is not None:
            GLib.threads_init()

    except AssertionError:
        log.error(_("You do not have the required versions of GTK+ 3.0 and PyGObject installed."))
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


def run() -> None:
    """Run the program."""

    # Load configuration and setup localisation.
    preferences.read_preferences_file()
    from mcomix import i18n
    i18n.install_gettext()

    # Retrieve and parse command line arguments.
    argv = sys.argv[1:]
    opts, args = parse_arguments(argv)

    # First things first: set the log level.
    log.setLevel(opts.loglevel)

    # Reconfigure stdout to replace characters that cannot be printed
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')

    if opts.language_code:
        i18n.install_gettext(opts.language_code)

    setup_dependencies()

    from gi.repository import Gdk, GLib, Gtk

    if not os.path.exists(constants.DATA_DIR):
        os.makedirs(constants.DATA_DIR, 0o700)

    if not os.path.exists(constants.CONFIG_DIR):
        os.makedirs(constants.CONFIG_DIR, 0o700)

    from mcomix import icons
    icons.load_icons()

    open_path = None
    # 0 leaves the choice of page to the file handler: the first one, or
    # the last read page if there is one for this book.
    open_page = 0
    if len(args) == 1:
        open_path = args[0]
    elif len(args) > 1:
        open_path = args

    elif preferences.prefs['auto load last file'] \
        and preferences.prefs['path to last file'] \
        and os.path.isfile(preferences.prefs['path to last file']):
        open_path = preferences.prefs['path to last file']
        open_page = preferences.prefs['page of last file']

    # Some languages require a RTL layout
    if preferences.prefs['language'] in ('he', 'fa'):
        Gtk.widget_set_default_direction(Gtk.TextDirection.RTL)

    Gdk.set_program_class(constants.APPNAME)
    GLib.set_prgname(constants.APPNAME)

    settings = Gtk.Settings.get_default()
    if settings:
        # Enable icons for menu items.
        settings.props.gtk_menu_images = True

        # Prefer dark theme if system theme mode is set to dark
        if portability.is_system_ui_dark_themed() == constants.SystemThemeLightness.DARK:
            settings.set_property('gtk-application-prefer-dark-theme', True)

    from mcomix import main
    window = main.MainWindow(fullscreen = opts.fullscreen, is_slideshow = opts.slideshow,
            show_library = opts.library, manga_mode = opts.manga,
            double_page = opts.doublepage, zoom_mode = opts.zoommode,
            open_path = open_path, open_page = open_page)
    main.set_main_window(window)

    if 'win32' != sys.platform:
        # Add a SIGCHLD handler to reap zombie processes. Signals coalesce,
        # so one delivery can stand for several children having exited;
        # reap until there is nothing left to collect.
        def on_sigchld(signum, frame):
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
        Gtk.main()
    except KeyboardInterrupt: # Will not always work because of threading.
        window.terminate_program()

# vim: expandtab:sw=4:ts=4
