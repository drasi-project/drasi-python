# Python bindings: API surface and gap audit

> Audit for [`drasi-project/team#109`](https://github.com/drasi-project/team/issues/109),
> and the record of closing it in
> [#110](https://github.com/drasi-project/team/issues/110).
>
> **Status: every gap identified below is closed.** `drasi-python` is at
> **48/48 `@drasi/lib` methods (100%)** plus 21 methods Node does not have.
> The sections below are kept as the record of what was found and what was
> done; the original findings are marked ✅ where they have been addressed.
>
> `drasi-core-python` is deprecated. `drasi-python` is the binding.

## Summary

At the time of the audit there were **two** Python binding prototypes with
different architectures. `drasi-core-python` has since been deprecated, and its
one genuine advantage — streaming as async iterators — has been carried over.

| | `drasi-python` | `drasi-core-python` |
| --- | --- | --- |
| Visibility | public | private |
| Last touched | active | 2026-02-14 |
| Wraps | `drasi-lib` + `drasi-host-sdk` | `drasi-core` / `drasi-lib` |
| Components | **loaded at runtime** from `ghcr.io/drasi-project` | **linked at compile time**, one PyPI package each |
| PyPI packages | 1 | 23 + workspace root |
| Engine methods | 37 | 27 |
| Errors | 8 classes, 26 codes | 1 class, no codes |
| Streaming | none | async iterators |
| Python | ≥3.10 (abi3) | ≥3.11 |

Note also that `drasi-core-python`'s workspace root is itself named
`drasi-python` in its `pyproject.toml`, so the two efforts collided on name.

They were **complementary, not redundant**: each implemented most of what the
other lacked. That made choosing between them the blocking decision for #110.
The decision was to keep `drasi-python`.

Against `@drasi/lib`, `drasi-python` was at 30/48 methods (62%) when audited,
and is now at **48/48 (100%)**.

## Method

- `drasi-python`'s surface was enumerated from the built module by
  introspection, not from documentation.
- `drasi-core-python`'s surface was read from its committed `.pyi` stubs.
- `@drasi/lib`'s surface was taken from `src/drasi.rs` and `test/types.test-d.ts`.
- The engine surface was taken from `drasi-lib` 0.8.9 `src/lib_core_ops/`.
- Method names were normalised to snake_case, and the language-specific
  `addJsSource`/`addJsReaction`/`addDurableJsReaction` mapped to their
  `add_python_*` equivalents.

---

## 1. `drasi-python` — current public surface

37 methods on `Drasi`, plus an `id` property.

### Lifecycle (5)

| Method | Notes |
| --- | --- |
| `Drasi.create(id)` | static, awaitable |
| `start()` / `stop()` / `close()` | |
| `is_running()` | not in Node |

Supports `async with`.

### Queries (9)

`add_query` · `update_query` · `remove_query` · `start_query` · `stop_query` ·
`get_query_results` · `get_query_status` · `list_queries` · `wait_for_query`

Cypher and GQL; multi-source; synthetic joins.

### Components defined in Python (3)

`add_python_source` · `push_change` · `add_python_reaction`

`push_change` accepts nodes and relations, with the Node.js key spellings
(`startId`, `inId`) as input aliases.

### Plugin-backed components (10)

`add_source` · `remove_source` · `start_source` · `stop_source` · `list_sources`
`add_reaction` · `remove_reaction` · `start_reaction` · `stop_reaction` · `list_reactions`

### Plugins (10)

`load_plugins` · `plugin_kinds` · `host_info` · `search_plugins` ·
`list_plugin_tags` · `resolve_plugin` · `install_plugin` ·
`source_config_schema` · `reaction_config_schema` · `bootstrap_config_schema`

### Module exports (15)

`Drasi`, `host_info`, `ERROR_CODES`, the version constants, and 8 exception
classes.

### Errors

Hierarchy rooted at `DrasiError`, every instance carrying a stable `.code`
drawn from 26 values:

```
DrasiError
├── ConfigError
│   └── UnknownKindError
├── SourceError
└── PluginError
    ├── PluginNotFoundError
    ├── PluginCompatibilityError
    └── PluginSignatureError
```

Unlike the Node.js binding — where napi-rs can only attach a code to a
*synchronous* throw, forcing async failures to embed the code in the message
text as `"... [UNKNOWN_SOURCE_KIND]"` — these are raised as typed exceptions
from sync and async paths alike.

### Type stubs

Hand-written `_drasi.pyi` plus `py.typed`. A test asserts the stub declares
every method the extension exposes and nothing it does not, so drift fails CI.
Config and result types are `TypedDict`s.

### Async ergonomics

Async-first: every I/O method returns an awaitable driven by a shared tokio
runtime via `pyo3-async-runtimes`. The GIL is released while the engine works —
covered by a test asserting a pending engine call does not starve the event
loop. `async with` is supported.

---

## 2. `drasi-core-python` — prototype surface

`PyDrasiLib` exposes 27 async methods:

- **Lifecycle**: `start`, `stop`, `is_running`
- **Sources**: `add_source`, `remove_source`, `start_source`, `stop_source`,
  `list_sources`, `get_source_status`
- **Queries**: `add_query`, `remove_query`, `start_query`, `stop_query`,
  `list_queries`, `get_query_status`
- **Reactions**: `add_reaction`, `remove_reaction`, `start_reaction`,
  `stop_reaction`, `list_reactions`, `get_reaction_status`
- **Streaming**: `subscribe_{source,query,reaction}_events`,
  `subscribe_{source,query,reaction}_logs`

Construction is builder-based (`DrasiLibBuilder`, `Query.cypher(...)`), and
components are concrete Python classes from separate packages
(`PyApplicationSource`, `PyApplicationReaction`, ...).

**What it has that `drasi-python` does not**

- Event and log streaming, as **async iterators** (`__aiter__`) with replayable
  `history()` — a better shape than Node's callbacks.
- `get_source_status` / `get_reaction_status`.
- Index backend and state store providers wired through the builder.
- Middleware package.

**What it lacks**

- Any plugin loading — components are compile-time dependencies, so there is no
  registry, no OCI, no signature verification, no compatibility checking.
- `get_query_results` — no way to read a result set.
- Metrics, schema discovery, secrets, `from_config`.
- Error codes: one `DrasiError`, so callers must match on message text.
- 23 packages have to be versioned and released in lockstep.

---

## 3. Gap analysis vs `@drasi/lib`

At audit: 30 of 48 methods (62%). **Now 48 of 48 (100%).**

| Area | Was missing | Status |
| --- | --- | --- |
| Streaming | `on_all_events`, `on_{query,source,reaction}_events`, `on_{query,source,reaction}_logs` | ✅ plus async iterators |
| Metrics | `get_query_metrics`, `get_reaction_metrics`, `get_lifecycle_metrics` | ✅ |
| Schema | `get_source_schema`, `get_graph_schema` | ✅ |
| Config | `from_config` | ✅ |
| Components | `update_source`, `update_reaction` | ✅ |
| Reactions | `add_durable_python_reaction` | ✅ |
| Plugins | `watch_plugins`, `pull_plugin` | ✅ |
| Secret store | `secrets`, and the resolver plugins call back through | ✅ |
| State store | redb | ✅ |
| Index store | RocksDB, behind a Cargo feature | ✅ |
| Identity | password and token | ✅ |

**21 methods exist here that Node does not have**: the eight streaming
iterators (`query_results`, `query_events`, `source_events`,
`reaction_events`, `all_events`, `query_logs`, `source_logs`,
`reaction_logs`) and `on_query_results`; the plugin ergonomics
(`install_plugin`, `resolve_plugin`, `search_plugins`, `write_lockfile`,
`read_lockfile`, `install_from_lockfile`); and introspection (`host_info`,
`get_query_status`, `get_source_status`, `get_reaction_status`,
`wait_for_query`, `is_running`).

## 4. Gap analysis vs the `drasi-lib` engine

Comparing against `drasi-lib` 0.8.9 `src/lib_core_ops/`, the engine also offers,
unexposed by *either* prototype:

| Engine capability | Notes |
| --- | --- |
| `get_query_config` / `get_query_info` | inspect a running query |
| `get_source_info` / `get_reaction_info` | |
| `snapshot_configuration` / `get_current_config` | round-trip config to disk |
| `subscribe_all_component_events` | |
| Query tuning: `with_middleware`, `with_recovery_policy`, `with_storage_backend`, `with_outbox_capacity`, `dispatch_mode` | `Query` builder options; only `joins` and `language` are exposed today |
| WAL providers | |

These are lower priority than the Node parity gaps — they are engine surface
neither binding has needed yet — but `snapshot_configuration` pairs naturally
with `from_config`.

## 5. Prioritized gap list — all closed

Each item became a work item under #110. All are done.

### P0 — blocks realistic use

1. **Event and log streaming.** The only way to observe a query today is to poll
   `get_query_results`. Expose both the callback form (Node parity) and async
   iterators (`async for event in drasi.query_events(id)`), the latter being the
   shape `drasi-core-python` already proved out.
2. **Secret store.** Without `CreateOptions.secrets`, any plugin whose config
   references a secret cannot be configured — that is most production sources.
3. **State store (redb).** Prerequisite for durable reactions and recovery.

### P1 — needed for parity

4. **`from_config`** — declarative construction of a whole topology.
5. **Metrics** — `get_query_metrics`, `get_reaction_metrics`,
   `get_lifecycle_metrics`.
6. **Schema discovery** — `get_source_schema`, `get_graph_schema`.
7. **`update_source` / `update_reaction`** — reconfigure without remove/add.
8. **Index store (RocksDB)** — already a Cargo feature; needs exposing plus
   wheels built with it.
9. **Identity providers.**
10. **Typed config objects** — dataclasses/`TypedDict`s for every config and
    result, replacing raw dicts at the boundary.

### P2 — completeness and ergonomics

11. **Durable Python reactions** — depends on (3).
12. **`watch_plugins`** — hot-reload a plugin directory.
13. **`pull_plugin`** — download an explicit reference without resolution.
14. **Plugin lockfiles** — `PluginLockfile` is in `drasi-host-sdk` and unexposed;
    needed for reproducible installs.
15. **Sync facade** — `drasi.sync.Drasi` for scripts and notebooks.
16. **Query tuning options** — middleware, recovery policy, storage backend.
17. **`get_source_status` / `get_reaction_status`** — `get_query_status` exists;
    the other two do not.

### Cross-cutting

18. **Wheel matrix and PyPI release** — tracked separately as #112.
19. **Free-threaded (3.13t/3.14t)** — revisit after abi3 wheels ship.

## 6. Assessment against the issue's specific questions

**Type-stub coverage.** Complete and enforced. `_drasi.pyi` plus `py.typed`,
with a test comparing the stub against the built module in both directions. The
gap is depth rather than breadth: several return types are `dict[str, Any]`
where a `TypedDict` would be better (item 10).

**Error types.** The strongest part of the current surface, and ahead of both
`@drasi/lib` (codes only on sync throws) and `drasi-core-python` (a single
`DrasiError`). Remaining work is coverage — plugin and compatibility failures
are well modelled, but engine-side failures still collapse into
`ENGINE_FAILURE`.

**Async ergonomics.** Sound: async-first, GIL released across engine calls,
`async with`, and `wait_for_query` for the auto-start race. Two gaps: no async
iterators until streaming lands (item 1), and no sync facade (item 15).

## Recommendation — accepted

`drasi-python` is the released binding. The streaming design from
`drasi-core-python` was ported rather than maintaining both.

The reasoning is distribution, not code quality. `drasi-core-python`'s
compile-time model needs 23 PyPI packages released in lockstep, and adding a
source means shipping a new package; users pick components at install time.
`drasi-python` ships one wheel and resolves components at runtime from the
registry that `drasi-server` and `@drasi/lib` already use, so a new plugin is
available to Python users the day it is published, with no release on our side.
That also keeps the three host implementations on one distribution story.

The trade: runtime loading means a plugin has to match
the host's `sdk`/`core`/`lib` versions and target triple, which is a class of
failure the compile-time model does not have. That risk is already mitigated —
`install_plugin` resolves a compatible build automatically, mismatches raise
`PluginCompatibilityError` naming the host's versions, and CI fails if our crate
pins drift from what the registry publishes.

`drasi-core-python` is deprecated and should be archived with a pointer here, so
nobody has to make this comparison again.

## What is left

Not API gaps, and tracked separately in the epic:

- Wheel matrix and PyPI release — team#112
- First stable release — team#113
- Introduction article and tutorial — team#115, #116

Two engine-level behaviours, both pinned by tests:

- `get_reaction_metrics()["checkpoint_sequence"]` is the forwarder's *delivery*
  position, not the durable checkpoint. It advances even when a durable handler
  fails, so it cannot be used to assert durability.
- redb holds an exclusive lock for the life of the process. Closing an engine
  does not release it, so a state store cannot be reopened in the same process.
