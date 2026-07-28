# drasi-lib

Embed the [Drasi](https://drasi.io) continuous-query engine directly in your
Python application. `drasi-lib` is a native [PyO3](https://pyo3.rs) binding
around Drasi's embeddable engine (`drasi-lib`) and its plugin host SDK
(`drasi-host-sdk`), so you get:

- **In-process continuous queries** over a property graph, in Cypher or GQL.
- **A working plugin ecosystem** — search, resolve, download, verify and install
  the Drasi source/reaction/bootstrap plugins published to
  `ghcr.io/drasi-project`, picking the build that is compatible with your host.
- **Python-defined components** — define a reaction as a Python callback, or a
  source you push changes into from your own code. No Rust required.
- **Streaming** — `async for event in drasi.query_results(id)`, plus lifecycle
  events and component logs.
- **A blocking API** — `drasi.sync.Drasi` for scripts and notebooks.

> Status: pre-1.0, not yet on PyPI. The API is complete — full parity with
> `@drasi/lib` plus streaming as async iterators, a blocking facade, and
> plugin lockfiles. See [`docs/api-audit.md`](./docs/api-audit.md).

## Install

> Not published to PyPI yet. Build it from source — see
> [Development](#development), or [`examples/README.md`](./examples/README.md)
> for a step-by-step walkthrough.

```bash
pip install drasi-lib   # once released
```

## Quickstart

Push changes from your own code and react to the results — no plugins needed:

```python
import asyncio
from drasi import Drasi


async def main() -> None:
    async with await Drasi.create("my-app") as drasi:
        await drasi.start()

        await drasi.add_python_source("orders")
        await drasi.add_query(
            "open",
            "MATCH (o:Order) WHERE o.status = 'open' RETURN o.id AS id, o.total AS total",
            ["orders"],
        )

        def on_results(event):
            for diff in event["results"]:
                print(diff["type"], diff.get("data"))

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
        await asyncio.sleep(0.5)
        print(await drasi.get_query_results("open"))


asyncio.run(main())
```

Three things that are easy to get wrong:

- Call `start()` **first**, then add components; they auto-start individually.
  Adding everything and then calling `start()` also works, but logs a spurious
  "already running" error for each component.
- Drasi's Cypher dialect uses **single-quoted** string literals.
- A change's `id` is the graph **key**, not a property. A query selecting `o.id`
  reads a property of that name, so emit it explicitly.

`add_query` returns once the query is provisioned; it finishes starting in the
background, so reading results immediately can raise "is not running". Await
`wait_for_query(id)` if you need to read straight away.

## Using a plugin

`install_plugin()` resolves the build that is compatible with your machine,
downloads it, verifies it and loads it:

```python
async with await Drasi.create("my-app") as drasi:
    await drasi.install_plugin("source/mock")
    await drasi.start()

    await drasi.add_source("mock", "counters", {"dataType": {"type": "counter"}, "intervalMs": 500})
    await drasi.add_query("counts", "MATCH (c:Counter) RETURN c.value AS value", ["counters"])
```

Browse what is available first, if you like:

```python
for plugin in await drasi.search_plugins():
    print(plugin["reference"])  # e.g. source/postgres, reaction/http
```

Plugin configuration keys are defined by the plugin itself, so they are passed
through untouched — `dataType` above is the mock source's own spelling. Drasi's
own API is snake_case, and accepts the Node.js camelCase spellings as aliases.

## Plugins

Drasi plugins are self-contained `cdylib` files distributed as OCI artifacts
from `ghcr.io/drasi-project`, published per platform:

```
ghcr.io/drasi-project/{type}/{kind}:{version}-{arch}
```

Because a plugin is a native library loaded into your process, it is only usable
by a host built against a compatible set of Drasi crates. `install_plugin()`
handles this for you — it reads the registry index, picks the newest build whose
`sdk`/`core`/`lib` versions and target triple match this host, downloads it,
optionally verifies its cosign signature, and loads it.

See [`docs/plugins.md`](./docs/plugins.md).

## Watching a query

Polling is rarely what you want:

```python
async for event in await drasi.query_results("open"):
    for diff in event["results"]:
        print(diff["type"], diff.get("data"))
```

Lifecycle events (`query_events`, `source_events`, `reaction_events`,
`all_events`) and logs (`query_logs`, `source_logs`, `reaction_logs`) stream the
same way, and replay their history first. Callback forms (`on_query_results`,
`on_*_events`, `on_*_logs`) exist for parity with the Node.js binding.

## Without async

```python
from drasi.sync import Drasi

with Drasi.create("my-app") as drasi:
    drasi.start()
    drasi.add_python_source("orders")
    print(drasi.get_query_results("open"))
```

Streams become ordinary iterators. Don't use this inside an existing event loop
— it will tell you so rather than deadlocking.

## Durability

A durable reaction only advances its checkpoint once your callback succeeds, so
an unhandled event is replayed after a restart:

```python
drasi = await Drasi.create("app", state_store={"kind": "redb", "path": "state.redb"})


async def handle(event):
    await write_somewhere(event)  # if this raises, the event is retried


await drasi.add_durable_python_reaction("sink", ["open"], handle)
```

## Status

[`docs/api-audit.md`](./docs/api-audit.md) inventories the public API and
compares it against the Node.js bindings and the Rust engine. It is at full
parity — 48/48 methods — plus 21 methods Node does not have.

## Examples

Runnable programs are in [`examples/`](./examples), with a guide covering how to
build the package locally and run them:

| Example | What it shows | Needs |
| --- | --- | --- |
| `python_source.py` | Push changes from your own code; react to results | nothing |
| `install_plugin.py` | Browse the registry, install a plugin, use it | network |
| `postgres_cdc.py` | React to a real Postgres database | Docker, network |

```bash
make venv && make develop
.venv/bin/python examples/python_source.py
```

## Development

```bash
make venv        # create .venv with a managed Python and the dev tooling
make develop     # build the native extension and install it editable
make test        # unit tests + hermetic end-to-end tests
make test-oci    # download and install real plugins from ghcr.io
```

Building requires a Rust toolchain. The optional `rocksdb` feature additionally
requires `libclang` and a C++ toolchain. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](./LICENSE).
