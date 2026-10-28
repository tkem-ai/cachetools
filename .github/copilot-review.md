# Code Review — cachetools 8.0.0 (development)

**Date:** 2026-10-28
**Reviewed:** `develop` at `7bc1326` ("Various documentation improvements.", rebased
onto `505aece`; `__version__` still 7.2.7, no 8.0.0 changelog section yet).

**CI status:** All `tox` environments pass locally on CPython 3.14.4: `py` (391
passed), `docs`, `doctest`, `pyright` (0 errors), `ruff`, `ruff-format`. GitHub
Actions not checked (branch not pushed).

**Coverage:** 100% except `_descriptor.py:32`, the pre-3.13 path where `@classmethod`
calls `__get__(cls, type(cls))` on a descriptor without `__set_name__`; on < 3.13 that
line is the only way into `_MethodDescriptor.__call__`, so the matrix covers both.

**Verified:** the refactored wrappers by a probe script: `@cached` on instance, static
and class methods binds through `__get__` and `create_autospec(instance=True)` strips
the receiver; module-level and class-attribute `@cached` wrappers pickle and deep-copy
to themselves while local ones raise `PicklingError`, as with `functools.lru_cache`;
`cached(None)` raises at decoration time; a non-sized custom cache fails only in
`cache_info()`; a method parameter named `pending` still works with `condition`;
wrong receivers and stacked decorators behave as described below; performance by the
benchmarks below.

## Code — Potential Issues

| # | Priority | Location | Finding |
|---|----------|----------|---------|
| 1 | Low | `Cache.__setitem__` / `__delitem__` | Size accounting assumes a value's size is stable after insertion; mutating cached values in place desyncs `currsize`. Documented footgun. |
| 2 | Low | `_cached.py` `_WrapperBase` | Wrappers have no `__repr__`, so a decorated function prints as `<cachetools._cached._BasicWrapper object at 0x...>` and `inspect.isfunction()` is false. Same as the C `functools.lru_cache`, but a `__repr__` naming `__wrapped__` would help debugging. |
| 3 | Low | `_decorator.py` `_ConditionMixin` / `_ConditionInfoMixin` via `@cachedmethod` | Pending sets are per wrapper, so two instances sharing one cache and condition do not coordinate pending keys. |
| 4 | Info | `_MethodDescriptor.__get__` (class-access path) | `Cls.method(obj, ...)` builds and discards a wrapper per call before `obj.__dict__.setdefault()` returns the stored one: 2606 ns per hit against 440 through the instance and 975 via `super()`, which reuses its stored wrapper (*Maintainer Decisions*). |
| 5 | Info | `_cachedmethod.py` `_wrapper` | `update_wrapper(descriptor, method)` runs *after* `_MethodDescriptor(wrapper)`, so a stacked `@cachedmethod` copies the inner descriptor's `__dict__` (factory, owner, name) over the outer's and the pair silently acts as the inner decorator alone. Calling `update_wrapper()` first would turn this into a `TypeError`, though with the misleading "class methods" message. Unsupported (*Maintainer Decisions*). |
| 6 | Info | `_cached.py` `_WrapperBase.__reduce__` | Pickling by `__qualname__` means a wrapper rebound under another name, or whose original name was deleted, unpickles to the wrong object or fails; wrappers on local functions raise `PicklingError`. Same rules as plain functions. |
| 7 | Info | condition variants of `@cached` / `@cachedmethod` | Same-thread recursion on the same key deadlocks (`wait()` on its own pending marker). |
| 8 | Info | `_MethodDescriptor.__get_unbound` | Lazy creation of the `_Unbound` object is unsynchronized; concurrent first class accesses may briefly see distinct, equivalent objects. Benign. |
| 9 | Info | `_descriptor.py` `_Unbound.__call__` | By design, autospec'd instances accept any arguments, so autospec no longer checks arity. A wrong receiver (`Cls.method(1)`) raises `TypeError` "No `__dict__` attribute on 'int' instance". |
| 10 | Info | `TTLCache.__delitem__` / `TLRUCache.__delitem__` | Deleting a present-but-expired key removes it and raises `KeyError`, consistent with `key in cache`; `pop(key, default)` and `del` differ around the expiry instant. Intentional. |
| 11 | Info | `CacheInfo._make_info` | A cache without `__len__` is only reported, as `TypeError` from `len()`, when `cache_info()` runs; documented requirement. |
| 12 | Info | `_cachedmethod.py` `_WrapperBase.__reduce__` | Unpickling and deep-copying rebuild wrappers through their descriptor, so `info=True` counters reset (asserted by tests). Acceptable. |
| 13 | Info | `_MethodDescriptor.__reduce__` / `_lookup` | `_lookup` must stay importable and resolves through the owner's *current* class dict, so a pickle loaded while `Cls.method` is patched yields the patched attribute. A descriptor that never saw `__set_name__` pickles but fails to load with `AttributeError`. |

No implementation bugs found beyond the items above.

## Performance

Hot-path costs on `develop` at `7bc1326`, measured on 2026-10-28 on CPython 3.14.4,
ns per operation, best of 7 (`timeit`, one pinned core; run-to-run noise about ±5%).
Caches hold 100 items for reads and updates and are full (`maxsize=100`) for evicting
inserts, with new keys from `itertools.count()` (19 ns included); decorators use
`LRUCache(1024)` and a one-argument function.

| Operation | `dict` | `Cache` | `LRU` | `LFU` | `TTL` | `TLRU` |
|---|---|---|---|---|---|---|
| get hit | 13 | 27 | 65 | 138 | 178 | 179 |
| contains | 13 | 37 | 37 | 37 | 132 | 132 |
| get miss (`KeyError`) | 65 | 255 | 329 | 331 | 425 | 443 |
| set, existing key | 14 | 65 | 109 | 172 | 398 | 645 |
| set, evicting | 111 | 333 | 489 | 588 | 1068 | 1563 |

`FIFOCache` evicting 395, `RRCache` 541; with a custom `getsizeof` (size-dict path)
`Cache` updates cost 129. The `dict` evicting row includes `del d[next(iter(d))]`.

| Decorator call | hit | evicting miss |
|---|---|---|
| `@cached` | 293 | 1533 |
| `@cached(lock=Lock())` | 371 | 1773 |
| `@cached(condition=Condition())` | 476 | 2311 |
| `@cached(info=True)` | 338 | 1611 |
| `@cached` on a method (bound) | 314 | |
| `@cachedmethod` | 422 | 1741 |
| `@cachedmethod(condition=...)` | 738 | 2660 |
| `@cachedmethod(info=True)` | 470 | 1830 |
| `cachetools.func.lru_cache` | 529 | 2388 |
| `functools.lru_cache` (C) | 27 | 81 |

| # | Priority | Location | Finding |
|---|----------|----------|---------|
| 1 | Info | `TTLCache.__setitem__` / `popitem` (and `TLRUCache`) | An evicting insert costs 1068 ns against 489 for `LRUCache` (TLRU 1563): `expire()` runs twice, the `_Timer` is entered twice and `del self[key]` re-checks expiry. Skipping `popitem()`'s own `expire()` and bypassing `__delitem__` would save ~13% more, but a direct `popitem()` could then return an expired item and subclass `__delitem__` overrides would no longer see evictions. |
| 2 | Info | `_decorator.py` mixin `__call__` | A `@cached` hit costs 293 ns: instance `__call__` dispatch plus the `self.cache` / `self.cache_key` attribute loads that a closure would hold as cell variables. Price of the shared mixins. |
| 3 | Info | `_cachedmethod.py` `_WrapperBase` properties | A `@cachedmethod` hit costs 422 ns against 293 for `@cached`: the `cache` (and `cache_lock`) properties call the user's `cache(self)` lambda on every call, and key and method go through `functools.partial`. First access per instance 3285 ns including `M()` at 782 (wrapper construction alone 976); class call 2606 (Code #4). Inherent to the per-instance design. |
| 4 | Info | `cachetools.func` | `lru_cache` hit 529 ns against 27 for `functools.lru_cache`, since every `func` decorator uses `condition=Condition()` and `info=True`. By design. |
| 5 | Info | `keys.typedkey` | 427 ns against 90 for `hashkey(1, 2, 3)`: two `_HashedTuple` allocations and a generator; `tuple(map(type, args))` and a single concatenation would trim it. Rarely hot. |

## Type Stubs (`__init__.pyi`, `keys.pyi`, `func.pyi`)

| # | Priority | Finding |
|---|----------|---------|
| 1 | Info | `_cachedmethod_unbound.__call__` takes the receiver positional-only, so `Cls.method(self=obj, ...)` works at runtime but needs `# type: ignore` (`test_class_call_keyword_receiver`). |
| 2 | Info | `@classmethod` over `@cached`/`func.*_cache` reports a false "Argument missing" error; pyright does not bind through the wrapper's `__get__`. Rare. |
| 3 | Info | `_cached_wrapper_info.__get__` needs `# pyright: ignore[reportIncompatibleMethodOverride]`; the override is sound. |

Otherwise fine: `ParamSpec`/`Concatenate[Any, _P]` preserve signatures, the
keyword-only `info: Literal[True]` overload precedes the `Literal[False]` default,
`Cache.setdefault` has the `None`-default overload, `CacheInfo` is exported, and
`func.pyi` covers both `@lru_cache` and `@lru_cache(...)`.

## Tests — Gaps

| # | Priority | Finding |
|---|----------|---------|
| 1 | Low | `test_cached.py` has no `create_autospec()` test for a class with `@cached` methods, although `__get__` binding is new; the probe shows it works. |
| 2 | Low | `UnboundMethodTest` does not assert that class access exposes no `cache_clear`/`cache_info`, nor class access for the lock/condition variants. |
| 3 | Info | `CacheTestMixin` checks key existence rather than the eviction victim, since it is shared across cache types; policy checks live per cache. No action needed. |
| 4 | Info | `test_func.py` calls decorators through `Callable[..., Any]`; `FIFODecoratorTest.test_method_typed` covers the stubs, enough since all five decorators share one wrapper type. |

## Docs (`docs/index.rst`)

| # | Priority | Finding |
|---|----------|---------|
| 1 | Low | The `@cachedmethod` docs do not mention that class access yields a callable without `cache_clear()`/`cache_info()` taking the receiver positionally or by name, or that pickling resets `cache_info()` counters (Code #12). |
| 2 | Low | Neither `@cached` nor `cachetools.func.*_cache` mention decorating methods, which now bind explicitly through `__get__`; a one-line caveat that cache and counters are then shared across instances would help. |
| 3 | Info | The `versionchanged:: 8.0` notes cover `cache=None`, `@classmethod`, immutable `__dict__` and `CacheInfo`; the Python 3.11 floor and the wrapper-object change (Code #2) are not mentioned, which is fine for the reference. |

## `CHANGELOG.rst`

No 8.0.0 section yet (release-only). Breaking changes to tag when it is written: Python
3.10 dropped; `@cachedmethod` with `@classmethod` or without a mutable `__dict__`
raises `TypeError`; `@cached(cache=None)` raises `TypeError`; `info=True` requires
`len()` on custom caches; `CacheInfo` is public; `@cached` wrappers are callable objects
rather than functions.

## Keys & Func Modules

No issues found. `_HashedTuple` uses the C tuple hash (rationale kept in a comment),
every `func.py` decorator is built on `cached(..., condition=Condition(), info=True)`,
and `_UnboundTTLCache` handles `maxsize=None`.
