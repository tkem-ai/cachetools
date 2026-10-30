# Copilot Instructions for cachetools

Memoizing collections and decorators, including `functools.lru_cache` variants. Pure
Python ≥ 3.11, no runtime dependencies, `src/` layout, type stubs in `*.pyi`. Single
maintainer; `master` is the release branch, `develop` the 8.0 line. Keep this file under
100 lines: rules an agent would otherwise get wrong, not documentation.

## Commands

Run everything through `tox`, never bare `pytest`, `ruff` or `pyright`:

```bash
tox -p auto                                # all environments, as CI does
tox -e py -- tests/test_ttl.py -k expire   # tests; posargs go to pytest
tox -e pyright                             # type stubs
tox -e ruff,ruff-format                    # lint and formatting
tox -e docs,doctest                        # docs build and doctests
```

CI (GitHub Actions on `tkem/cachetools`) runs CPython 3.11–3.15, free-threaded
3.13t–3.15t and PyPy 3.11, where `types.MethodType` skips the callable check that
`functools.partial` makes. Branch coverage is 100 %; on 3.13+ only the pre-3.13
`@classmethod` line in `_MethodDescriptor.__get__` is uncovered, CI covers it.

## Code Style

- No annotations in `.py` files; types live in the `.pyi` stubs. Decorator
  `@overload`s come in the order keyword-only `info: Literal[True]`,
  `info: Literal[False] = ...` (default), positional `Literal[True]`.
- Prefer clarity and performance over DRY: one wrapper class per lock/condition/info
  combination in `_decorator.py`, `_cached.py` and `_cachedmethod.py`. Apply a change
  to **all** variants.
- Keep hot paths free of avoidable Python-level calls. Look links and items up with
  `.get()` instead of catching `KeyError` per new key (~200 ns each):

  ```python
  link = links.get(key)
  if link is None:
      ...  # new key
  ```

- Unsupported use raises `TypeError` before anything is cached, chained `from None`;
  a store that fails with `ValueError` (value too large) is swallowed and the
  computed value returned.
- Docs (`docs/index.rst`, doctested): wrap prose at column 70, two spaces after a
  sentence, single backticks for parameters and `:meth:`/`:func:`/`:exc:` roles. Keep
  `README.rst` examples in sync with it.

## Architecture Constraints

- A value's size must not change after insertion. With the default `getsizeof` the
  size dict is `None` and `getsizeof()` is never called: keep that fast path.
- Cache subclasses override `__setitem__`, `__delitem__`, `popitem()`, `clear()` and
  optionally `__getitem__`; after the parent `__getitem__`, check the subclass's own
  bookkeeping, not `key in self`, since `__missing__` may not store the item.
  `popitem()` evicts via `del self[key]`, so `__delitem__` overrides see evictions.
- Timed caches expire lazily; `expire()` is a documented override hook, so every
  insert and `popitem()` must keep calling it.
- `@cachedmethod` stores per-instance wrappers in `obj.__dict__`. Pickling and
  deep-copying such objects (#417) and `create_autospec()` on their classes (#443)
  must keep working; `_descriptor.py` documents how.

## Testing

- New behavior needs tests under `tests/`; user-visible features need docs in
  `docs/index.rst`. Objects pickled by name must be reachable from module level.
- Stub checks need concrete annotated tests without `# type: ignore`, since
  `test_func.py` calls decorators via `Callable[..., Any]`.
- Threading tests join with `TIMEOUT` and assert the thread finished.
- Performance: `timeit`, best of 7, on a pinned core (`taskset`), never in a VM,
  against a git worktree of the previous release. Never trade documented subclass
  hooks or semantics for speed.

## Boundaries

- Never edit `CHANGELOG.rst` or bump `__version__`; both are release-only.
- Never promise cross-version pickle compatibility or build on the byte format; any
  release, even a bugfix, may change it.
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
- Run `tox` before pushing. Update this file in the same PR that changes a convention.

## Code Review

- Reviews amend `.github/copilot-review.md` in place: header (date, commit, CI,
  coverage, one *Verified* paragraph), then tables `# | Priority | Location | Finding`
  ordered High, Medium, Low, Info. Renumber after changes; cross-reference as "Code #3".
- Resolved issues are removed, never marked resolved; settled matters go to
  *Maintainer Decisions* above. Brief rows, numbers only where they decide something,
  current snapshot only; no new files or dated sections.
