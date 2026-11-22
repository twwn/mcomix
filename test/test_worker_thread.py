"""How many orders a pool of worker threads works on at once."""

import ast
import inspect
import threading
import time
import unittest
import unittest.mock

from mcomix import worker_thread
from mcomix import thumbnail_list
from mcomix.worker_thread import WorkerThread

THREADS = 8


def wait_until(condition, seconds=5):
    """Whether <condition> came true within <seconds>, asked every
    millisecond; no main loop turns here."""
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.001)
    return True


class OrdersAtOnceTest(unittest.TestCase):

    def setUp(self):
        self._lock = threading.Lock()
        self._in_hand = 0
        self._done = 0
        #: Orders at or above this number wait for it before they end.
        self.go_on = threading.Event()
        self.addCleanup(self.go_on.set)
        self._waits_from = 0
        #: Threads waiting for go_on, and threads waiting in the pool.
        self._held = 0
        self._parked = 0

    def _order(self, number):
        with self._lock:
            self._in_hand += 1
        if number >= self._waits_from:
            with self._lock:
                self._held += 1
            self.go_on.wait(10)
            with self._lock:
                self._held -= 1
        with self._lock:
            self._in_hand -= 1
            self._done += 1

    def _pool(self, narrow_first):
        pool = WorkerThread(self._order, max_threads=THREADS,
                            narrow_first=narrow_first)
        self.addCleanup(pool.stop)
        self.addCleanup(self.go_on.set)
        wait = pool._condition.wait

        def parked(*args, **kwargs):
            # Called, and back, with the pool's lock held.
            self._parked += 1
            try:
                return wait(*args, **kwargs)
            finally:
                self._parked -= 1
        pool._condition.wait = parked
        return pool

    def _settled_in_hand(self, pool):
        """How many orders are in hand once every thread of <pool> waits:
        in an order for go_on, or in the pool where it may not take an
        order.  Nothing moves after that until the test moves it, so no
        stretch of quiet has to be waited out to say no more will start.
        """
        def settled():
            with pool._condition:
                held_back = (not pool._orders_queue
                             or pool._in_hand >= pool._at_once)
                with self._lock:
                    return ((held_back or not self._parked)
                            and self._held + self._parked
                            == len(pool._threads))
        self.assertTrue(wait_until(settled), 'the pool never settled')
        with self._lock:
            return self._in_hand

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
                             self._settled_in_hand(pool))
            self.go_on.set()
            self._wait_done(20)

    def test_one_slow_order_puts_every_thread_to_work(self):
        pool = self._pool(narrow_first=True)
        self._waits_from = 2
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 0):
            pool.extend_orders(range(20))
            self.assertEqual(THREADS, self._settled_in_hand(pool))
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
                             self._settled_in_hand(pool))
            self.go_on.set()
            self._wait_done(30)

    def test_a_pool_starts_only_the_threads_it_works_with(self):
        """It started a thread per order added, up to all of them, to
        wait while two worked; and woke every one at each order."""
        pool = self._pool(narrow_first=True)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            pool.extend_orders(range(10))
            for number in range(10, 20):
                pool.append_order(number)
            self._settled_in_hand(pool)
            self.assertEqual(worker_thread.FIRST_AT_ONCE, len(pool._threads))
            self.go_on.set()
            self._wait_done(20)

    def test_orders_one_at_a_time_are_worked_on_two_at_once(self):
        """What a view does as it binds its cells: one order each."""
        pool = self._pool(narrow_first=True)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            for number in range(20):
                pool.append_order(number)
            self.assertEqual(worker_thread.FIRST_AT_ONCE,
                             self._settled_in_hand(pool))
            self.go_on.set()
            self._wait_done(20)

    def test_a_pool_not_narrow_puts_every_thread_to_work_at_once(self):
        pool = self._pool(narrow_first=False)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            pool.extend_orders(range(20))
            self.assertEqual(THREADS, self._settled_in_hand(pool))
            self.go_on.set()
            self._wait_done(20)

    def test_a_pool_stopped_starts_narrow_again(self):
        pool = self._pool(narrow_first=True)
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 0):
            self._waits_from = 2
            pool.extend_orders(range(20))
            self.assertEqual(THREADS, self._settled_in_hand(pool))
            self.go_on.set()
            pool.stop()
        self.go_on.clear()
        self._waits_from = 0
        with unittest.mock.patch.object(worker_thread, 'SLOW_ORDER', 60):
            pool.extend_orders(range(20))
            self.assertEqual(worker_thread.FIRST_AT_ONCE,
                             self._settled_in_hand(pool))


class ThumbnailViewPoolTest(unittest.TestCase):

    def test_the_thumbnail_views_start_narrow(self):
        """Covers and page thumbnails the disk or memory holds cost a
        fraction of a millisecond each."""
        tree = ast.parse(inspect.getsource(thumbnail_list))
        pools = [call for call in ast.walk(tree)
                 if isinstance(call, ast.Call)
                 and getattr(call.func, 'id', None) == 'WorkerThread']
        self.assertEqual(1, len(pools))
        keywords = {keyword.arg: keyword.value for keyword in pools[0].keywords}
        self.assertIs(True, ast.literal_eval(keywords['narrow_first']))
