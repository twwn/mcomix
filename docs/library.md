# Library

The library, CTRL+L, files books in collections and shows their covers.
A book is an archive in any format MComix opens; folders cannot be added.

![Library window](images/mcomix-library.png)

<sub>The covers are from "The Potion of Flight", episode 1 of [Pepper&Carrot](https://www.peppercarrot.com/) by David Revoy, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), scaled down.</sub>

## Collections

- Collections are on the left; the selected one's books on the right, with those of the collections under it.
- "All books" holds every book.
- Drag a collection onto another to file it there.
- Drag books onto a collection to move them there from the collection on show; from "All books" they are added and stay where they were.
- Hold CTRL while dragging to copy them instead: they stay in the collection on show as well.
- "Recent" holds the books that are read, not books dragged onto it.
- "Add..." and books dropped from a file manager go into the collection on show; under "All books" or "Recent" they join no collection.
- Right-clicking a collection offers "Add...", "New", "Rename", "Duplicate", "Clean up", "Relocate..." and "Remove".
  - "Duplicate" makes a copy beside it, holding every book it shows.
  - "Clean up" drops books whose files are gone.
  - "Relocate..." follows a folder of books that was moved or renamed outside MComix; see below.
  - "Remove" keeps the books in the library, and moves the collections under it to the top.

## A folder that moved

- The library holds a book by its path. A folder moved or renamed outside MComix leaves its books without their files.
- "Relocate...", in the collections' right-click menu, asks for the folder the books were in and the folder they are in now.
- Every book the library holds under the old folder follows, at any depth, whichever collection it is in.
- The books keep their collections, covers, bookmarks, the page they were left at, and the pages skipped, shown alone or turned.
- Watched folders under the old folder follow too.
- Where the missing books share one folder and no book in it is left, that folder is filled in.
- A book the library already holds at the new place stays where it was.

## Books

- The search field shows the books whose name or path contains its text, case aside, once Enter is pressed.
- A book's cover is its first picture, or the first one named "cover" or "front". Pictures named "credit" or "banner" are passed over.
- To choose another, open the book, right-click the page and tick "Cover in the library". The book is not changed. Untick it there to go back.
- A book read to its last page has a tick on its cover.
- "Mark as read" in the books' right-click menu gives the selected books the tick; "Mark as unread" takes it away, with the page they were left at.
- The line under the covers gives the selected book's folder, size, page count, and the page it was left on or when it was finished.
- With no book selected, it counts the books on show: how many, how many were started and finished, the pages read, and when the last was read.
- Right-clicking the books offers "Open", "Open without closing library", "Mark as read", "Mark as unread", "Add...", "Clean up", "Copy", and three ways to take them out:
  - "Remove from this collection".
  - "Remove from the library".
  - "Remove and move to the trash": the only one that touches the files. They can be restored from the trash. Where the trash would refuse one, MComix asks to delete it permanently instead. It also takes them out of the recent files and asks about their bookmarks.
- "Copy" puts a single book's path and cover on the clipboard.
- "Sort" orders by name, full path, file size or date added; "Cover size" sets how large covers are drawn.
- A middle click on a cover starts a second MComix on that book.
- A book opened from the library is one of the books shown. The next and previous archive are the next and previous of those, in the order shown, not of its folder. Past the last one shown there is no next.
- A RAR book in volumes is added as its first volume; the others are left out.
- An encrypted book is added without asking its password. Its cover is a padlock; the password is asked when it is opened.

## Watched folders

- "Watch list", at the bottom of the library window, names folders to look in for new books, each with its collection and whether subfolders are searched.
- "Scan now" searches at once; closing an edited list searches too.
- With "Automatically scan for new books when library is opened", the search runs whenever the library opens.

## Recent books

- While "Store information about recently opened files" is "Always", every archive opened joins the "Recent" collection with the page it was left at.
- That page is remembered by its picture, so re-sorting the archive does not move it.
- "Never" stops this, and offers to clear what is kept.
