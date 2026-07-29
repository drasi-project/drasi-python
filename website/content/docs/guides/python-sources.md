---
title: "Python sources"
linkTitle: "Python sources"
weight: 10
description: >
  Push changes into the engine from your own code.
---

A Python source is one you feed yourself. Register it, then call `push_change` when
your application changes something worth querying.

```python
await drasi.add_python_source("orders")
```

## Pushing a node

```python
await drasi.push_change(
    "orders",
    {
        "op": "insert",
        "id": "o1",
        "labels": ["Order"],
        "properties": {"id": "o1", "status": "open", "total": 42},
    },
)
```

`op` is one of `insert`, `update` or `delete`. The aliases `add` and `remove` are
accepted, and the value is case-insensitive, so `INSERT` works too.

{{% alert title="id is the key, not a property" color="warning" %}}
`id` identifies the node in the graph. A query selecting `o.id` reads a *property*
called `id`, so emit it in `properties` as well or the column comes back `None` — with
no error to tell you why.
{{% /alert %}}

## Updating and deleting

An update replaces the node's properties:

```python
await drasi.push_change(
    "orders",
    {
        "op": "update",
        "id": "o1",
        "labels": ["Order"],
        "properties": {"id": "o1", "status": "shipped", "total": 42},
    },
)
```

A delete needs only the key:

```python
await drasi.push_change("orders", {"op": "delete", "id": "o1", "labels": ["Order"]})
```

## Relations

Supplying `start_id` and `end_id` makes the change a relation rather than a node:

```python
await drasi.push_change(
    "graph",
    {"op": "insert", "id": "r1", "labels": ["OWNS"], "start_id": "c1", "end_id": "o1"},
)
```

The Node.js spellings `startId`/`endId` and `inId`/`outId` are accepted too, so a
change built for `@drasi/lib` can be passed straight through.

Both endpoints must exist before the relation is pushed, or the change is rejected.

## Validation happens early

A malformed change raises immediately, on the call rather than the await:

```python
pending = drasi.push_change("orders", {"id": "o1"})  # raises here
```

The error carries a code you can branch on — `CHANGE_OP_REQUIRED` in that case. See
[error handling](../error-handling/).

## Concurrency

`push_change` is safe to call concurrently on the same source. Dispatch is serialised
internally, so changes reach queries in the order their sequence numbers were assigned:

```python
await asyncio.gather(*(drasi.push_change("orders", order(i)) for i in range(100)))
```

## Ordering with respect to queries

A query only sees changes that arrive after it subscribes. Push before the query is
running and those changes are simply not in its result set — there is no error, and
nothing to notice later. Wait for the query first:

```python
await drasi.add_query("open", OPEN_ORDERS, ["orders"])
await drasi.wait_for_query("open")
await drasi.push_change("orders", ...)
```

For a source backed by a real system, use a [bootstrap
provider](../../concepts/#bootstrap) instead, which loads what already exists.

## Next

- [Python reactions](../python-reactions/) — receiving the diffs.
- [Streaming results](../streaming/) — consuming them as an async iterator.
