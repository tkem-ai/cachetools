"""Mixin helpers.

At least for now, the implementation prefers clarity and performance
over ease of maintenance, thus providing separate wrappers for all
valid combinations of parameters lock, condition and info.

"""

# pyright: reportAttributeAccessIssue=false

__all__ = ()

import weakref

# Pending keys shared by all wrappers whose condition is the same object,
# so @cachedmethod instances sharing a cache and a condition coordinate
# pending calls.  Each entry maps id(cache) to the keys pending for that
# cache, so wrappers sharing only the condition do not wait for each
# other; an in-flight call keeps its cache alive, and the entry is
# removed with its last pending key.
_pending = weakref.WeakKeyDictionary()


def _shared_pending(cond):
    try:
        return _pending.setdefault(cond, {})
    except TypeError:
        return {}  # cannot create weak reference to cond: own pending keys


class _BasicMixin:
    def __init__(self, func):
        self.__func = func

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)

        try:
            return cache[key]
        except KeyError:
            pass  # key not found
        val = self.__func(*args, **kwargs)
        try:
            cache[key] = val
        except ValueError:
            pass  # value too large
        return val

    def cache_clear(self):
        self.cache.clear()


class _LockedMixin:
    def __init__(self, func):
        self.__func = func

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock

        with lock:
            try:
                return cache[key]
            except KeyError:
                pass  # key not found
        val = self.__func(*args, **kwargs)
        with lock:
            try:
                # In case of a race condition, i.e. if another thread
                # stored a value for this key while we were calling
                # self.__func(), prefer the cached value.
                return cache.setdefault(key, val)
            except ValueError:
                return val  # value too large

    def cache_clear(self):
        with self.cache_lock:
            self.cache.clear()


class _ConditionMixin:
    def __init__(self, func):
        self.__func = func
        self.__pending = set()

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock
        cond = self.cache_condition

        with lock:
            # apparently significantly faster than cond.wait_for(...)
            while key in self.__pending:
                cond.wait()
            try:
                return cache[key]
            except KeyError:
                self.__pending.add(key)
        try:
            val = self.__func(*args, **kwargs)
            with lock:
                try:
                    cache[key] = val
                except ValueError:
                    pass  # value too large
                return val
        finally:
            with lock:
                self.__pending.remove(key)
                cond.notify_all()

    def cache_clear(self):
        with self.cache_lock:
            self.cache.clear()


class _SharedConditionMixin:
    """Like _ConditionMixin, but with pending keys that may be shared by
    wrappers using the same condition object, kept per cache identity."""

    def __init__(self, func):
        self.__func = func
        self.__pending = None  # resolved on first call, see _shared_pending()

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock
        cond = self.cache_condition
        pending = self.__pending
        if pending is None:
            # not resolved at construction, since cache_condition may not
            # be available yet, e.g. while unpickling the instance
            pending = self.__pending = _shared_pending(cond)
        cache_id = id(cache)

        with lock:
            # apparently significantly faster than cond.wait_for(...)
            keys = pending.get(cache_id)
            while keys and key in keys:
                cond.wait()
                keys = pending.get(cache_id)
            try:
                return cache[key]
            except KeyError:
                if keys is None:
                    keys = pending[cache_id] = set()
                keys.add(key)
        try:
            val = self.__func(*args, **kwargs)
            with lock:
                try:
                    cache[key] = val
                except ValueError:
                    pass  # value too large
                return val
        finally:
            with lock:
                keys.remove(key)
                if not keys:
                    del pending[cache_id]
                cond.notify_all()

    def cache_clear(self):
        with self.cache_lock:
            self.cache.clear()


class _InfoMixin:
    def __init__(self, func, info):
        self.__func = func
        self.__info = info
        self.__hits = self.__misses = 0

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)

        try:
            result = cache[key]
            self.__hits += 1
            return result
        except KeyError:
            self.__misses += 1
        val = self.__func(*args, **kwargs)
        try:
            cache[key] = val
        except ValueError:
            pass  # value too large
        return val

    def cache_clear(self):
        self.cache.clear()
        self.__hits = self.__misses = 0

    def cache_info(self):
        return self.__info(self.cache, self.__hits, self.__misses)


class _LockedInfoMixin:
    def __init__(self, func, info):
        self.__func = func
        self.__info = info
        self.__hits = self.__misses = 0

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock

        with lock:
            try:
                result = cache[key]
                self.__hits += 1
                return result
            except KeyError:
                self.__misses += 1
        val = self.__func(*args, **kwargs)
        with lock:
            try:
                # In case of a race condition, i.e. if another thread
                # stored a value for this key while we were calling
                # self.__func(), prefer the cached value.
                return cache.setdefault(key, val)
            except ValueError:
                return val  # value too large

    def cache_clear(self):
        with self.cache_lock:
            self.cache.clear()
            self.__hits = self.__misses = 0

    def cache_info(self):
        with self.cache_lock:
            return self.__info(self.cache, self.__hits, self.__misses)


class _SharedConditionInfoMixin:
    """Like _ConditionInfoMixin, with shared pending keys as in
    _SharedConditionMixin."""

    def __init__(self, func, info):
        self.__func = func
        self.__info = info
        self.__hits = self.__misses = 0
        self.__pending = None  # resolved on first call, see _shared_pending()

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock
        cond = self.cache_condition
        pending = self.__pending
        if pending is None:
            # not resolved at construction, since cache_condition may not
            # be available yet, e.g. while unpickling the instance
            pending = self.__pending = _shared_pending(cond)
        cache_id = id(cache)

        with lock:
            # apparently significantly faster than cond.wait_for(...)
            keys = pending.get(cache_id)
            while keys and key in keys:
                cond.wait()
                keys = pending.get(cache_id)
            try:
                result = cache[key]
                self.__hits += 1
                return result
            except KeyError:
                if keys is None:
                    keys = pending[cache_id] = set()
                keys.add(key)
                self.__misses += 1
        try:
            val = self.__func(*args, **kwargs)
            with lock:
                try:
                    cache[key] = val
                except ValueError:
                    pass  # value too large
                return val
        finally:
            with lock:
                keys.remove(key)
                if not keys:
                    del pending[cache_id]
                cond.notify_all()

    def cache_clear(self):
        with self.cache_lock:
            self.cache.clear()
            self.__hits = self.__misses = 0

    def cache_info(self):
        with self.cache_lock:
            return self.__info(self.cache, self.__hits, self.__misses)


class _ConditionInfoMixin:
    def __init__(self, func, info):
        self.__func = func
        self.__info = info
        self.__hits = self.__misses = 0
        self.__pending = set()

    def __call__(self, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock
        cond = self.cache_condition

        with lock:
            # apparently significantly faster than cond.wait_for(...)
            while key in self.__pending:
                cond.wait()
            try:
                result = cache[key]
                self.__hits += 1
                return result
            except KeyError:
                self.__pending.add(key)
                self.__misses += 1
        try:
            val = self.__func(*args, **kwargs)
            with lock:
                try:
                    cache[key] = val
                except ValueError:
                    pass  # value too large
                return val
        finally:
            with lock:
                self.__pending.remove(key)
                cond.notify_all()

    def cache_clear(self):
        with self.cache_lock:
            self.cache.clear()
            self.__hits = self.__misses = 0

    def cache_info(self):
        with self.cache_lock:
            return self.__info(self.cache, self.__hits, self.__misses)
