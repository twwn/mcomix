Documentation
===

[TOC]

This is the user manual for MComix. The [Installation] page covers installing it, and [Preferences], [Keybindings] and [External_Commands] have pages of their own.

The main window
---

[[img src="mcomix-mainwindow.png" alt="MComix' main window"]]

The pages in the screenshots on this page are from "The Potion of Flight", episode 1 of [Pepper&Carrot](https://www.peppercarrot.com/) by David Revoy, published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and scaled down here.

The window has a menu bar and a toolbar at the top, the page thumbnails on the left, the page in the middle and a status bar at the bottom. "View &rarr; Toolbars" turns the menubar, the toolbar, the statusbar, the scrollbars and the thumbnails on and off, and "Hide all" in the same menu, or the I key, puts all of them away at once. Fullscreen mode, the F key, hides them too while "Automatically hide all toolbars in fullscreen" is set in the preferences.

The arrow keys scroll the page, and PageDown and PageUp turn it. "Move to", in the page's right-click menu, moves the file that is open, or the archive the page is in, to another folder. The book goes on being read where it was, and what MComix records about it - its place in the library, the page it was left on, any bookmark in it, and its entry in the recent files - follows it to the new folder.

"File &rarr; Properties" describes the page being read and the archive it is in. Where the archive carries a ComicInfo.xml, the archive's page also names the series, the issue number, the title and the writer given there.

### Fit modes ###

Mode | Key | What it does
-----|-----|-------------
Best fit | B | Scales a page down to fit within the window.
Fit to width | W | Scales a page down to the width of the window. A taller page scrolls up and down, which suits reading comics.
Fit to height | H | Scales a page down to the height of the window. A wider page scrolls sideways.
Fit to size | S | Scales pages to the sizes set in the preferences, one for a wide page, such as a double-page spread, and one for the rest. They are 3790x960 and 1450x1800 by default.
Manual zoom | A | No scaling is performed on the page.

No mode scales a small page up unless "View &rarr; Stretch small images" is on.

### Double page mode and manga mode ###

Double page mode, the D key, shows two pages side by side, so that a double-page spread reads as one. The first page of a book, which is its cover, and any page wider than it is tall are shown on their own unless the preferences say otherwise. Pages turn two at a time; CTRL with PageDown or PageUp turns one.

Manga mode, the M key, lays pages out and scrolls from right to left.

### Slideshow mode ###

CTRL+S starts a slideshow, which works like pressing the Down arrow key at intervals. By default it scrolls down 50 pixels every three seconds; a delay of 0.05 seconds with a step of 1 pixel scrolls smoothly instead. Both are set in the preferences.

### Enhancing the image ###

"Tools &rarr; Enhance image...", the E key, sets the brightness, contrast, saturation and sharpness of the pages with sliders, beside a histogram of the page being read. "Automatically adjust contrast" adjusts the contrast of each colour band to the page, and "Invert image colors", also CTRL+I, turns the colours to their negative. A change shows at once on the pages, the thumbnails, the magnifying lens and the library's covers, and lasts until MComix is closed, whichever book is open.

"Save" keeps the values as the ones MComix starts with, "Revert" goes back to those, and "OK" closes the dialog with the values as they are.

### Rotating and flipping pages ###

"Tools &rarr; Transform image" turns the page 90 degrees clockwise, the R key, or anticlockwise, SHIFT+R, or 180 degrees, and flips it horizontally or vertically. In double page mode both pages turn together. The next page is shown upright and unflipped again, unless "Keep transformation", the K key, is on: then every page gets the same rotation and flips, also after MComix is started again.

"Auto-rotate image", in the same submenu, turns every page that is taller than it is wide, or every page that is wider than it is tall, 90 degrees one way or the other, until it is set back to "Never". It goes by what is shown, so that two pages side by side count as one wide page, and it adds to a rotation given by hand. Images whose metadata, such as an Exif tag, says which way up they belong are turned that way while "Automatically rotate images according to their metadata" is set in the preferences.

### Opening a book in another window ###

Picking an entry under "File &rarr; Recent" or in the "Bookmarks" menu closes the book being read and opens the one picked. A bookmark in the book that is already open only turns to its page, so that the pages picked out and the changes that can be undone stay as they are; in a directory of images, the page is found by its file, wherever sorting has put it. Clicking an entry with the middle mouse button starts a second MComix on it instead, at the page a bookmark marks.

From a shell, `mcomix --page 42 book.cbz` opens a book at page 42.

Editing and saving books
---

"Edit &rarr; Edit archive..." opens the archive editor on the book, which may be an archive or a directory of images. Its "Images" tab shows the pages as thumbnails, which can be dragged into another order, and its "Comment files" tab lists the text files that came with them. "Remove from archive", in the right-click menu of either list, takes out what is selected, "Rename page..." in the same menu, or F2, gives the selected page a name, and "Import" adds images from elsewhere on disk. A comment file is renamed the same way, with "Rename file..." or F2 in its own list, and is written under that name by "Save As"; the ComicInfo.xml MComix writes for a saved book keeps its own name, whatever the list calls it. CTRL+Z undoes a change, and CTRL+Y or CTRL+SHIFT+Z redoes it.

"Apply" hands the edited page list to the main window without writing anything to disk, so that the book can be read in its new order before it is saved. "Save As" writes the pages and the comment files out as a new archive. "Cancel" leaves the book and the archive as they were.

A saved archive names its pages after the book, numbered in the order they are read: a twelve-page "Batman 01.cbz" is written with "01 - Batman 01.jpg" first and "12 - Batman 01.jpg" last, in as many digits as the page count needs, and a three-page book counts "1" to "3". The names the pages had are not kept, so a book saved in a new order is a book whose page names say that order. The comment files keep their own names, and one that a page has taken is given an underscore in front of it.

Deleting the open file takes it out of the recent files and out of the library, both of which describe a file that is no longer there; the library also offers "Clean up" for books deleted from outside MComix. Bookmarks in the file are a page the reader marked rather than a record of it, so MComix asks before removing them, and that answer can be given for good like the others under "Prompts answered for good" in the preferences.

"Copy page", in the page's right-click menu, puts the page the menu was opened over on the clipboard, as the image it is and as the path to its file; "Edit &rarr; Copy" takes the view instead, which in double page mode is both pages joined as they read.

"Rename page...", in the page's right-click menu or F2, gives the page the name it is written under the next time the book is saved. The name replaces the whole of the old one - the entry offers the name with everything but the extension picked out, as a file manager does - and a name typed without an extension keeps the old one, since that is what says the page is a picture. Renaming a page may put the book in a different order the next time it is opened, the order of an archive being the order of its names; the pages that were not renamed go on being numbered after the book. A book read as a folder of images has no archive to write, so renaming one of its pages renames the file at once, and a name a file that is not a page has is refused rather than written over.

A name another page of the book holds is said so on a warning line in the dialog, which then offers what can be done about it rather than the plain rename: "Swap the names" gives that page the name this one had, and "Replace" gives this page the name and takes the other page out of the book, as a file manager writes over the file that was there. For a book read as a folder of images both happen on disk at once, so a replace writes over the other page's file. Without either of them, two pages named alike used to be written with an underscore in front of the second, which nothing said.

Two pages change places with CTRL+SHIFT and a click: the first page clicked is marked, drawn with a dashed outline, and the second changes places with it. Clicking the marked page again takes the mark off. In double page mode the same modifiers drag one page onto the other, which swaps them without marking anything. The book in the window is what changes, "Edit &rarr; Undo" puts the pages back, and the archive on disk is not touched until it is saved.

Pages can also be taken out in the main window. "Delete page", in the page's right-click menu, removes the page the menu was opened over, and "Edit &rarr; Undo" puts it back. CTRL and a click picks a page out, which is drawn outlined, and another such click puts it back; Delete then removes every page picked out, and the archive editor opens with them selected. The archive on disk is not touched until it is written. MComix offers to write it after any change to the pages - one removed, two swapped, one renamed - and when a book with pages still picked out is left; either offer can be answered for good, and taken back under "Prompts answered for good" in the preferences.

A change that has not been written is offered again on the way out: closing the book, opening another over it and quitting all stop to ask whether to write the archive first, since closing is what throws the change away. The question is the one asked at the change itself, so an answer remembered there stands here as well, and a book whose changes have all been undone has nothing to ask about.

### The format a save is written in ###

Archives are saved as ZIP files, whatever they were read as. With "Save an edited archive in the format it was opened in" set in the preferences, a book is written back in its own format where MComix can write that: ZIP and tar always, 7z where the `7z` program is installed, and RAR where `rar` is. `unrar`, which reads RAR files, cannot write them, and a PDF is never written back.

The same preference is needed to write a book back over its own file, since the file keeps its name and the name has to go on saying what the file is. Without it, only a ZIP can be written over itself, and anything else is saved to a new file with "Save As".

### ComicInfo.xml ###

Every archive MComix saves carries a ComicInfo.xml, the metadata file at the root of a comic archive that readers of them agree on. MComix writes two of its fields, PageCount and Pages, which give the number of pages and the size of each, so that another reader can lay the book out before decoding it. An archive that came with a ComicInfo.xml keeps every other field in it. MComix does not read the file itself.

The book library
---

The library, CTRL+L, files books in collections and shows their covers. A book is an archive in any format MComix opens; a directory cannot be added.

[[img src="mcomix-library.png" alt="Library window"]]

The collections are on the left, and the books of the one selected on the right, including those in the collections under it. "All books" holds every book in the library. Drag a collection onto another to file it there, and drag books onto a collection to add them to it. The search field shows only the books whose name or path contains what is typed.

Right-clicking a collection offers "New", "Add...", "Rename", "Duplicate", "Clean up", which drops the books whose files are gone, and "Remove". Removing a collection keeps its books in the library, and moves the collections under it to the top level.

Right-clicking the books offers "Open", "Open without closing library", "Add...", three ways to take them out - "Remove from this collection", "Remove from the library" and "Remove and delete from disk", the only one that touches the files - and "Copy", which puts the books on the clipboard. Deleting books from disk asks about any bookmarks in them, as deleting the open file does. Its "Sort" and "Cover size" submenus set the order, by book name, full path, file size or date added, and how large the covers are drawn. Clicking a cover with the middle mouse button starts a second MComix on that book.

### Library watch list ###

The watch list, opened from the library window, names directories to look in for new books, each with the collection its books go into and whether the directories under it are searched as well. "Scan now" searches them at once, and closing the list searches them if it was edited. With "Automatically scan for new books when library is opened" ticked, the search runs whenever the library is opened.

### Recent books ###

While "Store information about recently opened files" is set to "Always", every archive with pages that is opened in MComix joins the "Recent" collection, which remembers the page it was left at. Setting it to "Never" stops that, and offers to clear what is kept.

Execute external programs
---

"File &rarr; Open with" runs programs of your choosing on the file that is open. The [External_Commands] page describes how to set them up.
