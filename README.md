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

> Status: early development. See `docs/` for design notes.

## Install

```bash
pip install drasi-lib
```

## Quickstart

```python
import asyncio
from drasi import Drasi


async def main() -> None:
    async with await Drasi.create("my-app") as drasi:
        # Resolve a compatible build for this machine, download, verify and load it.
        await drasi.install_plugin("source/mock")
        await drasi.start()

        await drasi.add_source(
            "mock", "counters", {"data_type": {"type": "counter"}, "interval_ms": 500}
        )
        await drasi.add_query(
            "big",
            "MATCH (c:Counter) WHERE c.value > 3 RETURN c.value AS value",
            sources=["counters"],
        )

        async for event in drasi.query_events("big"):
            for diff in event.results:
                print(diff.kind, diff.data)


asyncio.run(main())
```

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

## Development

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python maturin pytest pytest-asyncio pytest-timeout ruff
VIRTUAL_ENV="$PWD/.venv" .venv/bin/maturin develop
.venv/bin/pytest
```

Building requires a Rust toolchain. The optional `rocksdb` feature additionally
requires `libclang` and a C++ toolchain.

## License

Apache-2.0. See [LICENSE](./LICENSE).
