# Preferences

F12 opens the dialog. Six tabs: Appearance, Behaviour, Navigation, Display, Advanced, and Shortcuts, the keybinding editor ([Keyboard and mouse](shortcuts.md#changing-keys)).

- Changes apply at once, except the language and the number of thumbnail threads, which are read at start.
- Picking a language offers to restart MComix, keeping the book, page and window size. Declining keeps the choice for the next start.
- "Clear dialog choices", beside Close, sets every prompt answered for good back to asking.
- On the Shortcuts tab that button is "Reset keys": every key back to its default.

## Appearance tab

Option | Explanation
-------|------------
Language (needs restart) | "Auto-detect (Default)" follows the system.
Theme | "Follow the system" takes the desktop's colour scheme; "Light" or "Dark" picks one; "Pitch black" is dark with black backgrounds, for OLED screens.
Escape key closes program | Escape quits, instead of only leaving fullscreen. Pages picked out are put back first either way.
Use this colour as background | The colour behind the page.
Use dynamic background colour | A colour taken from the page's edges instead: a page with a white border is shown on white. For the page and for the thumbnails.
Use this colour as the thumbnail background | The colour behind the sidebar's thumbnails.
Show page numbers on thumbnails |
Thumbnail size (in pixels) | 80 by default.
Use checkered background for transparent images | A grey checkerboard behind transparent parts, instead of white.

## Behaviour tab

Option | Explanation
-------|------------
Automatically open the last viewed file on startup | Started without a file, reopen the one open at last close, at the picture that was shown. After "Save and quit" this happens regardless.
Open the library on startup | As `-l` does: the library comes up beside the window, to pick the book there.
Store information about recently opened files | "Always" keeps File → Recent and each book's last page, which the library's "Recent" collection lists. Switching to "Never" offers to clear both.
Save As opens at the last directory saved into | Instead of the book's own directory.
Save an edited archive in the format it was opened in | Write it back as the ZIP, tar, 7z or RAR it was read as. 7z and RAR need the `7z` and `rar` programs, which MComix does not install; a format it cannot write is saved as ZIP.
Prompts answered for good | Every prompt whose answer can be remembered, with its answer: reopening a part-read book, deleting the open file, bookmarking a book that has bookmarks, deleting books removed from the library, deleting a bookmarked file, changing the pages of the open book, leaving a book with pages picked out. "Do not ask again" sets an answer here; "Ask every time" takes it back.

## Navigation tab

Option | Explanation
-------|------------
Use smart scrolling | Space and the mouse wheel follow a comic page's reading order: sideways, down, sideways again. A page that cannot scroll sideways, as in "Fit to width", scrolls down only.
Flip pages when scrolling off the edges of the page | Scrolling past a page's end, with the wheel or the arrow keys, turns it.
Skip pages that cannot be shown | Turn past a page that is damaged or unreadable, the way you were going, instead of showing the broken-image icon. Past the last page that can be shown, a turn opens the next book, as from the last page. The thumbnail bar leaves them out once their thumbnails are made. Off by default. In double page mode its partner is shown alone.
Number of pixels to scroll per arrow key press | 50 by default.
Number of pixels to scroll per mouse wheel turn | 50 by default.
Fraction of page to scroll per space key press (in percent) | 50 by default.
Number of "steps" to take before flipping the page | Scrolls past a page's end before it turns, so reaching the bottom does not turn it by accident. 3 by default, at least 1.
Automatically open the next archive | Past the last page, open the next archive in the directory; past the first, the previous one. A RAR book in volumes (name.part1.rar, name.part2.rar, …) counts as one, opened from its first volume.
Automatically open next directory | Past the last book in the directory, open the next directory with a book; past the first, the previous one. The walk stays on the shelf: the directory above the one the book was opened from by hand. It visits the shelf's directories and the ones in those, each before the ones in it, in natural order. It skips directories with no book, and does not go into a linked directory. Archives follow an archive and loose pictures follow pictures. A directory with none of that kind opens its other kind.
Open first file when navigating to previous archive | Instead of its last file, which is shown from its bottom.
Open first file when navigating to previous directory | Instead of its last file.
Sort files and directories by | Order of files in a directory: "No sorting", "File name", "File name (GLib)", "File size" or "Last modified", and direction. Not the order inside an archive. A change reopens the book in the new order, at the same picture.
Sort archives by | Order of files inside an archive, and direction. "Natural order" reads numbers: Page1, Page3, Page20. "Literal order" compares characters: Page1, Page20, Page3. "GLib order" sorts as many GTK programs do. A change reopens the archive in the new order, at the same picture.

## Display tab

Option | Explanation
-------|------------
Use fullscreen by default |
Automatically hide all toolbars in fullscreen | Menu bar, toolbar, status bar, thumbnails and scrollbars go away in fullscreen.
Flip two pages in double page mode | Turn two pages at a time while two are shown. CTRL with PageUp or PageDown always turns one.
Show only one page where appropriate | When double page mode shows one page: "Never", "Only for title pages" (the cover), "Only for wide images", or "Always" (both).
Page auto-resizing | How two pages of different sizes are fitted side by side: "Prefer same scale", "Prefer same size" or "Fit to same size".
Space between two pages (in pixels) | 0 to 100; 2 by default.
Fixed width for wide pages | "Fit to size" gives wide pages, such as spreads, a size of their own. 3790 by default.
Fixed height for wide pages | 960 by default.
Fixed width for other pages | 1450 by default.
Fixed height for other pages | 1800 by default.
Slideshow delay (in seconds) | 3 by default.
Slideshow step (in pixels) | How far each slideshow step scrolls: forward if positive, back if negative, a page turn if 0. 50 by default.
During a slideshow automatically open the next archive |
Automatically rotate images according to their metadata | Such as an Exif orientation tag. Thumbnails, the file chooser's preview and library covers turn the same way. Thumbnails in the desktop's shared store stay upright, as other programs expect.
Scaling mode | "Normal (fast)", "Bilinear" or "Hyperbolic (slow)": slower means better quality. "Bilinear" by default.

## Advanced tab

Option | Explanation
-------|------------
Maximum number of concurrent extraction threads | For formats more than one thread can unpack: ZIP, PDF, and those unpacked by an outside program, such as 7z. 4 by default.
Maximum number of concurrent thumbnail threads | Read at start. 3 by default.
Store thumbnails for opened files | In the freedesktop.org thumbnail directory that file managers and other programs share.
Maximum number of pages to store in the cache | 7 by default. -1 caches the whole book; a large number can run MComix out of memory.
Magnifying lens size (in pixels) | The side of the square lens. 200 by default.
Magnification factor | 2 by default.
Comment extensions | Which files in an archive count as comments. txt, nfo and xml by default.
Animation mode | "Normal" plays an animated image; "Never" shows its first frame.
