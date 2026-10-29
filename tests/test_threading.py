import unittest
from threading import Barrier, Condition, Event, Lock, Thread

from cachetools import LRUCache, cached, cachedmethod


class WaitCondition(Condition):
    def __init__(self):
        super().__init__()
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

    def test_cachedmethod_cond_shared(self):
        # instances sharing a cache and a condition coordinate pending keys
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

                first, second = Cached().method, Cached().method
                self.run_cond_wait_test(first, cond, started, release, calls, second)

    def test_cachedmethod_cond_separate_caches(self):
        # instances sharing only a condition do not wait for each other,
        # and a method may call another method sharing its condition
        for info in (False, True):
            with self.subTest(info=info):
                cond = Condition()
                started = Event()
                release = Event()

                class Cached:
                    def __init__(self, block):
                        self.block = block
                        self.cache = LRUCache(2)
                        self.other = LRUCache(2)

                    @cachedmethod(
                        lambda s: s.cache, condition=lambda _: cond, info=info
                    )
                    def method(
                        self, started=started, release=release, timeout=self.TIMEOUT
                    ):
                        if self.block:
                            started.set()
                            release.wait(timeout)
                        return object()

                    @cachedmethod(
                        lambda s: s.other, condition=lambda _: cond, info=info
                    )
                    def nested(self):
                        return self.method()

                blocked, free = Cached(True), Cached(False)
                thread = Thread(target=blocked.method)
                thread.start()
                self.assertTrue(started.wait(self.TIMEOUT))
                # the key pending for another instance's cache must not block
                self.assertIsNotNone(free.nested())
                self.assertIn(free.method.cache_key(), free.method.cache)
                self.assertIn(free.nested.cache_key(), free.nested.cache)
                release.set()
                thread.join(timeout=self.TIMEOUT)
                self.assertFalse(thread.is_alive())

    def test_cachedmethod_cond_other_key(self):
        # a different key pending on the same cache does not block
        for info in (False, True):
            with self.subTest(info=info):
                cond = Condition()
                started = Event()
                release = Event()

                class Cached:
                    def __init__(self):
                        self.cache = LRUCache(2)

                    @cachedmethod(
                        lambda s: s.cache, condition=lambda _: cond, info=info
                    )
                    def method(
                        self,
                        value,
                        started=started,
                        release=release,
                        timeout=self.TIMEOUT,
                    ):
                        if value == 1:
                            started.set()
                            release.wait(timeout)
                        return value

                cached = Cached()
                thread = Thread(target=cached.method, args=[1])
                thread.start()
                self.assertTrue(started.wait(self.TIMEOUT))
                self.assertEqual(cached.method(2), 2)
                self.assertEqual(cached.method(2), 2)
                release.set()
                thread.join(timeout=self.TIMEOUT)
                self.assertFalse(thread.is_alive())
                self.assertEqual(cached.method(1), 1)
                self.assertEqual(len(cached.cache), 2)

    def run_cond_wait_test(self, func, cond, started, release, calls, second=None):
        results = [None] * 2
        funcs = (func, func if second is None else second)

        def run(index):
            results[index] = funcs[index]()

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

    def run_cond_test(self, func, cache, info):
        self.run_threading_test(func, cache)

        if info:
            cache_info = func.cache_info()
            self.assertEqual(cache_info.hits, self.NTHREADS - 1)
            self.assertEqual(cache_info.misses, 1)

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
