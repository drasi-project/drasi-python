---
title: "Error handling"
linkTitle: "Error handling"
weight: 50
description: >
  The typed exception hierarchy and the stable error codes behind it.
---

Every failure raised by `drasi-lib` is a `DrasiError` or a subclass of one, and carries
a stable `code` you can branch on.

```python
from drasi import DrasiError

try:
    await drasi.add_query("open", "MATCH (o:Order", ["orders"])
except DrasiError as err:
    print(err.code, err)
```

## The hierarchy

```text
DrasiError
├── ConfigError
├── UnknownKindError
├── SourceError
├── StreamLaggedError
└── PluginError
    ├── PluginNotFoundError
    ├── PluginCompatibilityError
    └── PluginSignatureError
```

Catching `DrasiError` catches everything from the library and nothing from anywhere
else, so it is safe to wrap a whole block. Catching a subclass narrows to one kind of
problem — `PluginSignatureError` on its own, say, if an unverified plugin should be
fatal but a missing one should not.

## Branch on the code, not the message

Messages are written for people and may be reworded. The `code` is part of the API:

```python
from drasi import DrasiError

try:
    await drasi.push_change("orders", change)
except DrasiError as err:
    if err.code == "CHANGE_OP_REQUIRED":
        raise ValueError(f"malformed change from {origin}") from err
    raise
```

The full set is available at runtime as `drasi.ERROR_CODES`.

## The codes

| Code | Raised when |
| --- | --- |
| `UNKNOWN_SOURCE_KIND` | No source plugin is registered for that kind |
| `UNKNOWN_REACTION_KIND` | No reaction plugin is registered for that kind |
| `UNKNOWN_BOOTSTRAP_KIND` | No bootstrap plugin is registered for that kind |
| `BOOTSTRAP_KIND_REQUIRED` | A bootstrap block was given without a `kind` |
| `MISSING_CONFIG_FIELD` | A required configuration field was absent |
| `NO_PY_SOURCE` | The id does not name a Python-defined source |
| `PY_SOURCE_CLOSED` | The source was removed while a change was in flight |
| `CHANGE_NOT_OBJECT` | The change was not a mapping |
| `CHANGE_OP_REQUIRED` | The change had no `op` |
| `CHANGE_ID_REQUIRED` | The change had no `id` |
| `RELATION_REQUIRES_BOTH_ENDS` | Only one of `start_id` / `end_id` was supplied |
| `UNKNOWN_CHANGE_OP` | The `op` was not insert, update or delete |
| `STATE_STORE_PATH_REQUIRED` | A durable state store was configured without a path |
| `UNKNOWN_STATE_STORE_KIND` | The state store kind is not one this build supports |
| `INDEX_STORE_PATH_REQUIRED` | An index store was configured without a path |
| `UNKNOWN_INDEX_STORE_KIND` | The index store kind is not compiled into this wheel |
| `IDENTITY_KIND_REQUIRED` | An identity block was given without a `kind` |
| `UNKNOWN_IDENTITY_KIND` | No identity provider matches that kind |
| `IDENTITY_CONFIG_INVALID` | The identity block is missing fields its kind needs |
| `DURABLE_REQUIRES_STATE_STORE` | A durable reaction was added without a state store |
| `UNKNOWN_QUERY_LANGUAGE` | The language was not `cypher` or `gql` |
| `CONFIG_INVALID` | The configuration was malformed |
| `PLUGIN_SIGNATURE_INVALID` | Signature verification failed |
| `PLUGIN_INCOMPATIBLE` | The plugin was built against a different Drasi version |
| `PLUGIN_NOT_FOUND` | No such plugin in the registry, or no build for this platform |
| `STREAM_LAGGED` | A stream dropped items because they were not consumed fast enough |
| `ENGINE_CLOSED` | The engine was closed and then asked to change |
| `ENGINE_FAILURE` | The engine itself reported a failure |

## Errors raised before the await

Arguments are validated on the call, not when the coroutine is awaited:

```python
pending = drasi.push_change("orders", {"id": "o1"})  # raises here
```

This matters because a coroutine that raises only when awaited is easy to create and
forget, and the failure then surfaces somewhere unrelated — or not at all if it is
never awaited.

## Using a closed engine

Once `close()` has been called, anything that would change the engine raises
`ENGINE_CLOSED`:

```python
await drasi.close()
await drasi.add_query(...)  # ENGINE_CLOSED
```

Reads are still allowed, because inspecting a closed engine is harmless and often
useful. The alternative — accepting a component that can never run — hid the mistake
until much later.

## Next

- [Plugins](../plugins/) — the plugin-specific failures in context.
- [API reference](../../api/) — the full surface.
