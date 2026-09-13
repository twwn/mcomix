Documentation
===

[TOC]

Please note that this site is an ongoing effort to create a somewhat usable user manual for MComix.

Installation
---

Instructions for installing MComix can be found on the [Installation] page.


The main window
---

In the default configuration, MComix' user interface will look somewhat similar to the following screenshot. The main areas of interest are the tool- and menubar, the thumbnail sidebar on the left, and the display port in the center.

[[img src="mcomix-mainwindow.png" alt="MComix' main window"]]

This configuration is normally acceptable for general image viewing purposes. For reading comics, you will likely want a more uncluttered interface. This can be achieved either by pressing the "F" key to enter fullscreen mode, or by turning off what you do not want in the "View" menu, which carries one item each for the toolbar, the menubar, the statusbar, the scrollbars and the thumbnails. "Hide all" in the same menu, or the "I" key, puts all of them away at once. Normally, you will also want to switch from "Best fit" mode to "Fit to width" mode by pressing the "W" key. This way, images will only be scaled down to fit the screen width, not both width and height.

Paging and scrolling from one image to the next works similarly to most other image viewers. The arrow keys scroll the page, while PageDown and PageUp will switch to the next and previous pages.

### Fit modes ###

MComix has several automatic fit modes that scale down images by certain criteria. Those are:

- Best fit - Images are scaled down to fit within the window.
- Fit to width - Images are scaled down to fit the screen width. If an image is higher than the screen, it can be scrolled up and down.
- Fit to height - Images are scaled down to fit the screen height. If an image is wider than the screen,
it can be scrolled left and right.
- Fit to size - Resize images to a fixed size in pixels, set in the preferences dialog. A wide page and a page that is not wide are given sizes of their own, since a double-page spread wants a different shape from a single page; the defaults are 3790x960 for a wide page and 1450x1800 for the rest.
- Manual zoom mode - No scaling is performed on the image.

Normally, no mode will increase an image's size by scaling it up. If such behavior is desired, "View &rarr; Stretch small images" enables scaling in both directions, up and down.

### Double page mode and manga mode ###

Normally, MComix will only show one image at a time. For reading comics, especially on widescreen monitors, it can be desirable to display two images at once next to each other. This way, reading comics becomes more natural and double-page spreads can be viewed without having to edit the image files. Double-page mode is toggled by pressing "D". Unless set up otherwise, the first page of an archive or directory will always be displayed alone (representing the book cover). Pages with width exceeding height will also be displayed alone.

When changing pages in double-page mode, MComix will automatically forward or backward two pages at once. To forward only one page, hold the CTRL key while switching pages.

By default, MComix will arrange pages left-to-right, and also scroll in this direction. For manga, MComix has a special "Manga mode" activated by pressing "M". This mode lays out pages right-to-left, and changes scrolling accordingly.

### Slideshow mode ###

MComix can automatically scroll and switch pages by activating slideshow mode, using CTRL+S. Conceptually, this works the same way as pressing the "Down" arrow key repeatedly with a certain interval between each keypress. The delay and amount of pixels scrolled can be customized in the preferences dialog.

By default, MComix will scroll down 50 pixels every three seconds. For a smoother experience, the following settings might be worth a try:

- Slideshow delay: 0.05 seconds
- Slideshow step: 1 px

### Keybindings ###

For all key bindings available, please refer to [Keybindings].

### Opening a book in a window of its own ###

The entries under "File &rarr; Recent" and in the "Bookmarks" menu open in the window they were picked from, which closes the book being read. Clicking one with the middle mouse button starts a second MComix on it instead, and leaves the first one where it is. A bookmark opened this way opens at the page it marks.

The same thing can be asked for from a shell: `mcomix --page 42 book.cbz` opens the book at page 42.

Preferences
---

To customize MComix, you can press the "F12" key to open the preferences dialog. All options are documented on the [Preferences] page.

Editing and saving books
---

"Edit &rarr; Edit archive..." opens the archive editor on the book that is open, which may be an archive or a directory of images. It has two tabs: "Images" lists the pages as thumbnails, and "Comment files" lists the text files that came with them. Pages are put in another order by dragging them, "Remove from archive" in either list's right-click menu takes out what is selected, and "Import" adds images from elsewhere on disk. Ctrl+Z takes the last change back and Ctrl+Y, or Ctrl+Shift+Z, puts it back again; both work whichever of the two lists has the focus.

"Apply" hands the edited page list to the main window without writing anything to disk, so the book can be read in its new order before it is saved anywhere. "Save As" writes the pages and the comment files out as a new archive. "Cancel" leaves both the book and the archive as they were.

Pages can also be taken out without opening the editor: "Delete page" in the page's right-click menu removes the page the menu was opened over, and "Edit &rarr; Undo" puts it back. The archive on disk is not touched until it is written, and MComix offers to write it after each removal; the offer stops being made once "Do not ask again" is ticked in it, and can be asked for again under "Prompts answered for good" in the preferences dialog.

### The format a save is written in ###

Archives are written as ZIP files whatever they were read as, a ZIP of pictures being what every reader of comics understands. With "Save an edited archive in the format it was opened in" set in the preferences dialog, a book is written back in the format it came in wherever MComix can write that format: ZIP and tar always, 7z on a machine that has the `7z` program and RAR on one that has `rar`. Neither of those two is installed by MComix, and `unrar`, which is what a RAR is read with, only ever reads. A PDF is never written back.

Writing a book back over its own file needs that preference as well, since the file keeps the name it has and the name has to keep saying what the file is. Without it, only a book that was already a ZIP can be written over itself, and the rest can be written only to a new file with "Save As".

### ComicInfo.xml ###

Every archive MComix saves comes out carrying a ComicInfo.xml, whatever format it was written in: a CBZ, a CBT, a CB7 and a CBR are read by the same programs, and the file goes in before the format is chosen. That is the metadata file at the root of a comic archive, and the one thing readers of them agree on: it says how many pages the book has and how large each page is, which is what lets another reader lay the book out before it has decoded a single image.

Two fields are written, PageCount and Pages. The rest of the format describes the comic rather than the file - the series, the writer, the year the issue came out - which is not something MComix knows and not something it should guess at. An archive that came with a ComicInfo.xml keeps every field that file had: it is carried through as it stands, and rewritten only where a page added or removed has made its page count untrue. Nothing MComix shows is read out of it; what the pages are and what order they go in is the archive's own business.

The book library
---

MComix also has a library for organizing and keeping track of comic books. While it in no way is meant to replace a full-featured file manager, being able to categorize books into collections and showing a list of all book covers should normally be enough to allow the user quick access to his favorite books. The library only adds archives, not directories. So, a "book" in this context refers to a single archive of any format MComix can open.

[[img src="mcomix-library.png" alt="Library window"]]

The left side shows a list of collections, while the right side shows all books within the selected collection. The collection "All books" is special, as it automatically contains all books in every single collection. Collections can be nested by dragging one onto the collection it is to sit under, and books can be filed by dragging them from the book view onto a collection. When a collection is selected, books will be shown from the collection itself and from any children collections.

Right-clicking the collection list offers "New" for an empty collection, "Add..." to put books into the one clicked, and, for the collection clicked, "Rename", "Duplicate", "Clean up" - which drops the books whose files have gone away - and "Remove". Removing a collection removes the shelf and not the books on it: they stay in the library, and a collection filed under the one removed is moved to the top level rather than going with it.

Right-clicking the book view offers "Open", "Open without closing library" and "Add...", three ways to take books out - "Remove from this collection", "Remove from the library" and "Remove and delete from disk", which is the only one that touches the files - and "Copy", which puts the books on the clipboard. The same menu sets how the view is sorted, by book name, full path, file size or date added, ascending or descending, and how large the covers are drawn. Clicking a cover with the middle mouse button starts a second MComix on that book, leaving the library and the book being read where they are.

### Library watch list ###

By using the watch list, MComix can keep track of certain directories and automatically add new books to the library when they are added to those directories. The list is opened from the library's own window, and each directory in it names the collection new books go into and whether the directories under it are walked as well. "Scan now" searches the watched directories at once and leaves the list open; closing the list searches them too, if anything in it was edited. With "Automatically scan for new books when library is opened" ticked, the same search runs every time the library is opened.

### Recent books ###

With "Store information about recently opened files" set to "Always" in the preferences dialog, every archive opened from within the program is added to a collection called "Recent". From there it can be moved into another collection. Setting it to "Never" clears the history as well as stopping it from being kept.

Execute external programs
---

MComix can run a list of user-defined commands on the currently opened file/directory/archive. This might include external image viewers, file management tools or custom shell scripts. Please see [External_Commands] for more information.
