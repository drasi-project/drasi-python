---
title: "Python reactions"
linkTitle: "Python reactions"
weight: 20
description: >
  Handle result-set diffs in your own code, including across restarts.
---

A reaction receives the diffs a continuous query produces. The simplest is a callable:

```python
def on_results(event):
    for diff in event["results"]:
        if diff["type"] == "ADD":
            print("entered:", diff["data"])
        elif diff["type"] == "DELETE":
            print("left:", diff["data"])
        else:
            print("changed:", diff["before"], "->", diff["after"])


await drasi.add_python_reaction("watch", ["open-orders"], on_results)
```

One reaction can watch several queries. The event carries which query produced it, so
a single handler can serve them all.

## Async callbacks

An async callable works the same way, and is awaited on your event loop, so it can do
async work of its own:

```python
async def on_results(event):
    async with httpx.AsyncClient() as client:
        for diff in event["results"]:
            await client.post("https://example.com/hook", json=diff)


await drasi.add_python_reaction("webhook", ["open-orders"], on_results)
```

## Which keys a diff carries

`type` is always present. What comes with it depends on the type:

| `type` | Carries |
| --- | --- |
| `ADD` | `data` |
| `UPDATE` | `before` and `after` |
| `DELETE` | `data` |

Reading `data` on an `UPDATE` gets you nothing, so branch on `type` first.

## Durable reactions

An ordinary reaction starts from scratch after a restart: whatever was delivered while
the process was down is gone. A **durable** reaction records how far it got, and
resumes from there.

It needs a state store, configured when the engine is created:

```python
drasi = await Drasi.create(
    "app",
    state_store={"kind": "redb", "path": "/var/lib/myapp/drasi"},
)
```

Then register the reaction with a recovery policy:

```python
async def on_results(event): ...


await drasi.add_durable_python_reaction(
    "billing",
    ["open-orders"],
    on_results,
    recovery_policy="strict",
)
```

The policy decides what happens when the recorded checkpoint **cannot be satisfied** —
for example when the data it referred to is no longer available after a restart:

| Policy | Behaviour |
| --- | --- |
| `strict` | Refuse to start rather than deliver an incomplete stream. The default. |
| `auto_reset` | Start again from the current position, accepting the gap. |
| `skip_gap` | Continue past the gap and carry on from what is available. |

`strict` is the default: the alternatives accept data loss.

{{% alert title="Durable reactions must be async" color="warning" %}}
The reaction loop runs off your event loop, so a plain function cannot be awaited
there. Registering one raises immediately.
{{% /alert %}}

Checkpoints advance only after your callback returns without raising. If it raises, the
checkpoint stays where it was and the event is delivered again on the next attempt.

## Reading results directly

A reaction is push-based. To pull the current result set instead:

```python
rows = await drasi.get_query_results("open-orders")
```

That returns the full result set as it stands, which is useful for rendering an initial
view before switching to diffs.

## Removing a reaction

```python
await drasi.remove_reaction("watch")
```

Removing a reaction does not affect the query. Removing a *query* that a reaction still
depends on is refused, so you cannot leave a reaction subscribed to something that no
longer exists.

## Next

- [Streaming results](../streaming/) — the same data as an async iterator.
- [Error handling](../error-handling/) — what a failing callback does.
