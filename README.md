# drasi-lib

[![PyPI version](https://img.shields.io/pypi/v/drasi-lib)](https://pypi.org/project/drasi-lib/)
[![Python versions](https://img.shields.io/pypi/pyversions/drasi-lib)](https://pypi.org/project/drasi-lib/)
[![license](https://img.shields.io/pypi/l/drasi-lib)](https://github.com/drasi-project/drasi-python/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-drasi--project.github.io-blue)](https://drasi-project.github.io/drasi-python/)

📖 **Documentation: <https://drasi-project.github.io/drasi-python/>** — installation,
concepts, the full API reference, guides, and a worked example.

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

> Status: pre-1.0. The API is complete — full parity with
> `@drasi/lib` plus streaming as async iterators, a blocking facade, and
> plugin lockfiles. See [`docs/api-audit.md`](https://github.com/drasi-project/drasi-python/blob/main/docs/api-audit.md).

## Install

```bash
pip install drasi-lib
```

Imported as `drasi`. Wheels are abi3 for Python 3.10+ on Linux (x86_64,
aarch64), macOS (x86_64, arm64) and Windows (x86_64), so no Rust toolchain is
needed. To build from source instead, see [Development](#development), or
[`examples/README.md`](https://github.com/drasi-project/drasi-python/blob/main/examples/README.md) for a step-by-step walkthrough.

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

See the [plugins guide](https://drasi-project.github.io/drasi-python/docs/guides/plugins/), or
[`docs/plugins.md`](https://github.com/drasi-project/drasi-python/blob/main/docs/plugins.md)
for the contributor-facing detail.

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

[`docs/api-audit.md`](https://github.com/drasi-project/drasi-python/blob/main/docs/api-audit.md) inventories the public API and
compares it against the Node.js bindings and the Rust engine. It is at full
parity — 48/48 methods — plus 21 methods Node does not have.

## Examples

Runnable programs are in [`examples/`](https://github.com/drasi-project/drasi-python/tree/main/examples), with a guide covering how to
build the package locally and run them. The documentation site also has a worked
[Postgres dashboard](https://drasi-project.github.io/drasi-python/docs/examples/postgres-dashboard/)
example built entirely on published plugins.

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
requires `libclang` and a C++ toolchain. See [CONTRIBUTING.md](https://github.com/drasi-project/drasi-python/blob/main/CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](https://github.com/drasi-project/drasi-python/blob/main/LICENSE).
