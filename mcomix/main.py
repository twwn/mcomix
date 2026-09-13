"""main.py - Main window."""

import math
import os
import shutil
import threading

from gi.repository import Gdk, Gtk, GLib

from mcomix import canvas
from mcomix import constants
from mcomix import cursor_handler
from mcomix import i18n
from mcomix import enhance_backend
from mcomix import event
from mcomix import file_chooser_simple_dialog
from mcomix import file_handler
from mcomix import image_handler
from mcomix import image_tools
from mcomix import lens
from mcomix import preferences
from mcomix.preferences import prefs
from mcomix import ui
from mcomix import slideshow
from mcomix import status
from mcomix import theme
from mcomix import thumbbar
from mcomix import clipboard
from mcomix import pageselect
from mcomix import osd
from mcomix import page_image
from mcomix import keybindings
from mcomix import zoom
from mcomix import bookmark_backend
from mcomix import message_dialog
from mcomix import callback
from mcomix.library import backend, main_dialog
from mcomix import tools
from mcomix import box
from mcomix import layout
from mcomix import log
from mcomix import widgets
from mcomix.transform import Matrix, Transform
from mcomix.i18n import _
from mcomix.dialog import Response

from collections.abc import Iterable, Sequence


class MainWindow(Gtk.Window):

    """The main window, is created at start and terminates the
    program when closed.
    """

    #: What set_bg_colour()'s style rule matches the page area by.
    _BG_CSS_NAME = 'mcomix-page-area'

    def __init__(self, fullscreen: bool = False, is_slideshow: bool = False,
                 show_library: bool = False, manga_mode: bool = False,
                 double_page: bool = False,
                 zoom_mode: "constants.ZoomMode | None" = None,
                 open_path: "str | list[str] | None" = None,
                 open_page: int = 0) -> None:
        super().__init__()

        # ----------------------------------------------------------------
        # Attributes
        # ----------------------------------------------------------------
        # Used to detect window fullscreen state transitions.
        self.was_fullscreen = False
        self.is_manga_mode = False
        #: The size the window was laid out at last, or a pair of
        #: Nones until it has been laid out at all.
        self.previous_size: tuple[int, int] | tuple[None, None] = (None, None)
        self.was_out_of_focus = False
        #: The page the right-click menu was opened over, which is what
        #: the menu's own Save As saves; None where it was opened on the
        #: background around the pages.
        self.popup_page: int | None = None
        # Remember last scroll destination.
        self._last_scroll_destination: int | None = constants.SCROLL_TO_START

        self.layout = layout.create_dummy_layout()
        self.transforms: list[Matrix] = []
        self._spacing = prefs['space between two pages']
        self._waiting_for_redraw = False
        #: Where the redraw that is pending was asked to scroll to.
        self._pending_scroll_to: int | None = None

        self._main_layout = canvas.PageCanvas()
        # Gtk.EventBox was only ever here to give the pages a background
        # colour of their own; in GTK4 any widget can have one, and
        # every widget takes input, so the box is gone.  A style provider
        # is per display rather than per widget now, so the canvas is
        # named for the rule set_bg_colour() writes to single it out.
        self._main_layout.set_name(self._BG_CSS_NAME)
        self._bg_css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            widgets.display(), self._bg_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._event_handler = event.EventHandler(self)
        self._vadjust = self._main_layout.get_vadjustment()
        self._hadjust = self._main_layout.get_hadjustment()
        self._scroll = (
            Gtk.Scrollbar.new(Gtk.Orientation.HORIZONTAL, self._hadjust),
            Gtk.Scrollbar.new(Gtk.Orientation.VERTICAL, self._vadjust),
        )

        self.filehandler = file_handler.FileHandler(self)
        self.filehandler.file_closed += self._on_file_closed
        self.filehandler.file_opened += self._on_file_opened
        self.imagehandler = image_handler.ImageHandler(self)
        self.imagehandler.page_available += self._page_available
        self.thumbnailsidebar = thumbbar.ThumbnailSidebar(self)

        self.statusbar = status.Statusbar()
        self.clipboard = clipboard.Clipboard(self)
        self.slideshow = slideshow.Slideshow(self)
        self.cursor_handler = cursor_handler.CursorHandler(self)
        self.enhancer = enhance_backend.ImageEnhancer(self)
        self.lens = lens.MagnifyingLens(self)
        self.osd = osd.OnScreenDisplay(self)
        self.zoom = zoom.ZoomModel()
        self.uimanager = ui.MainUI(self)
        self.menubar = self.uimanager.menubar
        self.toolbar = self.uimanager.toolbar
        self.popup = self.uimanager.popup
        self.actiongroup = self.uimanager.actions

        self.images = [page_image.PageImage(),
                       page_image.PageImage()]  # XXX limited to at most 2 pages

        # ----------------------------------------------------------------
        # Setup
        # ----------------------------------------------------------------
        self.set_title(constants.APPNAME)
        # A GTK4 window has no icon of its own to set, from a pixbuf or
        # otherwise: it is named, and the desktop finds it in the icon
        # theme.  'mcomix' is what mcomix.desktop names as well.
        Gtk.Window.set_default_icon_name('mcomix')
        self.set_size_request(300, 300)  # Avoid making the window *too* small

        # Hook up keyboard shortcuts
        self._event_handler.register_key_events()

        for img in self.images:
            self._main_layout.put(img, 0, 0)
        self.set_bg_colour(prefs['bg colour'])

        # There were four lines here setting step and page increments on
        # these adjustments.  They assigned to .step_increment, which lands
        # on the Python wrapper and never reaches the adjustment; and the
        # scrolled window recomputes both from the viewport on every size
        # allocation anyway, so setting them properly does not survive
        # either.  MComix does its own scrolling regardless.

        # Three columns - thumbnail sidebar, page area, vertical scrollbar -
        # and six rows, of which the fourth is a spacer the sidebar spans.
        # Gtk.Table.attach() took the edges a child spans and Gtk.Grid's
        # takes its corner and size; what Table passed as attach options is
        # a property of the child in Grid.  SHRINK has no Grid counterpart
        # and Grid already aligns children to FILL, so only EXPAND carries
        # over, as hexpand/vexpand.
        grid = Gtk.Grid()
        for child, column, row, width, height, hexpand, vexpand in (
                (self.menubar,                            0, 0, 3, 1, False, False),
                (self.toolbar,                            0, 1, 3, 1, False, False),
                (self.thumbnailsidebar,                   0, 2, 1, 3, False, True),
                (self._main_layout,                       1, 2, 1, 1, True,  True),
                (self._scroll[constants.PageAxis.HEIGHT], 2, 2, 1, 1, False, False),
                (self._scroll[constants.PageAxis.WIDTH],  1, 4, 1, 1, False, False),
                (self.statusbar,                          0, 5, 3, 1, False, False),
        ):
            child.set_hexpand(hexpand)
            child.set_vexpand(vexpand)
            grid.attach(child, column, row, width, height)

        if prefs['default double page'] or double_page:
            self.actiongroup.get_action('double_page').activate()

        if prefs['default manga mode'] or manga_mode:
            self.actiongroup.get_action('manga_mode').activate()

        # Determine zoom mode. If zoom_mode is passed, it overrides
        # the zoom mode preference.
        zoom_actions = {constants.ZoomMode.BEST: 'best_fit_mode',
                        constants.ZoomMode.WIDTH: 'fit_width_mode',
                        constants.ZoomMode.HEIGHT: 'fit_height_mode',
                        constants.ZoomMode.SIZE: 'fit_size_mode',
                        constants.ZoomMode.MANUAL: 'fit_manual_mode'}

        if zoom_mode is not None:
            zoom_action = zoom_actions[zoom_mode]
        else:
            zoom_action = zoom_actions[constants.ZoomMode(prefs['zoom mode'])]

        if zoom_action == 'fit_manual_mode':
            # This little ugly hack is to get the activate call on
            # 'fit_manual_mode' to actually create an event (and callback).
            # Since manual mode is the default selected radio button action
            # it won't send an event if we activate it when it is already
            # the selected one.
            self.actiongroup.get_action('best_fit_mode').activate()

        self.actiongroup.get_action(zoom_action).activate()

        if prefs['stretch']:
            self.actiongroup.get_action('stretch').activate()

        if prefs['invert smart scroll']:
            self.actiongroup.get_action('invert_scroll').activate()

        if prefs['keep transformation']:
            prefs['keep transformation'] = False
            self.actiongroup.get_action('keep_transformation').activate()
        else:
            prefs['rotation'] = 0
            prefs['vertical flip'] = False
            prefs['horizontal flip'] = False

        # List of "toggles" than can be shown/hidden by the user.
        self._toggle_list = (
            # Preference        Action        Widget(s)
            ('show menubar', 'menubar', (self.menubar,)),
            ('show scrollbar', 'scrollbar', self._scroll),
            ('show statusbar', 'statusbar', (self.statusbar,)),
            ('show thumbnails', 'thumbnails', (self.thumbnailsidebar,)),
            ('show toolbar', 'toolbar', (self.toolbar,)),
        )

        # Each "toggle" widget "eats" part of the main layout visible area.
        self._toggle_axis = {
            self.thumbnailsidebar: constants.PageAxis.WIDTH,
            self._scroll[constants.PageAxis.HEIGHT]: constants.PageAxis.WIDTH,
            self._scroll[constants.PageAxis.WIDTH]: constants.PageAxis.HEIGHT,
            self.statusbar: constants.PageAxis.HEIGHT,
            self.toolbar: constants.PageAxis.HEIGHT,
            self.menubar: constants.PageAxis.HEIGHT,
        }

        # Start with all "toggle" widgets hidden to avoid ugly transitions.
        for preference, action, widget_list in self._toggle_list:
            for widget in widget_list:
                widget.set_visible(False)

        toggleaction = self.actiongroup.get_action('hide_all')
        toggleaction.set_active(prefs['hide all'])

        # Sync each "toggle" widget active state with its preference.
        for preference, action, widget_list in self._toggle_list:
            self.actiongroup.get_action(action).set_active(
                preferences.by_name(preference))

        # Inverted colours are not one of those widgets, and the item
        # started unticked however the preferences had been left: the
        # enhancer reads the preference itself and inverted the pages
        # while the menu said it did not.  Only the tick is out of step,
        # so it is moved rather than toggled - toggling it here would
        # redraw a window that is still being built.
        self.actiongroup.get_action('invert_color').show_active(
            prefs['invert color'])

        self.actiongroup.get_action('menu_autorotate_width').set_sensitive(False)
        self.actiongroup.get_action('menu_autorotate_height').set_sensitive(False)

        self.set_child(grid)

        # GTK4 has no event masks and no *-event signals: a widget takes
        # what a controller added to it delivers.  The window's key
        # controller runs in the capture phase, which is where the old
        # key-press-event handler on the toplevel sat - before the
        # thumbnail list could make its own use of Up, Down and Space.
        self._event_handler.register_controllers(self, self._main_layout)

        self.connect('notify::is-active', self._event_handler.focus_changed)
        self.connect('close-request', self.close_program)
        # A window's default size is what it asked for, not what the
        # compositor gave it, so the canvas is what says it has changed.
        self._main_layout.connect('resized', self._event_handler.resize_event)
        self.connect('notify::fullscreened', self._event_handler.window_state_event)
        self.connect('notify::maximized', self._event_handler.window_state_event)

        self.uimanager.set_sensitivities()
        self.restore_window_geometry()
        self.present()

        if prefs['default fullscreen'] or fullscreen:
            toggleaction = self.actiongroup.get_action('fullscreen')
            toggleaction.set_active(True)

        if prefs['previous quit was quit and save']:
            fileinfo = self.filehandler.read_fileinfo_file()

            if fileinfo is not None:

                open_path = fileinfo[0]
                open_page = fileinfo[1] + 1

        prefs['previous quit was quit and save'] = False

        if open_path is not None:
            self.filehandler.open_file(open_path, open_page)

        if is_slideshow:
            self.actiongroup.get_action('slideshow').activate()

        if show_library:
            self.actiongroup.get_action('library').activate()

        self.cursor_handler.auto_hide_on()

    def gained_focus(self, *args: object) -> None:
        """Note that the window has the focus again.

        A click into a window that had lost the focus arrives as the
        focus first and the button afterwards, and that click is meant
        to raise the window rather than to turn a page.  So the flag the
        button handler reads is not cleared here but from the idle
        queue, which is to say after that button has been dealt with.
        """
        def _delayed_unset_out_of_focus(_: None) -> bool:
            self.was_out_of_focus = False
            return False

        if self.was_out_of_focus:
            GLib.idle_add(_delayed_unset_out_of_focus, None,
                          priority=GLib.PRIORITY_DEFAULT_IDLE)

    def lost_focus(self, *args: object) -> None:
        """Note that the window no longer has the focus."""
        self.was_out_of_focus = True

    def draw_image(self, scroll_to: int | None = None) -> None:
        """Draw the current pages and update the titlebar and statusbar.
        """
        # A redraw that is already pending will do, but where it was
        # asked to scroll to must not go with the call that is dropped:
        # a page turn landing on the redraw a toggled statusbar
        # scheduled would open wherever the page before it was left.
        if scroll_to is not None:
            self._pending_scroll_to = scroll_to
        if not self._waiting_for_redraw:  # Don't stack up redraws.
            self._waiting_for_redraw = True
            GLib.idle_add(self._draw_image,
                          priority=GLib.PRIORITY_HIGH_IDLE)

    def _update_toggle_preference(self, preference: str,
                                  toggleaction: "ui.Action") -> None:
        """Update "toggle" widget corresponding <preference>.

        Note: the widget visibility itself is left unchanged."""
        preferences.set_by_name(preference, toggleaction.get_active())
        if preference == 'hide all':
            self._update_toggles_sensitivity()
        # Since the size of the drawing area is dependent
        # on the visible "toggles", redraw the page.
        self.draw_image()

    def _should_toggle_be_visible(self, preference: str) -> bool:
        """Return <True> if "toggle" widget for <preference> should be visible."""
        if self.is_fullscreen():
            visible = not prefs['hide all in fullscreen']
        else:
            visible = not prefs['hide all']
        visible &= preferences.by_name(preference)
        if preference == 'show thumbnails':
            visible &= self.filehandler.file_loaded
            visible &= self.imagehandler.get_number_of_pages() > 0
        return bool(visible)

    def _update_toggles_sensitivity(self) -> None:
        """Update each "toggle" widget sensitivity."""
        sensitive = True
        if prefs['hide all']:
            sensitive = False
        elif prefs['hide all in fullscreen'] and self.is_fullscreen():
            sensitive = False
        for preference, action, widget_list in self._toggle_list:
            self.actiongroup.get_action(action).set_sensitive(sensitive)

    def _update_toggles_visibility(self) -> None:
        """Update each "toggle" widget visibility."""
        for preference, action, widget_list in self._toggle_list:
            should_be_visible = self._should_toggle_be_visible(preference)
            for widget in widget_list:
                # No change in visibility?
                if should_be_visible != widget.get_visible():
                    widget.set_visible(should_be_visible)

    def _draw_image(self) -> bool:
        """Put the current page or pages on screen.

        Runs from the idle queue, once, however many redraws
        draw_image() was asked for in the meantime.

        In order: the toolbars and the sidebar are shown or hidden,
        since what is visible decides how much room the pages have; the
        pages are fetched and turned; a layout is built for them at the
        size the zoom mode asks for; each page is scaled, flipped and
        enhanced into that layout; and the statusbar, the background
        colour and the scroll position follow.

        Three rotations compose into the one each page is drawn under:
        what a page's own Exif tag asks for, what the shape of the pages
        side by side asks for, and what the reader has turned the book
        to by hand.  A rotation that swaps width for height swaps the
        axes the layout is built along with it, which is why the axes
        are variables here rather than the constants they start as.

        An animation is left out of all of that - it is drawn frame by
        frame at a size the layout gives, and there is no one frame to
        transform - which is what do_not_transform marks.

        Returns False, so the idle source does not run again.
        """
        scroll_to = self._pending_scroll_to
        self._pending_scroll_to = None

        self._update_toggles_visibility()

        self.osd.clear()

        if not self.filehandler.file_loaded:
            self._clear_main_area()
            self._waiting_for_redraw = False
            return False

        if self.imagehandler.page_is_available():
            distribution_axis = constants.DISTRIBUTION_AXIS
            alignment_axis = constants.ALIGNMENT_AXIS
            pixbuf_count = 2 if self.displayed_double() else 1  # XXX limited to at most 2 pages
            pixbuf_list = list(self.imagehandler.get_pixbufs(pixbuf_count))
            do_not_transform = [image_tools.is_animation(x) for x in pixbuf_list]
            size_list = [[pixbuf.get_width(), pixbuf.get_height()]
                         for pixbuf in pixbuf_list]

            # A list from the start: the rotation handling below turns
            # it around and negates it, both of which give back a list.
            orientation = list(constants.MANGA_ORIENTATION if self.is_manga_mode
                               else constants.WESTERN_ORIENTATION)

            # Rotation handling:
            # - apply Exif rotation on individual images
            # - apply automatic rotation (size based) on whole page
            # - apply manual rotation on whole page
            if prefs['auto rotate from exif']:
                rotation_list = [image_tools.get_implied_rotation(pixbuf)
                                 for pixbuf in pixbuf_list]
            else:
                rotation_list = [0] * len(pixbuf_list)
            virtual_size = [0, 0]
            for i in range(pixbuf_count):
                if tools.rotation_swaps_axes(rotation_list[i]):
                    size_list[i].reverse()
                size = size_list[i]
                virtual_size[distribution_axis] += size[distribution_axis]
                virtual_size[alignment_axis] = max(virtual_size[alignment_axis],
                                                   size[alignment_axis])
            rotation = tools.compile_rotations(
                image_tools.get_size_rotation(*virtual_size), prefs['rotation'])
            if tools.rotation_swaps_axes(rotation):
                distribution_axis, alignment_axis = alignment_axis, distribution_axis
                orientation.reverse()  # 2D only
                for i in range(pixbuf_count):
                    if do_not_transform[i]:
                        continue
                    size_list[i].reverse()  # 2D only
            if rotation in (180, 270):
                orientation = tools.vector_opposite(orientation)
            for i in range(pixbuf_count):
                rotation_list[i] = tools.compile_rotations(rotation_list[i], rotation)
            if prefs['vertical flip'] and tools.rotation_swaps_axes(rotation):
                orientation = tools.vector_opposite(orientation)
            if prefs['horizontal flip'] and not tools.rotation_swaps_axes(rotation):
                orientation = tools.vector_opposite(orientation)

            self.layout = layout.FiniteLayout.create_finite_layout(
                pixbuf_count, orientation, self._spacing, distribution_axis,
                alignment_axis, self._show_scrollbars, self.get_visible_area_size,
                # Every page is laid out at the size the zoom mode
                # asks for, animations included: they cannot be scaled
                # ahead of time, but the size is what tells the widget
                # what to scale each frame to.
                lambda zoom_dummy_size: self.zoom.get_zoomed_size(
                    size_list, zoom_dummy_size, distribution_axis,
                    [False] * pixbuf_count,
                    prefs['double page autoresize'] in (
                        constants.DOUBLE_PAGE_AUTORESIZE_SIZE,
                        constants.DOUBLE_PAGE_AUTORESIZE_FIT_SIZE),
                    prefs['double page autoresize']
                    == constants.DOUBLE_PAGE_AUTORESIZE_FIT_SIZE))
            content_boxes = self.layout.get_content_boxes()
            scaled_sizes = list(map(box.Box.get_size, content_boxes))

            self.transforms = [Transform.ID] * pixbuf_count
            for i in range(pixbuf_count):
                if do_not_transform[i]:
                    continue
                pixbuf_list[i] = image_tools.fit_pixbuf_to_rectangle(
                    pixbuf_list[i], scaled_sizes[i], rotation_list[i])
                # The turn only.  fit_pixbuf_to_rectangle() also scaled
                # the page to the content box, which the lens - the one
                # reader of these - takes from the box itself rather
                # than from here.
                self.transforms[i] += Transform.from_rotation(rotation_list[i])

            for i in range(pixbuf_count):
                if do_not_transform[i]:
                    continue
                if prefs['horizontal flip']:
                    pixbuf_list[i] = image_tools.flip_pixbuf(pixbuf_list[i], 0)
                    self.transforms[i] += Transform.from_flips(True, False)
                if prefs['vertical flip']:
                    pixbuf_list[i] = image_tools.flip_pixbuf(pixbuf_list[i], 1)
                    self.transforms[i] += Transform.from_flips(False, True)
                pixbuf_list[i] = self.enhancer.enhance(pixbuf_list[i])

            for i in range(pixbuf_count):
                self.images[i].show_pixbuf(pixbuf_list[i], scaled_sizes[i])

            scales = tuple(map(lambda x, y: math.sqrt(tools.div(
                tools.volume(x), tools.volume(y))), scaled_sizes, size_list))

            resolutions = tuple(map(lambda sz, sc, ds: sz + [sc, ds], size_list,
                                    scales, self.layout.get_content_distorted()))
            if self.is_manga_mode:
                resolutions = tuple(reversed(resolutions))
            self.statusbar.set_resolution(resolutions)
            self.statusbar.update()

            smartbg = prefs['smart bg']
            smartthumbbg = prefs['smart thumb bg'] and prefs['show thumbnails']
            if smartbg or smartthumbbg:
                bg_colour = self.imagehandler.get_pixbuf_auto_background(pixbuf_count)
            if smartbg:
                self.set_bg_colour(bg_colour, dynamic=True)
            if smartthumbbg:
                self.thumbnailsidebar.change_thumbnail_background_color(
                    bg_colour, dynamic=True)

            self._main_layout.set_content_size(*(self.layout.get_union_box().get_size()))
            for i in range(pixbuf_count):
                self._main_layout.move(self.images[i],
                                       *content_boxes[i].get_position())

            for i in range(pixbuf_count):
                self.images[i].set_visible(True)
            for i in range(pixbuf_count, len(self.images)):
                self.images[i].set_visible(False)

            # Reset orientation so scrolling behaviour is sane.
            if self.is_manga_mode:
                self.layout.set_orientation(constants.MANGA_ORIENTATION)
            else:
                self.layout.set_orientation(constants.WESTERN_ORIENTATION)

            if scroll_to is not None:
                destination = (scroll_to,) * 2
                if constants.SCROLL_TO_START == scroll_to:
                    index = constants.FIRST_INDEX
                elif constants.SCROLL_TO_END == scroll_to:
                    index = constants.LAST_INDEX
                else:
                    index = None
                self.scroll_to_predefined(destination, index)

        else:
            # Save scroll destination for when the page becomes available.
            self._last_scroll_destination = scroll_to
            # The pages are hidden rather than cleared, and this stops
            # short of _clear_main_area(), which would also throw the
            # layout away and reset the background colour: this page is
            # on its way, not gone.
            for image in self.images:
                image.set_visible(False)
            self._show_scrollbars([False] * len(self._scroll))

        self._waiting_for_redraw = False

        return False

    def _update_page_information(self) -> None:
        """ Updates the window with information that can be gathered
        even when the page pixbuf(s) aren't ready yet. """

        page_number = self.imagehandler.get_current_page()
        if not page_number:
            return
        double = self.displayed_double()

        def make_status(info: "str | tuple[str, str] | None") -> str:
            """One status bar field, from one page or from both.

            A double page answers with a value for each of its two
            pages, and manga mode reads them right to left, so they are
            listed in that order too.  A page with no file behind it
            has nothing to say, and the field is left empty.
            """
            if info is None:
                return ''
            if not isinstance(info, tuple):
                return info
            if self.is_manga_mode:
                info = (info[1], info[0])
            return ", ".join(info)

        filename = make_status(self.imagehandler.get_page_filename(double=double))
        filesize = make_status(self.imagehandler.get_page_filesize(double=double))
        self.statusbar.set_page_number(page_number,
                                       self.imagehandler.get_number_of_pages(),
                                       2 if double else 1)
        self.statusbar.set_filename(filename)
        self.statusbar.set_root(self.filehandler.get_base_filename())
        self.statusbar.set_filesize(filesize)
        self.statusbar.update()
        self.update_title()

    def _page_available(self, page: int) -> None:
        """ Called whenever a new page is ready for displaying. """
        # Refresh display when currently opened page becomes available.
        current_page = self.imagehandler.get_current_page()
        nb_pages = 2 if self.displayed_double() else 1
        if current_page <= page < (current_page + nb_pages):
            self.draw_image(scroll_to=self._last_scroll_destination)
            self._update_page_information()

    def _on_file_opened(self) -> None:
        """Follow a book being opened: menus, lens and statusbar."""
        self.lens.file_changed()
        self.uimanager.set_sensitivities()
        number, count = self.filehandler.get_file_number()
        self.statusbar.set_file_number(number, count)
        self.statusbar.update()

    def _on_file_closed(self) -> None:
        """Follow a book being closed: empty the window and the sidebar."""
        self.lens.file_changed()
        self.clear()
        self.thumbnailsidebar.set_visible(False)
        self.thumbnailsidebar.clear()
        self.uimanager.set_sensitivities()

    def new_page(self, at_bottom: bool = False) -> None:
        """Draw a *new* page correctly (as opposed to redrawing the same
        image with a new size or whatever).
        """
        if not prefs['keep transformation']:
            prefs['rotation'] = 0
            prefs['horizontal flip'] = False
            prefs['vertical flip'] = False

        if at_bottom:
            scroll_to = constants.SCROLL_TO_END
        else:
            scroll_to = constants.SCROLL_TO_START

        self.draw_image(scroll_to=scroll_to)

    @callback.Callback
    def page_changed(self) -> None:
        """ Called on page change. """
        self.thumbnailsidebar.load_thumbnails()
        self._update_page_information()

    def set_page(self, num: int, at_bottom: bool = False) -> None:
        """Switch to page <num> of the currently open book.

        A bookmark, or the archive editor after pages were removed, can name
        a page that no longer exists, so <num> is clamped to what the book
        actually has rather than taken at face value.
        """
        num = min(max(num, 1), self.imagehandler.get_number_of_pages())
        if num < 1 or num == self.imagehandler.get_current_page():
            return
        self.imagehandler.set_page(num)
        self.page_changed()
        self.new_page(at_bottom=at_bottom)
        self.slideshow.update_delay()

    def next_book(self) -> None:
        """Open whatever follows the book being read, if anything should.

        Two preferences say what that is, and a running slideshow may
        stand in for the first: the next archive, and failing that the
        next directory.  A reader who has turned off "auto open next
        archive" is not taken out of an archive into the next directory
        either, since that would be the same jump by another route.
        """
        archive_open = self.filehandler.archive_type is not None
        next_archive_opened = False
        if (self.slideshow.is_running() and
            prefs['slideshow can go to next archive']) or \
           prefs['auto open next archive']:
            next_archive_opened = self.filehandler._open_next_archive()

        # If "Auto open next archive" is disabled, do not go to the next
        # directory if current file was an archive.
        if not next_archive_opened and \
           prefs['auto open next directory'] and \
           (not archive_open or prefs['auto open next archive']):
            self.filehandler.open_next_directory()

    def previous_book(self) -> None:
        """Open whatever comes before the book being read, if anything
        should.  The preferences are read as next_book() reads them."""
        archive_open = self.filehandler.archive_type is not None
        previous_archive_opened = False
        if (self.slideshow.is_running() and
                prefs['slideshow can go to next archive']) or \
                prefs['auto open next archive']:
            previous_archive_opened = self.filehandler._open_previous_archive()

        # If "Auto open next archive" is disabled, do not go to the previous
        # directory if current file was an archive.
        if not previous_archive_opened and \
                prefs['auto open next directory'] and \
                (not archive_open or prefs['auto open next archive']):
            self.filehandler.open_previous_directory()

    def flip_page(self, step: int, single_step: bool = False) -> None:
        """Turn <step> pages, and open the next or previous book at the ends.

        In double page mode a turn of one page moves two, unless
        <single_step> says otherwise or the pages either side of the
        turn cannot be shown as a pair.  Stepping past the last page
        opens the next book and stepping back from the first opens the
        previous one; a step that would land outside the book for any
        other reason stops at its end.
        """
        if not self.filehandler.file_loaded:
            return

        current_page = self.imagehandler.get_current_page()
        number_of_pages = self.imagehandler.get_number_of_pages()

        new_page = current_page + step
        if (abs(step) == 1 and
                not single_step and
                prefs['default double page'] and
                prefs['double step in double page mode']):
            if +1 == step and not self.imagehandler.get_virtual_double_page():
                new_page += 1
            elif -1 == step and not self.imagehandler.get_virtual_double_page(new_page - 1):
                new_page -= 1

        if new_page <= 0:
            # Only switch to previous page when flipping one page before the
            # first one. (Note: check for (page number <= 1) to handle empty
            # archive case).
            if -1 == step and current_page <= 1:
                return self.previous_book()
            # Handle empty archive case.
            new_page = min(1, number_of_pages)
        elif new_page > number_of_pages:
            if step == 1:
                return self.next_book()
            new_page = number_of_pages

        if new_page != current_page:
            self.set_page(new_page, at_bottom=(-1 == step))

    def first_page(self) -> None:
        number_of_pages = self.imagehandler.get_number_of_pages()
        if number_of_pages:
            self.set_page(1)

    def last_page(self) -> None:
        number_of_pages = self.imagehandler.get_number_of_pages()
        if number_of_pages:
            self.set_page(number_of_pages)

    def page_select(self, *args: object) -> None:
        pageselect.Pageselector(self)

    def rotate_90(self, *args: object) -> None:
        prefs['rotation'] = tools.compile_rotations(prefs['rotation'], 90)
        self.draw_image()

    def rotate_180(self, *args: object) -> None:
        prefs['rotation'] = tools.compile_rotations(prefs['rotation'], 180)
        self.draw_image()

    def rotate_270(self, *args: object) -> None:
        prefs['rotation'] = tools.compile_rotations(prefs['rotation'], 270)
        self.draw_image()

    def flip_horizontally(self, *args: object) -> None:
        prefs['horizontal flip'] = not prefs['horizontal flip']
        self.draw_image()

    def flip_vertically(self, *args: object) -> None:
        prefs['vertical flip'] = not prefs['vertical flip']
        self.draw_image()

    def change_double_page(self, toggleaction: "ui.Action") -> None:
        """Show one page at a time or two, and redraw either way."""
        prefs['default double page'] = toggleaction.get_active()
        self._update_page_information()
        self.draw_image()

    def change_manga_mode(self, toggleaction: "ui.Action") -> None:
        """Read right to left or left to right.

        Which way round a double page goes, and which way the arrow keys
        turn, both follow from this.
        """
        prefs['default manga mode'] = toggleaction.get_active()
        self.is_manga_mode = toggleaction.get_active()
        self._update_page_information()
        self.draw_image()

    def change_invert_scroll(self, toggleaction: "ui.Action") -> None:
        """Set which way smart scrolling walks a page.  Nothing is
        redrawn: the setting is read the next time one is scrolled."""
        prefs['invert smart scroll'] = toggleaction.get_active()

    def change_fullscreen(self, toggleaction: "ui.Action") -> None:
        """Fill the screen, or go back to a window.

        The size the window had is saved on the way in, since that is
        the size it goes back to, and the menu item is insensitive until
        the window state event says the change has happened - a second
        toggle in between would ask for the state that is already on its
        way.  Nothing is redrawn here: the resize does that.
        """
        toggleaction.set_sensitive(False)
        if toggleaction.get_active():
            if self.previous_size != (None, None):
                self.save_window_geometry()
            self.fullscreen()
        else:
            self.unfullscreen()

    def change_invert_color(self, toggleaction: "ui.Action") -> None:
        """Draw the pages in their own colours or in the opposite ones.

        The menu item's own state is what the preference and the
        enhancer are set to, rather than the opposite of what the
        enhancer holds: the enhance dialog sets the same thing, so the
        two are only ever in step if each follows the tick.
        """
        prefs['invert color'] = toggleaction.get_active()
        self.enhancer.invert_color = prefs['invert color']
        self.enhancer.signal_update()

    def change_zoom_mode(self, radioaction: "ui.Action | None" = None,
                         *args: object) -> None:
        """Fit pages by width, by height, to the window, or not at all.

        Called with no action to put the zoom back to what the
        preference says, which is what a book being opened wants; any
        zooming the reader had done by hand is dropped either way.
        """
        if radioaction:
            prefs['zoom mode'] = radioaction.get_current_value()
        self.zoom.set_fit_mode(prefs['zoom mode'])
        self.zoom.set_scale_up(prefs['stretch'])
        self.zoom.reset_user_zoom()
        self.draw_image()

    def change_autorotation(self, radioaction: "ui.Action | None" = None,
                            *args: object) -> None:
        """ Switches between automatic rotation modes, depending on which
        radiobutton is currently activated. """
        if radioaction:
            prefs['auto rotate depending on size'] = radioaction.get_current_value()
        self.draw_image()

    def change_stretch(self, toggleaction: "ui.Action", *args: object) -> None:
        """ Toggles stretching small images. """
        prefs['stretch'] = toggleaction.get_active()
        self.zoom.set_scale_up(prefs['stretch'])
        self.draw_image()

    def change_toolbar_visibility(self, toggleaction: "ui.Action") -> None:
        self._update_toggle_preference('show toolbar', toggleaction)

    def change_menubar_visibility(self, toggleaction: "ui.Action") -> None:
        self._update_toggle_preference('show menubar', toggleaction)

    def change_statusbar_visibility(self, toggleaction: "ui.Action") -> None:
        self._update_toggle_preference('show statusbar', toggleaction)

    def change_scrollbar_visibility(self, toggleaction: "ui.Action") -> None:
        self._update_toggle_preference('show scrollbar', toggleaction)

    def change_thumbnails_visibility(self, toggleaction: "ui.Action") -> None:
        self._update_toggle_preference('show thumbnails', toggleaction)

    def change_hide_all(self, toggleaction: "ui.Action") -> None:
        self._update_toggle_preference('hide all', toggleaction)

    def change_keep_transformation(self, *args: object) -> None:
        prefs['keep transformation'] = not prefs['keep transformation']

    def manual_zoom_in(self, *args: object) -> None:
        self.zoom.zoom_in()
        self.draw_image()

    def manual_zoom_out(self, *args: object) -> None:
        self.zoom.zoom_out()
        self.draw_image()

    def manual_zoom_original(self, *args: object) -> None:
        self.zoom.reset_user_zoom()
        self.draw_image()

    def _show_scrollbars(self, request: Sequence[bool]) -> None:
        """ Enables scroll bars depending on requests and preferences. """

        limit = self._should_toggle_be_visible('show scrollbar')
        for scrollbar, wanted in zip(self._scroll, request):
            scrollbar.set_visible(bool(limit and wanted))

    def is_scrollable(self) -> bool:
        """ Returns True if the current images do not fit into the viewport. """
        return not all(tools.smaller_or_equal(self.layout.get_union_box().get_size(),
                                              self.get_visible_area_size()))

    def scroll_with_flipping(self, x: float, y: float) -> bool:
        """Returns true if able to scroll without flipping to
        a new page and False otherwise."""
        return self._event_handler._scroll_with_flipping(x, y)

    def scroll(self, x: float, y: float, bound: str | None = None) -> bool:
        """Scroll <x> px horizontally and <y> px vertically. If <bound> is
        'first' or 'second', we will not scroll out of the first or second
        page respectively (dependent on manga mode). The <bound> argument
        only makes sense in double page mode.

        Return True if call resulted in new adjustment values, False
        otherwise.
        """
        old_hadjust = self._hadjust.get_value()
        old_vadjust = self._vadjust.get_value()

        visible_width, visible_height = self.get_visible_area_size()

        hadjust_upper = max(0, self._hadjust.get_upper() - visible_width)
        vadjust_upper = max(0, self._vadjust.get_upper() - visible_height)
        hadjust_lower = 0

        if bound is not None and self.is_manga_mode:
            bound = {'first': 'second', 'second': 'first'}[bound]

        if bound == 'first':
            hadjust_upper = max(0, hadjust_upper -
                                self.images[1].get_preferred_size()[1].width - 2)  # XXX transitional(double page limitation)

        elif bound == 'second':
            hadjust_lower = self.images[0].get_preferred_size()[1].width + 2  # XXX transitional(double page limitation)

        new_hadjust = old_hadjust + x
        new_vadjust = old_vadjust + y

        new_hadjust = max(hadjust_lower, new_hadjust)
        new_vadjust = max(0, new_vadjust)

        new_hadjust = min(hadjust_upper, new_hadjust)
        new_vadjust = min(vadjust_upper, new_vadjust)

        self._vadjust.set_value(new_vadjust)
        self._hadjust.set_value(new_hadjust)

        return old_vadjust != new_vadjust or old_hadjust != new_hadjust

    def scroll_to_predefined(self, destination: Sequence[int],
                             index: int | None = None) -> None:
        """Scroll to a named place - a corner, an edge, the middle - of
        the page at <index>, or of the whole layout if there is none."""
        self.layout.scroll_to_predefined(destination, index)
        self.update_viewport_position()

    def update_viewport_position(self) -> None:
        """Move the scrollbars to where the layout says the view is."""
        viewport_position = self.layout.get_viewport_box().get_position()
        self._hadjust.set_value(viewport_position[0])  # 2D only
        self._vadjust.set_value(viewport_position[1])  # 2D only

    def update_layout_position(self) -> None:
        """Tell the layout where the scrollbars have been moved to.

        The opposite direction from update_viewport_position(), and what
        the scrollbars' own handlers call.
        """
        self.layout.set_viewport_position(
            (int(round(self._hadjust.get_value())), int(round(self._vadjust.get_value()))))

    def clear(self) -> None:
        """Clear the currently displayed data (i.e. "close" the file)."""
        self.set_title(constants.APPNAME)
        self.statusbar.set_message('')
        self.draw_image()

    def _clear_main_area(self) -> None:
        """Leave an empty window: no pages, no scrollbars, plain colour.

        The layout is replaced by a dummy one rather than dropped, so
        that everything which asks the layout for a size goes on working
        with no book open.
        """
        for i in self.images:
            i.set_visible(False)
        for i in self.images:
            i.clear()
        self._show_scrollbars([False] * len(self._scroll))
        self.layout = layout.create_dummy_layout()
        self._main_layout.set_content_size(*self.layout.get_union_box().get_size())
        self.set_bg_colour(prefs['bg colour'])

    def displayed_double(self) -> bool:
        """Return True if two pages are currently displayed."""
        return bool(self.imagehandler.get_current_page() and
                    prefs['default double page'] and
                    not self.imagehandler.get_virtual_double_page() and
                    self.imagehandler.get_current_page() != self.imagehandler.get_number_of_pages())

    def get_visible_area_size(self) -> tuple[int, ...]:
        """Return a 2-tuple with the width and height of the visible part
        of the main layout area.
        """
        dimensions = list(self.get_window_size())

        for preference, action, widget_list in self._toggle_list:
            for widget in widget_list:
                if widget.get_visible():
                    axis = self._toggle_axis[widget]
                    requisition = widget.get_preferred_size()[1]
                    if constants.PageAxis.WIDTH == axis:
                        size = requisition.width
                    elif constants.PageAxis.HEIGHT == axis:
                        size = requisition.height
                    dimensions[axis] -= size

        return tuple(dimensions)

    def get_layout_pointer_position(self) -> tuple[float, float]:
        """Return a 2-tuple with the x and y coordinates of the pointer
        on the main layout area, relative to the layout.
        """
        x, y = self._main_layout.get_pointer()
        x += self._hadjust.get_value()
        y += self._vadjust.get_value()

        return (x, y)

    def set_layout_cursor(self, mode: "Gdk.Cursor | None") -> None:
        """Set the cursor on the main layout area to <mode>. You should
        probably use the cursor_handler instead of using this method
        directly.

        Not set_cursor: Gtk.Widget has one of its own in GTK4, and it
        puts the cursor on the widget it is called on rather than on the
        area the pages are drawn in.
        """
        self._main_layout.set_cursor(mode)

    def update_title(self) -> None:
        """Set the title acording to current state."""
        this_screen = 2 if self.displayed_double() else 1  # XXX limited to at most 2 pages
        # TODO introduce formatter to merge these string ops with the ops for status bar updates
        title = '['
        for i in range(this_screen):
            title += '%d' % (self.imagehandler.get_current_page() + i)
            if i < this_screen - 1:
                title += ','
        title += ' / %d]  %s' % (self.imagehandler.get_number_of_pages(),
                                 self.imagehandler.get_pretty_current_filename())
        title = i18n.to_unicode(title)

        if self.slideshow.is_running():
            title = '[%s] %s' % (_('SLIDESHOW'), title)

        self.set_title(i18n.to_display_string(title))

    def set_bg_colour(self, colour: Sequence[float],
                      dynamic: bool = False) -> None:
        """Set the background colour to <colour>, a sequence of Gdk.RGBA
        components: red, green, blue and alpha, each between 0 and 1.

        <dynamic> says the colour was read off the page rather than
        taken from the preference, which is what keeps the pitch black
        scheme from overruling it.
        """
        colour = list(theme.background(colour, dynamic)[:4])
        self._bg_css_provider.load_from_string(
            '#%s { background-color: %s; }'
            % (self._BG_CSS_NAME, Gdk.RGBA(*colour).to_string()))
        if prefs['thumbnail bg uses main colour']:
            self.thumbnailsidebar.change_thumbnail_background_color(prefs['bg colour'])
        self._bg_colour = colour

    def get_bg_colour(self) -> Sequence[float]:
        return self._bg_colour

    def displayed_pages(self) -> "list[int]":
        """The numbers of the pages on screen, in the order they read in."""
        this_screen = 2 if self.displayed_double() else 1  # XXX limited to at most 2 pages
        current: int = self.imagehandler.get_current_page()
        pages = [current + offset for offset in range(this_screen)]
        return list(reversed(pages)) if self.is_manga_mode else pages

    def page_at(self, x: float, y: float) -> "int | None":
        """The number of the page drawn at <x>, <y> on the page area.

        The coordinates are the page area's own, as a click on it gives
        them, and the pages are placed on it as a whole rather than on
        the part of it that shows, so the scroll position is added
        before they are compared.  None where no page is drawn there:
        the background around them, or no file open.
        """
        current: int = self.imagehandler.get_current_page()
        if not self.filehandler.file_loaded or not current:
            return None
        x += self._hadjust.get_value()
        y += self._vadjust.get_value()
        # The layout holds one box per page on screen, in the order the
        # pages were handed to it, wherever it decided to put them.
        for offset, content in enumerate(self.layout.get_content_boxes()):
            left, top = content.get_position()
            width, height = content.get_size()
            if left <= x < left + width and top <= y < top + height:
                return current + offset
        return None

    def extract_page(self, *args: object) -> None:
        """Save the pages on screen to disk."""
        self._save_pages(self.displayed_pages())

    def extract_popup_page(self, *args: object) -> None:
        """Save the page the right-click menu was opened over.

        In double page mode two pages stand side by side and the menu is
        opened on one of them; opened on the background around them
        there is no one page to mean, so both are offered, which is what
        the menu bar's own Save As does.
        """
        page = self.popup_page
        self._save_pages([page] if page is not None
                         else self.displayed_pages())

    def _save_pages(self, pages: "Iterable[int]") -> None:
        """Ask where each of <pages> should go, and put it there.

        A number is appended to the name offered where a file of that
        name is in the target directory already.
        """
        for page in pages:
            file_path = self.imagehandler.get_path_to_page(page)
            if not file_path:
                return
            file_name = os.path.split(file_path)[-1]

            if self.filehandler.archive_type is not None:
                # Prepend the archive base name to the filename being displayed
                archive_name = self.filehandler.get_pretty_current_filename()
                file_name = (
                    os.path.splitext(archive_name)[0] + '_' + file_name)

            target_dir = prefs['path of last saved in filechooser']
            suggest_name = i18n.to_unicode(file_name)
            attempt = 1
            while os.path.exists(os.path.join(target_dir, suggest_name)):
                suggest_name = tools.append_number_to_filename(
                    file_name, number=attempt)
                attempt += 1

            # MComix' own chooser, as the archive editor's Save As and
            # every Open in the program use.  A Gtk.FileDialog asks the
            # desktop for the chooser instead, which is drawn by the
            # file chooser portal where one is installed - another
            # program, which MComix' colour scheme does not reach.
            save_dialog = file_chooser_simple_dialog.SimpleFileChooserDialog(
                Gtk.FileChooserAction.SAVE, self, folder=target_dir)
            save_dialog.set_title(_('Save page as'))
            save_dialog.set_save_name(suggest_name)

            # Both pages of a double page get a dialog of their own, and
            # they stand at the same time: each answer needs the page it
            # was asked about, not whichever one the loop ended on.
            def saved(paths: list[str], file_path: str = file_path,
                      dialog: file_chooser_simple_dialog.SimpleFileChooserDialog
                      = save_dialog) -> None:
                dialog.destroy()
                if paths:
                    self._save_page_to(file_path, paths[0])

            save_dialog.run_async(saved)

    def _save_page_to(self, file_path: str, target: str) -> None:
        """Copy the page at <file_path> to <target>.

        Where it went is where the next save starts from, which is not
        the folder the chooser opened in: the user may have walked out
        of it.
        """
        target = i18n.to_unicode(target)
        try:
            shutil.copy2(file_path, target)
        except Exception as e:
            log.warning(e)

        prefs['path of last saved in filechooser'] = \
            os.path.dirname(target) \
            if prefs['store last saved in directory'] \
            else constants.HOME_DIR

    def delete(self, *args: object) -> None:
        """ The currently opened file/archive will be deleted after showing
        a confirmation dialog. """

        current_file = self.imagehandler.get_real_path()
        if current_file is None:
            # The menu entry is insensitive without a file open.
            return
        dialog = message_dialog.MessageDialog(
                self, modal=True, buttons=Gtk.ButtonsType.NONE)
        dialog.set_should_remember_choice(
                message_dialog.RememberedDialog.DELETE_OPENED_FILE)
        dialog.set_text(
                _('Delete "%s"?') % os.path.basename(current_file),
                _('The file will be deleted from your harddisk.'))
        dialog.add_button(_('_Cancel'), Response.CANCEL)
        dialog.add_button(_('_Delete'), Response.OK)
        # Enter must not delete a file.  A confirmation defaults to the
        # answer that changes nothing, and the one that does not is
        # drawn as the destructive action it is.
        dialog.set_default_response(Response.CANCEL)
        deletes = dialog.get_widget_for_response(Response.OK)
        if deletes is not None:
            deletes.add_css_class('destructive-action')
        dialog.run_async(lambda response: self._delete_answered(response, current_file))

    def _delete_answered(self, result: int, current_file: str) -> None:
        """Delete <current_file> if the confirmation came back positive."""
        if result == Response.OK:
            # Go to next page/archive, and delete current file
            if self.filehandler.archive_type is not None:
                self.filehandler.last_read_page.clear_page(current_file)

                next_opened = self.filehandler._open_next_archive()
                if not next_opened:
                    next_opened = self.filehandler._open_previous_archive()
                if not next_opened:
                    self.filehandler.close_file()

                if os.path.isfile(current_file):
                    os.unlink(current_file)
            else:
                if self.imagehandler.get_number_of_pages() > 1:
                    # Open the next/previous file
                    if self.imagehandler.get_current_page() >= self.imagehandler.get_number_of_pages():
                        self.flip_page(-1)
                    else:
                        self.flip_page(+1)
                    # Unlink the desired file
                    if os.path.isfile(current_file):
                        os.unlink(current_file)
                    # Refresh the directory
                    self.filehandler.refresh_file()
                else:
                    self.filehandler.close_file()
                    if os.path.isfile(current_file):
                        os.unlink(current_file)

    def show_info_panel(self) -> None:
        """ Shows an OSD displaying information about the current page. """

        if not self.filehandler.file_loaded:
            return

        text = ''
        filename = self.imagehandler.get_pretty_current_filename()
        if filename:
            text += '%s\n' % filename
        file_number, file_count = self.filehandler.get_file_number()
        if file_count:
            text += '(%d / %d)\n' % (file_number, file_count)
        else:
            text += '\n'
        page_number = self.imagehandler.get_current_page()
        number_of_pages = self.imagehandler.get_number_of_pages()
        if page_number:
            text += '%s %d / %d' % (_('Page'), page_number, number_of_pages)
        text = text.strip('\n')
        if text:
            self.osd.show(text)

    def minimize(self, *args: object) -> None:
        """ Minimizes the MComix window.

        The extra arguments are the ones a Gio action hands its callback;
        Gtk.Window.minimize() takes none.
        """
        super().minimize()

    def write_config_files(self) -> None:
        """Write out everything that is kept between sessions."""
        self.filehandler.write_fileinfo_file()
        preferences.write_preferences_file()
        bookmark_backend.BookmarksStore.write_bookmarks_file()

        # Write keyboard accelerator map
        keybindings.keybinding_manager(self).save()

    def save_and_terminate_program(self, *args: object) -> None:
        """Quit, and open this book at this page next time.

        The preference is what the next start reads to tell a quit that
        meant to be resumed from one that did not.
        """
        prefs['previous quit was quit and save'] = True

        self.terminate_program()

    def get_window_size(self) -> tuple[int, int]:
        """Return the size of the window.

        Gtk.Window.get_size() is not in GTK4.  A window that is on screen
        knows its size as its own allocation; before that, the only size
        there is is the one it asked for.  Not get_size() either, which
        Gtk.Widget defines as one number for one orientation.
        """
        width, height = self.get_width(), self.get_height()
        if width and height:
            return (width, height)
        default_width, default_height = self.get_default_size()
        return (default_width, default_height)

    def save_window_geometry(self) -> None:
        """Remember how large the window is, for the next start."""
        width, height = self.get_window_size()
        prefs['window width'] = width
        prefs['window height'] = height
        prefs['window maximized'] = self.is_maximized()

    def restore_window_geometry(self) -> bool:
        """Give the window the size it had, and say whether that changed it.

        Where the window is is not the program's to say: GTK4 has no way
        to place one, so only the size and whether it was maximised are
        remembered.
        """
        if self.get_window_size() == (prefs['window width'],
                                      prefs['window height']) \
           and self.is_maximized() == prefs['window maximized']:
            return False

        if prefs['window maximized']:
            self.maximize()
        else:
            self.set_default_size(prefs['window width'],
                                  prefs['window height'])
        return True

    def update_space(self) -> None:
        """Take the gap between two pages from the preferences and redraw."""
        self._spacing = prefs['space between two pages']
        self.draw_image()

    def close_program(self, *args: object) -> None:
        """Quit, keeping the window size unless it is a fullscreen one."""
        if not self.is_fullscreen():
            self.save_window_geometry()
        self.terminate_program()

    def terminate_program(self) -> None:
        """Run clean-up tasks and exit the program."""

        self.set_visible(False)

        if _main_loop.is_running():
            _main_loop.quit()

        if prefs['auto load last file'] and self.filehandler.file_loaded:
            prefs['path to last file'] = \
                self.imagehandler.get_real_path() or ''
            prefs['page of last file'] = self.imagehandler.get_current_page()

        else:
            prefs['path to last file'] = ''
            prefs['page of last file'] = 1

        self.write_config_files()

        self.filehandler.close_file()
        if main_dialog._dialog is not None:
            main_dialog._dialog.close()
        backend.LibraryBackend().close()

        # Wait for the threads that are still doing work which has to
        # finish - extracting, packing, deleting - before the process
        # goes.  A daemon thread is by definition one that nothing waits
        # for, and the page animation's decoder is one of those: it runs
        # until the page it draws is replaced or cleared, which quitting
        # does not do, so joining it never came back at all.  Joining
        # every thread was a guard against Python issue #1856, a crash
        # when a daemon thread ran on into interpreter shutdown; that was
        # fixed in Python 3.9, well below the 3.12 this needs.  A dummy
        # thread is daemonic too, so this covers those as well.
        for thread in threading.enumerate():
            if thread is threading.current_thread() or thread.daemon:
                continue
            log.debug('Waiting for thread %s to finish before exit', thread)
            thread.join()


#: The loop the program runs in.  Gtk.main() and Gtk.main_quit() are
#: not in GTK4; the main context they ran was always GLib's.
_main_loop = GLib.MainLoop()


def main_loop() -> GLib.MainLoop:
    """Return the loop the program runs in."""
    return _main_loop


#: Main window instance
__main_window: 'MainWindow | None' = None


def main_window() -> 'MainWindow | None':
    """ Returns the global main window instance, or None before one has
    been built: a dialog opened during startup has no parent yet. """
    return __main_window


def set_main_window(window: 'MainWindow') -> None:
    """Name <window> as the one main_window() answers with."""
    global __main_window
    __main_window = window


# vim: expandtab:sw=4:ts=4
