---
title: "Streaming results"
linkTitle: "Streaming"
weight: 30
description: >
  Consume results, component events and logs as async iterators.
---

Anything you can receive through a callback can also be consumed as an async iterator,
which usually reads better and lets you use ordinary control flow.

## Query results

```python
async for event in await drasi.query_results("open-orders"):
    for diff in event["results"]:
        print(diff["type"], diff.get("data"))
```

The stream ends when it is closed or the engine shuts down. Breaking out of the loop
closes it.

Each stream is backed by its own reaction. Pass `reaction_id` to name it, which makes
it visible to `list_reactions` and lets you remove it explicitly:

```python
stream = await drasi.query_results("open-orders", reaction_id="ui-feed")
```

## Component events and logs

The same shape covers lifecycle events and logs, which is how you watch a component
start, fail or report progress:

```python
async for event in await drasi.query_events("open-orders"):
    print(event["status"], event["message"])

async for entry in await drasi.source_logs("db"):
    print(entry["level"], entry["message"])
```

| Stream | What it carries |
| --- | --- |
| `query_results(id)` | Result-set diffs |
| `query_events(id)` / `source_events(id)` / `reaction_events(id)` | Lifecycle events for one component |
| `all_events()` | Lifecycle events for every component |
| `query_logs(id)` / `source_logs(id)` / `reaction_logs(id)` | Log lines from one component |

## Callback form

Every stream has a callback counterpart, for when a background subscription suits
better than a loop:

```python
await drasi.on_query_results("open-orders", lambda event: print(event))
await drasi.on_all_events(lambda event: print(event["component_id"], event["status"]))
```

These exist mainly for parity with the Node.js binding; the iterator form is usually
the more natural one in Python.

## Falling behind

A stream has a bounded buffer. A consumer slower than the producer would otherwise grow
memory without limit, so the stream drops the oldest items and tells you rather than
quietly losing them:

```python
from drasi import StreamLaggedError

try:
    async for event in await drasi.query_results("open-orders"):
        await slow_work(event)
except StreamLaggedError as err:
    print("fell behind:", err)
```

The message says how many items were dropped, so you can decide whether to re-read the
full result set with `get_query_results` and carry on, or treat it as an error.

Being told is the point: silently dropping events is exactly the failure that makes a
dashboard drift from reality with nothing in the logs.

## Ending a stream

Iteration ends when the engine stops producing, so closing the engine terminates any
open stream rather than leaving it hanging. Breaking out of the loop stops consuming,
and the stream is cleaned up when it goes out of scope:

```python
async for event in await drasi.query_results("open-orders"):
    if done(event):
        break
```

If you named the stream's reaction with `reaction_id`, you can also remove it
explicitly with `remove_reaction`.

## Next

- [Python reactions](../python-reactions/) — the push-based equivalent.
- [Error handling](../error-handling/) — the exception hierarchy.
