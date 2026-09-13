Preferences dialog
===

The preferences dialog can be opened by pressing "F12". All options are grouped in a number of tabs, each relating to a certain aspect of the application. Independently of the currently selected tab, this dialog also contains the button "Clear dialog choices". When MComix presents the user with different choices in a confirmation dialog, the dialog usually also contains a checkbox to remember the selected choice. By pressing the "Clear dialog choices" button, all stored choices will be reset, and MComix will start presenting choice dialogs again.

Changing an option usually takes effect immediately, even without closing the preferences dialog. The only exception is switching UI languages, which will require an application restart to take effect.

Appearance tab
---

Option | Explanation
-------|------------
Theme | How MComix itself is painted, whatever colour scheme the desktop asks for. "Follow the system" takes the desktop's answer; "Light" and "Dark" pick one side of whatever theme is in use; "Pitch black" is the dark theme with black backgrounds, which a screen that lights its pixels one by one shows as no light at all. Where [libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) is installed, this is the same choice every other GTK 4 application offers.
Use static or dynamic background color | The color that will be used as background in the main image window. If "Dynamic background color" is selected, the background color will be computed from the edge colors of the currently displayed page. Comic pages with white border will result in a white background, for example.
Use static or dynamic thumbnail background color | Same as above, except for the thumbnail sidebar.
Show page numbers on thumbnails | If this option is enabled, page numbers will be shown next to each thumbnail on the thumbnail sidebar.
Use archive thumbnail as application icon | When set, a miniature icon of the first page of an archive will be used as application icon. This only works on certain X window managers.
Thumbnail size | Size of each thumbnail in the thumbnail sidebar.
Use checkered background for transparent images | If enabled, transparent parts of an image will be replaced by a checkered black-white pattern. Otherwise, white will be used.

Behavior tab
---

Option | Explanation
-------|------------
Use smart scrolling | In this mode, the Space key and mouse wheel will attempt to follow the flow of reading for comic pages. This means that instead of scrolling right down, images will be scrolled sideways first, then down, then sideways again, until the end of the page is reached. If the current image cannot be scrolled sideways (for example, in "Fit to width" mode), scrolling will behave regularly. 
Flip pages when scrolling off the edges of the page | If enabled, scrolling down a page when the end has been reached will result in a page flip. If disabled, the page will never be automatically be changed unless the user explicitly uses the hotkeys for next/previous page.
Automatically open next archive | When the end of the current archive has been reached, flipping to the next page will automatically open the next archive in the same directory.
Automatically open next directory | When the last page of the current directory has been reached, flipping to the next page will automatically open the first image in the next sibling directory.
Number of pixels to scroll per key press/wheel turn | This governs how far MComix will scroll down when one of the scrolling keys is used.
Fraction of page to scroll per space key press | How much of the (visible) page, in percent, Space will scroll down when pressed. 
Number of steps to take before flipping page | To prevent accidentally switching pages when scrolling down a page, MComix will require a number of "steps" before the page is actually flipped. With a setting of "3", for example, the user has to scroll down three more times when the end of the page has been reached before the next page will be loaded. Setting this option to "0" disabled the protection.
Flip two pages in double page mode | When enabled, MComix will advance two pages instead of one in double-page mode. Please note that holding the CTRL key while scrolling will always only advance one page, even if this option is enabled.
Show only one page where appropriate | In certain conditions, only one page will be displayed even when double-page mode is enabled. These are either a) the first page of an archive is loaded, i.e. the cover of the book, b) an image's width exceeds its height, or c) a combination of these conditions. When "Never" is selected, MComix will always show two pages in double-page mode.
Automatically open the last viewed file on startup | When the program is closed while images are still loaded, MComix will resume from that position the next time it is started without arguments. Even with this option disabled, quitting MComix by using "Save and quit" will result in the same behavior.
Store information about recently opened files | If checked, a history of recently opened files will be kept by MComix under "File &rarr; Recent". Enabling this option also automatically adds all opened books to a special collection in the library called "Recent". Unchecking this option will clear all history entries.

Display tab
---

Option | Explanation
-------|------------
Use fullscreen by default | Checking this will automatically start MComix in full-screen mode.
Automatically hide all toolbars in fullscreen | The menu bar, toolbar, side bar and scrollbars will automatically be hidden when the user enables full-screen mode.
Fit to width or height and fixed size for selected dimension | Determines how the "Fit to size" mode handles images. When "Fit to size" is enabled, the side specified here will be scaled down to a fixed size, in pixel. The default setting is "Fit to height" and 1400px. An image with the dimensions of 2000x1000px would be scaled down to 1400x700px, for example.
Slideshow delay | How long to wait before each scrolling step in slideshow mode.
Slideshow step | How many pixels to scroll down for each scrolling operation.
During a slideshow automatically open the next archive | If enabled, MComix will automatically open the next archive in slideshow mode once the last page of the current archive has been reached.
Automatically rotate images according to their metadata | If an image contains EXIF orientation metadata, MComix will automatically rotate the image accordingly.
Scaling mode | Set the algorithm that is used to scale images up and down. The default mode should be of acceptable speed and quality.

Advanced tab
---

Option | Explanation
-------|------------
Language | Specify the user interface language. "Auto" tries to deduce the correct language from the system configuration. A change to this option requires a program restart before taking effect.
Escape key closes program | When enabled, pressing Escape will quit MComix. If disabled, Escape only returns from full-screen mode.
Sort files and directories by | Determines how files inside directories are sorted. This option has no effect for files inside archives.
Sort archives by | Determines how files inside archives are sorted. "Natural order" will sort filenames that contain numbers according to the perceived "natural" order of the files, i.e. Page1.jpg, Page3.jpg, Page20.jpg. "Literal order" uses standard C sorting, which means that in the previous example, files would be sorted as Page1.jpg, Page20.jpg, Page3.jpg.
Store thumbnails for opened files | If enabled, MComix will store image thumbnails on disk, and re-use those thumbnails when they are needed again. If disabled, thumbnails will only be kept in memory and re-created when necessary.
Maximum number of pages to store in the cache | MComix caches keeps a certain amount of pages before and after the current page in cache for faster page switching. With the default setting, "7", three pages before and after the current page are kept in memory. It is not advised to increase this number too much, as it might result in MComix running out of memory.
Magnifying lens size | Determines the size of the magnifying lens, in pixel.
Magnification factor | The factor by which the lens zooms in.
Comment extensions | File extensions MComix' archive editor will recognize as comment files. When repacking archives, only images and comment files are kept, while other files will be discarded.
