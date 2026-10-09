# Editing books

MComix edits the open book: rename, reorder, swap and delete pages, with undo.
The archive on disk is untouched until the changes are written.

## In the main window

- "Copy page", in the page's right-click menu, copies that page as an image and as its file's path. "Edit → Copy" copies the view: both pages, joined, in double page mode.
- "Save As", in the page's right-click menu, saves that page to a file of its own.
- A thumbnail dragged from the sidebar to a file manager copies that page's file there.
- "Rename page...", in the page's menu or F2, names the page for the next save.
  - The name replaces the whole old one; the entry picks out everything but the extension.
  - A name without an extension keeps the old extension.
  - Renaming can change the book's order next time it opens, since an archive is ordered by name.
  - In a folder of images the file is renamed at once; a name a file that is not a page already has is refused.
- A name another page holds is flagged in the dialog, with two choices:
  - "Swap the names": that page gets this page's old name.
  - "Replace": this page gets the name, and the other page leaves the book. In a folder of images its file is written over.
- CTRL+SHIFT and a click marks a page, drawn with a dashed outline; the next such click swaps the two. Clicking the marked page again unmarks it.
  In double page mode, the same keys drag one page onto the other.
- "Delete page", in the page's menu, removes that page; "Edit → Undo" puts it back.
- CTRL and a click picks a page out (outlined in red, in the thumbnails too); again puts it back.
  Escape, or "Put back pages picked out" in the Edit and page menus, puts back all of them.
  Delete removes every page picked out, and opens the archive editor with them selected.

## The archive editor

"Edit → Edit archive..." opens it on the book: an archive or a folder of images.

- "Images" shows the pages as thumbnails; drag them into another order.
- "Comment files" lists the text files that came with them.
- "Remove from archive", in either list's right-click menu, takes out what is selected.
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
- Nothing is asked when every change was undone, or when MComix deleted the archive.
- Deleting the open file takes it out of the recent files and the library. Bookmarks in it are asked about first.
- Once the file is gone, the next one in its folder opens, or the last one. A file that could not be deleted stays open, on the same page.

## Saved archives

- Pages are named after the book, numbered in reading order: a twelve-page "Batman 01.cbz" is written "01 - Batman 01.jpg" to "12 - Batman 01.jpg".
  Numbers take as many digits as the page count needs: a three-page book counts "1" to "3".
- The old page names are not kept, so a reordered book's names say its new order.
- Comment files keep their names; one a page has taken gets an underscore in front.
- The ComicInfo.xml MComix writes keeps its own name, whatever the list calls it.

## The format a save is written in

- Archives are saved as ZIP files by default.
- With "Save an edited archive in the format it was opened in", a book is written in its own format where MComix can: ZIP and tar always, 7z with the `7z` program, RAR with `rar`. `unrar` cannot write RAR, and a PDF is never written.
- The same preference is needed to write a book over its own file. Without it, only a ZIP is written over itself; anything else goes to a new file with "Save As".

## ComicInfo.xml

- Every archive MComix saves carries a ComicInfo.xml, the metadata file comic readers agree on.
- MComix writes two fields: PageCount and Pages, the number of pages and the size of each, so other readers can lay the book out before decoding it.
- An archive's existing ComicInfo.xml keeps every other field.
