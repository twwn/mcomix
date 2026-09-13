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

Preferences
---

To customize MComix, you can press the "F12" key to open the preferences dialog. All options are documented on the [Preferences] page.

The book library
---

MComix also has a library for organizing and keeping track of comic books. While it in no way is meant to replace a full-featured file manager, being able to categorize books into collections and showing a list of all book covers should normally be enough to allow the user quick access to his favorite books. The library only adds archives, not directories. So, a "book" in this context refers to a single archive of any format MComix can open.

[[img src="mcomix-library.png" alt="Library window"]]

The left side shows a list of collections, while the right side shows all books within the selected collection. The collection "All books" is special, as it automatically contains all books in every single collection. Collections can be nested by dragging one onto the collection it is to sit under, and books can be filed by dragging them from the book view onto a collection. When a collection is selected, books will be shown from the collection itself and from any children collections.

Right-clicking the collection list offers "New" for an empty collection, "Add..." to put books into the one clicked, and, for the collection clicked, "Rename", "Duplicate", "Clean up" - which drops the books whose files have gone away - and "Remove". Removing a collection removes the shelf and not the books on it: they stay in the library, and a collection filed under the one removed is moved to the top level rather than going with it.

Right-clicking the book view offers "Open", "Open without closing library" and "Add...", three ways to take books out - "Remove from this collection", "Remove from the library" and "Remove and delete from disk", which is the only one that touches the files - and "Copy", which puts the books on the clipboard. The same menu sets how the view is sorted, by book name, full path, file size or date added, ascending or descending, and how large the covers are drawn.

### Library watch list ###

By using the watch list, MComix can keep track of certain directories and automatically add new books to the library when they are added to those directories. Every time the library is opened, new directories will be scanned, and books that aren't part of the library yet will be added.

### Recent books ###

With "Store information about recently opened files" set to "Always" in the preferences dialog, every archive opened from within the program is added to a collection called "Recent". From there it can be moved into another collection. Setting it to "Never" clears the history as well as stopping it from being kept.

Execute external programs
---

MComix can run a list of user-defined commands on the currently opened file/directory/archive. This might include external image viewers, file management tools or custom shell scripts. Please see [External_Commands] for more information.
