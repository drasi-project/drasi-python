---
title: "Query middleware"
linkTitle: "Middleware"
weight: 35
description: >
  Transform changes on their way into a query.
---

Middleware runs over a source's changes before the query sees them, so a query can
match on data that the source does not emit in the shape the query needs.

Declaring middleware and applying it are two steps. A declaration names an instance;
a source's `pipeline` decides where it runs. A declaration nothing refers to does
nothing.

```python
await drasi.add_query(
    "orders-by-city",
    "MATCH (o:Order) RETURN o.id AS id, o.city AS city",
    [{"id": "orders", "pipeline": ["flatten"]}],
    middleware=[
        {
            "name": "flatten",
            "kind": "promote",
            "config": {"mappings": [{"path": "$.address.city", "target_name": "city"}]},
        }
    ],
)
```

The source pushes `{"address": {"city": "Cambridge"}}`, and the query selects `o.city`.
Without the pipeline that column is `None`, because `city` is nested rather than a
property of the node. `promote` lifts it, and the query resolves it.

A source that needs no middleware stays a plain string, and the two forms can be mixed:

```python
await drasi.add_query(
    "orders-by-city",
    QUERY,
    ["payments", {"id": "orders", "pipeline": ["flatten"]}],
    middleware=[...],
)
```

## Available kinds

`kind` selects the middleware type. These are compiled into the wheel:

| Kind | What it does |
| --- | --- |
| `promote` | Lifts a nested value to a top-level property, selected by JSONPath |
| `unwind` | Expands an array property into separate elements |
| `map` | Rewrites a change into one or more different changes |
| `parse_json` | Parses a JSON string property into structured data |
| `decoder` | Decodes an encoded property, such as base64 |
| `relabel` | Renames the labels a change carries |

Each kind reads its own `config`, which is passed through untouched, so what the keys
mean is that middleware's business.

{{% alert title="jq middleware is not included" color="info" %}}
Drasi also has a `jq` middleware, which is not compiled into these wheels: it links
against libjq, and a C dependency would put the cross-compiled Linux and Windows
builds at risk. Naming `kind: "jq"` raises rather than silently doing nothing.
{{% /alert %}}

## Declarative topologies

`from_config` takes the same two keys on a query entry:

```python
drasi = await Drasi.from_config(
    {
        "id": "app",
        "queries": [
            {
                "id": "orders-by-city",
                "query": "MATCH (o:Order) RETURN o.id AS id, o.city AS city",
                "sources": [{"id": "orders", "pipeline": ["flatten"]}],
                "middleware": [
                    {
                        "name": "flatten",
                        "kind": "promote",
                        "config": {"mappings": [{"path": "$.address.city", "target_name": "city"}]},
                    }
                ],
            }
        ],
    }
)
```

## Failures

A middleware problem stops the query being registered rather than degrading it, so
these raise:

- a `kind` no middleware is registered for
- a `pipeline` naming a middleware that was not declared
- a declaration missing `name` or `kind`
- a `config` the middleware itself rejects

## Next

- [Python sources](../python-sources/) — pushing the changes middleware transforms.
- [API reference](../../api/) — the full `add_query` signature.
