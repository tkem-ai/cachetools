# Code Review — cachetools 8.0.2

**Date:** 2026-11-25, `__version__` 8.0.2; baseline `v8.0.2` (`0876d5e`).
**Reviewed:** `develop` at `2d23a62` "Update copilot instructions and review." (source, tests and docs as of `fd503ad` "Reject None as the receiver of unbound @cachedmethod calls."), plus this review commit.

**CI status:** `tox -p auto` passes on CPython 3.14.6 (480 tests, pyright 0 errors, 0 warnings); the tests also pass on 3.11.15, 3.12.13, 3.13.17, 3.15.0b4, free-threaded 3.13.14 and 3.14.6, and PyPy 7.3.23 (3.11). Actions is green for `2d23a62`.
**Coverage:** 100% on 3.11, 3.12 and PyPy; 3.13 and later lack `_descriptor.py:36`.

## Code — Potential Issues

| # | Priority | Location | Finding |
|---|----------|----------|---------|
| 1 | Low | condition variants of `@cached` / `@cachedmethod` | Two threads that each compute one key and call the wrapper with the other's key wait for each other forever; `77ae12c` only covers recursion within one thread. The lock variants and `functools.lru_cache` return, as `cachetools.func` did through 5.5.2 (hangs since 6.0.0). A fix needs to know which key each waiting thread is computing; undocumented. |
| 2 | Info | `Cache` (inherited `items()` / `values()`) | Iterating either view reads through `__getitem__`; a full traversal changed the next victim from `b` to `a` in `LRUCache`, unexpired `TTLCache` and `TLRUCache`, and an `LFUCache` frequency tie. `keys()`, `in` and `repr()` do not count as uses. |
| 3 | Info | `_decorator.py:72, 191` via `@cachedmethod` | Pending keys are tracked per instance wrapper, not per cache or condition, so sharing both does not prevent duplicate work. An event-controlled probe with deliberately colliding keys and different results returned both values and left the last writer's result cached. |
| 4 | Info | `TTLCache.__iter__` / `TLRUCache.__iter__` (#469) | Both yield inside `with self.timer`, so while an iterator is suspended the whole cache sees the frozen time: expired items stay visible and an item set meanwhile takes its expiry from it. Yielding outside the freeze could make `for key in cache: cache[key]` raise `KeyError`, a potentially breaking change; undocumented. |

## Performance

CPython 3.14.4, ns per operation, best of 7 (`timeit`, one pinned core, about ±5%),
measured 2026-11-15 on bare metal with `.github/copilot-bench.py`. Caches hold 100
items (`maxsize=100` for evicting inserts, new keys from `itertools.count()`, 20 ns
included); decorators use `LRUCache(1024)`, method calls include the attribute lookup
(`obj.method(1)`).

| Operation | `dict` | `Cache` | `LRU` | `LFU` | `TTL` | `TLRU` |
|---|---|---|---|---|---|---|
| get hit | 13 | 27 | 65 | 143 | 180 | 184 |
| contains | 13 | 36 | 36 | 36 | 135 | 137 |
| get miss (`KeyError`) | 66 | 257 | 339 | 341 | 433 | 440 |
| set, existing key | 14 | 66 | 107 | 173 | 418 | 662 |
| set, evicting | 111 | 336 | 396 | 492 | 1152 | 1674 |

| Decorator call | hit | evicting miss |
|---|---|---|
| `@cached` | 247 | 1337 |
| `@cached(lock=Lock())` | 326 | 1599 |
| `@cached(condition=Condition())` | 426 | 2057 |
| `@cached(info=True)` | 292 | 1401 |
| `@cached` on a method (bound) | 365 | |
| `@cachedmethod` | 331 | 1472 |
| `@cachedmethod(condition=...)` | 637 | 2337 |
| `@cachedmethod(info=True)` | 375 | 1537 |
| `cachetools.func.lru_cache` | 400 | 1883 |
| `functools.lru_cache` (C) | 28 | 82 |

`FIFOCache` evicting 413, `RRCache` 556, `Cache` update with `getsizeof` 132;
`hashkey(1, 2, 3)` 46, `hashkey(1, 2, a=3)` 212, `typedkey(1, 2, 3)` 155. `copy.copy()`
of 1000 items, in µs: `dict` 2.4, `Cache` 2.8, `FIFOCache` 36, `LRUCache` 36, `LFUCache`
80, `RRCache` 7, `TTLCache` 248, `TLRUCache` 246. `list()` of 1000 items (2026-11-18):
3.7 for the untimed cache classes, `TTLCache` 195, `TLRUCache` 197. The `func.lru_cache`
row is from 2026-11-24, after #485 (best of three runs; the other decorator rows agree
within 3%). Timed-cache hit and contains figures vary by 20 ns between processes.
The condition-wrapper and `func.lru_cache` rows predate `77ae12c` (a miss now also calls `get_ident()`, and each new `@cachedmethod` condition wrapper runs an import statement), the class-call figure predates `fd503ad`; not remeasured (VM).

| # | Priority | Location | Finding |
|---|----------|----------|---------|
| 1 | Info | `_cached.py` `_WrapperBase.__get__` | A hit through a method costs 365 ns against 247 for a direct call: each attribute access runs the Python-level `__get__` and builds a `types.MethodType`. |
| 2 | Info | `TTLCache.__setitem__` / `popitem` (and `TLRUCache`) | An evicting insert costs 1152 ns against 396 for `LRUCache` (TLRU 1674): `expire()` runs twice, the `_Timer` is entered twice (three times in `TLRUCache`) and `del self[key]` re-checks expiry. Skipping these would let a direct `popitem()` return an expired item or hide evictions from `__delitem__` overrides. |
| 3 | Info | `_cachedmethod.py` `_WrapperBase` properties | A `@cachedmethod` hit costs 331 ns against 247 for `@cached`: the user's `cache(self)` is called on every call and the key goes through `functools.partial`. First call on a new instance 1967 ns, class call 2136. |
| 4 | Info | `LFUCache.__touch` | A hit that moves its key to the next use-count link costs 232 ns against 143 for a key alone in its link. Evicting inserts stay flat with size: 543 ns at `maxsize` 10 000, 541 at 100 000. |
| 5 | Info | `TTLCache.__iter__` / `TLRUCache.__iter__` | Listing a timed cache costs about 195 ns per key against 4 for the other classes: each key from the snapshot is looked up again and enters the timer. |
| 6 | Info | condition variants of `@cached` / `@cachedmethod` | With `condition` alone, every `with` on the lock runs the Python-level `Condition.__enter__()` and `__exit__()`, about 50 ns each time (once per hit, three times per miss). Passing `lock=` and `condition=Condition(lock)` avoids it, as `func.py` does since #485 and the `cached` docs now note. |

## Type Stubs

| # | Priority | Finding |
|---|----------|---------|
| 1 | Info | `_cachedmethod_unbound.__call__` takes the receiver positional-only, so `Cls.method(self=obj, ...)` works at runtime but needs `# type: ignore` ("Expected 1 more positional argument"). |
| 2 | Info | `@classmethod` over `@cached` or `func.*_cache` type-checks falsely: calls through the class or an instance report "Argument missing for parameter" (pyright), though they work at runtime. |

## Tests — Gaps

| # | Priority | Finding |
|---|----------|---------|
| 1 | Info | Of the decorators that the new `@cachedmethod` error message names, only an outer function decorator is tested (`test_outer_decorator`), not `@staticmethod` or `@property`. |
| 2 | Info | `test_self_keyword` (#451) covers the default `@cached` and `@cachedmethod` wrappers and the class call only, not the lock, condition and `info` variants. |
| 3 | Info | `__repr__` on timed caches is never asserted to expire on its own, and `currsize` only indirectly through `cache_info()`. |
| 4 | Info | `NoneMethodTest.test_none_info` asserts only that `cache_info()` raises `TypeError` when `cache(self)` returns `None`; that the call itself fails with `TypeError` is unasserted. |
| 5 | Info | `test_lfu_copy_use_counts` pickles with the default protocol and the C pickler only, which without the #474 fix fails on 3.11 only (from 247 use counts), so elsewhere only its deep-copy arm guards that fix. |
| 6 | Info | No test covers #485: `test_func.py` never looks at `cache_lock` or `cache_condition`, so passing the condition alone again would only show in the benchmark. Likewise, the recursion tests use `condition` alone, not `lock` with `Condition(lock)` as `cachetools.func` passes it. |

## Docs (`docs/index.rst`)

| # | Priority | Finding |
|---|----------|---------|
| 1 | Low | Neither `@cached` nor `cachetools.func.*_cache` mention decorating methods, where cache and counters are shared across instances. |
| 2 | Low | The `cached` and `cachedmethod` sections describe `cache_lock` as the `lock` parameter, though with `condition` alone it is the condition object. The `cached` section also calls the wrapper a function rather than a callable object. |
| 3 | Low | New in 8.0.1 and undocumented: what a shallow copy of a cache shares (keys, values and attributes) and that a subclass with mutable state of its own must extend `__copy__`; that `@cached` wrappers copy and deep-copy as themselves; and that `@cachedmethod` must be the outermost decorator, where the docs name only `classmethod`. |
| 4 | Low | Since 8.0.2, `TTLCache` and `TLRUCache` snapshot keys when iteration starts: brand-new keys are skipped, missing or expired keys are filtered, and a deleted then reinserted key can still be visited in its original position. Document this and the suspended-iterator behavior (Code #4). |
| 5 | Info | The `README.rst` PyOWM and `get_pep` snippets are outside the Sphinx doctest run and were not rerun here. |

## Changelog
| # | Priority | Finding |
|---|----------|---------|
| 1 | Low | There is no section after v8.0.2 yet for the `cachetools.func` speed-up (#485) or the documentation improvements. The speed-up has a visible side effect: `cache_lock` of the `func` wrappers is now an `RLock`, no longer the `Condition` in `cache_condition`. |
| 2 | Low | The recursion fix needs an entry, e.g. “Fix a deadlock when a condition-backed decorator is called recursively with the same cache key (broken since v6.0.0).”; 5.5.2 returns for `cachetools.func`, 6.0.0 hangs. Side effect: such calls run uncached and count as misses. |
| 3 | Low | The receiver fix needs an entry, e.g. “Reject ``None`` as the receiver of unbound ``@cachedmethod`` calls.”; `Cls.method(None, obj, ...)` ran as `obj.method(...)` since v7.2.2 (7.2.1 raised `AttributeError`). Both fixes also apply to 7.3.3. |
