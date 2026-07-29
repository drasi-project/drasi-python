---
title: "Typing"
linkTitle: "Typing"
weight: 70
description: >
  The shipped type stubs, and the shapes the API accepts and returns.
---

`drasi-lib` ships type information: the package is marked with `py.typed`, the native
extension has a stub, and the shapes it accepts and returns are declared in
`drasi.types`. Type checkers pick all of that up with no configuration.

```python
from drasi import Drasi
from drasi.types import QueryResultEvent, SourceChange


def on_results(event: QueryResultEvent) -> None:
    for diff in event["results"]:
        print(diff["type"])


def order(order_id: str) -> SourceChange:
    return {
        "op": "insert",
        "id": order_id,
        "labels": ["Order"],
        "properties": {"id": order_id, "status": "open"},
    }
```

## TypedDicts, not classes

The shapes are `TypedDict`s rather than dataclasses, so plain dicts keep working. The
types describe what the API accepts; they do not change it. Nothing forces you to
import them, and code written without annotations behaves identically.

Some of the more useful ones:

| Type | Describes |
| --- | --- |
| `SourceChange` | A change pushed into a Python source |
| `QueryResultEvent` | A batch of diffs from a query |
| `ResultDiff` | One way the result set changed |
| `ComponentEvent` | A lifecycle event |
| `LogMessage` | A log line from a component |
| `HostInfo` | Versions and target of this build |
| `StateStore` / `IndexStore` / `Identity` | Engine creation options |
| `InstalledPlugin` / `ResolvedPlugin` / `LockedPlugin` | Plugin metadata |

## Literal types catch typos

Values with a fixed set are `Literal`, so a wrong one is caught before it runs:

```python
ChangeOp = Literal["insert", "add", "update", "delete", "remove"]
DiffType = Literal["ADD", "UPDATE", "DELETE", "aggregation", "noop"]
QueryLanguage = Literal["cypher", "gql"]
RecoveryPolicy = Literal["strict", "auto_reset", "skip_gap"]
```

## Reading a diff

`ResultDiff` always has `type`. Which of `data`, `before` and `after` accompanies it
depends on that type, which a single `TypedDict` cannot express — so those keys are
optional and checked at runtime:

```python
for diff in event["results"]:
    if diff["type"] == "ADD":
        handle(diff["data"])
    elif diff["type"] == "UPDATE":
        handle(diff["before"], diff["after"])
```

If your checker is configured to flag reads of non-required keys, this is the one place
you will see it.

## Plugin configuration is deliberately untyped

Configuration passed to `add_source` and `add_reaction` is a plain mapping, because
those keys belong to the plugin rather than to this library. Ask the plugin what it
accepts instead:

```python
schema = await drasi.source_config_schema("postgres")
```

Typing them here would mean this package claiming to know the shape of every plugin
that exists, and going stale the moment one changes.

## Paths

Anywhere a directory is taken, both `str` and `os.PathLike` work:

```python
from pathlib import Path

await drasi.load_plugins(Path("plugins"))
```

## Next

- [API reference](../../api/) — the full surface.
