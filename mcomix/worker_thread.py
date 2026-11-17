""" Worker thread class. """


import threading
import time
import traceback
from collections.abc import Callable, Iterable
from types import TracebackType
from typing import Generic, TypeVar

from mcomix import log
from mcomix.i18n import _

#: A work order.  Each pool carries orders of one kind, whatever the
#: function that processes them takes.
Order = TypeVar('Order')

#: How many orders a pool works on at once until one of them proves
#: slow, and again once it has nothing left to do.
FIRST_AT_ONCE = 2
#: How long, in seconds, an order takes that opens the pool up to all
#: its threads.
SLOW_ORDER = 0.005


class WorkerThread(Generic[Order]):

    def __init__(self, process_order: Callable[[Order], object],
                 name: str | None = None, max_threads: int = 1,
                 sort_orders: bool = False, unique_orders: bool = False,
                 narrow_first: bool = False) -> None:
        """Create a new pool of worker threads.

        Optional <name> will be added to spawned thread names.
        <process_order> will be called to process each work order.
        At most <max_threads> will be started for processing.
        If <sort_orders> is True, the orders queue will be sorted
        after each addition. If <unique_orders> is True, duplicate
        orders will not be added to the queue.

        With <narrow_first>, only FIRST_AT_ONCE orders are worked on at
        once until one takes SLOW_ORDER or longer, and again once the
        queue is empty and no order is in hand.  An order that costs a
        fraction of a millisecond, a cover the library has stored, gains
        nothing from more threads, and every thread more running Python
        takes the interpreter lock from the main thread: 400 such covers
        came last at 147 to 313 ms with 24 at once against 110 to 117
        with one, and the cover grid took up to four times as long to
        settle after a jump.  An order that reads a book gains from all
        of them: 400 covers read from their books took 1.5 s with 8, 7 s
        with one.  Not for a pool whose quick orders still gain from
        threads: a ZIP's pages unpacked in 0.19 s instead of 0.08 with 8
        threads so, each well under SLOW_ORDER. """
        self._name = name
        self._process_order = process_order
        self._max_threads = max_threads
        self._sort_orders = sort_orders
        self._unique_orders = unique_orders
        self._stop = False
        #: Set for good by retire(): the pool takes no more orders.
        self._retired = False
        self._threads: list[threading.Thread] = []
        # Queue of orders waiting for processing.
        self._orders_queue: list[Order] = []
        # Track orders, when they have to be unique.
        self._orders_set: set[object] = set()
        self._condition = threading.Condition()
        #: How many orders may be worked on at once while none has
        #: proved slow, how many now, and how many are.
        self._first_at_once = (min(FIRST_AT_ONCE, max_threads)
                               if narrow_first else max_threads)
        self._at_once = self._first_at_once
        self._in_hand = 0

    def __enter__(self) -> bool:
        return self._condition.__enter__()

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc_value: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self._condition.__exit__(exc_type, exc_value, traceback)

    def _start(self, nb_threads: int = 1) -> None:
        for n in range(nb_threads):
            if len(self._threads) == self._max_threads:
                break
            thread = threading.Thread(target=self._run)
            if self._name is not None:
                thread.name += '-' + self._name
            thread.daemon = False
            thread.start()
            self._threads.append(thread)

    def _order_uid(self, order: Order) -> object:
        if isinstance(order, tuple) or isinstance(order, list):
            return order[0]
        return order

    def _run(self) -> None:
        order_uid: object = None
        while True:
            with self._condition:
                if order_uid is not None:
                    # Gone already where retire() or a stop() after it
                    # emptied the set while this order was processed.
                    self._orders_set.discard(order_uid)
                while not self._stop and (
                        not self._orders_queue
                        or self._in_hand >= self._at_once):
                    self._condition.wait()
                if self._stop:
                    return
                order = self._orders_queue.pop(0)
                self._in_hand += 1
                if self._unique_orders:
                    order_uid = self._order_uid(order)
            begun = time.perf_counter()
            try:
                self._process_order(order)
            except Exception as e:
                log.error(_('! Worker thread processing %(function)r failed: %(error)s'),
                          {'function': self._process_order, 'error': e})
                log.debug('Traceback:\n%s', traceback.format_exc())
            slow = time.perf_counter() - begun >= SLOW_ORDER
            with self._condition:
                self._in_hand -= 1
                if slow and self._at_once < self._max_threads:
                    self._at_once = self._max_threads
                    self._condition.notify_all()
                elif not self._orders_queue and not self._in_hand:
                    self._at_once = self._first_at_once
                elif self._orders_queue:
                    self._condition.notify()

    def must_stop(self) -> bool:
        """Return true if we've been asked to stop processing.

        Can be used by the processing function to check if it must abort early.
        """
        return self._stop

    def clear_orders(self) -> list[Order]:
        """Clear the current orders queue, and return what was waiting
        in it, for an owner that wants some of it done after all."""
        with self._condition:
            if self._unique_orders:
                # We can't just clear the set, as some orders
                # can be in the process of being processed.
                for order in self._orders_queue:
                    order_uid = self._order_uid(order)
                    self._orders_set.remove(order_uid)
            waiting, self._orders_queue = self._orders_queue, []
            return waiting

    def append_order(self, order: Order) -> None:
        """Append work order to the thread orders queue."""
        with self._condition:
            if self._retired:
                return
            if self._unique_orders:
                order_uid = self._order_uid(order)
                if order_uid in self._orders_set:
                    # Duplicate order.
                    return
                self._orders_set.add(order_uid)
            self._orders_queue.append(order)
            if self._sort_orders:
                self._orders_queue.sort()
            self._condition.notify_all()
            self._start()

    def extend_orders(self, orders_list: Iterable[Order]) -> None:
        """Append work orders to the thread orders queue."""
        with self._condition:
            if self._retired:
                return
            orders_list = list(orders_list)
            if self._unique_orders:
                nb_added = 0
                for order in orders_list:
                    order_uid = self._order_uid(order)
                    if order_uid in self._orders_set:
                        # Duplicate order.
                        continue
                    self._orders_set.add(order_uid)
                    self._orders_queue.append(order)
                    nb_added += 1
            else:
                self._orders_queue.extend(orders_list)
                nb_added = len(orders_list)
            if nb_added == 0:
                return
            if self._sort_orders:
                self._orders_queue.sort()
            self._condition.notify_all()
            self._start(nb_threads=nb_added)

    def stop(self) -> None:
        """Stop the worker threads and flush the orders queue."""
        self._stop = True
        with self._condition:
            self._condition.notify_all()
        for thread in self._threads:
            thread.join()
        self._threads = []
        self._stop = self._retired
        self._orders_queue = []
        self._at_once = self._first_at_once
        if self._unique_orders:
            self._orders_set.clear()

    def retire(self) -> None:
        """Stop the worker threads for good, without waiting for them.

        A thread busy with an order finishes it and ends; the orders
        waiting are dropped, and later ones are refused. For an owner
        that goes away while what its orders use outlives it, so that
        nothing has to wait for a slow order to end. stop() joins, and
        resets the shared stop flag after the join, so a pool that is to
        be used again cannot be let go of like this.
        """
        with self._condition:
            self._retired = True
            self._stop = True
            self._orders_queue = []
            self._orders_set.clear()
            self._condition.notify_all()
        self._threads = []

# vim: expandtab:sw=4:ts=4
