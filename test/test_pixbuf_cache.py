import threading
import unittest

from mcomix.library.pixbuf_cache import _PixbufCache


class PixbufCacheTest(unittest.TestCase):

    def test_stores_and_returns_entries(self) -> None:
        cache = _PixbufCache(3)
        cache.add('a', 1)
        self.assertEqual(cache.get('a'), 1)
        self.assertIsNone(cache.get('b'))

    def test_never_grows_past_its_size(self) -> None:
        cache = _PixbufCache(3)
        for n in range(10):
            cache.add(n, n)
        self.assertEqual(len(cache._cache), 3)

    def test_evicts_the_least_recently_used_entry(self) -> None:
        cache = _PixbufCache(3)
        for name in 'abc':
            cache.add(name, name)
        # Touching 'a' makes 'b' the oldest, so 'b' goes when 'd' arrives.
        self.assertEqual(cache.get('a'), 'a')
        cache.add('d', 'd')
        self.assertIsNone(cache.get('b'))
        self.assertEqual(cache.get('a'), 'a')
        self.assertEqual(cache.get('c'), 'c')
        self.assertEqual(cache.get('d'), 'd')

    def test_invalidate_removes_only_that_entry(self) -> None:
        cache = _PixbufCache(3)
        cache.add('a', 1)
        cache.add('b', 2)
        cache.invalidate('a')
        cache.invalidate('missing')
        self.assertIsNone(cache.get('a'))
        self.assertEqual(cache.get('b'), 2)

    def test_invalidate_all_empties_the_cache(self) -> None:
        cache = _PixbufCache(3)
        cache.add('a', 1)
        cache.invalidate_all()
        self.assertIsNone(cache.get('a'))

    def test_concurrent_use_keeps_the_cache_consistent(self) -> None:
        # Covers are generated on several worker threads at once.
        cache = _PixbufCache(8)
        errors = []

        def hammer(offset):
            try:
                for n in range(400):
                    key = (n + offset) % 32
                    if cache.get(key) is None:
                        cache.add(key, key)
                    cache.invalidate((key + 1) % 32)
            except Exception as error:  # pragma: no cover - only on failure
                errors.append(error)

        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertLessEqual(len(cache._cache), 8)

# vim: expandtab:sw=4:ts=4
