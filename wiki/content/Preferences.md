Preferences dialog
===

The preferences dialog opens on F12. Its options are grouped into five tabs, each covering one aspect of the program: Appearance, Behaviour, Display, Advanced and Shortcuts. Shortcuts is the keybinding editor, which [Keybindings] describes.

Changing an option takes effect at once, without closing the dialog, with two exceptions that the labels name: the interface language and the number of thumbnail threads are both read when MComix starts. Picking a language therefore offers to start MComix again, which is the only way to show one language throughout; declining keeps the choice for the next start. The book being read, its page and the window size are carried over.

Appearance tab
---

Option | Explanation
-------|------------
Theme | How MComix itself is painted, whatever colour scheme the desktop asks for. "Follow the system" takes the desktop's answer; "Light" and "Dark" pick one side of whatever theme is in use; "Pitch black" is the dark theme with black backgrounds, which a screen that lights its pixels one by one shows as no light at all. Where [libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) is installed, this is the same choice every other GTK 4 application offers.
Use this colour as background | The colour behind the page in the main window. Set it and every page is shown against it.
Use dynamic background colour | Instead of the colour above, one worked out from the edges of the page on screen, so that a page with a white border is shown against white.
Use this colour as the thumbnail background | As above, for the thumbnail sidebar.
Use dynamic background colour (thumbnails) | As above, for the thumbnail sidebar.
Use checkered background for transparent images | Show the transparent parts of an image as a grey checkerboard. Unset, they are plain white.
Escape key closes program | Escape quits instead of only leaving fullscreen mode.
Show page numbers on thumbnails | Write each page's number beside its thumbnail in the sidebar.
Language (needs restart) | The interface language. "Auto" takes it from the system configuration.
Thumbnail size (in pixels) | How large each thumbnail in the sidebar is drawn.

Behaviour tab
---

Option | Explanation
-------|------------
Use smart scrolling | The space key and the mouse wheel follow the reading order of a comic page instead of only going down: sideways first, then down, then sideways again, until the page runs out. A page that cannot be scrolled sideways - in "Fit to width" mode, for instance - scrolls as it normally would.
Flip pages when scrolling off the edges of the page | Scrolling past the end of a page turns it. Unset, the page changes only when a page-turn key or button is used.
Automatically open the next archive | Turning past the last page opens the next archive in the directory, and turning back past the first opens the previous one.
Automatically open next directory | Turning past the last page of the last file in a directory opens the first file of the next sibling directory, and turning back past the first page opens the previous one.
Open first file when navigating to previous archive | Arriving at the previous archive opens its first file rather than its last.
Open first file when navigating to previous directory | Arriving at the previous directory opens its first file rather than its last.
Number of pixels to scroll per arrow key press | How far one press of an arrow key scrolls.
Number of pixels to scroll per mouse wheel turn | How far one turn of the wheel scrolls. Separate from the arrow keys, so the two can be set apart.
Fraction of page to scroll per space key press (in percent) | How much of the visible page the space key scrolls.
Number of "steps" to take before flipping the page | How many further scrolls past the end of a page it takes to turn it, so that reaching the bottom does not turn the page by accident. Set it to 0 for no protection at all.
Flip two pages in double page mode | Turn two pages at a time rather than one while two are shown. The single-step page turns - CTRL with PageUp or PageDown - always move one page whatever this is set to.
Show only one page where appropriate | When to show a single page although double page mode is on: "Never", "Only for title pages" - the first page of an archive, which is the cover - "Only for wide images", or "Always", which is both.
Page auto-resizing | How two pages of different sizes are fitted beside each other: "Prefer same scale", "Prefer same size" or "Fit to same size".
Space between two pages (in pixels) | The gap left between the two pages in double page mode.
Automatically open the last viewed file on startup | Started with no arguments, MComix reopens the file that was open when it last closed. "Save and quit" does this whatever the setting.
Store information about recently opened files | "Always" keeps a history under File &rarr; Recent and adds every book opened to the library's "Recent" collection; "Never" keeps none and clears what is there.
Save As opens at the last directory saved into | The Save As dialog starts in the directory the last file was saved into, rather than where the book came from.
Save an edited archive in the format it was opened in | Write an edited archive back as the ZIP, tar, 7z or RAR it was read as. The last two need the `7z` and `rar` programs, which MComix does not install; a format it cannot write is saved as a ZIP instead.
Prompts answered for good | Not one option but a list: every prompt whose answer can be remembered, with the answer it has been given. A confirmation dialog carries a tick to stop asking, and this is where that is taken back. The prompts are opening a part-read book, deleting the opened file, bookmarking an already bookmarked page, deleting books removed from the library, writing an archive a page was removed from, and leaving a book with pages still picked out.

Display tab
---

Option | Explanation
-------|------------
Use fullscreen by default | Start in fullscreen mode.
Automatically hide all toolbars in fullscreen | The menu bar, toolbar, sidebar and scrollbars go away in fullscreen mode.
Fixed width for wide pages | The width "Fit to size" mode scales a wide page to. Wide pages are set apart from the rest because a double-page spread wants a different shape from a single page. 3790 by default.
Fixed height for wide pages | The height it scales a wide page to, 960 by default.
Fixed width for other pages | The width it scales a page that is not wide to, 1450 by default.
Fixed height for other pages | The height it scales a page that is not wide to, 1800 by default.
Slideshow delay (in seconds) | How long a slideshow waits before each step.
Slideshow step (in pixels) | How far each step of a slideshow scrolls. A positive value goes forward, a negative one backwards, and 0 turns the page rather than scrolling.
During a slideshow automatically open the next archive | A slideshow reaching the last page of an archive opens the next one.
Automatically rotate images according to their metadata | Turn an image the way its metadata asks, such as an Exif orientation tag.
Scaling mode | Which algorithm scales an image up or down: "Normal (fast)", "Bilinear" or "Hyperbolic (slow)". A slower one gives better quality and a longer page load.

Advanced tab
---

Option | Explanation
-------|------------
Sort files and directories by | How the files in a directory are ordered, and whether ascending or descending. Nothing to do with the files inside an archive.
Sort archives by | How the files inside an archive are ordered, and in which direction. "Natural order" reads the numbers in a name, so Page1, Page3, Page20; "Literal order" compares character by character, giving Page1, Page20, Page3; "GLib order" uses the collation keys many other GTK applications sort by.
Maximum number of concurrent extraction threads | How many threads may unpack at once, for the formats that allow more than one.
Maximum number of concurrent thumbnail threads | How many threads may draw thumbnails at once. Read when MComix starts.
Store thumbnails for opened files | Keep thumbnails on disk, in the freedesktop.org location that file managers and other programs share, rather than only in memory.
Maximum number of pages to store in the cache | How many pages are held either side of the one on screen, so that turning back and forth does not read them again. The default is 7; -1 caches the whole archive, and a large number can run MComix out of memory.
Magnifying lens size (in pixels) | The lens is a square with a side this long. 200 by default.
Magnification factor | How far the lens zooms in. 2 by default.
Comment extensions | Which file extensions count as a comment file. Writing an archive again keeps the images and the comment files in it and discards everything else.
Animation mode | Whether an animated image is played: "Normal", or "Never", which shows the first frame only.
