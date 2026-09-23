"""Tests for the bookmark store, which several MComix instances share.

The store keeps its bookmarks in one pickle under the data directory, so
a second instance can write it between two writes of the first.  Every
write therefore re-reads the file and merges what it finds.
"""

import datetime
import os
import pickle

from . import MComixTest

from mcomix import bookmark_backend
from mcomix import bookmark_menu_item
from mcomix import constants


class MergeTest(MComixTest):

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.store = bookmark_backend.BookmarksStore
        self.store._initialized = False
        self.store._bookmarks = []
        self.store._bookmarks_mtime = 0

    def _bookmark(self, page):
        """A bookmark on <page> of a book of its own."""
        return bookmark_menu_item._Bookmark(
            None, None, 'book %d' % page, '/books/%d.cbz' % page, page, 20,
            None, datetime.datetime(2026, 1, 1))

    def _write_pickle(self, bookmarks):
        """Write <bookmarks> to the store's file, as another instance would."""
        with open(constants.BOOKMARK_PICKLE_PATH, 'wb') as fd:
            pickle.dump(constants.VERSION, fd, pickle.HIGHEST_PROTOCOL)
            pickle.dump([bookmark.pack() for bookmark in bookmarks], fd,
                        pickle.HIGHEST_PROTOCOL)

    def test_a_merge_keeps_the_order_the_reader_sees(self):
        """The bookmarks menu lists the store in its own order, so a
        merge that reshuffles it rearranges the menu behind the reader's
        back - and writes the new arrangement out, so it sticks."""
        ours = [self._bookmark(page) for page in range(1, 7)]
        self.store._bookmarks = list(ours)
        self._write_pickle(ours[:3] + [self._bookmark(7)])

        self.store.write_bookmarks_file()

        self.assertEqual([bookmark._page for bookmark in self.store._bookmarks],
                         [1, 2, 3, 4, 5, 6, 7],
                         'the merge reordered the bookmarks')

    def test_a_merge_takes_the_other_instance_s_bookmarks_once(self):
        """They are identified by the page of the file they mark, so the
        three the two instances have in common are not duplicated."""
        ours = [self._bookmark(page) for page in range(1, 7)]
        self.store._bookmarks = list(ours)
        self._write_pickle(ours[:3] + [self._bookmark(7)])

        self.store.write_bookmarks_file()

        self.assertEqual(len(self.store._bookmarks), 7)

    def test_a_file_that_is_not_there_has_not_been_modified(self):
        """get_bookmarks() re-reads the file whenever it says yes, so a
        yes here emptied the list over bookmarks nothing had written out
        yet - and the next bookmark added wrote that empty list back."""
        self.store._bookmarks = [self._bookmark(1)]
        self.assertFalse(os.path.exists(constants.BOOKMARK_PICKLE_PATH))

        self.assertFalse(self.store.file_was_modified())
        self.assertEqual([bookmark._page
                          for bookmark in self.store.get_bookmarks()], [1])

    def test_clearing_writes_the_store_once(self):
        """Removing them one at a time re-pickled and fsynced the whole
        store for every bookmark."""
        self.store._bookmarks = [self._bookmark(page) for page in range(1, 6)]
        writes = []
        real_write = bookmark_backend.tools.atomic_write

        def counted(path, binary=False):
            writes.append(path)
            return real_write(path, binary=binary)

        bookmark_backend.tools.atomic_write = counted
        try:
            self.store.clear_bookmarks()
        finally:
            bookmark_backend.tools.atomic_write = real_write

        self.assertEqual(len(writes), 1,
                         'the store was written %d times' % len(writes))
        self.assertEqual(self.store._bookmarks, [])

    def test_clearing_removes_the_other_instance_s_bookmarks_too(self):
        """"All stored bookmarks will be removed" is what the reader was
        asked, so this one write does not merge the file back in."""
        ours = [self._bookmark(1)]
        self.store._bookmarks = list(ours)
        self._write_pickle(ours + [self._bookmark(2)])

        self.store.clear_bookmarks()

        self.assertEqual(self.store._bookmarks, [])
        written, _mtime = self.store.load_bookmarks()
        self.assertEqual(written, [], 'the file kept a bookmark')

    def test_the_merged_order_is_what_reaches_the_file(self):
        ours = [self._bookmark(page) for page in range(1, 7)]
        self.store._bookmarks = list(ours)
        self._write_pickle(ours[:3] + [self._bookmark(7)])

        self.store.write_bookmarks_file()
        written, _mtime = self.store.load_bookmarks()

        self.assertEqual([bookmark._page for bookmark in written],
                         [1, 2, 3, 4, 5, 6, 7])


class MemberRecordTest(MComixTest):

    """The name within its archive of each bookmark's page is stored in
    a record after the bookmarks, which an older MComix reading the file
    stops short of."""

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.store = bookmark_backend.BookmarksStore
        self.store._initialized = False
        self.store._bookmarks = []
        self.store._bookmarks_mtime = 0

    _bookmark = MergeTest._bookmark
    _write_pickle = MergeTest._write_pickle

    def _with_member(self, page, member):
        return bookmark_menu_item._Bookmark(
            None, None, 'book', '/books/b.cbz', page, 20, 1,
            datetime.datetime(2026, 1, 1), member=member)

    def test_the_names_come_back_with_their_bookmarks(self):
        self.store._bookmarks = [self._with_member(2, 'pages/02.jpg'),
                                 self._with_member(3, None)]
        self.store.write_bookmarks_file(merge=False)
        bookmarks, _mtime = self.store.load_bookmarks()
        self.assertEqual(['pages/02.jpg', None],
                         [bookmark.get_member() for bookmark in bookmarks])

    def test_a_file_an_older_mcomix_wrote_has_no_names(self):
        self._write_pickle([self._bookmark(2), self._bookmark(3)])
        bookmarks, _mtime = self.store.load_bookmarks()
        self.assertEqual([None, None],
                         [bookmark.get_member() for bookmark in bookmarks])

    def test_an_older_mcomix_reads_the_file_as_it_always_did(self):
        """What it reads: the version record, then one tuple of six
        fields per bookmark, each of which it builds a bookmark from."""
        self.store._bookmarks = [self._with_member(2, 'pages/02.jpg')]
        self.store.write_bookmarks_file(merge=False)
        with open(constants.BOOKMARK_PICKLE_PATH, 'rb') as fd:
            pickle.load(fd)
            packs = pickle.load(fd)
        self.assertEqual([6], [len(pack) for pack in packs])
        bookmark_menu_item._Bookmark(None, None, *packs[0])


class MovedBookTest(MComixTest):

    """A bookmark holds the path of the file it marks, so a book moved
    out from under it was bookmarked where it no longer is."""

    def setUp(self):
        super().setUp()
        os.makedirs(constants.DATA_DIR, exist_ok=True)
        self.store = bookmark_backend.BookmarksStore
        self.store._initialized = False
        self.store._bookmarks = []
        self.store._bookmarks_mtime = 0

    def _bookmark(self, path, page=3):
        return bookmark_menu_item._Bookmark(
            None, None, os.path.basename(path), path, page, 20, None,
            datetime.datetime(2026, 1, 1))

    def test_a_bookmark_of_the_moved_book_holds_its_new_path(self):
        self.store._bookmarks = [self._bookmark('/books/one.cbz'),
                                 self._bookmark('/books/two.cbz')]

        self.store.update_path('/books/one.cbz', '/elsewhere/one.cbz')

        self.assertEqual([bookmark._path
                          for bookmark in self.store._bookmarks],
                         ['/elsewhere/one.cbz', '/books/two.cbz'],
                         'the bookmark did not follow the book, or moved '
                         'out of its place in the list')

    def test_what_the_bookmark_says_about_the_page_is_kept(self):
        self.store._bookmarks = [self._bookmark('/books/one.cbz', page=7)]

        self.store.update_path('/books/one.cbz', '/elsewhere/one.cbz')

        moved = self.store._bookmarks[0]
        self.assertEqual(moved.pack()[2:],
                         (7, 20, None, datetime.datetime(2026, 1, 1)))
        self.assertEqual(moved.pack()[0], 'one.cbz')

    def test_every_bookmark_of_the_same_book_follows_it(self):
        self.store._bookmarks = [self._bookmark('/books/one.cbz', page=2),
                                 self._bookmark('/books/one.cbz', page=9)]

        self.store.update_path('/books/one.cbz', '/elsewhere/one.cbz')

        self.assertEqual([bookmark._path
                          for bookmark in self.store._bookmarks],
                         ['/elsewhere/one.cbz'] * 2)

    def test_a_book_that_is_bookmarked_nowhere_writes_nothing(self):
        self.store._bookmarks = [self._bookmark('/books/two.cbz')]
        written = []
        self.store.write_bookmarks_file = lambda *args: written.append(args)
        try:
            self.store.update_path('/books/one.cbz', '/elsewhere/one.cbz')
        finally:
            del self.store.write_bookmarks_file
        self.assertEqual(written, [])
