---
title: "Concepts"
linkTitle: "Concepts"
weight: 20
description: >
  The change-driven model: sources, continuous queries, reactions and bootstrap.
---

## Why continuous queries

A normal query answers a question once. To keep an answer current you either re-run it
on a timer, which is wasteful and always slightly stale, or you hand-write logic that
works out which events could have changed the answer — which is where the bugs live.

A **continuous query** is declared once and maintained. Drasi tracks what the result
set is, and when a change arrives it works out precisely which rows entered, left or
changed, and tells you about those. You get the *difference*, not a new snapshot to
diff yourself.

That difference is the useful part. Knowing an order is no longer in the "open orders"
set is a fact you can act on directly, and it is exactly what polling makes you
reconstruct.

## The pieces

<div class="card-grid card-grid--3">
  <div class="unified-card unified-card--concepts">
    <div class="unified-card-icon"><i class="fas fa-database"></i></div>
    <div class="unified-card-content">
      <h3 class="unified-card-title">Source</h3>
      <p class="unified-card-summary">Where changes come from — a database's change feed, a stream, or your own code.</p>
    </div>
  </div>
  <div class="unified-card unified-card--reference">
    <div class="unified-card-icon"><i class="fas fa-project-diagram"></i></div>
    <div class="unified-card-content">
      <h3 class="unified-card-title">Continuous query</h3>
      <p class="unified-card-summary">A Cypher or GQL query whose result set is kept current as changes arrive.</p>
    </div>
  </div>
  <div class="unified-card unified-card--howto">
    <div class="unified-card-icon"><i class="fas fa-bolt"></i></div>
    <div class="unified-card-content">
      <h3 class="unified-card-title">Reaction</h3>
      <p class="unified-card-summary">What happens when the result set changes — your callback, or a plugin.</p>
    </div>
  </div>
</div>

### Sources

A source turns changes in some system into graph changes: nodes and relations being
inserted, updated or deleted. It can be a **plugin** that follows a real system — a
Postgres write-ahead log, a Kafka topic, a Kubernetes cluster — or a **Python source**
you push changes into yourself with `push_change`.

Every change carries an `id`, which is the node's key in the graph. That is worth
holding onto: `id` is *not* automatically a property, so a query selecting `o.id`
reads a property of that name and gets `None` unless the source emits it in
`properties` as well.

### Continuous queries

Queries are written in Cypher (the default) or GQL, against the graph the sources
produce. Node labels come from the source, which decides how it labels what it emits;
its own documentation is what tells you.

One query can span several sources. That is where Drasi differs from a database view:
the sources can be entirely different systems, and the join between them is maintained
incrementally as either side changes.

### Reactions

A reaction receives result-set diffs. Each diff has a `type`:

| Type | Meaning | Carries |
| --- | --- | --- |
| `ADD` | A row entered the result set | `data` |
| `UPDATE` | A row already in the set changed | `before` and `after` |
| `DELETE` | A row left the result set | `data` |

A reaction can be a Python callable, an async callable, an async iterator you consume
with `async for`, or a plugin such as `dashboard`, `http` or `grpc`.

Note that `DELETE` means *left the result set*, which is not the same as a row being
deleted. Shipping an order removes it from "open orders" without deleting anything.

### Bootstrap

A change feed only tells you what changed *since you started listening*. A query over
a table that already holds a million rows would start empty and stay wrong until every
row happened to be touched.

A **bootstrap provider** closes that gap by loading the current contents when the query
subscribes, after which the change feed takes over. Attach one when you add the source:

```python
await drasi.add_source(
    "postgres",
    "db",
    config,
    bootstrap={"kind": "postgres", **connection},
)
```

Python sources need no bootstrap, because nothing exists before you push it.

## How it runs

The engine is the same Rust implementation Drasi runs in Kubernetes, hosted in your
process through a [PyO3](https://pyo3.rs) extension. There is no broker, no sidecar,
and no network hop between your code and the query engine.

Work happens on a Tokio runtime inside the extension, bridged to `asyncio` so that
awaiting a Drasi call does not block your event loop. Python callbacks are invoked on
your loop, so they can await your own async code.

## Where state lives

By default queries keep their indexes in memory, which is fastest and loses everything
on restart. For state that outlives the process, configure a store when creating the
engine:

- **`state_store`** — component state and reaction checkpoints, backed by
  [redb](https://github.com/cberner/redb).
- **`index_store`** — query indexes, in memory or RocksDB when the wheel was built with
  that feature. `host_info()["index_backends"]` reports which are available.

A durable reaction records how far it got, so after a restart it resumes rather than
replaying from the beginning or silently skipping what it missed.

{{% alert title="Restarting with a Python source loses the first few changes" color="warning" %}}
A query restores its indexes from `index_store` correctly, including after a crash. But
it also restores the sequence number it had reached, while a source added with
`add_python_source()` starts counting from 1 again — it has no durable position of its
own to recover from. Changes whose sequence the query has already seen are discarded, so
the first *K* changes you push after a restart vanish, where *K* is how many you pushed
before it. `push_change()` reports no error.

This is [drasi-core#664](https://github.com/drasi-project/drasi-core/issues/664). Until
it is fixed, treat a restarted Python source as needing its first *K* changes re-sent, or
keep the query's index in memory so it rebuilds from scratch.
{{% /alert %}}

## Next

- [Guides](../guides/) — putting each piece to work.
- [API reference](../api/) — the full surface.
