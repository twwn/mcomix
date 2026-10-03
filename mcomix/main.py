"""main.py - Main window."""

import math
import os
import threading

from gi.repository import Gdk, GdkPixbuf, Gtk, GLib

from mcomix import canvas
from mcomix import constants
from mcomix import cursor_handler
from mcomix import i18n
from mcomix import enhance_backend
from mcomix import event
from mcomix import edit_dialog
from mcomix import file_actions
from mcomix import file_handler
from mcomix import image_handler
from mcomix import image_tools
from mcomix import lens
from mcomix import preferences
from mcomix import process
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

from collections.abc import Callable, Iterable, Sequence


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
                 open_page: int = 0,
                 open_member: str | None = None) -> None:
        super().__init__()
        widgets.drop_focus_when_closed(self)

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
        #: The pages a reader has picked out with Ctrl and a click,
        #: which are the ones Delete removes.  They stay picked out
        #: while the book is read, so that pages can be marked as they
        #: go by and dealt with together; only closing the book, or
        #: removing them, empties this.
        self.selected_pages: set[int] = set()
        #: The page marked to be swapped with the next one clicked, if
        #: any: a swap takes two pages, and they are picked one at a
        #: time.
        self.swap_page: "int | None" = None
        #: Saving, deleting and moving the files of the book, and the
        #: undo stack they are taken back through.
        self.file_actions = file_actions.FileActions(self)
        #: Where a page that was not extracted yet when it was drawn is
        #: to be scrolled to once it arrives: kept until a redraw asks
        #: for somewhere else, not dropped by one that asks for nowhere.
        self._last_scroll_destination: int | None = constants.SCROLL_TO_START

        self.layout = layout.create_dummy_layout()
        self.transforms: list[Matrix] = []
        self._spacing = prefs['space between two pages']
        self._waiting_for_redraw = False
        #: The idle that will run _draw_image(), while one is queued.
        self._redraw_source: int | None = None
        #: Where the redraw that is pending was asked to scroll to.
        self._pending_scroll_to: int | None = None
        #: The page the reader last turned to, the page they turned from,
        #: and which way that went, for _skip_broken_page(); whether it
        #: was a turn of a page, which past an end of the book opens the
        #: next or the previous one; whether the search past pages that
        #: will not load has turned around at an end of the book yet,
        #: and whether it has given up, finding none that would.
        self._skip_origin: int | None = None
        self._skip_from = 0
        self._skip_direction = 1
        self._skip_turning = False
        self._skip_reversed = False
        self._skip_gave_up = False
        #: The last page but one, where a book opened at its end in
        #: double page mode stands until the sizes of its last two pages
        #: say whether they are shown together; see arrive_at_end().
        self._end_pending: int | None = None

        self.page_area = canvas.PageCanvas()
        # A style provider applies to the whole display rather than to
        # one widget, so the page area is named, and the rule
        # set_bg_colour() writes picks it out by that name.
        self.page_area.set_name(self._BG_CSS_NAME)
        self._bg_css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            widgets.display(), self._bg_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.event_handler = event.EventHandler(self)
        self._vadjust = self.page_area.get_vadjustment()
        self._hadjust = self.page_area.get_hadjustment()
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

        # Exactly two, which is the most a screen ever shows; the
        # second is hidden whenever a single page is displayed.
        self.images = [page_image.PageImage(),
                       page_image.PageImage()]

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
        self.event_handler.register_key_events()

        for img in self.images:
            self.page_area.put(img, 0, 0)
        self.set_bg_colour(prefs['bg colour'])

        # No step or page increments are set on the adjustments: the page
        # area sets both from the size of what shows every time it is
        # allocated, in PageCanvas._configure().

        # Three columns - thumbnail sidebar, page area, vertical scrollbar -
        # and six rows, of which the fourth is a spacer the sidebar spans.
        # A child fills its cell already, so all each one needs besides
        # its place is whether it expands.
        grid = Gtk.Grid()
        for child, column, row, width, height, hexpand, vexpand in (
                (self.menubar,                            0, 0, 3, 1, False, False),
                (self.toolbar,                            0, 1, 3, 1, False, False),
                (self.thumbnailsidebar,                   0, 2, 1, 3, False, True),
                (self.page_area,                          1, 2, 1, 1, True,  True),
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

        self.actiongroup.get_action(zoom_action).activate()

        if prefs['stretch']:
            self.actiongroup.get_action('stretch').activate()

        if prefs['invert smart scroll']:
            self.actiongroup.get_action('invert_scroll').activate()

        if prefs['keep transformation']:
            self.actiongroup.get_action('keep_transformation').activate()
        else:
            prefs['rotation'] = 0
            prefs['vertical flip'] = False
            prefs['horizontal flip'] = False

        # List of "toggles" that can be shown/hidden by the user.
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

        # Inverted colours are not one of those widgets.  The enhancer
        # reads the preference itself, and Ctrl+I toggles the action's
        # state, so a state left off would make the first Ctrl+I set the
        # colours to what they already are.  Only the state is out of
        # step, so it is moved rather than toggled - toggling it here
        # would redraw a window that is still being built.
        self.actiongroup.get_action('invert_color').show_active(
            prefs['invert color'])

        self.actiongroup.get_action('menu_autorotate_width').set_sensitive(False)
        self.actiongroup.get_action('menu_autorotate_height').set_sensitive(False)

        self.set_child(grid)

        # A widget takes what a controller added to it delivers.  The
        # window's key controller runs in the capture phase, so it hears
        # a key before the thumbnail list can make its own use of Up,
        # Down and Space.
        self.event_handler.register_controllers(self, self.page_area)

        self.connect('notify::is-active', self.event_handler.focus_changed)
        self.connect('close-request', self.close_program)
        # A window's default size is what it asked for, not what the
        # compositor gave it, so the canvas is what says it has changed.
        self.page_area.connect('resized', self.event_handler.resize_event)
        self.connect('notify::fullscreened', self.event_handler.window_state_event)
        self.connect('notify::maximized', self.event_handler.window_state_event)
        self.connect_after('unrealize', MainWindow._release)

        self.uimanager.set_sensitivities()
        self.restore_window_geometry()
        self.present()

        if prefs['default fullscreen'] or fullscreen:
            toggleaction = self.actiongroup.get_action('fullscreen')
            toggleaction.set_active(True)

        if prefs['previous quit was quit and save']:
            fileinfo = self.filehandler.read_fileinfo_file()

            if fileinfo is not None:

                open_path, index, open_member = fileinfo
                open_page = index + 1

        prefs['previous quit was quit and save'] = False

        if open_path is not None:
            self.filehandler.open_file(open_path, open_page,
                                       start_member=open_member)

        if is_slideshow and open_path is not None:
            self._start_slideshow_once_open()

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
            self._redraw_source = GLib.idle_add(
                self._draw_image, priority=GLib.PRIORITY_HIGH_IDLE)

    def _update_toggle_preference(self, preference: str,
                                  toggleaction: "ui.Action") -> None:
        """Update "toggle" widget corresponding <preference>.

        Note: the widget visibility itself is left unchanged."""
        preferences.set_by_name(preference, toggleaction.get_active())
        if preference == 'hide all':
            self.update_toggles_sensitivity()
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

    def update_toggles_sensitivity(self) -> None:
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
        self._redraw_source = None
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
            pixbuf_count = self.displayed_page_count()
            pixbuf_list = list(self.imagehandler.get_pixbufs(pixbuf_count))
            do_not_transform = [image_tools.is_animation(x) for x in pixbuf_list]
            size_list = [[pixbuf.get_width(), pixbuf.get_height()]
                         for pixbuf in pixbuf_list]
            # A page that would not load stands in as a page as tall as
            # the room there is, whatever size it was read at: it is
            # drawn again at the size it is laid out at, below.
            missing = [image_tools.is_missing_image(x) for x in pixbuf_list]
            if prefs['skip broken pages'] and not self._skip_gave_up and (
                    missing[0] or (any(missing) and not self.displayed_double())):
                # Unless the reader would rather not see it.  A first
                # page that would not load is turned past; a second one
                # leaves the first on its own, now that it has been read
                # and get_virtual_double_page() knows it for what it is.
                self._waiting_for_redraw = False
                if missing[0]:
                    self._skip_broken_page()
                else:
                    self.draw_image(scroll_to=scroll_to)
                return False
            if any(missing):
                room = max(1, self.get_visible_area_size()[1])
                for i in range(pixbuf_count):
                    if missing[i]:
                        width, height = size_list[i]
                        size_list[i] = [max(1, round(width * room / height)),
                                        room]

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
                if missing[i]:
                    # Drawn from its SVG at the size shown, turned as the
                    # page would be, so that the fitting below only turns it.
                    width, height = scaled_sizes[i]
                    if tools.rotation_swaps_axes(rotation_list[i]):
                        width, height = height, width
                    pixbuf_list[i] = image_tools.missing_image_icon(
                        max(1, int(width)), max(1, int(height)))
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
                bg_colour = self._edge_colour(pixbuf_list, content_boxes)
            if smartbg:
                self.set_bg_colour(bg_colour, dynamic=True)
            if smartthumbbg:
                self.thumbnailsidebar.change_thumbnail_background_color(
                    bg_colour, dynamic=True)

            self.page_area.set_content_size(*(self.layout.get_union_box().get_size()))
            for i in range(pixbuf_count):
                self.page_area.move(self.images[i],
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

            # The pages have changed under the pointer, which has not
            # moved, so no motion event will redraw the lens.
            self.lens.redraw()

        else:
            # Save scroll destination for when the page becomes available,
            # unless this redraw was asked for none: one that came while
            # the page was on its way - a resize, a toggled statusbar -
            # would otherwise leave it to open wherever the page before
            # it had been left.
            if scroll_to is not None:
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

    @staticmethod
    def _edge_colour(pixbufs: Sequence[GdkPixbuf.Pixbuf],
                     boxes: Sequence[box.Box]) -> list[float]:
        """The colour the pages on screen fade into, for the dynamic
        background.

        It is read off <pixbufs> as they are drawn - turned, flipped and
        enhanced - down the outer sides of the pages standing furthest
        left and right in <boxes>, the places each is drawn at.  The
        pages as they are in the file would need enhancing a second
        time, at their full size, for this alone, and their sides are
        not the ones on screen once a quarter turn has been applied.
        """
        order = sorted(range(len(pixbufs)),
                       key=lambda index: boxes[index].get_position()[0])
        if len(order) == 1:
            return image_tools.get_most_common_edge_colour(pixbufs[order[0]])
        return image_tools.get_most_common_edge_colour(
            (pixbufs[order[0]], pixbufs[order[-1]]))

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
        self.statusbar.set_page_number(self.displayed_pages(),
                                       self.imagehandler.get_number_of_pages())
        self.statusbar.set_filename(filename)
        self.statusbar.set_root(self.filehandler.get_base_filename())
        self.statusbar.set_filesize(filesize)
        self.statusbar.update()
        self.update_title()

    def arrive_at_end(self, page: int) -> None:
        """Note that the book was opened at <page>, its last but one, to
        show its last two pages together.

        Whether they are shown together is known only once both are out
        of the archive: a wide one is shown on its own, and the last page
        was then never shown at all - going back from the next book stood
        on the wide page before it (upstream bug 95).  _page_available()
        moves on to the last page if so, or this, where both are out
        already.
        """
        self._end_pending = page
        self._settle_at_end()

    def _settle_at_end(self) -> None:
        """Move from the last page but one to the last, if the two are
        not shown together; see arrive_at_end()."""
        pending = self._end_pending
        if pending is None:
            return
        if self.imagehandler.get_current_page() != pending:
            # The reader has moved on; where they went stands.
            self._end_pending = None
            return
        if not (self.imagehandler.page_is_available(pending)
                and self.imagehandler.page_is_available(pending + 1)):
            return
        self._end_pending = None
        if self.imagehandler.get_virtual_double_page(pending):
            self.set_page(pending + 1, at_bottom=True)

    def _page_available(self, page: int) -> None:
        """ Called whenever a new page is ready for displaying. """
        self._settle_at_end()
        # Refresh display when currently opened page becomes available.
        current_page = self.imagehandler.get_current_page()
        nb_pages = self.displayed_page_count()
        if current_page <= page < (current_page + nb_pages):
            self.draw_image(scroll_to=self._last_scroll_destination)
            self._update_page_information()

    def _start_slideshow_once_open(self) -> None:
        """Start the slideshow the command line asked for.

        The action can be used only with a book open, and the book the
        command line names is still being read when the window starts:
        activated then, as it was, it did nothing at all.  So it waits
        for the book, once - the listener stays behind, since taking a
        listener out of the list while that list is being called skips
        the one after it, but it does nothing again.
        """
        started = False

        def opened() -> None:
            nonlocal started
            if not started:
                started = True
                self.actiongroup.get_action('slideshow').activate()

        if self.filehandler.file_loaded:
            opened()
        else:
            self.filehandler.file_opened += opened

    def _on_file_opened(self) -> None:
        """Follow a book being opened: menus, lens and statusbar."""
        self.lens.file_changed()
        self.uimanager.set_sensitivities()
        number, count = self.filehandler.get_file_number()
        self.statusbar.set_file_number(number, count)
        self.statusbar.update()

    def _on_file_closed(self) -> None:
        """Follow a book being closed: empty the window and the sidebar."""
        # All of them stand against the pages of the book that is
        # going, and none means anything against the next one.
        self._end_pending = None
        self.selected_pages = set()
        self.swap_page = None
        self.file_actions.forget_changes()
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
        # The pages picked out stay picked out through a page turn; it
        # is which of them are on screen that has changed.
        self._draw_selection()
        self.thumbnailsidebar.load_thumbnails()
        self._update_page_information()

    def pages_replaced(self, image_files: list[str], page: int = 1) -> None:
        """Show the open book with <image_files> as its pages, at <page>.

        What the archive editor's Apply leaves behind, and what deleting
        a page from the window does: the listing is a new one, so every
        page number the window is holding stands against the book that
        was there before.  set_page() will not do on its own, since it
        returns early when it is asked for the page that is current
        already - which page 1 usually is - and the window then went on
        showing the drawn page, the page count and the thumbnails of the
        listing that had just been replaced.

        A book every page of which was removed is left drawn as it was:
        there is no page to move to, and closing the file is not what
        applying an edit was asked to do.
        """
        self.imagehandler.replace_pages(image_files)
        self._skip_origin = None
        self.thumbnailsidebar.clear()
        count = self.imagehandler.get_number_of_pages()
        if not count:
            return
        self.imagehandler.set_page(min(max(page, 1), count))
        self.page_changed()
        self.new_page()
        self._draw_selection()

    def set_page(self, num: int, at_bottom: bool = False,
                 turning: bool = False) -> None:
        """Switch to page <num> of the currently open book.

        A bookmark, or the archive editor after pages were removed, can name
        a page that no longer exists, so <num> is clamped to what the book
        actually has rather than taken at face value.  <turning> says it
        is a turn of a page, as flip_page() makes it, rather than a jump.
        """
        num = min(max(num, 1), self.imagehandler.get_number_of_pages())
        current = self.imagehandler.get_current_page()
        if num < 1 or num == current:
            return
        self._skip_origin = num
        self._skip_from = current
        self._skip_direction = 1 if num > current else -1
        self._skip_turning = turning
        self._skip_reversed = False
        self._skip_gave_up = False
        self._show_page(num, at_bottom)

    def _show_page(self, num: int, at_bottom: bool) -> None:
        """Turn to page <num>, which is in the book."""
        self.imagehandler.set_page(num)
        self.page_changed()
        self.new_page(at_bottom=at_bottom)
        self.slideshow.update_delay()

    def _skip_broken_page(self) -> None:
        """Turn past the page on screen, which would not load.

        "Skip broken pages" has it, and the search goes on the way the
        reader was going, one page at a time, each page drawn - and so
        read - in turn.  At an end of the book it turns around and
        looks the other way from the page the reader turned to, which is
        what Home or End onto a page that will not load wants; finding
        nothing that way either, it goes back to that page and shows
        what it always showed, the picture of a page that would not
        load.  A turn of a page is different: pages that will not load
        from there to the end are as good as no pages, so the turn goes
        past the end, back to the page it started from and on to the
        next book or the previous one, as a turn from that page would.
        """
        count = self.imagehandler.get_number_of_pages()
        current = self.imagehandler.get_current_page()
        origin = self._skip_origin
        if origin is None or not 1 <= origin <= count:
            # The pages were replaced since the reader last turned one.
            origin = self._skip_origin = current
            self._skip_direction = 1
        page = current + self._skip_direction
        if not 1 <= page <= count and self._skip_turning:
            # Should that open nothing, the reader is left where they
            # were; should the page they were on not load either, the
            # search goes on from it, away from the end.
            self._skip_turning = False
            self._skip_origin = self._skip_from
            self._skip_reversed = True
            direction = self._skip_direction
            self._skip_direction = -direction
            self._show_page(self._skip_from, direction > 0)
            if direction > 0:
                self.next_book()
            else:
                self.previous_book()
            return
        if not 1 <= page <= count and not self._skip_reversed:
            self._skip_reversed = True
            self._skip_direction = -self._skip_direction
            page = origin + self._skip_direction
        if not 1 <= page <= count:
            self._skip_gave_up = True
            if origin == current:
                self.draw_image()
            else:
                self._show_page(origin, False)
            return
        self._show_page(page, self._skip_direction < 0)

    def next_book(self) -> None:
        """Open whatever follows the book being read, if anything should.

        Two preferences say what that is, and a running slideshow may
        stand in for the first: the next archive, and failing that the
        next directory.  A reader who has turned off "auto open next
        archive" is not taken out of an archive into the next directory
        either, since that would be the same jump by another route.
        """
        self._leaving_book(self._open_next_book)

    def previous_book(self) -> None:
        """Open whatever comes before the book being read, if anything
        should.  The preferences are read as next_book() reads them."""
        self._leaving_book(self._open_previous_book)

    def _leaving_book(self, then: "Callable[[], None]") -> None:
        """Offer to remove the pages picked out, and then run <then>.

        Pages are picked out as a book goes by so that they can be dealt
        with together, and the end of the book is where that is.  There
        is nothing to ask where none are picked out, or where the
        archive is not one MComix could write the answer into: an
        offer to remove pages that could then not be saved would take
        the book apart for nothing.
        """
        if not self.selected_pages \
                or self.file_actions.writeable_archive_type() is None:
            then()
            return
        path = self.filehandler.get_path_to_base() or ''
        dialog = message_dialog.MessageDialog(
            self, modal=True, buttons=Gtk.ButtonsType.NONE)
        dialog.set_should_remember_choice(
            message_dialog.RememberedDialog.REMOVE_PICKED_OUT_PAGES)
        dialog.set_text(
            i18n.get_translation().ngettext(
                'Remove the page picked out of "%s"?',
                'Remove the pages picked out of "%s"?',
                len(self.selected_pages)) % os.path.basename(path),
            _('They are taken out of the archive on disk, which is '
              'written again at once. Leaving the book without removing '
              'them forgets which pages they were.'))
        dialog.add_button(_('_Keep them'), Response.NO)
        dialog.add_button(_('_Remove'), Response.YES)
        # Enter must not take pages out of an archive.  A confirmation
        # defaults to the answer that changes nothing.
        dialog.set_default_response(Response.NO)
        removes = dialog.get_widget_for_response(Response.YES)
        if removes is not None:
            removes.add_css_class('destructive-action')
        dialog.run_async(lambda response: self._leaving_answered(response,
                                                                 then))

    def _leaving_answered(self, response: int,
                          then: "Callable[[], None]") -> None:
        """Remove the pages if that is the answer, then leave the book."""
        if response == Response.YES and self.file_actions.remove_pages(
                self.selected_pages):
            self.file_actions.save_archive()
        then()

    def _open_next_book(self) -> None:
        archive_open = self.filehandler.archive_type is not None
        next_archive_opened = False
        if (self.slideshow.is_running() and
            prefs['slideshow can go to next archive']) or \
           prefs['auto open next archive']:
            next_archive_opened = self.filehandler.open_next_archive()

        # If "Auto open next archive" is disabled, do not go to the next
        # directory if current file was an archive.
        if not next_archive_opened and \
           prefs['auto open next directory'] and \
           (not archive_open or prefs['auto open next archive']):
            self.filehandler.open_next_directory()

    def _open_previous_book(self) -> None:
        archive_open = self.filehandler.archive_type is not None
        previous_archive_opened = False
        if (self.slideshow.is_running() and
                prefs['slideshow can go to next archive']) or \
                prefs['auto open next archive']:
            previous_archive_opened = self.filehandler.open_previous_archive()

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
            elif -1 == step:
                new_page = self._previous_spread(current_page)

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
            self.set_page(new_page, at_bottom=(-1 == step),
                          turning=abs(step) == 1)

    def _previous_spread(self, current_page: int) -> int:
        """The page a turn back from <current_page> lands on, in double
        page mode.

        The pages before it are shown as they were turning forward: a
        narrow page just before a wide one stood on its own, or was the
        second of a pair, as the run of narrow pages since the last wide
        page, or the start of the book, fell.  Only a spread that ends
        before <current_page> will do; where the pairing forward cannot
        be worked out, or would reach into the pages on screen - the
        reader has turned a single page since - the two pages before it
        are paired where they can be.
        """
        before = current_page - 1
        start = self.imagehandler.spread_start(before)
        if start == before - 1 or (
                start == before
                and self.imagehandler.get_virtual_double_page(before)):
            return start
        if not self.imagehandler.get_virtual_double_page(before - 1):
            return before - 1
        return before

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

        The size the window had is saved on the way in, since that is the
        size it goes back to; save_window_geometry() is what makes sure a
        second toggle arriving before the first has taken effect does not
        record the screen instead.  Nothing is redrawn here: the resize
        does that.
        """
        if toggleaction.get_active():
            if self.previous_size != (None, None):
                self.save_window_geometry()
            self.fullscreen()
        else:
            self.unfullscreen()

    def change_invert_color(self, toggleaction: "ui.Action") -> None:
        """Draw the pages in their own colours or in the opposite ones.

        The action's own state is what the preference and the enhancer
        are set to, rather than the opposite of what the enhancer holds:
        the enhance dialog sets the same thing, so the two are only ever
        in step if each follows the action.  No menu carries it; Ctrl+I
        is what toggles it.
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

    def change_keep_transformation(self, toggleaction: "ui.Action") -> None:
        """Keep the rotation and flips from one page to the next, or not.

        The action's state is the answer, as it is for every toggle
        here, rather than the preference turned over: the two agree
        only for as long as nothing else sets either.
        """
        prefs['keep transformation'] = toggleaction.get_active()

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
        return self.event_handler.scroll_with_flipping(x, y)

    def scroll(self, x: float, y: float) -> bool:
        """Scroll <x> px horizontally and <y> px vertically.

        Return True if call resulted in new adjustment values, False
        otherwise.
        """
        # From the page area rather than the scroll bars: until the
        # page area is next allocated, a frame after a page turn, they
        # still hold the page turned from.
        old_hadjust, old_vadjust = self.page_area.get_position()

        visible_width, visible_height = self.get_visible_area_size()
        content_width, content_height = self.page_area.get_content_size()

        hadjust_upper = max(0, content_width - visible_width)
        vadjust_upper = max(0, content_height - visible_height)

        new_hadjust = old_hadjust + x
        new_vadjust = old_vadjust + y

        new_hadjust = max(0, new_hadjust)
        new_vadjust = max(0, new_vadjust)

        new_hadjust = min(hadjust_upper, new_hadjust)
        new_vadjust = min(vadjust_upper, new_vadjust)

        self.page_area.scroll_to(new_hadjust, new_vadjust)

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
        self.page_area.scroll_to(*viewport_position)  # 2D only

    def update_layout_position(self) -> None:
        """Tell the layout where the page area is scrolled to.

        The opposite direction from update_viewport_position(), and what
        smart scrolling calls before it asks the layout for its next
        step.
        """
        x, y = self.page_area.get_position()
        self.layout.set_viewport_position((int(round(x)), int(round(y))))

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
        self.page_area.set_content_size(*self.layout.get_union_box().get_size())
        self.set_bg_colour(prefs['bg colour'])

    def displayed_double(self) -> bool:
        """Return True if two pages are currently displayed."""
        return bool(self.imagehandler.get_current_page() and
                    prefs['default double page'] and
                    not self.imagehandler.get_virtual_double_page() and
                    self.imagehandler.get_current_page() != self.imagehandler.get_number_of_pages())

    def displayed_page_count(self) -> int:
        """The number of pages on screen: two side by side, or one.

        Two is the most MComix ever shows.  The window holds exactly
        that many page widgets, and every caller that asks for pixbufs,
        page numbers or a background colour for what is on screen is
        sized by this.
        """
        return 2 if self.displayed_double() else 1

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

    def scroll_offset(self) -> tuple[float, float]:
        """How far the page area is scrolled, across and down.

        The pages are placed on the page area as a whole rather than on
        the part of it that shows, so this is what turns a point in the
        widget into a point on the pages.
        """
        return (self._hadjust.get_value(), self._vadjust.get_value())

    def set_layout_cursor(self, mode: "Gdk.Cursor | None") -> None:
        """Set the cursor on the main layout area to <mode>. You should
        probably use the cursor_handler instead of using this method
        directly.

        Not set_cursor: Gtk.Widget has one of its own in GTK4, and it
        puts the cursor on the widget it is called on rather than on the
        area the pages are drawn in.
        """
        self.page_area.set_cursor(mode)

    def update_title(self) -> None:
        """Set the title according to current state."""
        title = '[%s]  %s' % (
            status.format_page_number(self.displayed_pages(),
                                      self.imagehandler.get_number_of_pages()),
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
            % (self._BG_CSS_NAME, image_tools.rgba(*colour).to_string()))
        self._bg_colour = colour

    def get_bg_colour(self) -> Sequence[float]:
        return self._bg_colour

    def displayed_pages(self) -> "list[int]":
        """The numbers of the pages on screen, in the order they read in."""
        this_screen = self.displayed_page_count()
        current: int = self.imagehandler.get_current_page()
        pages = [current + offset for offset in range(this_screen)]
        return list(reversed(pages)) if self.is_manga_mode else pages

    #: The CSS classes that outline a picked-out page and the page
    #: waiting to be swapped; theme.py draws them.
    _SELECTED_CLASS = theme.PICKED_OUT_CLASS
    _MARKED_CLASS = theme.MARKED_CLASS

    def _numbered_page(self, page: "int | None") -> "int | None":
        """<page> if it is a page of the book that is open, else None.

        What the two gestures that name a page with the mouse ask
        before acting on what they were given: None is what page_at()
        answers for the background around the pages, and a number
        outside the book is what a listing that has changed under a
        caller leaves it holding.
        """
        if page is None or not 1 <= page <= \
                self.imagehandler.get_number_of_pages():
            return None
        return page

    def select_page(self, page: "int | None") -> None:
        """Pick <page> out, or put it back if it is picked out already.

        Toggling rather than setting is the way out of a page picked out
        by mistake, and more than one page can be picked out at a time:
        the point of picking them out while reading is to gather them up
        and deal with them at the end.  None picks out nothing, and
        leaves what is picked out alone.
        """
        page = self._numbered_page(page)
        if page is None:
            return
        self.selected_pages ^= {page}
        self._draw_selection()
        self.uimanager.set_sensitivities()

    def mark_for_swap(self, page: "int | None") -> None:
        """Mark <page> to be swapped, or swap it with the marked one.

        The first page clicked is marked and drawn as such; the second
        changes places with it.  Clicking the marked page again takes
        the mark off, which is the way out of a page marked by mistake,
        and clicking anywhere that is not a page leaves the mark where
        it is.
        """
        page = self._numbered_page(page)
        if page is None:
            return
        if self.swap_page is None:
            self.swap_page = page
            self._draw_selection()
            return
        marked, self.swap_page = self.swap_page, None
        if marked != page:
            self.file_actions.swap_pages(marked, page)
        self._draw_selection()
        self.uimanager.set_sensitivities()

    def clear_selection(self, *args: object) -> None:
        """Put every picked-out page back."""
        if not self.selected_pages:
            return
        self.selected_pages = set()
        self._draw_selection()
        self.uimanager.set_sensitivities()

    def selected_page_paths(self) -> list[str]:
        """The file of each picked-out page, in page order.

        A path outlives the number a page is at, which a deletion
        anywhere before it changes, so this is what the archive editor
        is handed and what it hands back.
        """
        files = self.imagehandler.get_image_files()
        return [files[number - 1] for number in sorted(self.selected_pages)
                if 1 <= number <= len(files)]

    def select_page_paths(self, paths: "Iterable[str]") -> None:
        """Pick out the pages whose files are <paths>, and no others."""
        wanted = set(paths)
        files = self.imagehandler.get_image_files()
        self.selected_pages = {number for number, path
                               in enumerate(files, start=1)
                               if path in wanted}
        self._draw_selection()
        self.uimanager.set_sensitivities()

    def _draw_selection(self) -> None:
        """Outline the page widgets showing a picked-out or marked page.

        A page picked out to be removed and a page marked to be swapped
        are drawn differently, and a page can be both.
        """
        current = self.imagehandler.get_current_page()
        for offset, image in enumerate(self.images):
            on_screen = offset < self.displayed_page_count()
            for css_class, marked in (
                    (self._SELECTED_CLASS,
                     current + offset in self.selected_pages),
                    (self._MARKED_CLASS, current + offset == self.swap_page)):
                if on_screen and marked:
                    image.add_css_class(css_class)
                else:
                    image.remove_css_class(css_class)
        # The thumbnail bar outlines them wherever they are in the book.
        self.thumbnailsidebar.restyle()

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
        offset_x, offset_y = self.scroll_offset()
        x += offset_x
        y += offset_y
        # The layout holds one box per page on screen, in the order the
        # pages were handed to it, wherever it decided to put them.
        for offset, content in enumerate(self.layout.get_content_boxes()):
            left, top = content.get_position()
            width, height = content.get_size()
            if left <= x < left + width and top <= y < top + height:
                return current + offset
        return None


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
        meant to be resumed from one that did not.  Everything else is
        what any other quit does, the window size included: this went
        straight to terminate_program(), so the one menu entry that
        promises to put the reader back where they were was also the one
        that forgot how large their window had been.
        """
        prefs['previous quit was quit and save'] = True

        self.close_program()

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
        """Remember how large the window is, for the next start.

        A window that is filling the screen is not saved: this size is
        what the next start is given and what leaving fullscreen goes
        back to, so recording the screen would make fullscreen permanent.
        Both callers can reach this with a fullscreen window - quitting
        out of fullscreen, and a fullscreen toggle arriving before the
        one before it has taken effect - so the guard is here rather than
        at each of them.
        """
        if self.is_fullscreen():
            return
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

    def close_program(self, *args: object) -> bool:
        """Quit, keeping the window size unless it is a fullscreen one.

        What has to be asked before a book closes is asked first - the
        archive editor's unapplied work, and the book's own unwritten
        changes - and the quit waits for the answer.  This is the
        window's close-request handler as well as the Quit action, so
        it answers whether the window may go: not while a question is
        up, since the window it stands against would be taken down with
        it.
        """
        self.save_window_geometry()
        quit_now: list[bool] = []

        def quit_for_good() -> None:
            quit_now.append(True)
            self.terminate_program()

        self.file_actions.before_closing(quit_for_good)
        # Whether the quit happened while this ran says whether there is
        # a question on screen: everything before_closing() asks about
        # is answered later, from the main loop.
        return not quit_now

    def restart_program(self) -> None:
        """Quit, and start MComix again on the book being read.

        Some of what the preferences dialog offers cannot reach an
        interface that is already on screen.  The interface language is
        the clearest case: gettext is asked for the catalogue as the
        modules are imported, so several hundred of the strings shown -
        the keybinding names, the error messages, the menu and toolbar
        tables - are translated before any window exists, and changing
        the preference afterwards leaves most of the interface in the
        language it started in.  Starting again is the only way to show
        one language throughout.

        What carries over is what the configuration files hold, which
        close_program() has just written, plus the book and its page,
        which are passed on the command line the way a shell would pass
        them.  The window geometry is among the written settings, so the
        new window comes up where this one stood.
        """
        # Both have to be read before the file handler is closed.
        path = self.imagehandler.get_real_path()
        page = self.imagehandler.get_current_page()

        def start_again() -> None:
            """Quit and start the new MComix, once the book being read
            has been dealt with: quitting can stop to ask whether to
            write the book out, and the new window is not to come up
            over that question."""
            self.close_program()
            process.launch_mcomix(path, page)

        self.file_actions.before_closing(start_again)

    def _release(self) -> None:
        """Let go of everything that would keep the closed window alive.

        GTK 4 does not dispose a destroyed window's widgets, and the
        handlers Python connected to them - and to the actions the menus
        trigger - are held in C, where Python's collector cannot see
        that they close over this window.  MComix builds one window per
        process, so that cost a reader nothing; the tests build one each,
        and kept every one of them alive with all it showed.
        """
        if self._redraw_source is not None:
            # A redraw queued as the window closed would draw onto the
            # cleared page area, and hold the window until it ran.
            GLib.source_remove(self._redraw_source)
            self._redraw_source = None
        widgets.release(self)
        self.page_area.clear()
        self.uimanager.release()
        self.cursor_handler.release()
        self.lens.release()
        bookmark_backend.BookmarksStore.forget(self)
        keybindings.forget(self)
        # Taking the widgets off the window frees the ones nothing else
        # holds.  A widget GTK holds as a child keeps its Python wrapper,
        # and the wrapper's attributes, out of reach of the collector:
        # the thumbnail bar's reference to this window kept it alive.
        self.set_child(None)
        # And whatever else hangs on the window: GTK finalized it with
        # popovers still parented to it ("Finalizing MainWindow, but it
        # still has children left"), and they went on asking their dead
        # root for its display the next time a style changed.
        child = self.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            child.unparent()
            child = following
        Gtk.StyleContext.remove_provider_for_display(
            widgets.display(), self._bg_css_provider)

    def terminate_program(self) -> None:
        """Run clean-up tasks and exit the program."""

        self.set_visible(False)

        if _main_loop.is_running():
            _main_loop.quit()

        if prefs['auto load last file'] and self.filehandler.file_loaded:
            prefs['path to last file'] = \
                self.imagehandler.get_real_path() or ''
            page = self.imagehandler.get_current_page()
            prefs['page of last file'] = page
            # The file of that page within an archive, which finds it
            # again however the archive is sorted by then.
            prefs['member of last file'] = \
                self.filehandler.page_member(page) or ''

        else:
            prefs['path to last file'] = ''
            prefs['page of last file'] = 1
            prefs['member of last file'] = ''

        self.write_config_files()

        # Whatever was to be done about a book with unwritten changes
        # has been done by now: close_program() asks before it quits,
        # and the close below is not to stop for a question with the
        # main loop already gone.  The archive editor is taken down for
        # the same reason - it is asked about before the quit, and a
        # question raised from here would never be answered.
        self.file_actions.forget_changes()
        edit_dialog.close_dialog()
        self.filehandler.close_file()
        library = main_dialog.get_dialog()
        if library is not None:
            library.close()
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


#: The loop the program runs in, on GLib's default main context,
#: which is the one GTK dispatches its events on.
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
