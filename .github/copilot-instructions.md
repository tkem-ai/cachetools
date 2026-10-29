# Copilot Instructions for cachetools

Memoizing collections and decorators, including `functools.lru_cache` variants. Pure
Python ≥ 3.11, no runtime dependencies, `src/` layout, inline type stubs (`*.pyi`,
`py.typed`). Single maintainer. `master` is the release branch, `develop` the 8.0 line.
This file holds instructions, not documentation: stay under 150 lines and drop what the
code already shows before adding.

## Commands

Run everything through `tox`, never bare `pytest`, `ruff` or `pyright`:

```bash
tox -p auto                                # all environments, as CI does
tox -e py -- tests/test_ttl.py -k expire   # tests; posargs go to pytest
tox -e pyright                             # type stubs
tox -e ruff,ruff-format                    # lint and formatting
tox -e docs,doctest                        # docs build and doctests
```

CI (GitHub Actions on `tkem/cachetools`, every push) runs CPython 3.11–3.15,
free-threaded 3.13t–3.15t and PyPy 3.11. Branch coverage is 100 %, except that on 3.13+
the pre-3.13 `@classmethod` line in `_MethodDescriptor.__get__` is uncovered; CI covers
it.

## Code Style

- `ruff format` and `ruff check` decide formatting and lint. No annotations in `.py`
  files; types live in the `.pyi` stubs.
- Prefer clarity and performance over DRY: there is one wrapper class per
  lock/condition/info combination (`_decorator.py`, `_cached.py`, `_cachedmethod.py`).
  Apply a change to **all** variants.
- Keep hot paths free of avoidable Python-level calls. Look links and items up with
  `.get()` instead of catching `KeyError` per new key (~200 ns each):

  ```python
  link = links.get(key)
  if link is None:
      ...  # new key
  ```

- Stubs: decorator `@overload`s come in the order keyword-only `info: Literal[True]`,
  `info: Literal[False] = ...` (default), positional `Literal[True]`; wrappers use
  `ParamSpec`, `_cachedmethod_wrapper` uses `Concatenate[Any, _P]`; `@cached` wrappers
  have three `__get__` overloads (class access, instance binding, `obj: object`);
  `_cachedmethod_unbound.__call__` takes the receiver positional-only. pyright runs in
  `standard` mode with `reportUnnecessaryTypeIgnoreComment`; the wrapper and descriptor
  modules silence it with module-level `# pyright: report...=false`, everything else
  uses scoped suppressions.
- Docs (`docs/index.rst`, doctested): wrap prose at column 70, two spaces after a
  sentence, single backticks for parameters and `:meth:`/`:func:`/`:exc:` roles. Keep
  `README.rst` examples in sync with it.

## Error Handling

- Decorators swallow `ValueError` from a store (value too large) and return the
  computed value; never let it reach the caller.
- Unsupported use raises `TypeError` before anything is cached: `cached(None)`,
  `@classmethod` over `@cachedmethod`, a receiver without a mutable `__dict__`, a
  descriptor that never received `__set_name__`. Chain with `from None`.
- Timed caches: deleting a present-but-expired key removes it and raises `KeyError`.
- Wrappers pickle by name, so wrappers on local functions raise `AttributeError` like
  plain functions do. Do not catch it.

## Architecture Constraints

- `Cache` is a `MutableMapping`; a value's size must not change after insertion. With
  the default `getsizeof` the size dict is `None`, each item counts 1 and `getsizeof()`
  is never called: keep that fast path.
- Subclasses override `__setitem__`, `__delitem__`, `popitem()`, `clear()` and
  optionally `__getitem__`; after the parent `__getitem__`, check the subclass's own
  bookkeeping (not `key in self`), since `__missing__` may not store the item.
  `popitem()` evicts via `del self[key]`, so subclass `__delitem__` overrides see
  evictions.
- `_TimedCache` (`TTLCache`, `TLRUCache`): expiry is lazy (`__len__`, `__repr__` and
  `currsize` call `expire()`, `clear()` does not). `expire()` is a documented override
  hook; every insert and `popitem()` must keep calling it.
- `CacheInfo._make_info()` reports `maxsize`/`currsize` for a `Cache`, else `None` and
  `len(cache)`: other mappings used with `info=True` need `len()`.
- Mixins (`_decorator.py`) implement `__call__`, `cache_clear()` and `cache_info()`
  against `self.cache`, `self.cache_key`, `self.cache_lock` and `self.cache_condition`,
  with state in name-mangled attributes; `condition` without `lock` serves as both.
- `@cached` wrappers are objects: `functools.update_wrapper()` runs *before* the public
  attributes are set, `__get__` binds via `types.MethodType`, `__reduce__` returns
  `__qualname__`.
- `@cachedmethod`: `_MethodDescriptor` stores the per-instance wrapper in
  `obj.__dict__` via `setdefault` and `super()` wrappers in
  `obj.__dict__["__cachetools_cachedmethods"]` keyed by descriptor. Class access
  returns a lazy `_Unbound` object, deliberately not a function so `create_autospec()`
  strips the receiver (#443). Pickle and deepcopy (#417) rebuild wrappers through
  their descriptor; `_MethodDescriptor._lookup` must stay importable.
- `func.py` decorators use `cached(..., condition=Condition(), info=True)`.
  `keys.hashkey` returns a `_HashedTuple` using the C tuple hash (a Python-level hash
  cache was slower).

## Testing

- New behavior needs tests under `tests/`; user-visible features need docs in
  `docs/index.rst`.
- `tests/__init__.py` provides `CacheTestMixin`, `CountedLock` and `CountedCondition`;
  one `TestCase` per cache type; TTL tests use a manual `Timer`. Objects pickled by name
  must be reachable from module level by their `__qualname__`.
- `test_cached.py` keeps a duck-typed non-`Mapping` cache (`CustomCacheTest`);
  `@classmethod` tests live in `test_cachedmethod.py`. Stub checks need concrete
  annotated tests without `# type: ignore` (`test_decorator_method`,
  `test_method_typed`), since `test_func.py` calls decorators via `Callable[..., Any]`.
- `test_threading.py`: join with `TIMEOUT` and assert threads finished;
  `WaitCondition` forces a contended `wait()`; single-threaded `wait_count` stays 0.
- Performance: `timeit`, best of 7, on a pinned core (`taskset`), never in a VM,
  against a git worktree of the previous release. Never trade documented subclass
  hooks or semantics for speed.

## Boundaries

- Never edit `CHANGELOG.rst` or bump `__version__`; both are release-only.
- Never promise cross-version pickle compatibility or build on the byte format; any
  release, even a bugfix, may change it. Pickling and deep-copying objects that use
  `@cachedmethod` (#417) must keep working.
- A review changes nothing; fix only when asked.
- **Maintainer Decisions** (do not re-raise): `copy.copy()` of an instance shares its
  active `@cachedmethod` wrapper; stacking `@cachedmethod` decorators is unsupported
  and untested; class access (`Cls.method(obj, ...)`) builds and discards a wrapper per
  call; a `condition` must provide the full `threading.Condition` interface, with
  `notify()` reserved for future use.

## Git

- Target `develop` for 8.0 work and `master` for bugfix releases.
- PRs reference an open issue (except trivial fixes), in separate commits:
  `Fix #123: ...`, `Tests for #123: ...`, `Docs for #123: ...`.
- Run `tox` before pushing; all nine CI jobs must stay green.

## Code Review

- Reviews amend `.github/copilot-review.md` in place (header: date, commit, CI status,
  coverage, one *Verified* paragraph); never new files, dated sections or per-commit
  change summaries (git history is the record).
- Findings are tables ordered High, Medium, Low, Info with columns
  `# | Priority | Location | Finding`; renumber after changes; cross-reference as
  "Code #3". Resolved issues are removed, never marked resolved.
- One or two sentences per row, numbers only where they decide something, current
  snapshot only. Its `CHANGELOG.rst` section lists changes to tag "(breaking change)",
  "(potentially breaking change)" or "(broken since vX.Y.Z)". Settled matters go to
  *Maintainer Decisions* above.
