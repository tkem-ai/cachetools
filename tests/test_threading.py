import unittest
from threading import Barrier, Condition, Event, Lock, Thread

import cachetools.func
from cachetools import LRUCache, cached, cachedmethod


class WaitCondition(Condition):
    def __init__(self, lock=None):
        super().__init__(lock)
        self.waiting = Event()

    def wait(self, timeout=None):
        self.waiting.set()
        return super().wait(timeout)


class ThreadingTest(unittest.TestCase):
    NTHREADS = 10

    TIMEOUT = 10

    def test_cached_lock(self):
        for info in (False, True):
            with self.subTest(info=info):
                barrier = Barrier(self.NTHREADS, timeout=self.TIMEOUT)
                cache = LRUCache(1)

                @cached(cache, lock=Lock(), info=info)
                def func(barrier=barrier):
                    result = object()
                    barrier.wait()
                    return result

                self.run_lock_test(func, cache, info)

    def test_cachedmethod_lock(self):
        for info in (False, True):
            with self.subTest(info=info):
                barrier = Barrier(self.NTHREADS, timeout=self.TIMEOUT)
                cache = LRUCache(1)
                lock = Lock()

                class Cached:
                    @cachedmethod(lambda _: cache, lock=lambda _: lock, info=info)
                    def method(self, barrier=barrier):
                        result = object()
                        barrier.wait()
                        return result

                self.run_lock_test(Cached().method, cache, info)

    def test_cached_cond(self):
        for info in (False, True):
            with self.subTest(info=info):
                cache = LRUCache(1)
                cond = WaitCondition()
                started = Event()
                release = Event()
                calls = []

                @cached(cache, condition=cond, info=info)
                def func(calls=calls, started=started, release=release):
                    calls.append(None)
                    started.set()
                    release.wait(self.TIMEOUT)
                    return object()

                self.run_cond_wait_test(func, cond, started, release, calls)

    def test_cachedmethod_cond(self):
        for info in (False, True):
            with self.subTest(info=info):
                cache = LRUCache(1)
                cond = WaitCondition()
                started = Event()
                release = Event()
                calls = []

                class Cached:
                    @cachedmethod(lambda _: cache, condition=lambda _: cond, info=info)
                    def method(
                        self,
                        calls=calls,
                        started=started,
                        release=release,
                        timeout=self.TIMEOUT,
                    ):
                        calls.append(None)
                        started.set()
                        release.wait(timeout)
                        return object()

                func = Cached().method
                self.run_cond_wait_test(func, cond, started, release, calls)

    def test_cached_lock_cond(self):
        for info in (False, True):
            with self.subTest(info=info):
                cache = LRUCache(1)
                lock = Lock()
                cond = WaitCondition(lock)
                started = Event()
                release = Event()
                calls = []

                @cached(cache, lock=lock, condition=cond, info=info)
                def func(calls=calls, started=started, release=release):
                    calls.append(None)
                    started.set()
                    release.wait(self.TIMEOUT)
                    return object()

                self.run_cond_wait_test(func, cond, started, release, calls)

    def test_cachedmethod_lock_cond(self):
        for info in (False, True):
            with self.subTest(info=info):
                cache = LRUCache(1)
                lock = Lock()
                cond = WaitCondition(lock)
                started = Event()
                release = Event()
                calls = []

                class Cached:
                    @cachedmethod(
                        lambda _: cache,
                        lock=lambda _: lock,
                        condition=lambda _: cond,
                        info=info,
                    )
                    def method(
                        self,
                        calls=calls,
                        started=started,
                        release=release,
                        timeout=self.TIMEOUT,
                    ):
                        calls.append(None)
                        started.set()
                        release.wait(timeout)
                        return object()

                func = Cached().method
                self.run_cond_wait_test(func, cond, started, release, calls)

    def test_cached_unrelated_lock_cond(self):
        # a condition variable not created with the lock fails on
        # the first cache miss, even without concurrent calls
        for info in (False, True):
            with self.subTest(info=info):

                @cached(LRUCache(1), lock=Lock(), condition=Condition(), info=info)
                def func():
                    return object()

                with self.assertRaises(RuntimeError):
                    func()

    def test_cachedmethod_unrelated_lock_cond(self):
        for info in (False, True):
            with self.subTest(info=info):
                cache = LRUCache(1)
                lock = Lock()
                cond = Condition()

                class Cached:
                    @cachedmethod(
                        lambda _: cache,
                        lock=lambda _: lock,
                        condition=lambda _: cond,
                        info=info,
                    )
                    def method(self):
                        return object()

                with self.assertRaises(RuntimeError):
                    Cached().method()

    def test_cached_cond_recursion(self):
        # a function calling itself with the same arguments, e.g. to
        # retry, must not wait for its own pending key
        for info in (False, True):
            for lock in (None, Lock()):
                with self.subTest(info=info, lock=lock):
                    cond = Condition(lock)
                    calls = []

                    @cached(LRUCache(1), lock=lock, condition=cond, info=info)
                    def func(calls=calls):
                        calls.append(None)
                        return func() if len(calls) < 3 else object()

                    self.run_cond_recursion_test(func, calls, info)

    def test_cachedmethod_cond_recursion(self):
        for info in (False, True):
            with self.subTest(info=info):
                cache = LRUCache(1)
                cond = Condition()
                calls = []

                class Cached:
                    @cachedmethod(lambda _: cache, condition=lambda _: cond, info=info)
                    def method(self, calls=calls):
                        calls.append(None)
                        return self.method() if len(calls) < 3 else object()

                self.run_cond_recursion_test(Cached().method, calls, info)

    def test_func_recursion(self):
        calls = []

        @cachetools.func.lru_cache
        def func(calls=calls):
            calls.append(None)
            return func() if len(calls) < 3 else object()

        self.run_cond_recursion_test(func, calls, True)

    def run_cond_recursion_test(self, func, calls, info):
        results = []

        def run():
            results.append(func())
            results.append(func())

        thread = Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=self.TIMEOUT)
        self.assertFalse(thread.is_alive())
        # recursive calls are not cached, only the outermost one is
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])
        if info:
            cache_info = func.cache_info()
            self.assertEqual(cache_info.hits, 1)
            self.assertEqual(cache_info.misses, 3)
            self.assertEqual(cache_info.currsize, 1)

    def run_cond_wait_test(self, func, cond, started, release, calls):
        results = [None] * 2

        def run(index):
            results[index] = func()

        first = Thread(target=run, args=[0])
        first.start()
        self.assertTrue(started.wait(self.TIMEOUT))
        second = Thread(target=run, args=[1])
        second.start()
        # second caller must block on the pending key
        self.assertTrue(cond.waiting.wait(self.TIMEOUT))
        release.set()
        for thread in (first, second):
            thread.join(timeout=self.TIMEOUT)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(results[0])
        self.assertIs(results[0], results[1])

    def run_lock_test(self, func, cache, info):
        self.run_threading_test(func, cache)

        if info:
            cache_info = func.cache_info()
            self.assertEqual(cache_info.hits + cache_info.misses, self.NTHREADS)
            self.assertGreaterEqual(cache_info.misses, 1)

    def run_threading_test(self, func, cache):
        results = [None] * self.NTHREADS

        def run(index):
            results[index] = func()

        threads = [Thread(target=run, args=[i]) for i in range(self.NTHREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=self.TIMEOUT)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(cache), 1)

        # multiple threads may compute the value, but the first one
        # should always win and all concurrent invocations should
        # return the same result
        cached_result = next(iter(cache.values()))
        for result in results:
            self.assertIs(result, cached_result)
