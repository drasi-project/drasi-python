# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `use_secret_store(kind, config)`, which routes a plugin's `{"kind": "Secret"}`
  references through an installed `secret-store` plugin. Previously the only
  source of a secret was the mapping passed to `create(secrets=...)`.
- `secret_store_config_schema(kind)`, matching the source, reaction and bootstrap
  equivalents.
- `UNKNOWN_SECRET_STORE_KIND`.
- `create(..., plugins_dir=...)`, which loads plugins from a directory before the
  engine is built. This is what makes an `identity/*` plugin selectable: an
  identity provider only reaches the engine through its builder, which runs
  before anything could call `install_plugin`.
- `identity={"kind": ...}` now accepts a kind provided by a plugin, alongside the
  built-in `password` and `token`.

### Fixed

- Secret store and identity provider plugins were loaded and then discarded. The
  host SDK returns five kinds of descriptor and only three were registered, so
  `install_plugin("secret-store/file")` reported `loaded: True` while the store
  was never consulted - the failure showed up much later as a secret that could
  not be found. Both are now registered, and `plugin_kinds()` and the
  `load_plugins` summary report them.
- A directory scan skipped secret store and identity plugins entirely. The host
  SDK's filename patterns cover only sources, reactions and bootstrap providers,
  so `libdrasi_secret-store_file.dylib` and `libdrasi_identity_test.dylib`
  matched nothing and were not loaded, with no error: a file matching no pattern
  simply is not a plugin as far as the scan is concerned. A directory holding
  three plugins reported one. Discovery now matches the `drasi_` prefix rather
  than a list of plugin types, so a type added later is found without a code
  change - the plugin SDK already defines an index backend descriptor that the
  loader does not yet surface. A matched file still has to export
  `drasi_plugin_metadata()`, so matching more broadly cannot load something that
  is not a plugin. Reported upstream as drasi-project/drasi-core#661.
- Installed plugin files were named after the plugin type verbatim, so
  `secret-store/file` was written as `libdrasi_secret-store_file.dylib`. Rust
  turns a hyphen in a crate name into an underscore when it names the cdylib, so
  the build itself produced `libdrasi_secret_store_file.dylib` - the hyphen was
  ours, and it was the spelling that matched no pattern. Both halves of the name
  are normalised now, and the scan still accepts the old spelling.
- `load_plugins` reports `skipped`, the number of shared libraries in the
  directory that were not loaded. A file matching no pattern was previously
  passed over in silence, which is why the missing plugin types went unnoticed.

## [0.1.2] - 2026-07-28

### Added

- `add_source(..., bootstrap={"kind": ..., ...})`, which attaches a bootstrap
  provider to a plugin source. A CDC source such as `postgres` streams the
  write-ahead log from the point its replication slot is created, so rows
  written before that are invisible to it and a query starts empty however much
  data is already in the table. Loading the current contents is a bootstrap
  provider's job. The binding could already install and inspect
  `bootstrap/postgres`, but nothing attached it - `add_source` never called the
  source's `set_bootstrap_provider` - so installing it appeared to succeed and
  then did nothing, which looked like the source silently dropping data.

### Fixed

- `make typecheck` reported 1653 errors on a clean tree and CI never ran it.
  Nearly all of them came from pyright resolving imports against the wrong
  interpreter, which left every value derived from `drasi` as `Unknown`. CI now
  runs it.
- 23 `TypedDict`s were declared both in `types.py` and in the stub, and had
  already drifted: `SourceChange.op` was `ChangeOp` in one and `str` in the
  other. `types.py` is now the single source of truth.
- `SourceChange` documented the Node.js spellings `startId`, `endId`, `inId`
  and `outId` but did not declare them, so following the docstring failed type
  checking. All three spellings were confirmed at runtime.
- The sync facade declared weaker return types than it returns, for example
  `dict[str, int]` where it returns `LoadSummary`.
- Directory arguments were typed `str` although the Rust side accepts any
  `PathLike`, which our own tests rely on.
- `ResultDiff.type` was optional although it is always present.

## [0.1.1] - 2026-07-28

### Fixed

- The published description told readers the package was not on PyPI. `README.md`
  is the distribution's `long_description`, so 0.1.0's own project page carried
  "Not published to PyPI yet. Build it from source", which is the first thing a
  visitor reads. `README.md`, `examples/README.md` and `docs/metrics.md` now
  describe the released package, and the install section gives
  `pip install drasi-lib` with the supported platforms.
- The examples drift guard asserted the guide *did* say "not published to pypi
  yet", so it held the stale claim in place instead of catching it. It now
  asserts the opposite for both READMEs.
- Links in `README.md` were relative, so every one of them 404'd on the PyPI
  project page, which resolves them against `pypi.org`. They are absolute now,
  and a test keeps them that way.

## [0.1.0] - 2026-07-28

First release to PyPI.

### Added

- PyO3 extension module published as the `drasi-lib` distribution and imported
  as `drasi`, with package metadata driven from `Cargo.toml`.
- Async `Drasi` API for embedding the Drasi continuous-query engine in Python,
  with lifecycle, query, source, reaction and result-reading operations.
- Python-defined sources and reactions, including durable reactions and pushed
  graph changes.
- Plugin-backed sources, reactions and bootstrap providers loaded from
  `ghcr.io/drasi-project`, including registry search, tag listing, resolution,
  installation, explicit pulls, watching and lockfiles.
- Plugin compatibility and host introspection through `host_info()` and exposed
  Drasi crate version constants.
- Streaming query results, component events and component logs as async
  iterators, with callback forms for Node.js binding parity.
- Sync facade for scripts and notebooks.
- Typed errors with stable error codes, type stubs and `py.typed`.
- Declarative `from_config`, metrics, schema discovery, status accessors,
  in-place source/reaction updates, query tuning, secret resolvers, identity
  options, redb state storage and optional RocksDB indexing.
- CI, examples, end-to-end tests, plugin tests, documentation for plugins,
  examples and the API surface audit.
- `ENGINE_CLOSED` error code, raised when a closed engine is asked to change.
- `host_info()["index_backends"]`, reporting which index backends were compiled
  in, so callers can tell whether RocksDB is available in their build.

### Fixed

- A closed engine accepted components and changes instead of refusing them.
  `add_python_source`, `add_query`, `push_change`, `load_plugins` and the other
  mutating calls succeeded after `close()`, and the component then silently
  never ran. Reads are still allowed, since inspecting a closed engine is
  harmless and useful.
- The RocksDB tests decided availability from an environment variable rather
  than from the build, so they disagreed with reality whenever the two drifted.
  Release wheels are built with the feature but tested without the variable,
  which would have failed the release smoke test on every platform. They now
  ask the build.
- A query registered before `start()` was started twice, because `drasi-lib`
  starts an auto-start query as soon as it is added without the `is_running()`
  guard that adding a source or a reaction applies, and `start()` then started
  it again. The query reported `Error` while it was in fact running, and when
  the first start won the race an upstream assertion surfaced as a panic out of
  `start()`. Such a query is now registered with auto-start suppressed and
  started once, so both orderings behave the same. Upstream:
  drasi-project/drasi-core#639.
- Concurrent `push_change` calls to the same Python source could silently lose
  changes. `dispatch_source_change` takes its monotonic sequence with a
  `fetch_add` and then awaits its way to the subscribers, so two overlapping
  pushes can arrive in the opposite order to the sequences they took, and the
  query side discards anything at or below the highest sequence it has already
  seen. Twenty changes pushed through `asyncio.gather` lost one about three
  times in a hundred runs; sequential pushes never did. Dispatch for a Python
  source is now serialised, so ordering matches the sequence. Upstream:
  drasi-project/drasi-core#640.
- `start()` could return before a query it started had finished transitioning,
  so an immediate read failed with "Query '...' is not running". It now waits
  for the query to be running.
