---
title: "Getting Started"
linkTitle: "Getting Started"
weight: 10
description: >
  Install drasi-lib and run your first continuous query.
---

## Install

```bash
pip install drasi-lib
```

The distribution is named `drasi-lib` and imported as `drasi`:

```python
import drasi
```

Wheels are [abi3](https://docs.python.org/3/c-api/stable.html) for **Python 3.10 and
newer**, published for Linux (x86_64, aarch64), macOS (x86_64, arm64) and Windows
(x86_64). One wheel per platform covers every supported Python version, and no Rust
toolchain is needed to install.

## Your first continuous query

This pushes changes into a Python-defined source and prints each way the result set
changes. It needs nothing but the package:

```python
import asyncio

from drasi import Drasi

OPEN_ORDERS = """
MATCH (o:Order)
WHERE o.status = 'open'
RETURN o.id AS id, o.total AS total
"""


async def main() -> None:
    async with await Drasi.create("my-app") as drasi:
        await drasi.start()

        await drasi.add_python_source("orders")
        await drasi.add_query("open", OPEN_ORDERS, ["orders"])

        def on_results(event):
            for diff in event["results"]:
                print(diff["type"], diff.get("data") or diff.get("after"))

        await drasi.add_python_reaction("watch", ["open"], on_results)

        await drasi.push_change(
            "orders",
            {
                "op": "insert",
                "id": "o1",
                "labels": ["Order"],
                "properties": {"id": "o1", "status": "open", "total": 42},
            },
        )
        await asyncio.sleep(1)

        print(await drasi.get_query_results("open"))


asyncio.run(main())
```

Running it prints an `ADD` diff as the order enters the result set, then the current
result set.

## What each piece does

- **`Drasi.create(...)`** builds an engine. Used as an `async with`, it closes for you.
- **`start()`** starts the engine and every component set to auto-start.
- **`add_python_source(...)`** registers a source you push changes into from your own
  code. For real systems, load a [plugin](../guides/plugins/) instead.
- **`add_query(...)`** registers a continuous query. It re-evaluates incrementally as
  changes arrive, rather than re-running over the whole dataset.
- **`add_python_reaction(...)`** receives the diffs — what was added, updated and
  removed — as the result set changes.

## Ordering

Adding components before `start()` and after it both work. The example above starts
first, which is the pattern used throughout these docs.

## Not using asyncio?

Every method has a blocking counterpart in `drasi.sync`, for scripts, notebooks and
anywhere `async` would be awkward:

```python
import time

from drasi.sync import Drasi

OPEN_ORDERS = """
MATCH (o:Order)
WHERE o.status = 'open'
RETURN o.id AS id, o.total AS total
"""

with Drasi.create("script") as drasi:
    drasi.start()
    drasi.add_python_source("orders")
    drasi.add_query("open", OPEN_ORDERS, ["orders"])
    drasi.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 42},
        },
    )
    # A query processes changes asynchronously, so give it a moment before
    # reading the result set. `query_results` is the alternative: it yields each
    # change as it lands rather than making you guess how long to wait.
    time.sleep(1)
    print(drasi.get_query_results("open"))
```

See [the blocking API](../guides/blocking-api/) for the details.

## Connecting to a real system

Python-defined sources are the quickest way to see the engine work, but most
applications follow an existing system. Drasi publishes source, reaction and
bootstrap plugins to `ghcr.io/drasi-project`, and `drasi-lib` can resolve, download,
verify and load them at runtime:

```python
await drasi.install_plugin("source/postgres")
await drasi.install_plugin("bootstrap/postgres")
await drasi.start()

await drasi.add_source(
    "postgres",
    "db",
    {
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "password": "postgres",
        "database": "app",
        "tables": ["public.orders"],
        "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],
    },
    bootstrap={
        "kind": "postgres",
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "password": "postgres",
        "database": "app",
    },
)
```

The [plugins guide](../guides/plugins/) covers searching the registry, pinning
versions, signature verification and lockfiles. The [Postgres dashboard
example](../examples/postgres-dashboard/) puts the whole thing together.

## Next

- [Concepts](../concepts/) — how the change-driven model fits together.
- [Guides](../guides/) — sources, reactions, plugins, streaming and errors.
- [API reference](../api/) — every method, grouped by area.
