---
title: "The blocking API"
linkTitle: "Blocking API"
weight: 60
description: >
  drasi.sync for scripts, notebooks and anywhere async would be awkward.
---

`drasi.sync.Drasi` mirrors the async API method for method, minus the `await`. It suits
scripts, notebooks, test fixtures and existing synchronous code that has no event loop
to hand.

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
    drasi.wait_for_query("open")

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

Note `with`, not `async with`, and `Drasi.create(...)` returning the engine directly
rather than an awaitable.

## Streams become ordinary iterators

```python
for event in drasi.query_results("open"):
    for diff in event["results"]:
        print(diff["type"])
```

Callbacks work unchanged, and are invoked from the background loop:

```python
drasi.on_query_results("open", lambda event: print(event))
```

## How it works

The engine is inherently asynchronous, so the sync facade runs an asyncio loop on a
background thread and submits work to it. That thread is shared by every sync engine in
the process, so creating several is cheap.

The consequence worth knowing: **do not use `drasi.sync` from inside a running event
loop.** Blocking the loop to wait on the background thread is a deadlock waiting to
happen. In async code, use `drasi.Drasi` directly — that is what it is for.

## Choosing between them

| Use | When |
| --- | --- |
| `drasi.Drasi` | Your code is already async, or you need concurrency |
| `drasi.sync.Drasi` | A script, a notebook, a synchronous service, or a quick experiment |

Both drive the same engine, so neither is a reduced version of the other.

## Next

- [API reference](../../api/) — every method, with the sync equivalents noted.
