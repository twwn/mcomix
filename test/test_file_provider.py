import itertools
import os
import shutil
import tempfile
from unittest import mock

from . import MComixTest, get_testfile_path

from mcomix import constants
from mcomix import file_provider
from mcomix.file_provider import FileProvider, OrderedFileProvider, PreDefinedFileProvider
from mcomix.preferences import prefs


def _stat_failing_on(doomed: str):
    """Returns an os.stat that raises for <doomed> and works otherwise,
    standing in for a file deleted after the directory was listed."""

    real_stat = os.stat

    def stat(path, *args, **kwargs):
        if path == doomed:
            raise FileNotFoundError(2, 'No such file or directory', path)
        return real_stat(path, *args, **kwargs)

    return stat


class OrderedFileProviderTest(MComixTest):

    def setUp(self) -> None:
        super().setUp()
        self.root = tempfile.mkdtemp(prefix='file_provider.')
        for name in ('a', 'b', 'c'):
            os.mkdir(os.path.join(self.root, name))

    def _provider(self, name):
        return OrderedFileProvider(os.path.join(self.root, name))

    def _walk(self, provider, step):
        """Return the directory names <step> visits until it runs out."""
        visited = [os.path.basename(provider.get_directory())]
        while step(provider):
            visited.append(os.path.basename(provider.get_directory()))
        return visited

    def test_walks_siblings_forwards(self) -> None:
        provider = self._provider('a')
        self.assertEqual(self._walk(provider, OrderedFileProvider.next_directory),
                         ['a', 'b', 'c'])

    def test_walks_siblings_backwards(self) -> None:
        provider = self._provider('c')
        self.assertEqual(self._walk(provider, OrderedFileProvider.previous_directory),
                         ['c', 'b', 'a'])

    def _nest(self):
        """Fill a/ with a1/ and a2/, and a2/ with deep/, a level further
        down than the walk goes."""
        for name in ('a1', os.path.join('a2', 'deep')):
            os.makedirs(os.path.join(self.root, 'a', name))

    def test_the_walk_goes_into_the_directories_on_the_shelf(self) -> None:
        """The shelf is the directory above the one the book opened in;
        each directory comes before the ones in it, two levels deep."""
        self._nest()
        provider = self._provider('a')
        self.assertEqual(self._walk(provider, OrderedFileProvider.next_directory),
                         ['a', 'a1', 'a2', 'b', 'c'])

    def test_the_walk_back_is_the_walk_on_reversed(self) -> None:
        self._nest()
        provider = self._provider('c')
        self.assertEqual(
            self._walk(provider, OrderedFileProvider.previous_directory),
            ['c', 'b', 'a2', 'a1', 'a'])

    def test_the_walk_never_climbs_above_the_shelf(self) -> None:
        """Opened in a/a2, the shelf is a: the walk back ends at a1
        rather than going on to a, and the walk on ends after deep."""
        self._nest()
        provider = self._provider(os.path.join('a', 'a2'))
        self.assertEqual(
            self._walk(provider, OrderedFileProvider.previous_directory),
            ['a2', 'a1'])
        provider = self._provider(os.path.join('a', 'a2'))
        self.assertEqual(self._walk(provider, OrderedFileProvider.next_directory),
                         ['a2', 'deep'])

    def test_a_linked_directory_is_visited_but_not_gone_into(self) -> None:
        elsewhere = tempfile.mkdtemp(prefix='file_provider.')
        self.addCleanup(shutil.rmtree, elsewhere)
        os.mkdir(os.path.join(elsewhere, 'inside'))
        try:
            os.symlink(elsewhere, os.path.join(self.root, 'b2'),
                       target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('no symbolic links here')
        provider = self._provider('b')
        self.assertEqual(self._walk(provider, OrderedFileProvider.next_directory),
                         ['b', 'b2', 'c'])

    def test_directories_not_accepted_are_passed_over(self) -> None:
        provider = self._provider('a')
        self.assertTrue(provider.next_directory(
            lambda: os.path.basename(provider.get_directory()) != 'b'))
        self.assertEqual('c', os.path.basename(provider.get_directory()))

    def test_with_nothing_accepted_the_directory_stays(self) -> None:
        provider = self._provider('a')
        self.assertFalse(provider.next_directory(lambda: False))
        self.assertEqual('a', os.path.basename(provider.get_directory()))

    def test_root_directory_has_no_siblings(self) -> None:
        # The root is not listed inside itself, which used to raise ValueError.
        provider = OrderedFileProvider(os.path.abspath(os.sep))
        self.assertFalse(provider.next_directory())
        self.assertFalse(provider.previous_directory())

    def test_removed_directory_has_no_siblings(self) -> None:
        provider = self._provider('b')
        shutil.rmtree(os.path.join(self.root, 'b'))
        self.assertFalse(provider.next_directory())
        self.assertFalse(provider.previous_directory())

    def test_rejects_a_path_that_does_not_exist(self) -> None:
        self.assertRaises(ValueError, OrderedFileProvider,
                          os.path.join(self.root, 'nope'))

    def test_lists_images_and_archives_separately(self) -> None:
        directory = get_testfile_path('archives')
        provider = OrderedFileProvider(directory)
        archives = provider.list_files(OrderedFileProvider.ARCHIVES)
        images = provider.list_files(OrderedFileProvider.IMAGES)
        self.assertIn(os.path.join(directory, '01-ZIP-Normal.zip'), archives)
        self.assertEqual(images, [])

    def test_a_deleted_file_does_not_empty_the_listing(self) -> None:
        """Sorting by size stats every name, so a file deleted between the
        listing and the sort used to be reported as a permissions problem
        and take every other file in the directory down with it."""
        directory = get_testfile_path('images')
        provider = OrderedFileProvider(directory)
        prefs['sort by'] = constants.SORT_NAME
        expected = provider.list_files()
        prefs['sort by'] = constants.SORT_SIZE
        with mock.patch('os.stat', _stat_failing_on(expected[0])):
            listed = provider.list_files()
        self.assertEqual(sorted(listed), sorted(expected))

    def test_an_unreadable_parent_leaves_the_directory_alone(self) -> None:
        """Walking to a sibling directory lists the parent, which the
        user may not be allowed to read; that used to raise out of the
        menu action."""
        provider = self._provider('b')
        with mock.patch('os.listdir', side_effect=PermissionError(
                13, 'Permission denied', self.root)):
            self.assertFalse(provider.next_directory())
            self.assertFalse(provider.previous_directory())
        self.assertEqual(os.path.basename(provider.get_directory()), 'b')

    def test_sort_order_is_reversed_for_descending(self) -> None:
        directory = get_testfile_path('images')
        provider = OrderedFileProvider(directory)
        prefs['sort by'] = constants.SORT_NAME
        prefs['sort order'] = constants.SORT_ASCENDING
        ascending = provider.list_files()
        prefs['sort order'] = constants.SORT_DESCENDING
        self.assertEqual(provider.list_files(), list(reversed(ascending)))


class AFolderReadWithTheFoldersInItTest(MComixTest):

    """ The "open folder tree as one book" preference: a folder is
    listed with the folders in it, and the walk steps over whole
    trees. """

    def setUp(self) -> None:
        super().setUp()
        self.root = os.path.join(self.tmp_dir, 'shelf')

    def _touch(self, *names: str) -> list[str]:
        """Make an empty file at each of <names>, paths below the shelf
        written with "/", and return their absolute paths."""
        paths = []
        for name in names:
            path = os.path.join(self.root, *name.split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb'):
                pass
            paths.append(path)
        return paths

    def _listed(self, folder: str, mode: int = FileProvider.IMAGES) -> list[str]:
        """What <folder> on the shelf lists, as paths below the shelf
        written with "/"."""
        provider = OrderedFileProvider(os.path.join(self.root, folder))
        return [os.path.relpath(path, self.root).replace(os.sep, '/')
                for path in provider.list_files(mode)]

    def _walk(self, provider: OrderedFileProvider, step) -> list[str]:
        visited = [os.path.relpath(provider.get_directory(), self.root)]
        while step(provider):
            visited.append(os.path.relpath(provider.get_directory(), self.root)
                           .replace(os.sep, '/'))
        return visited

    def test_without_the_preference_a_folder_lists_its_own_files(self) -> None:
        self._touch('Manga/cover.jpg', 'Manga/Vol 1/1.jpg')
        self.assertEqual(['Manga/cover.jpg'], self._listed('Manga'))

    def test_each_folder_comes_before_the_ones_in_it(self) -> None:
        prefs['open folder tree as one book'] = True
        self._touch('Manga/Vol 2/Ch 1/1.jpg', 'Manga/Vol 10/1.jpg',
                    'Manga/Vol 2/2.jpg', 'Manga/Vol 2/1.jpg',
                    'Manga/zz.jpg', 'Manga/Vol 2/Ch 1/2.jpg',
                    'Manga/Vol 1/Ch 2/1.jpg', 'Manga/Vol 1/Ch 1/1.jpg')
        self.assertEqual(
            ['Manga/zz.jpg',
             'Manga/Vol 1/Ch 1/1.jpg', 'Manga/Vol 1/Ch 2/1.jpg',
             'Manga/Vol 2/1.jpg', 'Manga/Vol 2/2.jpg',
             'Manga/Vol 2/Ch 1/1.jpg', 'Manga/Vol 2/Ch 1/2.jpg',
             'Manga/Vol 10/1.jpg'],
            self._listed('Manga'))

    def test_the_tree_ends_two_levels_down(self) -> None:
        prefs['open folder tree as one book'] = True
        self._touch('a/1.jpg', 'a/b/2.jpg', 'a/b/c/3.jpg', 'a/b/c/d/4.jpg')
        self.assertEqual(['a/1.jpg', 'a/b/2.jpg', 'a/b/c/3.jpg'],
                         self._listed('a'))
        self.assertEqual(file_provider.TREE_DEPTH, 2)

    def test_archives_are_listed_as_a_tree_too(self) -> None:
        prefs['open folder tree as one book'] = True
        self._touch('a/2.zip', 'a/1.jpg', 'a/b/1.cbz', 'a/b/1.jpg')
        self.assertEqual(['a/2.zip', 'a/b/1.cbz'],
                         self._listed('a', FileProvider.ARCHIVES))
        self.assertEqual(['a/1.jpg', 'a/b/1.jpg'], self._listed('a'))

    def test_a_descending_order_turns_each_folder_not_the_tree(self) -> None:
        prefs['open folder tree as one book'] = True
        prefs['sort order'] = constants.SORT_DESCENDING
        self._touch('a/1.jpg', 'a/2.jpg', 'a/b/1.jpg', 'a/b/2.jpg',
                    'a/c/1.jpg')
        self.assertEqual(['a/2.jpg', 'a/1.jpg', 'a/b/2.jpg', 'a/b/1.jpg',
                          'a/c/1.jpg'], self._listed('a'))

    def test_a_hidden_folder_is_left_out(self) -> None:
        prefs['open folder tree as one book'] = True
        self._touch('a/1.jpg', 'a/.thumbnails/1.jpg', 'a/b/2.jpg')
        self.assertEqual(['a/1.jpg', 'a/b/2.jpg'], self._listed('a'))

    def test_a_linked_folder_is_not_gone_into(self) -> None:
        prefs['open folder tree as one book'] = True
        self._touch('a/1.jpg', 'elsewhere/2.jpg')
        try:
            os.symlink(os.path.join(self.root, 'elsewhere'),
                       os.path.join(self.root, 'a', 'link'),
                       target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('no symbolic links here')
        self.assertEqual(['a/1.jpg'], self._listed('a'))

    def test_a_folder_that_cannot_be_read_leaves_the_rest_listed(self) -> None:
        prefs['open folder tree as one book'] = True
        self._touch('a/1.jpg', 'a/b/2.jpg', 'a/c/3.jpg')
        locked = os.path.join(self.root, 'a', 'b')
        real_listdir = os.listdir

        def listdir(path):
            if path == locked:
                raise PermissionError(13, 'Permission denied', path)
            return real_listdir(path)

        with mock.patch('os.listdir', listdir):
            with self.assertLogs('mcomix', level='WARNING'):
                self.assertEqual(['a/1.jpg', 'a/c/3.jpg'], self._listed('a'))

    def test_a_folder_named_in_a_list_is_listed_as_a_tree(self) -> None:
        prefs['open folder tree as one book'] = True
        listed = self._touch('a/1.jpg', 'a/b/2.jpg')
        provider = PreDefinedFileProvider(
            [os.path.join(self.root, 'a'), *self._touch('z.jpg')])
        self.assertEqual(listed + [os.path.join(self.root, 'z.jpg')],
                         provider.list_files(FileProvider.IMAGES))

    def test_the_walk_steps_over_whole_trees(self) -> None:
        """Each folder on the shelf is a book with the folders in it, so
        the walk does not open those one by one as well."""
        self._touch('a/a1/1.jpg', 'a/a2/1.jpg', 'b/b1/1.jpg', 'c/1.jpg')
        provider = OrderedFileProvider(os.path.join(self.root, 'a'))
        self.assertEqual(
            ['a', 'a/a1', 'a/a2', 'b', 'b/b1', 'c'],
            self._walk(OrderedFileProvider(os.path.join(self.root, 'a')),
                       OrderedFileProvider.next_directory))
        prefs['open folder tree as one book'] = True
        self.assertEqual(['a', 'b', 'c'], self._walk(
            provider, OrderedFileProvider.next_directory))
        self.assertEqual(['c', 'b', 'a'], self._walk(
            provider, OrderedFileProvider.previous_directory))

    def test_the_walk_leaves_a_folder_it_no_longer_visits(self) -> None:
        """Walked into b/b1 before the preference was turned on, the
        book is left from b, the folder the walk now steps over."""
        self._touch('a/1.jpg', 'b/b1/1.jpg', 'c/1.jpg')
        for step, expected in ((OrderedFileProvider.next_directory, 'c'),
                               (OrderedFileProvider.previous_directory, 'a')):
            prefs['open folder tree as one book'] = False
            provider = OrderedFileProvider(os.path.join(self.root, 'b'))
            self.assertTrue(provider.next_directory())
            self.assertEqual(os.path.join(self.root, 'b', 'b1'),
                             provider.get_directory())
            prefs['open folder tree as one book'] = True
            self.assertTrue(step(provider))
            self.assertEqual(os.path.join(self.root, expected),
                             provider.get_directory())


class SortFilesTest(MComixTest):

    """FileProvider.sort_files() is called on its own by the file chooser,
    which has no guard of its own to fall back on."""

    def test_sorting_survives_a_deleted_file(self) -> None:
        directory = get_testfile_path('images')
        files = [os.path.join(directory, name) for name in os.listdir(directory)]
        doomed = files[0]
        expected = set(files)
        prefs['sort by'] = constants.SORT_LAST_MODIFIED
        with mock.patch('os.stat', _stat_failing_on(doomed)):
            FileProvider.sort_files(files)
        self.assertEqual(set(files), expected)


    def test_files_a_key_cannot_tell_apart_are_sorted_by_name(self) -> None:
        """Pages copied in one go share their modification time and
        often their size, and were left in the order the directory
        listed them, which is not the same from one copy to the next."""
        directory = os.path.join(self.tmp_dir, 'book')
        os.makedirs(directory)
        files = []
        for name in ('3.png', '10.png', '1.png', '2.png'):
            path = os.path.join(directory, name)
            with open(path, 'wb') as page:
                page.write(b'x' * 10)
            os.utime(path, (1_000_000_000, 1_000_000_000))
            files.append(path)
        expected = [os.path.join(directory, name)
                    for name in ('1.png', '2.png', '3.png', '10.png')]
        for key in (constants.SORT_LAST_MODIFIED, constants.SORT_SIZE):
            for listed in itertools.permutations(files):
                with self.subTest(key=key, listed=listed):
                    prefs['sort by'] = key
                    prefs['sort order'] = constants.SORT_ASCENDING
                    ordered = list(listed)
                    FileProvider.sort_files(ordered)
                    self.assertEqual(expected, ordered)

class ExtensionlessPictureTest(MComixTest):

    """A picture saved without an extension is a page of its folder
    (upstream patch 29).  Only a name with no extension is opened to
    see what it holds: one with an extension is decided by it."""

    def setUp(self) -> None:
        super().setUp()
        self.folder = os.path.join(self.tmp_dir, 'book')
        os.mkdir(self.folder)
        red = get_testfile_path('images', 'red.png')
        for name in ('page2', 'page1.png', 'page3'):
            shutil.copyfile(red, os.path.join(self.folder, name))
        with open(os.path.join(self.folder, 'README'), 'w') as text:
            text.write('Not a picture.\n')
        # A picture under an extension MComix does not read stays out:
        # the name decides.
        shutil.copyfile(red, os.path.join(self.folder, 'notes.txt'))
        os.mkdir(os.path.join(self.folder, 'extras'))

    def _listed(self, provider):
        return [os.path.basename(path) for path in
                provider.list_files(FileProvider.IMAGES)]

    def test_the_folder_lists_them_in_order_with_the_others(self) -> None:
        provider = OrderedFileProvider(os.path.join(self.folder, 'page2'))
        self.assertEqual(['page1.png', 'page2', 'page3'],
                         self._listed(provider))

    def test_a_list_of_files_takes_them_as_pictures(self) -> None:
        provider = PreDefinedFileProvider(
            [os.path.join(self.folder, name)
             for name in ('page3', 'README', 'notes.txt')])
        self.assertEqual(['page3'], self._listed(provider))


class PreDefinedFileProviderTest(MComixTest):

    """The provider for a list of files, as the command line hands one
    over.  The file handler shows one kind of file at a time, so each
    kind is listed on its own; what it must never get is a listing with
    both in it."""

    def test_each_kind_is_listed_under_its_own_mode(self) -> None:
        archive = get_testfile_path('archives', '01-ZIP-Normal.zip')
        image = get_testfile_path('images', 'red.png')
        provider = PreDefinedFileProvider([archive, image])
        self.assertEqual([image],
                         provider.list_files(PreDefinedFileProvider.IMAGES))
        self.assertEqual([archive],
                         provider.list_files(PreDefinedFileProvider.ARCHIVES))

    def test_a_directory_gives_up_its_archives_as_well(self) -> None:
        """A directory in the list was listed for images alone, so the
        archives in it were in no listing at all: asking the provider
        for archives answered with the images."""
        archives = get_testfile_path('archives')
        images = get_testfile_path('images')
        provider = PreDefinedFileProvider([archives, images])
        self.assertIn(os.path.join(archives, '01-ZIP-Normal.zip'),
                      provider.list_files(PreDefinedFileProvider.ARCHIVES))
        self.assertIn(os.path.join(images, 'red.png'),
                      provider.list_files(PreDefinedFileProvider.IMAGES))

    def test_neither_listing_holds_the_other_kind(self) -> None:
        archives = get_testfile_path('archives')
        images = get_testfile_path('images')
        provider = PreDefinedFileProvider([archives, images])
        for path in provider.list_files(PreDefinedFileProvider.ARCHIVES):
            self.assertNotIn(images, path)
        for path in provider.list_files(PreDefinedFileProvider.IMAGES):
            self.assertNotIn(archives, path)

    def test_the_directory_is_the_one_the_files_are_in(self) -> None:
        """It answered with the working directory, which is where
        MComix was started rather than where the book is."""
        images = get_testfile_path('images')
        provider = PreDefinedFileProvider(
            [os.path.join(images, 'red.png')])
        self.assertEqual(images, provider.get_directory())

    def test_an_archive_alone_names_its_own_directory(self) -> None:
        archives = get_testfile_path('archives')
        provider = PreDefinedFileProvider(
            [os.path.join(archives, '01-ZIP-Normal.zip')])
        self.assertEqual(archives, provider.get_directory())

    def test_a_list_with_nothing_to_show_keeps_the_fallback(self) -> None:
        """There is no file to take a directory from."""
        provider = PreDefinedFileProvider(
            [os.path.join(self.tmp_dir, 'not-a-book.txt')])
        self.assertEqual([], provider.list_files())
        self.assertEqual(os.path.abspath(os.getcwd()),
                         provider.get_directory())

# vim: expandtab:sw=4:ts=4


class GetFileProviderTest(MComixTest):

    """Which provider a start is given, from the names it was handed."""

    def setUp(self) -> None:
        super().setUp()
        self.book = os.path.join(self.tmp_dir, 'book.cbz')
        shutil.copy(get_testfile_path('archives', '01-ZIP-Normal.zip'),
                    self.book)

    def test_one_name_is_walked_among_its_neighbours(self) -> None:
        provider = file_provider.get_file_provider([self.book])
        self.assertIsInstance(provider, OrderedFileProvider)

    def test_one_name_that_is_not_there_gives_none(self) -> None:
        self.assertIsNone(file_provider.get_file_provider(
            [os.path.join(self.tmp_dir, 'gone.cbz')]))

    def test_several_names_are_those_and_no_others(self) -> None:
        provider = file_provider.get_file_provider([self.book, self.book])
        self.assertIsInstance(provider, PreDefinedFileProvider)

    def test_no_names_reopen_the_last_file_where_asked_to(self) -> None:
        prefs['auto load last file'] = True
        prefs['path to last file'] = self.book
        provider = file_provider.get_file_provider([])
        self.assertIsInstance(provider, OrderedFileProvider)
        self.assertEqual(self.tmp_dir, provider.get_directory())

    def test_no_names_open_nothing_where_not_asked_to(self) -> None:
        prefs['auto load last file'] = False
        prefs['path to last file'] = self.book
        self.assertIsNone(file_provider.get_file_provider([]))

    def test_no_names_open_nothing_when_the_last_file_is_gone(self) -> None:
        prefs['auto load last file'] = True
        prefs['path to last file'] = os.path.join(self.tmp_dir, 'gone.cbz')
        self.assertIsNone(file_provider.get_file_provider([]))


class UnreadableDirectoryTest(MComixTest):

    def test_a_directory_that_cannot_be_listed_lists_nothing(self) -> None:
        folder = os.path.join(self.tmp_dir, 'locked')
        os.mkdir(folder)
        shutil.copy(get_testfile_path('images', 'blue.png'),
                    os.path.join(folder, 'blue.png'))
        provider = OrderedFileProvider(os.path.join(folder, 'blue.png'))
        with mock.patch('os.listdir', side_effect=PermissionError(13, 'No')):
            with self.assertLogs('mcomix', level='WARNING'):
                self.assertEqual([], provider.list_files())
