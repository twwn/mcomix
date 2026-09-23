"""preferences_dialog.py - Preferences dialog."""

import operator
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from gi.repository import GdkPixbuf, Gio, GObject, Gtk

from mcomix import preferences
from mcomix.preferences import prefs
from mcomix.dialog import Dialog
from mcomix import preferences_page
from mcomix import widgets
from mcomix import constants
from mcomix import image_tools
from mcomix import message_dialog
from mcomix import keybindings
from mcomix import keybindings_editor
from mcomix import theme
from mcomix import i18n
from mcomix.i18n import _
from mcomix.dialog import Response

if TYPE_CHECKING:
    from mcomix import main

_dialog: "_PreferencesDialog | None" = None

#: How many characters wide every spinner on a page is.
_SPINNER_WIDTH = 7

#: The widest gap the spinner offers between the two pages of a spread.
#: The fit modes take the gap out of the window before scaling the pages
#: to what is left, so a gap near the window's width shrinks both pages
#: to a few pixels; 100 is ample for a visible gutter and leaves most of
#: even a small window to the pages.
LARGEST_PAGE_GAP = 100


def _sort_row(first: Gtk.Widget, second: Gtk.Widget) -> Gtk.Box:
    """A row of two boxes, ending where the page ends.

    Each box keeps to its own width and the row hangs from the right,
    so that a row whose first box holds shorter words still ends where
    the one above it does.
    """
    row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
    row.set_halign(Gtk.Align.END)
    widgets.pack(row, first, False, False, 0)
    widgets.pack(row, second, False, False, 0)
    return row


class _PreferencesDialog(Dialog):

    """The preferences dialog where most (but not all) settings that are
    saved between sessions are presented to the user.
    """

    #: How wide the dialog opens.  The Shortcuts tab is what needs it:
    #: its list will not go under 832 pixels, and the dialog's own
    #: borders and the notebook's take 32 of whatever the dialog is
    #: given.  Past that the room goes to the column naming the action,
    #: which is the one that can use it.
    _DEFAULT_WIDTH = 900

    def __init__(self, window: "main.MainWindow") -> None:
        super().__init__(title=_('Preferences'), transient_for=window)

        # Button text is set later depending on active tab
        self.reset_button = self.add_button('', constants.RESPONSE_REVERT_TO_DEFAULT)
        self.add_button(_('_Close'), Response.CLOSE)

        self._window = window
        self.set_resizable(True)
        # Wide enough for the Shortcuts tab, which is a name and four
        # shortcut columns beside it and needs more room than any of
        # the others; the height is whatever the tabs come to.
        self.set_default_size(self._DEFAULT_WIDTH, -1)
        self.set_default_response(Response.CLOSE)

        self.connect('response', self._response)

        notebook = self.notebook = Gtk.Notebook()
        widgets.pack(self.get_content_area(), notebook, True, True, 0)
        widgets.set_border(self, 4)
        widgets.set_border(notebook, 6)

        #: The choosers for the prompts that are answered without being
        #: asked, so that clearing every answer can put them all back to
        #: asking.  The Behaviour tab fills this as it is built.
        self._remembered_answers: "list[widgets.Chooser[int | None]]" = []

        page_inits = (
            (_('Appearance'), self._init_appearance_tab),
            (_('Behaviour'), self._init_behaviour_tab),
            (_('Display'), self._init_display_tab),
            (_('Advanced'), self._init_advanced_tab),
        )

        for title, page_init in page_inits:
            container = Gtk.ScrolledWindow()
            container.set_policy(
                Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            container.set_min_content_height(400)
            container.set_propagate_natural_height(True)
            container.set_overlay_scrolling(False)
            page = page_init()
            container.set_child(page)
            notebook.append_page(container, Gtk.Label(label=title))

        # Shortcuts is already a ScrolledWindow
        self.shortcuts = self._init_shortcuts_tab()
        notebook.append_page(
            self.shortcuts, Gtk.Label(label=_('Shortcuts')))

        notebook.connect('switch-page', self._tab_page_changed)
        # Update the Reset button's tooltip
        self._tab_page_changed(notebook, None, 0)

        self.set_visible(True)

    def _init_appearance_tab(self) -> preferences_page._PreferencePage:
        # ----------------------------------------------------------------
        # The "Appearance" tab.
        # ----------------------------------------------------------------
        page = preferences_page._PreferencePage(None)

        page.new_section(_('User interface'))

        page.add_row(Gtk.Label(label=_('Language (needs restart):')),
                     self._create_language_control())

        page.add_row(Gtk.Label(label=_('Theme:')),
                     self._create_theme_control())

        page.add_row(self._create_pref_check_button(
            _('Escape key closes program'), 'escape quits',
            _('When active, the ESC key closes the program, instead of only '
              'disabling fullscreen mode.')))

        page.new_section(_('Background'))

        fixed_bg_button, dynamic_bg_button = self._create_binary_pref_radio_buttons(
            _('Use this colour as background:'),
            _('Always use this selected colour as the background colour.'),
            _('Use dynamic background colour'),
            'smart bg',
            _('Automatically pick a background colour that fits the viewed image.'))
        page.add_row(fixed_bg_button, self._create_color_button('bg colour'))
        page.add_row(dynamic_bg_button)

        page.new_section(_('Thumbnails'))

        thumb_fixed_bg_button, thumb_dynamic_bg_button = self._create_binary_pref_radio_buttons(
            _('Use this colour as the thumbnail background:'),
            _('Always use this selected colour as the thumbnail background colour.'),
            _('Use dynamic background colour'),
            'smart thumb bg',
            _('Automatically use the colour that fits the viewed image for the thumbnail background.'))
        page.add_row(thumb_fixed_bg_button, self._create_color_button('thumb bg colour'))
        page.add_row(thumb_dynamic_bg_button)

        page.add_row(self._create_pref_check_button(
            _('Show page numbers on thumbnails'),
            'show page numbers on thumbnails', None))

        page.add_row(Gtk.Label(label=_('Thumbnail size (in pixels):')),
                     self._create_pref_spinner(
                         'thumbnail size',
                         1, 20, 500, 1, 10, 0, None))

        page.new_section(_('Transparency'))

        page.add_row(self._create_pref_check_button(
            _('Use checkered background for transparent images'),
            'checkered bg for transparent images',
            _('Use a grey checkered background for transparent images. If this preference is unset, the background is plain white instead.')))

        return page

    def _init_behaviour_tab(self) -> preferences_page._PreferencePage:
        # ----------------------------------------------------------------
        # The "Behaviour" tab.
        # ----------------------------------------------------------------
        page = preferences_page._PreferencePage(None)

        page.new_section(_('Scroll'))

        page.add_row(self._create_pref_check_button(
            _('Use smart scrolling'),
            'smart scroll',
            _('With this preference set, the space key and mouse wheel '
              'do not only scroll down or up, but also sideways and so '
              'try to follow the natural reading order of the comic book.')))

        page.add_row(self._create_pref_check_button(
            _('Flip pages when scrolling off the edges of the page'),
            'flip with wheel',
            _('Flip pages when scrolling "off the page" with the scroll wheel or with the arrow keys. It takes n consecutive "steps" with the scroll wheel or the arrow keys for the pages to be flipped.')))

        page.add_row(self._create_pref_check_button(
            _('Automatically open the next archive'),
            'auto open next archive',
            _('Automatically open the next archive in the directory when flipping past the last page, or the previous archive when flipping past the first page.')))

        page.add_row(self._create_pref_check_button(
            _('Automatically open next directory'),
            'auto open next directory',
            _('Automatically open the first file in the next sibling directory when flipping past the last page of the last file in a directory, or the previous directory when flipping past the first page of the first file.')))

        page.add_row(self._create_pref_check_button(
            _('Open first file when navigating to previous archive'),
            'open first file in prev archive',
            _('Automatically open the first file of the previous archive when navigating to it, instead of opening the last file of the previous archive.')))

        page.add_row(self._create_pref_check_button(
            _('Open first file when navigating to previous directory'),
            'open first file in prev directory',
            _('Automatically open the first file of the previous directory when navigating to it, instead of opening the last file of the previous directory.')))

        page.add_row(Gtk.Label(label=_('Number of pixels to scroll per arrow key press:')),
                     self._create_pref_spinner(
                         'number of pixels to scroll per key event',
                         1, 1, 500, 1, 3, 0,
                         _('Set the number of pixels to scroll on a page when using the arrow keys.')))

        page.add_row(Gtk.Label(label=_('Number of pixels to scroll per mouse wheel turn:')),
                     self._create_pref_spinner(
                         'number of pixels to scroll per mouse wheel event',
                         1, 1, 500, 1, 3, 0,
                         _('Set the number of pixels to scroll on a page when using a mouse wheel.')))

        page.add_row(Gtk.Label(label=_('Fraction of page to scroll '
                                       'per space key press (in percent):')),
                     self._create_pref_spinner(
                         'smart scroll percentage',
                         0.01, 1, 100, 1, 5, 0,
                         _('Sets the percentage by which the page '
                           'will be scrolled down or up when the space key is pressed.')))

        page.add_row(Gtk.Label(label=_('Number of "steps" to take before flipping the page:')),
                     self._create_pref_spinner(
                         'number of key presses before page turn',
                         1, 1, 100, 1, 3, 0,
                         _('Set the number of "steps" needed to flip to the next or previous page.  Less steps will allow for very fast page turning but you might find yourself accidentally turning pages.')))

        page.new_section(_('Double page mode'))

        page.add_row(self._create_pref_check_button(
            _('Flip two pages in double page mode'),
            'double step in double page mode',
            _('Flip two pages, instead of one, each time we flip pages in double page mode.')))

        page.add_row(Gtk.Label(label=_('Show only one page where appropriate:')),
                     self._create_doublepage_as_one_control())

        page.add_row(Gtk.Label(label=_('Page auto-resizing:')),
                     self._create_double_page_autoresize_control())

        page.add_row(Gtk.Label(label=_('Space between two pages (in pixels):')),
                     self._create_pref_spinner(
                         'space between two pages',
                         1, 0, LARGEST_PAGE_GAP, 1, 10, 0, None))

        page.new_section(_('Files'))

        page.add_row(self._create_pref_check_button(
            _('Automatically open the last viewed file on startup'),
            'auto load last file',
            _('Automatically open, on startup, the file that was open when MComix was last closed.')))

        page.add_row(Gtk.Label(label=_('Store information about recently opened files:')),
                     self._create_store_recent_combobox())

        page.add_row(self._create_pref_check_button(_('Save As opens at the last directory saved into'),
                                                    'store last saved in directory',
                                                    _('Open the Save As dialog at the directory in which the last file was saved.')))

        page.add_row(self._create_pref_check_button(
            _('Save an edited archive in the format it was opened in'),
            'keep archive format when saving',
            _('Write an edited archive back as a ZIP, a tar, a 7z or a RAR, whichever it was read as. The last two need the 7z and rar programs, which MComix does not install; a format it cannot write is saved as a ZIP.')))

        page.new_section(_('Prompts answered for good'))

        for dialog_id, prompt in message_dialog.REMEMBERED_DIALOGS.items():
            chooser = self._create_remembered_answer_control(dialog_id, prompt)
            self._remembered_answers.append(chooser)
            page.add_row(Gtk.Label(label=prompt.label), chooser)

        return page

    def _init_display_tab(self) -> preferences_page._PreferencePage:
        # ----------------------------------------------------------------
        # The "Display" tab.
        # ----------------------------------------------------------------
        page = preferences_page._PreferencePage(None)

        page.new_section(_('Fullscreen'))

        page.add_row(self._create_pref_check_button(
            _('Use fullscreen by default'),
            'default fullscreen', None))

        page.add_row(self._create_pref_check_button(
            _('Automatically hide all toolbars in fullscreen'),
            'hide all in fullscreen', None))

        page.new_section(_('Fit to size mode'))

        page.add_row(Gtk.Label(label=_('Fixed width for wide pages:')),
                     self._create_pref_spinner(
                         'fit to size width wide',
                         1, 10, constants.RENDER_SIZE_LIMIT, 10, 50, 0, None))

        page.add_row(Gtk.Label(label=_('Fixed height for wide pages:')),
                     self._create_pref_spinner(
                         'fit to size height wide',
                         1, 10, constants.RENDER_SIZE_LIMIT, 10, 50, 0, None))

        page.add_row(Gtk.Label(label=_('Fixed width for other pages:')),
                     self._create_pref_spinner(
                         'fit to size width other',
                         1, 10, constants.RENDER_SIZE_LIMIT, 10, 50, 0, None))

        page.add_row(Gtk.Label(label=_('Fixed height for other pages:')),
                     self._create_pref_spinner(
                         'fit to size height other',
                         1, 10, constants.RENDER_SIZE_LIMIT, 10, 50, 0, None))

        page.new_section(_('Slideshow'))

        page.add_row(Gtk.Label(label=_('Slideshow delay (in seconds):')),
                     self._create_pref_spinner(
                         'slideshow delay',
                         1000.0, 0.01, 3600.0, 0.1, 1, 2, None))

        page.add_row(Gtk.Label(label=_('Slideshow step (in pixels):')),
                     self._create_pref_spinner(
                         'number of pixels to scroll per slideshow event',
                         1, -500, 500, 1, 1, 0,
                         _('Specify the number of pixels to scroll while in slideshow mode. A positive value will scroll forward, a negative value will scroll backwards, and a value of 0 will cause the slideshow to always flip to a new page.')))

        page.add_row(self._create_pref_check_button(
            _('During a slideshow automatically open the next archive'),
            'slideshow can go to next archive',
            _('While in slideshow mode allow the next archive to automatically be opened.')))

        page.new_section(_('Rotation'))

        page.add_row(self._create_pref_check_button(
            _('Automatically rotate images according to their metadata'),
            'auto rotate from exif',
            _('Automatically rotate images when an orientation is specified in the image metadata, such as in an Exif tag.')))

        page.new_section(_('Image quality'))

        page.add_row(Gtk.Label(label=_('Scaling mode')),
                     self._create_scaling_quality_combobox())

        return page

    def _init_advanced_tab(self) -> preferences_page._PreferencePage:
        # ----------------------------------------------------------------
        # The "Advanced" tab.
        # ----------------------------------------------------------------

        page = preferences_page._PreferencePage(None)

        page.new_section(_('File order'))

        page.add_row(Gtk.Label(label=_('Sort files and directories by:')),
                     self._create_sort_by_control())

        page.add_row(Gtk.Label(label=_('Sort archives by:')),
                     self._create_archive_sort_by_control())

        page.new_section(_('Extraction and cache'))

        page.add_row(Gtk.Label(label=_('Maximum number of concurrent extraction threads:')),
                     self._create_pref_spinner(
                         'max extract threads',
                         1, 1, 16, 1, 4, 0,
                         _('Set the maximum number of concurrent threads for formats that support it.')))

        page.add_row(Gtk.Label(label=_('Maximum number of concurrent thumbnail threads:')),
                     self._create_pref_spinner(
                         'max threads',
                         1, 1, 16, 1, 4, 0,
                         _('Set the maximum number of concurrent threads used to generate thumbnails. Takes effect the next time MComix is started.')))

        page.add_row(self._create_pref_check_button(
            _('Store thumbnails for opened files'),
            'create thumbnails',
            _('Store thumbnails for opened files according to the freedesktop.org specification. These thumbnails are shared by many other applications, such as most file managers.')))

        page.add_row(Gtk.Label(label=_('Maximum number of pages to store in the cache:')),
                     self._create_pref_spinner(
                         'max pages to cache',
                         1, -1, 500, 1, 3, 0,
                         _('Set the max number of pages to cache. A value of -1 will cache the entire archive.')))

        page.new_section(_('Magnifying Lens'))

        page.add_row(Gtk.Label(label=_('Magnifying lens size (in pixels):')),
                     self._create_pref_spinner(
                         'lens size',
                         1, 50, 400, 1, 10, 0,
                         _('Set the size of the magnifying lens. It is a square with a side of this many pixels.')))

        page.add_row(Gtk.Label(label=_('Magnification factor:')),
                     self._create_pref_spinner(
                         'lens magnification',
                         1, 1.1, 10.0, 0.1, 1.0, 1,
                         _('Set the magnification factor of the magnifying lens.')))

        page.new_section(_('Comments'))

        page.add_row(Gtk.Label(label=_('Comment extensions:')),
                     self._create_extensions_entry())

        page.new_section(_('Animated images'))

        page.add_row(Gtk.Label(label=_('Animation mode:')),
                     self._create_animation_mode_combobox())

        return page

    def _init_shortcuts_tab(self) -> keybindings_editor.KeybindingEditorWindow:
        # ----------------------------------------------------------------
        # The "Shortcuts" tab.
        # ----------------------------------------------------------------
        km = keybindings.keybinding_manager(self._window)
        page = keybindings_editor.KeybindingEditorWindow(km)
        self.shortcuts = page
        return page

    def _tab_page_changed(self, notebook: Gtk.Notebook,
                          page_ptr: "Gtk.Widget | None",
                          page_num: int) -> None:
        """ Dynamically switches the "Reset" button's text and tooltip
        depending on the currently selected tab page. """
        new_page = notebook.get_nth_page(page_num)
        if new_page == self.shortcuts:
            self.reset_button.set_label(_("_Reset keys"))
            self.reset_button.set_tooltip_text(
                _("Resets all keyboard shortcuts to their default values."))
            self.reset_button.set_sensitive(True)
        else:
            self.reset_button.set_label(_('Clear _dialog choices'))
            self.reset_button.set_tooltip_text(
                _('Clears all dialog choices that you have previously chosen not to be asked again.'))
            self.reset_button.set_sensitive(bool(prefs['stored dialog choices']))

    def _response(self, dialog: Dialog, response: int) -> None:
        if response == Response.CLOSE:
            _close_dialog()

        elif response == constants.RESPONSE_REVERT_TO_DEFAULT:
            if self.notebook.get_nth_page(self.notebook.get_current_page()) == self.shortcuts:
                # "Shortcuts" page is active, reset all keys to their default value
                km = keybindings.keybinding_manager(self._window)
                km.clear_all()
                self._window.event_handler.register_key_events()
                km.save()
                self.shortcuts.refresh_model()
            else:
                prefs['stored dialog choices'] = {}
                for chooser in self._remembered_answers:
                    chooser.set_value(None)
                self.reset_button.set_sensitive(False)

        else:
            # Other responses close the dialog, e.g. clicking the X icon on the dialog.
            _close_dialog()

    def _create_remembered_answer_control(
            self, dialog_id: "message_dialog.RememberedDialog",
            prompt: "message_dialog._Prompt") -> "widgets.Chooser[int | None]":
        """The chooser for how <prompt> is answered without being asked.

        "Ask every time" is the prompt having no answer stored at all,
        so picking it is what taking one answer back means; picking one
        of the answers is what ticking "Do not ask again" on the prompt
        itself does.
        """
        options: "list[tuple[str, int | None]]" = [(_('Ask every time'), None)]
        options.extend(prompt.answers)
        chooser = widgets.Chooser(
            options, prefs['stored dialog choices'].get(dialog_id))
        chooser.set_tooltip_text(
            _('What MComix answers this prompt with instead of asking. '
              'This is what the prompt\'s "Do not ask again" box sets.'))

        def answered(picked: "widgets.Chooser[int | None]") -> None:
            answer = picked.get_value()
            if answer is None:
                prefs['stored dialog choices'].pop(dialog_id, None)
            else:
                prefs['stored dialog choices'][dialog_id] = answer
            # The preference is the dictionary, which is the same
            # dictionary it was: only the answer in it is new.
            preferences.changed()
            self.reset_button.set_sensitive(
                bool(prefs['stored dialog choices']))

        chooser.connect_changed(answered)
        return chooser

    def _create_language_control(self) -> "widgets.Chooser[str]":
        """ Creates and returns the combobox for language selection. """
        # Source: http://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
        languages = [
            (_('Auto-detect (Default)'), 'auto'),
            ('Català', 'ca'),  # Catalan
            ('čeština', 'cs'),  # Czech
            ('Deutsch', 'de'),  # German
            ('ελληνικά', 'el'),  # Greek
            ('English', 'en'),  # English
            ('Español', 'es'),  # Spanish
            ('فارسی', 'fa'),  # Persian
            ('Français', 'fr'),  # French
            ('Galego', 'gl'),  # Galician
            ('עברית', 'he'),  # Hebrew
            ('Hrvatski jezik', 'hr'),  # Croatian
            ('Magyar', 'hu'),  # Hungarian
            ('Bahasa Indonesia', 'id'),  # Indonesian
            ('Italiano', 'it'),  # Italian
            ('日本語', 'ja'),  # Japanese
            ('한국어', 'ko'),  # Korean
            ('Nederlands', 'nl'),  # Dutch
            ('Język polski', 'pl'),  # Polish
            ('Português', 'pt_BR'),  # Portuguese
            ('pусский язык', 'ru'),  # Russian
            ('Svenska', 'sv'),  # Swedish
            ('українська мова', 'uk'),  # Ukrainian
            ('简体中文', 'zh_CN'),  # Chinese (simplified)
            ('正體中文', 'zh_TW')]  # Chinese (traditional)
        languages.sort(key=operator.itemgetter(0))

        # What the interface on screen was built from, which is not
        # necessarily what the preference holds: a reader who picks
        # another language and declines the restart leaves the
        # preference ahead of the interface, and this dialog is built
        # afresh every time it is opened.  Picking the language already
        # on screen is nothing to restart for.
        self._language_in_use = i18n.get_language_preference()
        self._language_chooser = self._create_combobox(
            languages, prefs['language'], self._language_changed_cb)

        return self._language_chooser

    def _create_theme_control(self) -> "widgets.Chooser[str]":
        """ Creates the ComboBox control for selecting how MComix is painted. """
        items = ((_('Follow the system'), theme.SYSTEM),
                 (_('Light'), theme.LIGHT),
                 (_('Dark'), theme.DARK),
                 (_('Pitch black'), theme.BLACK))

        box = self._create_combobox(items, prefs['colour scheme'],
                                    self._colour_scheme_changed_cb)

        box.set_tooltip_text(
            _('How MComix itself is painted, whatever the desktop asks for. '
              'Pitch black is the dark theme with black backgrounds, which a '
              'screen that lights its pixels one by one shows as no light at '
              'all.'))

        return box

    def _colour_scheme_changed_cb(self, combobox: "widgets.Chooser[str]",
                                  *args: object) -> None:
        """ Called whenever MComix is told to paint itself differently. """
        prefs['colour scheme'] = combobox.get_value()
        theme.apply_colour_scheme()
        # The page and the thumbnails follow the scheme as well, and
        # they are painted from a colour rather than from a style.
        self._window.set_bg_colour(prefs['bg colour'])
        self._window.thumbnailsidebar.change_thumbnail_background_color(
            prefs['thumb bg colour'])

    def _language_changed_cb(self, combobox: "widgets.Chooser[str]",
                             *args: object) -> None:
        """ Called whenever the language was changed. """
        prefs['language'] = combobox.get_value()
        if prefs['language'] != self._language_in_use:
            self._offer_restart()

    def _offer_restart(self) -> None:
        """Ask whether to start MComix again in the language just picked.

        The interface cannot change language while it is up - see
        main.MainWindow.restart_program() for why - so this is an offer
        rather than a notice, and declining it leaves the preference
        set for the next start.
        """
        dialog = message_dialog.MessageDialog(
            self, modal=True, buttons=Gtk.ButtonsType.YES_NO)
        dialog.set_default_response(Response.YES)
        dialog.set_text(
            _('Restart MComix in the language you picked?'),
            _('MComix is translated as it starts, so most of the '
              'interface stays in the language it started in until it '
              'is started again. The book being read, its page and the '
              'window size are kept.'))

        def responded(response: int) -> None:
            if response == Response.YES:
                self._window.restart_program()

        dialog.run_async(responded)

    def _create_doublepage_as_one_control(self) -> "widgets.Chooser[int]":
        """ Creates the ComboBox control for selecting virtual double page options. """
        items = (
                (_('Never'), 0),
                (_('Only for title pages'), constants.SHOW_DOUBLE_AS_ONE_TITLE),
                (_('Only for wide images'), constants.SHOW_DOUBLE_AS_ONE_WIDE),
                (_('Always'), constants.SHOW_DOUBLE_AS_ONE_TITLE | constants.SHOW_DOUBLE_AS_ONE_WIDE))

        box = self._create_combobox(items,
                                    prefs['virtual double page for fitting images'],
                                    self._double_page_changed_cb)

        box.set_tooltip_text(
            _("When showing the first page of an archive, or an image's width "
              "exceeds its height, only a single page will be displayed."))

        return box

    def _double_page_changed_cb(self, combobox: "widgets.Chooser[int]",
                                *args: object) -> None:
        """ Called when a new option was selected for the virtual double page option. """
        value = combobox.get_value()
        prefs['virtual double page for fitting images'] = value
        self._window.draw_image()

    def _create_double_page_autoresize_control(self) -> "widgets.Chooser[int]":
        """ Creates the ComboBox control for selecting double page autoresize options. """
        items = (
                (_('Prefer same scale'), constants.DOUBLE_PAGE_AUTORESIZE_SCALE),
                (_('Prefer same size'), constants.DOUBLE_PAGE_AUTORESIZE_SIZE),
                (_('Fit to same size'), constants.DOUBLE_PAGE_AUTORESIZE_FIT_SIZE))

        box = self._create_combobox(items,
                                    prefs['double page autoresize'],
                                    self._double_page_autoresize_changed_cb)

        box.set_tooltip_text(
            _("Maintain relative size or fit to same size."))

        return box

    def _double_page_autoresize_changed_cb(self, combobox: "widgets.Chooser[int]",
                                           *args: object) -> None:
        """ Called when a new option was selected for the double page autoresize option. """
        value = combobox.get_value()
        prefs['double page autoresize'] = value
        self._window.draw_image()

    def _create_sort_by_control(self) -> Gtk.Box:
        """ Creates the ComboBox control for selecting file sort by options. """
        sortkey_items = (
                (_('No sorting'), 0),
                (_('File name'), constants.SORT_NAME),
                (_('File name (GLib)'), constants.SORT_NAME_GLIB),
                (_('File size'), constants.SORT_SIZE),
                (_('Last modified'), constants.SORT_LAST_MODIFIED))

        sortkey_box = self._create_combobox(sortkey_items, prefs['sort by'],
                                            self._sort_by_changed_cb)

        sortorder_items = (
                (_('Ascending'), constants.SORT_ASCENDING),
                (_('Descending'), constants.SORT_DESCENDING))

        sortorder_box = self._create_combobox(sortorder_items,
                                              prefs['sort order'],
                                              self._sort_order_changed_cb)

        box = _sort_row(sortkey_box, sortorder_box)

        label = _("Files will be opened and displayed according to the sort order "
                  "specified here. This option does not affect ordering within archives.")
        sortkey_box.set_tooltip_text(label)
        sortorder_box.set_tooltip_text(label)

        return box

    def _sort_by_changed_cb(self, combobox: "widgets.Chooser[int]",
                            *args: object) -> None:
        """Sort the files of a directory by the key chosen, and reopen
        the open one so that its pages are listed in the new order."""
        value = combobox.get_value()
        prefs['sort by'] = value

        self._window.filehandler.refresh_file()

    def _sort_order_changed_cb(self, combobox: "widgets.Chooser[int]",
                               *args: object) -> None:
        """Sort the files of a directory ascending or descending, and
        reopen the open one so that its pages follow."""
        value = combobox.get_value()
        prefs['sort order'] = value

        self._window.filehandler.refresh_file()

    def _create_archive_sort_by_control(self) -> Gtk.Box:
        """ Creates the ComboBox control for selecting archive sort by options. """
        sortkey_items = (
                (_('No sorting'), 0),
                (_('Natural order'), constants.SORT_NAME),
                (_('Literal order'), constants.SORT_NAME_LITERAL),
                (_('GLib order'), constants.SORT_NAME_GLIB))

        sortkey_box = self._create_combobox(sortkey_items, prefs['sort archive by'],
                                            self._sort_archive_by_changed_cb)

        sortorder_items = (
                (_('Ascending'), constants.SORT_ASCENDING),
                (_('Descending'), constants.SORT_DESCENDING))

        sortorder_box = self._create_combobox(sortorder_items,
                                              prefs['sort archive order'],
                                              self._sort_archive_order_changed_cb)

        box = _sort_row(sortkey_box, sortorder_box)

        label = _("Files within archives will be sorted according to the order specified here. "
                  "Natural order will sort numbered files based on their natural order, "
                  "i.e. 1, 2, ..., 10, while literal order uses standard C sorting, "
                  "i.e. 1, 2, 34, 5. "
                  "GLib order will sort files using collate keys generated by GLib/GTK, "
                  "used by many other GTK applications.")
        sortkey_box.set_tooltip_text(label)
        sortorder_box.set_tooltip_text(label)

        return box

    def _sort_archive_by_changed_cb(self, combobox: "widgets.Chooser[int]",
                                    *args: object) -> None:
        """Sort the files within an archive by the key chosen, and
        reopen the open one so that its pages are listed in the new
        order."""
        value = combobox.get_value()
        prefs['sort archive by'] = value

        self._window.filehandler.refresh_file()

    def _sort_archive_order_changed_cb(self, combobox: "widgets.Chooser[int]",
                                       *args: object) -> None:
        """Sort the files within an archive ascending or descending,
        and reopen the open one so that its pages follow."""
        value = combobox.get_value()
        prefs['sort archive order'] = value

        self._window.filehandler.refresh_file()

    def _create_store_recent_combobox(self) -> "widgets.Chooser[bool]":
        """ Creates the combobox for "Store recently opened files". """
        items = (
                (_('Never'), False),
                (_('Always'), True))

        # Map legacy 0/1/2 values:
        if prefs['store recent file info'] == 0:
            selection = False
        elif prefs['store recent file info'] in (1, 2):
            selection = True
        else:
            selection = prefs['store recent file info']

        box = self._create_combobox(items, selection, self._store_recent_changed_cb)
        box.set_tooltip_text(
            _('Add information about all files opened from within MComix to the shared recent files list.'))
        return box

    def _store_recent_changed_cb(self, combobox: "widgets.Chooser[bool]",
                                 *args: object) -> None:
        """ Called when option "Store recently opened files" was changed. """
        value = combobox.get_value()
        last_value = prefs['store recent file info']
        prefs['store recent file info'] = value
        self._window.filehandler.last_read_page.set_enabled(value)

        # If "Never" was selected, ask to purge recent files.
        if (bool(last_value) is True and value is False
            and (self._window.uimanager.recent.count() > 0
                 or self._window.filehandler.last_read_page.count() > 0)):

            dialog = message_dialog.MessageDialog(
                self, modal=True, buttons=Gtk.ButtonsType.YES_NO)
            dialog.set_default_response(Response.YES)
            dialog.set_text(
                _('Delete information about recently opened files?'),
                _('This will remove all entries from the "Recent" menu,'
                  ' and clear information about last read pages.'))

            def responded(response: int) -> None:
                if response == Response.YES:
                    self._window.uimanager.recent.remove_all()
                    self._window.filehandler.last_read_page.clear_all()

            dialog.run_async(responded)

    def _create_scaling_quality_combobox(self) -> "widgets.Chooser[int]":
        """ Creates combo box for image scaling quality """
        items = (
                (_('Normal (fast)'), int(GdkPixbuf.InterpType.TILES)),
                (_('Bilinear'), int(GdkPixbuf.InterpType.BILINEAR)),
                (_('Hyperbolic (slow)'), int(GdkPixbuf.InterpType.HYPER)))

        selection = prefs['scaling quality']

        box = self._create_combobox(items, selection, self._scaling_quality_changed_cb)
        box.set_tooltip_text(
            _('Changes how images are scaled. Slower algorithms result in higher quality resizing, but longer page loading times.'))

        return box

    def _scaling_quality_changed_cb(self, combobox: "widgets.Chooser[int]",
                                    *args: object) -> None:
        """ Called when image scaling quality changes. """
        value = combobox.get_value()
        last_value = prefs['scaling quality']
        prefs['scaling quality'] = value

        if value != last_value:
            self._window.draw_image()

    def _create_animation_mode_combobox(self) -> "widgets.Chooser[int]":
        """ Creates combo box for animation mode """
        items = (
                (_('Never'), constants.ANIMATION_DISABLED),
                (_('Normal'), constants.ANIMATION_NORMAL))

        selection = prefs['animation mode']

        box = self._create_combobox(items, selection, self._animation_mode_changed_cb)
        box.set_tooltip_text(
            _('Controls how animated images should be displayed.'))

        return box

    def _animation_mode_changed_cb(self, combobox: "widgets.Chooser[int]",
                                   *args: object) -> None:
        """ Called whenever animation mode has been changed. """
        value = combobox.get_value()
        last_value = prefs['animation mode']
        prefs['animation mode'] = value

        if value != last_value:
            self._window.filehandler.refresh_file()

    def _create_combobox[V](self, options: Sequence[tuple[str, V]],
                            selected_value: V,
                            change_callback:
                            "Callable[[widgets.Chooser[V]], None] | None"
                            ) -> "widgets.Chooser[V]":
        """A dropdown of <options>, pairs of label and value, opening
        on <selected_value>.

        <change_callback>, where there is one, is called with the
        dropdown whenever a different option is picked.
        """
        assert options and len(options[0]) == 2, "Invalid format for options."

        box = widgets.Chooser(options, selected_value)

        if change_callback:
            box.connect_changed(change_callback)

        return box

    def _create_extensions_entry(self) -> Gtk.Entry:
        entry = Gtk.Entry()
        entry.set_size_request(200, -1)
        entry.set_text(', '.join(prefs['comment extensions']))
        entry.connect('activate', self._entry_cb)
        # There is no focus-out-event in GTK4; a focus controller says so.
        focus = Gtk.EventControllerFocus()
        focus.connect('leave', lambda _controller: self._entry_cb(entry))
        entry.add_controller(focus)
        entry.set_tooltip_text(
            _('Treat all files found within archives, that have one of these file endings, as comments.'))
        return entry

    def _create_pref_check_button(self, label: str, prefkey: str,
                                  tooltip_text: str | None) -> Gtk.CheckButton:
        button = Gtk.CheckButton(label=label)
        button.set_active(preferences.by_name(prefkey))
        button.connect('toggled', self._check_button_cb, prefkey)
        if tooltip_text:
            button.set_tooltip_text(tooltip_text)
        return button

    def _create_binary_pref_radio_buttons(
            self, label1: str, tooltip_text1: str | None, label2: str,
            prefkey: str,
            tooltip_text2: str | None) -> tuple[Gtk.CheckButton, Gtk.CheckButton]:
        """Two buttons for the two states of <prefkey>, off then on.

        One preference, not two: a key for each button would be two
        answers to a question that has one.

        A check button put in a group with another is a radio button.
        Neither of them is active until one is set, so both are set from
        the preference here - without which the pair would come up
        showing neither of its two answers.
        """
        button1 = Gtk.CheckButton(label=label1)
        if tooltip_text1:
            button1.set_tooltip_text(tooltip_text1)
        button2 = Gtk.CheckButton(label=label2)
        button2.set_group(button1)
        if tooltip_text2:
            button2.set_tooltip_text(tooltip_text2)
        button1.set_active(not preferences.by_name(prefkey))
        button2.set_active(preferences.by_name(prefkey))
        # Only the one the preference is about: a group announces both
        # the button that was turned on and the one that was turned off.
        button2.connect('toggled', self._check_button_cb, prefkey)
        return button1, button2

    def _create_color_button(self, prefkey: str) -> Gtk.ColorDialogButton:
        # Gtk.ColorButton, which GTK deprecated in 4.10, opened a colour
        # chooser of its own and said 'color-set' once one was picked.
        # Its replacement is handed the dialog to open, and the colour
        # that comes back arrives as a change to the rgba property, so
        # the button is given its own colour before anything listens.
        button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        button.set_rgba(image_tools.rgba(*preferences.by_name(prefkey)))
        button.connect('notify::rgba', self._color_button_cb, prefkey)
        return button

    def _check_button_cb(self, button: Gtk.CheckButton, preference: str) -> None:
        """Callback for all checkbutton-type preferences."""

        preferences.set_by_name(preference, button.get_active())

        if preference == 'smart bg':

            if prefs['smart bg']:
                # draw_image() will set the main background to the
                # colour it reads off the page.
                self._window.draw_image()
            else:
                self._window.set_bg_colour(prefs['bg colour'])

        elif preference == 'smart thumb bg':

            prefs['thumbnail bg uses main colour'] = False
            if not prefs['smart thumb bg']:
                self._window.thumbnailsidebar.change_thumbnail_background_color(
                    prefs['thumb bg colour'])
            else:
                # draw_image() will set the thumbnails' background to the
                # colour it reads off the page.
                self._window.draw_image()

        elif preference in ('checkered bg for transparent images',
                            'no double page for wide images'):
            self._window.draw_image()

        elif preference == 'auto rotate from exif':
            self._window.draw_image()
            # The sidebar's thumbnails are turned as the pages are, and
            # so are the library's covers, which are kept turned.
            self._window.thumbnailsidebar.resize()
            from mcomix.library import main_dialog, pixbuf_cache
            library = main_dialog.get_dialog()
            if library is not None:
                library.book_area.load_covers()
            else:
                pixbuf_cache.get_pixbuf_cache().invalidate_all()

        elif (preference == 'hide all in fullscreen' and
              self._window.is_fullscreen()):
            self._window.draw_image()

        elif preference == 'show page numbers on thumbnails':
            self._window.thumbnailsidebar.toggle_page_numbers_visible()

    def _color_button_cb(self, colorbutton: Gtk.ColorDialogButton,
                         _pspec: GObject.ParamSpec, preference: str) -> None:
        """Callback for the background colour selection button."""

        colour = colorbutton.get_rgba()
        chosen = [colour.red, colour.green, colour.blue, colour.alpha]

        if preference == 'bg colour':
            prefs['bg colour'] = chosen

            if not prefs['smart bg'] or not self._window.filehandler.file_loaded:
                self._window.set_bg_colour(prefs['bg colour'])

        elif preference == 'thumb bg colour':

            prefs['thumb bg colour'] = chosen

            if not prefs['smart thumb bg'] or not self._window.filehandler.file_loaded:
                self._window.thumbnailsidebar.change_thumbnail_background_color(
                    prefs['thumb bg colour'])

    def _create_pref_spinner(self, prefkey: str, scale: float,
                             lower: float, upper: float, step_incr: float,
                             page_incr: float, digits: int,
                             tooltip_text: str | None) -> Gtk.SpinButton:
        value = preferences.by_name(prefkey) / scale
        adjustment = Gtk.Adjustment.new(value, lower, upper, step_incr,
                                        page_incr, 0.0)
        spinner = Gtk.SpinButton.new(adjustment, 0.0, digits)
        spinner.set_size_request(80, -1)
        # Every spinner the same width.  GTK4 sizes one to the widest
        # number it can hold, so the slideshow delay - two decimals of
        # up to 3600 - came out wider than the rest of the page.
        spinner.set_width_chars(_SPINNER_WIDTH)
        spinner.set_max_width_chars(_SPINNER_WIDTH)
        spinner.connect('value_changed', self._spinner_cb, prefkey)
        if tooltip_text:
            spinner.set_tooltip_text(tooltip_text)
        return spinner

    def _spinner_cb(self, spinbutton: Gtk.SpinButton, preference: str) -> None:
        """Callback for spinner-type preferences."""
        value = spinbutton.get_value()

        # Most preferences are plain pixel/item counts; only those stored in
        # another unit than the spinner displays need converting.
        if preference == 'lens magnification':
            preferences.set_by_name(preference, value)
        elif preference == 'slideshow delay':
            preferences.set_by_name(preference, int(round(value * 1000)))
        elif preference == 'smart scroll percentage':
            preferences.set_by_name(preference, value / 100.0)
        else:
            preferences.set_by_name(preference, int(value))

        # Preferences that take more than storing the new value.
        if preference == 'slideshow delay':
            self._window.slideshow.update_delay()

        elif preference == 'thumbnail size':
            self._window.thumbnailsidebar.resize()
            self._window.draw_image()

        elif preference == 'max pages to cache':
            self._window.imagehandler.do_cacheing()

        elif preference == 'number of key presses before page turn':
            self._window.event_handler.reset_extra_scroll_events()

        elif preference in ('fit to size width wide', 'fit to size height wide',
                            'fit to size width other', 'fit to size height other',):
            self._window.change_zoom_mode()

        elif preference == 'space between two pages':
            self._window.update_space()

    def _entry_cb(self, entry: Gtk.Entry, *args: object) -> None:
        """Callback for entry-type preferences."""
        text = entry.get_text()
        extensions = [e.strip() for e in text.split(',')]
        prefs['comment extensions'] = [e for e in extensions if e]
        self._window.filehandler.update_comment_extensions()


def open_dialog(action: Gio.SimpleAction, window: "main.MainWindow") -> None:
    """Create and display the preference dialog."""

    global _dialog

    # if the dialog window is not created then create the window
    if _dialog is None:
        _dialog = _PreferencesDialog(window)
    else:
        # if the dialog window already exists bring it to the forefront of the screen
        _dialog.present()


def _close_dialog() -> None:

    global _dialog

    # if the dialog window exists then destroy it
    if _dialog is not None:
        _dialog.destroy()
        _dialog = None


# vim: expandtab:sw=4:ts=4
