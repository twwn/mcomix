Preferences dialog
===

The preferences dialog opens on F12. It has five tabs: Appearance, Behaviour, Display, Advanced and Shortcuts, the keybinding editor the [Keybindings] page describes.

A change takes effect at once, except for the interface language and the number of thumbnail threads, which are read when MComix starts. Picking a language offers to start MComix again, keeping the book, its page and the window size; declining keeps the choice for the next start.

Beside Close, "Clear dialog choices" puts every prompt answered for good back to asking. On the Shortcuts tab, the same button is "Reset keys", which puts every key back to its default.

Appearance tab
---

Option | Explanation
-------|------------
Language (needs restart) | "Auto-detect (Default)" takes the language from the system.
Theme | How MComix itself is painted. "Follow the system" takes the desktop's colour scheme, "Light" and "Dark" pick one side of the theme, and "Pitch black" is the dark theme with black backgrounds, which a screen that lights its pixels one by one shows as no light at all.
Escape key closes program | Escape quits instead of only leaving fullscreen mode.
Use this colour as background | The colour behind the page.
Use dynamic background colour | Instead of a set colour, one worked out from the edges of the page, so that a page with a white border is shown against white. The option is there for the page and for the thumbnails.
Use this colour as the thumbnail background | The colour behind the thumbnails in the sidebar.
Show page numbers on thumbnails |
Thumbnail size (in pixels) | 80 by default.
Use checkered background for transparent images | Show the transparent parts of an image as a grey checkerboard rather than white.

Behaviour tab
---

Option | Explanation
-------|------------
Use smart scrolling | The space key and the mouse wheel follow the reading order of a comic page: sideways first, then down, then sideways again. A page that cannot be scrolled sideways, as in "Fit to width" mode, scrolls down only.
Flip pages when scrolling off the edges of the page | Scrolling past the end of a page, with the wheel or the arrow keys, turns it.
Automatically open the next archive | Turning past the last page opens the next archive in the directory, and turning back past the first page opens the previous one.
Automatically open next directory | The same, past the last or first file of a directory, for the next or previous sibling directory.
Open first file when navigating to previous archive | Rather than its last file.
Open first file when navigating to previous directory | Rather than its last file.
Number of pixels to scroll per arrow key press | 50 by default.
Number of pixels to scroll per mouse wheel turn | 50 by default.
Fraction of page to scroll per space key press (in percent) | 50 by default.
Number of "steps" to take before flipping the page | How many scrolls past the end of a page it takes to turn it, so that reaching the bottom does not turn the page by accident. 3 by default, and at least 1.
Flip two pages in double page mode | Turn two pages at a time while two are shown. CTRL with PageUp or PageDown always turns one.
Show only one page where appropriate | When double page mode shows one page anyway: "Never", "Only for title pages" (the first page, which is the cover), "Only for wide images", or "Always", which is both.
Page auto-resizing | How two pages of different sizes are fitted beside each other: "Prefer same scale", "Prefer same size" or "Fit to same size".
Space between two pages (in pixels) | From 0 to 2; 2 by default.
Automatically open the last viewed file on startup | Started with no file to open, MComix reopens the one that was open when it last closed. After "Save and quit", it does so whatever this is set to.
Store information about recently opened files | "Always" keeps the history under File &rarr; Recent and the page each book was left at, which the library's "Recent" collection lists. Switching to "Never" offers to clear both.
Save As opens at the last directory saved into | Rather than at the directory the book came from.
Save an edited archive in the format it was opened in | Write an edited archive back as the ZIP, tar, 7z or RAR it was read as. The last two need the `7z` and `rar` programs, which MComix does not install; a format it cannot write is saved as a ZIP.
Prompts answered for good | Every prompt whose answer can be remembered, with the answer it has been given: opening a book that was left part-read, deleting the opened file, bookmarking a page that is bookmarked already, deleting books removed from the library, removing a page from the book being read, and leaving a book with pages still picked out. A prompt's "Do not ask again" box sets its answer here, and "Ask every time" takes it back.

Display tab
---

Option | Explanation
-------|------------
Use fullscreen by default |
Automatically hide all toolbars in fullscreen | The menu bar, the toolbar, the status bar, the thumbnails and the scrollbars go away in fullscreen mode.
Fixed width for wide pages | "Fit to size" mode scales a wide page, such as a double-page spread, to a shape of its own. 3790 by default.
Fixed height for wide pages | 960 by default.
Fixed width for other pages | 1450 by default.
Fixed height for other pages | 1800 by default.
Slideshow delay (in seconds) | 3 by default.
Slideshow step (in pixels) | How far each step of a slideshow scrolls: forward for a positive value, backwards for a negative one, and a page turn for 0. 50 by default.
During a slideshow automatically open the next archive |
Automatically rotate images according to their metadata | Such as an Exif orientation tag.
Scaling mode | "Normal (fast)", "Bilinear" or "Hyperbolic (slow)". A slower one gives better quality and a longer page load. "Bilinear" by default.

Advanced tab
---

Option | Explanation
-------|------------
Sort files and directories by | The order of the files in a directory, "No sorting", "File name", "File name (GLib)", "File size" or "Last modified", and its direction. Not the order inside an archive.
Sort archives by | The order of the files inside an archive, and its direction. "Natural order" reads the numbers in a name, giving Page1, Page3, Page20; "Literal order" compares character by character, giving Page1, Page20, Page3; "GLib order" uses the collation keys many other GTK applications sort by.
Maximum number of concurrent extraction threads | For the formats that can be unpacked by more than one thread. 1 by default.
Maximum number of concurrent thumbnail threads | Read when MComix starts. 3 by default.
Store thumbnails for opened files | In the freedesktop.org thumbnail directory that file managers and other programs share.
Maximum number of pages to store in the cache | 7 by default. -1 caches the whole book, and a large number can run MComix out of memory.
Magnifying lens size (in pixels) | The side of the square lens. 200 by default.
Magnification factor | 2 by default.
Comment extensions | Which files inside an archive count as comments. txt, nfo and xml by default.
Animation mode | "Normal" plays an animated image; "Never" shows its first frame only.
