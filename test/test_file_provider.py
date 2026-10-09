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
