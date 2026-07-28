# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

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
- `start()` could return before a query it started had finished transitioning,
  so an immediate read failed with "Query '...' is not running". It now waits
  for the query to be running.
