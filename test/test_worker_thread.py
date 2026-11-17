"""How many orders a pool of worker threads works on at once."""

import threading
import time
import unittest
import unittest.mock

from mcomix import worker_thread
from mcomix.worker_thread import WorkerThread

THREADS = 8


class OrdersAtOnceTest(unittest.TestCase):

    def setUp(self):
        self._lock = threading.Lock()
        self._in_hand = 0
        self._done = 0
        #: Orders at or above this number wait for it before they end.
        self.go_on = threading.Event()
        self.addCleanup(self.go_on.set)
        self._waits_from = 0

    def _order(self, number):
        with self._lock:
            self._in_hand += 1
        if number >= self._waits_from:
            self.go_on.wait(10)
        with self._lock:
            self._in_hand -= 1
            self._done += 1

    def _pool(self, narrow_first):
        pool = WorkerThread(self._order, max_threads=THREADS,
                            narrow_first=narrow_first)
        self.addCleanup(pool.stop)
        self.addCleanup(self.go_on.set)
        return pool

    def _settled_in_hand(self, at_least=0):
        """How many orders are in hand once that stops changing."""
        end = time.monotonic() + 5
        last, since = -1, time.monotonic()
        while time.monotonic() < end:
            with self._lock:
                now = self._in_hand
            if now != last:
                last, since = now, time.monotonic()
            elif now >= at_least and time.monotonic() - since > 0.2:
                break
            time.sleep(0.01)
        return last

    def _wait_done(self, count):
        end = time.monotonic() + 5
        while time.monotonic() < end and self._done < count:
            time.sleep(0.01)
        self.assertEqual(count, self._done)

    def test_quick_orders_are_worked_on_two_at_once(self):
        pool = self._pool(narrow_first=True)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            pool.extend_orders(range(20))
            self.assertEqual(worker_thread.FIRST_AT_ONCE,
                             self._settled_in_hand())
            self.go_on.set()
            self._wait_done(20)

    def test_one_slow_order_puts_every_thread_to_work(self):
        pool = self._pool(narrow_first=True)
        self._waits_from = 2
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 0):
            pool.extend_orders(range(20))
            self.assertEqual(THREADS, self._settled_in_hand(THREADS))
            self.go_on.set()
            self._wait_done(20)

    def test_a_pool_left_with_nothing_to_do_starts_narrow_again(self):
        pool = self._pool(narrow_first=True)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 0):
            pool.extend_orders(range(10))
            self.go_on.set()
            self._wait_done(10)
        self.go_on.clear()
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            pool.extend_orders(range(10, 30))
            self.assertEqual(worker_thread.FIRST_AT_ONCE,
                             self._settled_in_hand())
            self.go_on.set()
            self._wait_done(30)

    def test_orders_one_at_a_time_are_worked_on_two_at_once(self):
        """What a view does as it binds its cells: one order each."""
        pool = self._pool(narrow_first=True)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            for number in range(20):
                pool.append_order(number)
            self.assertEqual(worker_thread.FIRST_AT_ONCE,
                             self._settled_in_hand())
            self.go_on.set()
            self._wait_done(20)

    def test_a_pool_not_narrow_puts_every_thread_to_work_at_once(self):
        pool = self._pool(narrow_first=False)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            pool.extend_orders(range(20))
            self.assertEqual(THREADS, self._settled_in_hand(THREADS))
            self.go_on.set()
            self._wait_done(20)

    def test_a_pool_stopped_starts_narrow_again(self):
        pool = self._pool(narrow_first=True)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 0):
            self._waits_from = 2
            pool.extend_orders(range(20))
            self.assertEqual(THREADS, self._settled_in_hand(THREADS))
            self.go_on.set()
            pool.stop()
        self.go_on.clear()
        self._waits_from = 0
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            pool.extend_orders(range(20))
            self.assertEqual(worker_thread.FIRST_AT_ONCE,
                             self._settled_in_hand())


class ThumbnailViewPoolTest(unittest.TestCase):

    def test_the_thumbnail_views_start_narrow(self):
        """Covers and page thumbnails the disk or memory holds cost a
        fraction of a millisecond each."""
        import ast
        import inspect
        from mcomix import thumbnail_list
        tree = ast.parse(inspect.getsource(thumbnail_list))
        pools = [call for call in ast.walk(tree)
                 if isinstance(call, ast.Call)
                 and getattr(call.func, 'id', None) == 'WorkerThread']
        self.assertEqual(1, len(pools))
        keywords = {keyword.arg: keyword.value for keyword in pools[0].keywords}
        self.assertIs(True, ast.literal_eval(keywords['narrow_first']))
