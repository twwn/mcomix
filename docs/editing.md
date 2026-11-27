# Editing books

MComix edits the open book: rename, reorder, swap and delete pages, with undo.
The archive on disk is untouched until the changes are written.

## In the main window

- "Copy page", in the page's right-click menu, copies that page as an image and as its file's path. "Edit → Copy", or CTRL+C, copies the view: both pages, joined, in double page mode.
- "Save page as...", in the page's right-click menu and the File menu, saves that page to a file of its own.
- A thumbnail dragged from the sidebar to a file manager copies that page's file there.
- "Rename page...", in the page's menu or F2, names the page for the next save.
  - The name replaces the whole old one; the entry picks out everything but the extension.
  - A name without an extension keeps the old extension.
  - On Windows, a character Windows refuses in a file name (`: * ? " < > |`) becomes `_`, as in the names of an opened archive.
  - Renaming can change the book's order next time it opens, since an archive is ordered by name.
  - In a folder of images the file is renamed at once; a name a file that is not a page already has is refused.
- "Save rotation to file", in the page's menu, turns a JPEG picture in its file as the page is shown turned by hand, without loss, and the page then shows upright by itself in any viewer.
  - Where the picture's size lets them, its compressed blocks are turned with `jpegtran` ([Install](install.md#requirements); the Windows packages and the Flatpak bring it). Otherwise only its Exif orientation tag is turned; with "Automatically rotate images according to their metadata" off MComix would not show that turn, so it refuses and says why.
  - In a folder of images the file is written at once. In an archive the page is turned for the next save, and "Edit → Undo" gives back the page and its turn.
  - Not offered for other formats, in an archive MComix cannot write, with "Keep transformation" on, or in continuous mode.
- A name another page holds is flagged in the dialog, with two choices:
  - "Swap the names": that page gets this page's old name.
  - "Replace": this page gets the name, and the other page leaves the book. In a folder of images its file is written over.
- CTRL+SHIFT and a click, on a page or its thumbnail, marks that page, drawn with a dashed outline; the next such click swaps the two. Clicking the marked page again unmarks it.
  The same keys drag one page onto the other, in double page mode or among the thumbnails.
- "Delete page", in the page's menu, removes that page; "Edit → Undo" puts it back.
- CTRL and a click, on a page or its thumbnail, picks that page out (outlined in red, in the thumbnails too); again puts it back.
  Escape, or "Put back pages picked out" in the Edit and page menus, puts back all of them.
  Delete removes every page picked out at once; "Edit → Undo" puts them back.

## The archive editor

"Edit → Edit archive..." or CTRL+E opens it on the book: an archive or a folder of images.

- "Images" shows the pages as thumbnails; drag them into another order. Hold a dragged page near the top or bottom edge to scroll.
- "Comment files" lists the text files that came with them.
- "Remove from archive", in either list's right-click menu, or Delete, takes out what is selected.
- "Rename page..." or F2 names the selected page; "Rename file..." or F2 names a comment file.
- "Import" adds images from disk.
- CTRL+Z undoes, CTRL+Y or CTRL+SHIFT+Z redoes.
- "Apply" hands the new page list to the main window, to read before saving; nothing is written.
- "Save As" writes pages and comment files as a new archive.
- "Cancel" leaves book and archive as they were.
- The editor closes with its book. With changes not applied or saved, MComix asks first, and the book stays open if you go on editing.

## Writing the changes

- MComix offers to write the archive after any change to the pages, and when a book with pages picked out is left.
- A change not yet written is offered again on the way out: closing the book, opening another (also by turning past the last page), and quitting.
- Each offer can be answered for good, and that answer also stands on the way out. Take it back under "Prompts answered for good" in the preferences.
- Nothing is asked when every change was undone, when the book was saved after its last change, or when MComix deleted the archive.
- An archive another program has written since the book was opened is not written over unasked: what that program changed would be lost. "Cancel" leaves it as it is, and on the way out keeps the book open.
- A save that takes more than half a second shows its progress, and "Cancel" stops it. The archive on disk is then left as it was, and the changes stay to be written later. Cancelling a save made on the way out keeps the book open. A book closed or opened meanwhile waits for the save.
- Deleting the open file takes it out of the recent files and the library. Bookmarks in it are asked about first.
- A RAR book in volumes is deleted, moved or renamed whole: name.part1.rar and every volume after it. A new name keeps the numbering: "New" renames the set New.part1.rar, New.part2.rar, …
- Once the file is gone, the next one in its folder opens, or the last one. A file that could not be deleted stays open, on the same page.

## Saved archives

- Pages are named after the book, numbered in reading order: a twelve-page "Batman 01.cbz" is written "01 - Batman 01.jpg" to "12 - Batman 01.jpg".
  Numbers take as many digits as the page count needs: a three-page book counts "1" to "3".
- The old page names are not kept, so a reordered book's names say its new order.
- Comment files keep their names; one a page has taken gets an underscore in front.
- The ComicInfo.xml MComix writes keeps its own name, whatever the list calls it.
- In a CBZ, a page that is compressed already, such as a JPEG, PNG or WebP, is stored as it is: compressing it again saves a tenth of a percent or so, and makes the book slower to write and to read. Text files and uncompressed pictures, such as BMP, are compressed.
- With "Store PNG pages as lossless WebP when saving an archive", each PNG or GIF page is written as a WebP instead, its name ending in .webp: "03 - Batman 01.webp".
  - Lossless: a page becomes a WebP only where that decodes to exactly the same pixels and is smaller. The drawn and painted pages it was tried on took a quarter to three fifths less room; a page that would not shrink stays as it was.
  - Pages that WebP cannot hold exactly stay PNGs: 16 bits a channel, wider or higher than 16383 pixels, or with a gamma other than sRGB's. A colour profile and Exif go along with the page.
  - An animated PNG or GIF becomes an animated WebP where every frame shows the same pixels for as long, to the millisecond, and it plays as often (a GIF that does not say how often plays once); the colour under a wholly transparent pixel, which nothing shows, is not kept. An animated PNG stays a PNG where its own picture is not a frame of the animation, or where its frames would take more than a sixteenth of the memory to hold at once.
  - Other formats are left as they are: a JPEG made a WebP again would lose more of the picture each time. A GIF's comment is not carried over.
  - The pages are converted on all processors at once, as far as memory allows, and the save's progress counts them.
  - Some other comic readers and older devices cannot show WebP.

## The format a save is written in

- Archives are saved as ZIP files by default.
- With "Save an edited archive in the format it was opened in", a book is written in its own format where MComix can: ZIP and tar always, 7z with the `7z` program, RAR with `rar`. `unrar` cannot write RAR, and a PDF is never written.
- The same preference is needed to write a book over its own file. Without it, only a ZIP is written over itself; anything else goes to a new file with "Save As".

## ComicInfo.xml

- Every archive MComix saves carries a ComicInfo.xml, the metadata file comic readers agree on.
- MComix writes two fields: PageCount and Pages, the number of pages and the size of each, so other readers can lay the book out before decoding it. Pages marks the first page as the front cover.
- An archive's existing ComicInfo.xml keeps every other field.
