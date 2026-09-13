import os
import shutil
import tempfile

from . import MComixTest, get_testfile_path

from mcomix import constants
from mcomix.file_provider import OrderedFileProvider, PreDefinedFileProvider
from mcomix.preferences import prefs


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

    def test_sort_order_is_reversed_for_descending(self) -> None:
        directory = get_testfile_path('images')
        provider = OrderedFileProvider(directory)
        prefs['sort by'] = constants.SORT_NAME
        prefs['sort order'] = constants.SORT_ASCENDING
        ascending = provider.list_files()
        prefs['sort order'] = constants.SORT_DESCENDING
        self.assertEqual(provider.list_files(), list(reversed(ascending)))


class PreDefinedFileProviderTest(MComixTest):

    def test_keeps_only_files_of_the_first_kind(self) -> None:
        archive = get_testfile_path('archives', '01-ZIP-Normal.zip')
        image = get_testfile_path('images', 'red.png')
        provider = PreDefinedFileProvider([archive, image])
        self.assertEqual(provider.list_files(), [archive])

# vim: expandtab:sw=4:ts=4
