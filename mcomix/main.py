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
from mcomix import widgets
from mcomix import zoom
from mcomix import bookmark_backend
from mcomix import message_dialog
from mcomix import callback
from mcomix.library import backend, main_dialog
from mcomix import tools
from mcomix import box
from mcomix import layout
from mcomix import log
from mcomix.transform import Matrix, Transform
from mcomix.i18n import _

from collections.abc import Sequence
from typing import Any



class MainWindow(Gtk.Window):

    """The main window, is created at start and terminates the
    program when closed.
    """

    #: What set_bg_colour()'s style rule matches the page area by.
    _BG_CSS_NAME = 'mcomix-page-area'

    def __init__(self, fullscreen=False, is_slideshow=False,
            show_library=False, manga_mode=False, double_page=False,
            zoom_mode=None, open_path=None, open_page=0):
        super(MainWindow, self).__init__()

        # ----------------------------------------------------------------
        # Attributes
        # ----------------------------------------------------------------
        # Used to detect window fullscreen state transitions.
        self.was_fullscreen = False
        self.is_manga_mode = False
        self.previous_size = (None, None)
        self.was_out_of_focus = False
        # Remember last scroll destination.
        self._last_scroll_destination = constants.SCROLL_TO_START

        self.layout = layout.create_dummy_layout()
        self.transforms: list[Matrix] = []
        self._spacing = prefs['space between two pages']
        self._waiting_for_redraw = False

        self._main_layout = canvas.PageCanvas()
        # Gtk.EventBox was only ever here to give the pages a background
        # colour of their own; in GTK4 any widget can have one, and
        # every widget takes input, so the box is gone.  A style provider
        # is per display rather than per widget now, so the canvas is
        # named for the rule set_bg_colour() writes to single it out.
        self._main_layout.set_name(self._BG_CSS_NAME)
        self._bg_css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._bg_css_provider,
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
                       page_image.PageImage()] # XXX limited to at most 2 pages

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
        zoom_actions = { constants.ZoomMode.BEST: 'best_fit_mode',
                constants.ZoomMode.WIDTH: 'fit_width_mode',
                constants.ZoomMode.HEIGHT: 'fit_height_mode',
                constants.ZoomMode.SIZE: 'fit_size_mode',
                constants.ZoomMode.MANUAL: 'fit_manual_mode' }

        if zoom_mode is not None:
            zoom_action = zoom_actions[zoom_mode]
        else:
            zoom_action = zoom_actions[prefs['zoom mode']]

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
            ('show menubar'   , 'menubar'   , (self.menubar,)         ),
            ('show scrollbar' , 'scrollbar' , self._scroll            ),
            ('show statusbar' , 'statusbar' , (self.statusbar,)       ),
            ('show thumbnails', 'thumbnails', (self.thumbnailsidebar,)),
            ('show toolbar'   , 'toolbar'   , (self.toolbar,)         ),
        )

        # Each "toggle" widget "eats" part of the main layout visible area.
        self._toggle_axis = {
            self.thumbnailsidebar              : constants.PageAxis.WIDTH,
            self._scroll[constants.PageAxis.HEIGHT]: constants.PageAxis.WIDTH,
            self._scroll[constants.PageAxis.WIDTH] : constants.PageAxis.HEIGHT,
            self.statusbar                     : constants.PageAxis.HEIGHT,
            self.toolbar                       : constants.PageAxis.HEIGHT,
            self.menubar                       : constants.PageAxis.HEIGHT,
        }

        # Start with all "toggle" widgets hidden to avoid ugly transitions.
        for preference, action, widget_list in self._toggle_list:
            for widget in widget_list:
                widget.set_visible(False)

        toggleaction = self.actiongroup.get_action('hide_all')
        toggleaction.set_active(prefs['hide all'])

        # Sync each "toggle" widget active state with its preference.
        for preference, action, widget_list in self._toggle_list:
            self.actiongroup.get_action(action).set_active(prefs[preference])

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

    def gained_focus(self, *args):
        def _delayed_unset_out_of_focus(_):
            self.was_out_of_focus = False
            return False

        if self.was_out_of_focus:
            # Since clicking into an unfocused window triggers the
            # focus event first, then the mouse event, the mouse event
            # can no longer detect that it should be skipped. Thus, delay
            # unsetting was_out_of_focus.
            GLib.idle_add(_delayed_unset_out_of_focus, None,
                          priority=GLib.PRIORITY_DEFAULT_IDLE)

    def lost_focus(self, *args):
        self.was_out_of_focus = True

    def draw_image(self, scroll_to=None):
        """Draw the current pages and update the titlebar and statusbar.
        """
        # FIXME: what if scroll_to is different?
        if not self._waiting_for_redraw:  # Don't stack up redraws.
            self._waiting_for_redraw = True
            GLib.idle_add(self._draw_image, scroll_to,
                             priority=GLib.PRIORITY_HIGH_IDLE)

    def _update_toggle_preference(self, preference, toggleaction):
        ''' Update "toggle" widget corresponding <preference>.

        Note: the widget visibily itself is left unchanged. '''
        prefs[preference] = toggleaction.get_active()
        if 'hide all' == preference:
            self._update_toggles_sensitivity()
        # Since the size of the drawing area is dependent
        # on the visible "toggles", redraw the page.
        self.draw_image()

    def _should_toggle_be_visible(self, preference):
        ''' Return <True> if "toggle" widget for <preference> should be visible. '''
        if self.is_fullscreen:
            visible = not prefs['hide all in fullscreen']
        else:
            visible = not prefs['hide all']
        visible &= prefs[preference]
        if 'show thumbnails' == preference:
            visible &= self.filehandler.file_loaded
            visible &= self.imagehandler.get_number_of_pages() > 0
        return visible

    def _update_toggles_sensitivity(self) -> None:
        ''' Update each "toggle" widget sensitivity. '''
        sensitive = True
        if prefs['hide all']:
            sensitive = False
        elif prefs['hide all in fullscreen'] and self.is_fullscreen:
            sensitive = False
        for preference, action, widget_list in self._toggle_list:
            self.actiongroup.get_action(action).set_sensitive(sensitive)

    def _update_toggles_visibility(self) -> None:
        ''' Update each "toggle" widget visibility. '''
        for preference, action, widget_list in self._toggle_list:
            should_be_visible = self._should_toggle_be_visible(preference)
            for widget in widget_list:
                # No change in visibility?
                if should_be_visible != widget.get_visible():
                    widget.set_visible(should_be_visible)

    def _draw_image(self, scroll_to):

        self._update_toggles_visibility()

        self.osd.clear()

        if not self.filehandler.file_loaded:
            self._clear_main_area()
            self._waiting_for_redraw = False
            return False

        if self.imagehandler.page_is_available():
            distribution_axis = constants.DISTRIBUTION_AXIS
            alignment_axis = constants.ALIGNMENT_AXIS
            pixbuf_count = 2 if self.displayed_double() else 1 # XXX limited to at most 2 pages
            pixbuf_list = list(self.imagehandler.get_pixbufs(pixbuf_count))
            do_not_transform = [image_tools.is_animation(x) for x in pixbuf_list]
            size_list = [[pixbuf.get_width(), pixbuf.get_height()]
                         for pixbuf in pixbuf_list]

            if self.is_manga_mode:
                orientation = constants.MANGA_ORIENTATION
            else:
                orientation = constants.WESTERN_ORIENTATION

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
                orientation = list(orientation)
                orientation.reverse() # 2D only
                for i in range(pixbuf_count):
                    if do_not_transform[i]:
                        continue
                    size_list[i].reverse() # 2D only
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
                lambda zoom_dummy_size: self.zoom.get_zoomed_size(size_list, zoom_dummy_size,
                distribution_axis, [False] * pixbuf_count,
                prefs['double page autoresize'] in (constants.DOUBLE_PAGE_AUTORESIZE_SIZE,
                constants.DOUBLE_PAGE_AUTORESIZE_FIT_SIZE),
                prefs['double page autoresize'] == constants.DOUBLE_PAGE_AUTORESIZE_FIT_SIZE))
            content_boxes = self.layout.get_content_boxes()
            scaled_sizes = list(map(box.Box.get_size, content_boxes))

            self.transforms = [Transform.ID] * pixbuf_count
            for i in range(pixbuf_count):
                if do_not_transform[i]:
                    continue
                pixbuf_list[i] = image_tools.fit_pixbuf_to_rectangle(
                    pixbuf_list[i], scaled_sizes[i], rotation_list[i])
                self.transforms[i] += Transform.from_rotation(rotation_list[i]) # FIXME also include scales

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
                self.images[i].set_pixbuf(pixbuf_list[i], scaled_sizes[i])

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
            # If the pixbuf for the current page(s) isn't available,
            # hide all images to clear any old pixbufs.
            # XXX How about calling self._clear_main_area?
            for i in range(len(self.images)):
                self.images[i].set_visible(False)
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

        def make_status(info):
            if not isinstance(info, tuple):
                return info
            if self.is_manga_mode:
                info = reversed(info)
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

    def _page_available(self, page):
        """ Called whenever a new page is ready for displaying. """
        # Refresh display when currently opened page becomes available.
        current_page = self.imagehandler.get_current_page()
        nb_pages = 2 if self.displayed_double() else 1
        if current_page <= page < (current_page + nb_pages):
            self.draw_image(scroll_to=self._last_scroll_destination)
            self._update_page_information()

    def _on_file_opened(self) -> None:
        self.uimanager.set_sensitivities()
        number, count = self.filehandler.get_file_number()
        self.statusbar.set_file_number(number, count)
        self.statusbar.update()

    def _on_file_closed(self) -> None:
        self.clear()
        self.thumbnailsidebar.set_visible(False)
        self.thumbnailsidebar.clear()
        self.uimanager.set_sensitivities()

    def new_page(self, at_bottom=False):
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

    def set_page(self, num, at_bottom=False):
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
        archive_open = self.filehandler.archive_type is not None
        next_archive_opened = False
        if (self.slideshow.is_running() and \
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
        archive_open = self.filehandler.archive_type is not None
        previous_archive_opened = False
        if (self.slideshow.is_running() and \
            prefs['slideshow can go to next archive']) or \
            prefs['auto open next archive']:
            previous_archive_opened = self.filehandler._open_previous_archive()

        # If "Auto open next archive" is disabled, do not go to the previous
        # directory if current file was an archive.
        if not previous_archive_opened and \
            prefs['auto open next directory'] and \
            (not archive_open or prefs['auto open next archive']):
            self.filehandler.open_previous_directory()

    def flip_page(self, step, single_step=False):

        if not self.filehandler.file_loaded:
            return

        current_page = self.imagehandler.get_current_page()
        number_of_pages = self.imagehandler.get_number_of_pages()

        new_page = current_page + step
        if (1 == abs(step) and
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
            if 1 == step:
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

    def page_select(self, *args):
        pageselect.Pageselector(self)

    def rotate_90(self, *args):
        prefs['rotation'] = tools.compile_rotations(prefs['rotation'], 90)
        self.draw_image()

    def rotate_180(self, *args):
        prefs['rotation'] = tools.compile_rotations(prefs['rotation'], 180)
        self.draw_image()

    def rotate_270(self, *args):
        prefs['rotation'] = tools.compile_rotations(prefs['rotation'], 270)
        self.draw_image()

    def flip_horizontally(self, *args):
        prefs['horizontal flip'] = not prefs['horizontal flip']
        self.draw_image()

    def flip_vertically(self, *args):
        prefs['vertical flip'] = not prefs['vertical flip']
        self.draw_image()

    def change_double_page(self, toggleaction):
        prefs['default double page'] = toggleaction.get_active()
        self._update_page_information()
        self.draw_image()

    def change_manga_mode(self, toggleaction):
        prefs['default manga mode'] = toggleaction.get_active()
        self.is_manga_mode = toggleaction.get_active()
        self._update_page_information()
        self.draw_image()

    def change_invert_scroll(self, toggleaction):
        prefs['invert smart scroll'] = toggleaction.get_active()

    @property
    def is_fullscreen(self) -> bool:
        # Gdk.WindowState is gone; the window says so itself in GTK4.
        return self.get_property('fullscreened')

    def change_fullscreen(self, toggleaction):
        # Disable action until transition if complete.
        toggleaction.set_sensitive(False)
        if toggleaction.get_active():
            if self.previous_size != (None, None):
                self.save_window_geometry()
            self.fullscreen()
        else:
            self.unfullscreen()
        # No need to call draw_image explicitely,
        # as we'll be receiving a window state
        # change or resize event.

    def change_invert_color(self, toggleaction):
        prefs['invert color'] = not self.enhancer.invert_color
        self.enhancer.invert_color = prefs['invert color']
        self.enhancer.signal_update()

    def change_zoom_mode(self, radioaction=None, *args):
        if radioaction:
            prefs['zoom mode'] = radioaction.get_current_value()
        self.zoom.set_fit_mode(prefs['zoom mode'])
        self.zoom.set_scale_up(prefs['stretch'])
        self.zoom.reset_user_zoom()
        self.draw_image()

    def change_autorotation(self, radioaction=None, *args):
        """ Switches between automatic rotation modes, depending on which
        radiobutton is currently activated. """
        if radioaction:
            prefs['auto rotate depending on size'] = radioaction.get_current_value()
        self.draw_image()

    def change_stretch(self, toggleaction, *args):
        """ Toggles stretching small images. """
        prefs['stretch'] = toggleaction.get_active()
        self.zoom.set_scale_up(prefs['stretch'])
        self.draw_image()

    def change_toolbar_visibility(self, toggleaction):
        self._update_toggle_preference('show toolbar', toggleaction)

    def change_menubar_visibility(self, toggleaction):
        self._update_toggle_preference('show menubar', toggleaction)

    def change_statusbar_visibility(self, toggleaction):
        self._update_toggle_preference('show statusbar', toggleaction)

    def change_scrollbar_visibility(self, toggleaction):
        self._update_toggle_preference('show scrollbar', toggleaction)

    def change_thumbnails_visibility(self, toggleaction):
        self._update_toggle_preference('show thumbnails', toggleaction)

    def change_hide_all(self, toggleaction):
        self._update_toggle_preference('hide all', toggleaction)

    def change_keep_transformation(self, *args):
        prefs['keep transformation'] = not prefs['keep transformation']

    def manual_zoom_in(self, *args):
        self.zoom.zoom_in()
        self.draw_image()

    def manual_zoom_out(self, *args):
        self.zoom.zoom_out()
        self.draw_image()

    def manual_zoom_original(self, *args):
        self.zoom.reset_user_zoom()
        self.draw_image()

    def _show_scrollbars(self, request):
        """ Enables scroll bars depending on requests and preferences. """

        limit = self._should_toggle_be_visible('show scrollbar')
        for i in range(len(self._scroll)):
            self._scroll[i].set_visible(bool(limit and request[i]))

    def is_scrollable(self) -> bool:
        """ Returns True if the current images do not fit into the viewport. """
        if self.layout is None:
            return False
        return not all(tools.smaller_or_equal(self.layout.get_union_box().get_size(),
            self.get_visible_area_size()))

    def scroll_with_flipping(self, x, y):
        """Returns true if able to scroll without flipping to
        a new page and False otherwise."""
        return self._event_handler._scroll_with_flipping(x, y)

    def scroll(self, x, y, bound=None):
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
                self.images[1].get_preferred_size()[1].width - 2) # XXX transitional(double page limitation)

        elif bound == 'second':
            hadjust_lower = self.images[0].get_preferred_size()[1].width + 2 # XXX transitional(double page limitation)

        new_hadjust = old_hadjust + x
        new_vadjust = old_vadjust + y

        new_hadjust = max(hadjust_lower, new_hadjust)
        new_vadjust = max(0, new_vadjust)

        new_hadjust = min(hadjust_upper, new_hadjust)
        new_vadjust = min(vadjust_upper, new_vadjust)

        self._vadjust.set_value(new_vadjust)
        self._hadjust.set_value(new_hadjust)

        return old_vadjust != new_vadjust or old_hadjust != new_hadjust

    def scroll_to_predefined(self, destination, index=None):
        self.layout.scroll_to_predefined(destination, index)
        self.update_viewport_position()

    def update_viewport_position(self) -> None:
        viewport_position = self.layout.get_viewport_box().get_position()
        self._hadjust.set_value(viewport_position[0]) # 2D only
        self._vadjust.set_value(viewport_position[1]) # 2D only

    def update_layout_position(self) -> None:
        self.layout.set_viewport_position(
            (int(round(self._hadjust.get_value())), int(round(self._vadjust.get_value()))))

    def clear(self) -> None:
        """Clear the currently displayed data (i.e. "close" the file)."""
        self.set_title(constants.APPNAME)
        self.statusbar.set_message('')
        self.draw_image()

    def _clear_main_area(self) -> None:
        for i in self.images:
            i.set_visible(False)
        for i in self.images:
            i.clear()
        self._show_scrollbars([False] * len(self._scroll))
        self.layout = layout.create_dummy_layout()
        self._main_layout.set_content_size(*self.layout.get_union_box().get_size())
        self.set_bg_colour(prefs['bg colour'])

    def displayed_double(self):
        """Return True if two pages are currently displayed."""
        return (self.imagehandler.get_current_page() and
                prefs['default double page'] and
                not self.imagehandler.get_virtual_double_page() and
                self.imagehandler.get_current_page() != self.imagehandler.get_number_of_pages())

    def get_visible_area_size(self):
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

    def get_layout_pointer_position(self):
        """Return a 2-tuple with the x and y coordinates of the pointer
        on the main layout area, relative to the layout.
        """
        x, y = self._main_layout.get_pointer()
        x += self._hadjust.get_value()
        y += self._vadjust.get_value()

        return (x, y)

    def set_cursor(self, mode):
        """Set the cursor on the main layout area to <mode>. You should
        probably use the cursor_handler instead of using this method
        directly.
        """
        self._main_layout.set_cursor(mode)

    def update_title(self) -> None:
        """Set the title acording to current state."""
        this_screen = 2 if self.displayed_double() else 1 # XXX limited to at most 2 pages
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

    def get_bg_colour(self):
        return self._bg_colour

    def extract_page(self, *args):
        """Save the currently displayed images to disk, appending a number if a
        file with an identical name was already found in the target directory.
        """
        this_screen = 2 if self.displayed_double() else 1 # XXX limited to at most 2 pages
        for i in reversed(range(this_screen)) if self.is_manga_mode \
        else range(this_screen):
            file_path = self.imagehandler.get_path_to_page(
                self.imagehandler.get_current_page() + i)
            if not file_path:
                return
            file_name = os.path.split(file_path)[-1]

            if self.filehandler.archive_type is not None:
                # Prepend the archive base name to the filename being displayed
                archive_name = self.filehandler.get_pretty_current_filename()
                file_name = (
                    os.path.splitext(archive_name)[0] + '_' + file_name)

            target_dir = prefs['path of last saved in filechooser'] + os.sep
            suggest_name = i18n.to_unicode(file_name)
            attempt = 1
            while os.path.exists(target_dir + suggest_name):
                suggest_name = tools.append_number_to_filename(
                    file_name, number=attempt)
                attempt += 1

            # GTK4 takes the title, the parent and the buttons the way
            # every other window does: as properties, and by adding them.
            save_dialog = Gtk.FileChooserDialog(
                title=_('Save page as'), transient_for=self,
                action=Gtk.FileChooserAction.SAVE)
            save_dialog.add_buttons(_('_OK'), Gtk.ResponseType.ACCEPT,
                                    _('_Cancel'), Gtk.ResponseType.REJECT)
            save_dialog.set_create_folders(True)
            save_dialog.set_current_name(suggest_name)
            widgets.set_chooser_folder(save_dialog, target_dir)

            # Both pages of a double page get a dialog of their own, and
            # they stand at the same time: each answer needs the page it
            # was asked about, not whichever one the loop ended on.
            def save_responded(dialog: Any, response: int,
                               file_path: str = file_path) -> None:
                if response == Gtk.ResponseType.ACCEPT:
                    chosen = dialog.get_file()
                    target = chosen.get_path() if chosen else None
                    if target:
                        target = i18n.to_unicode(target)
                        try:
                            shutil.copy2(file_path, target)
                        except Exception as e:
                            log.warning(e)

                    prefs['path of last saved in filechooser'] = \
                        widgets.chooser_folder(dialog) \
                        if prefs['store last saved in directory'] \
                        else constants.HOME_DIR

                dialog.destroy()

            save_dialog.connect('response', save_responded)
            save_dialog.set_visible(True)

    def delete(self, *args):
        """ The currently opened file/archive will be deleted after showing
        a confirmation dialog. """

        current_file = self.imagehandler.get_real_path()
        dialog = message_dialog.MessageDialog(self, Gtk.DialogFlags.MODAL, Gtk.MessageType.QUESTION,
                Gtk.ButtonsType.NONE)
        dialog.set_should_remember_choice('delete-opend-file', (Gtk.ResponseType.OK,))
        dialog.set_text(
                _('Delete "%s"?') % os.path.basename(current_file),
                _('The file will be deleted from your harddisk.'))
        dialog.add_button(_('_Cancel'), Gtk.ResponseType.CANCEL)
        dialog.add_button(_('_Delete'), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.run_async(lambda response: self._delete_answered(response, current_file))

    def _delete_answered(self, result: int, current_file: str) -> None:
        """Delete <current_file> if the confirmation came back positive."""
        if result == Gtk.ResponseType.OK:
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

    def minimize(self, *args):
        """ Minimizes the MComix window.

        The extra arguments are the ones a Gio action hands its callback;
        Gtk.Window.minimize() takes none.
        """
        super(MainWindow, self).minimize()

    def write_config_files(self) -> None:

        self.filehandler.write_fileinfo_file()
        preferences.write_preferences_file()
        bookmark_backend.BookmarksStore.write_bookmarks_file()

        # Write keyboard accelerator map
        keybindings.keybinding_manager(self).save()

    def save_and_terminate_program(self, *args):
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
        width, height = self.get_window_size()
        prefs['window width'] = width
        prefs['window height'] = height
        prefs['window maximized'] = self.is_maximized()

    def restore_window_geometry(self) -> bool:
        # Where the window is is no longer the program's to say: GTK4
        # has no way to place a window, so only its size is remembered.
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
        self._spacing = prefs['space between two pages']
        self.draw_image()

    def close_program(self, *args):
        if not self.is_fullscreen:
            self.save_window_geometry()
        self.terminate_program()

    def terminate_program(self) -> None:
        """Run clean-up tasks and exit the program."""

        self.set_visible(False)

        if _main_loop.is_running():
            _main_loop.quit()

        if prefs['auto load last file'] and self.filehandler.file_loaded:
            prefs['path to last file'] = self.imagehandler.get_real_path()
            prefs['page of last file'] = self.imagehandler.get_current_page()

        else:
            prefs['path to last file'] = ''
            prefs['page of last file'] = 1

        self.write_config_files()

        self.filehandler.close_file()
        if main_dialog._dialog is not None:
            main_dialog._dialog.close()
        backend.LibraryBackend().close()

        # This hack is to avoid Python issue #1856.
        for thread in threading.enumerate():
            if thread is not threading.current_thread() and not isinstance(thread, threading._DummyThread):
                log.debug('Waiting for thread %s to finish before exit', thread)
                thread.join()

#: The loop the program runs in.  Gtk.main() and Gtk.main_quit() are
#: not in GTK4; the main context they ran was always GLib's.
_main_loop = GLib.MainLoop()


def main_loop() -> GLib.MainLoop:
    """Return the loop the program runs in."""
    return _main_loop


#: Main window instance
__main_window = None


def main_window():
    """ Returns the global main window instance. """
    return __main_window


def set_main_window(window):
    global __main_window
    __main_window = window


# vim: expandtab:sw=4:ts=4
