# Examples

Runnable programs demonstrating `drasi-lib`.

> These examples run against the code in **this repository**, not the released
> package, so that what you are running is what you have changed. You build it
> locally in one step below. If you only want to use Drasi rather than work on
> it, `pip install drasi-lib` and skip to [the examples](#run-them).

## Build the local package

You need:

- **Rust** — stable toolchain ([rustup.rs](https://rustup.rs))
- **Python 3.10+** — the extension targets the abi3 stable ABI, so the
  interpreter you build with must be at least 3.10
- **[uv](https://docs.astral.sh/uv/)** — optional, but the commands below use it

From the repository root:

```bash
make venv        # create .venv with a managed Python and the dev tooling
make develop     # compile the Rust extension and install it into .venv, editable
```

The first build compiles the Drasi engine and takes a few minutes. Later builds
are incremental.

<details>
<summary>Without <code>make</code> or <code>uv</code></summary>

```bash
python3.12 -m venv .venv
.venv/bin/pip install maturin
VIRTUAL_ENV="$PWD/.venv" .venv/bin/maturin develop
```

Built this way the environment has `pip`, so anywhere this guide runs
`uv pip install --python .venv/bin/python ...` you can use
`.venv/bin/pip install ...` instead.

</details>

Check it worked:

```bash
.venv/bin/python -c "import drasi; print(drasi.host_info())"
```

```
{'arch_suffix': 'darwin-arm64', 'core_version': '0.5.7',
 'ffi_sdk_version': '0.11.0', 'lib_version': '0.8.9',
 'sdk_version': '0.10.0', 'target_triple': 'aarch64-apple-darwin'}
```

(Your `target_triple` and `arch_suffix` will reflect your own machine.)

`make develop` installs the package as **editable**, so Python changes under
`python/drasi/` take effect immediately. After changing anything under `src/`
(Rust), re-run `make develop`.

## Run them

Use the interpreter from `.venv`, or activate it first:

```bash
source .venv/bin/activate   # then plain `python examples/...` works
```

| Example | What it shows | Needs |
| --- | --- | --- |
| [`python_source.py`](./python_source.py) | Push changes from your own code; react to results | nothing |
| [`install_plugin.py`](./install_plugin.py) | Browse the registry, install a plugin, use it | network |
| [`streaming.py`](./streaming.py) | Watch a query change, without polling | nothing |
| [`sync_quickstart.py`](./sync_quickstart.py) | The blocking API, for scripts | nothing |
| [`postgres_cdc.py`](./postgres_cdc.py) | React to a real Postgres database | Docker, network |

`_throwaway_postgres.py` is support code for the last one, not an example.

### `python_source.py`

The smallest useful program: define a source in Python, push order changes into
it, and watch a continuous query recompute. No plugins, no network, no database.

```bash
.venv/bin/python examples/python_source.py
```

```
placing two orders
  + {'customer': 'Ada', 'id': 'o1', 'total': 42}
  + {'customer': 'Grace', 'id': 'o2', 'total': 17}
shipping o1 — it should leave the result set
  - {'customer': 'Ada', 'id': 'o1', 'total': 42}

still open: [{'customer': 'Grace', 'id': 'o2', 'total': 17}]
```

Note the third line: shipping an order does not delete it, but it no longer
matches `WHERE o.status = 'open'`, so the query reports it as removed from the
result set.

### `streaming.py`

Three different things can be streamed, and they are easy to confuse: the diffs
a query produces, the lifecycle events of a component, and its log lines. This
shows the first two.

```bash
.venv/bin/python examples/streaming.py
```

```
watching for changes to the open orders...

  + {'id': 'o1', 'total': 42}
  + {'id': 'o2', 'total': 17}
  - {'id': 'o1', 'total': 42}  (no longer open)

how the query got here:
  Added: query added
  Starting: Starting query
  Running: Query started successfully

still open: [{'id': 'o2', 'total': 17}]
```

### `sync_quickstart.py`

The same engine without `await`, for scripts and notebooks. Streams become
ordinary iterators.

```bash
.venv/bin/python examples/sync_quickstart.py
```

### `install_plugin.py`

Lists everything published to `ghcr.io/drasi-project`, then installs the mock
source and runs a query against it. `install_plugin()` picks the build that
matches your machine, so you never deal with architecture tags.

```bash
.venv/bin/python examples/install_plugin.py
```

```
host: aarch64-apple-darwin
  drasi-core 0.5.7, drasi-lib 0.8.9
  plugin sdk 0.10.0, ffi abi 0.11.0

56 plugins published; sources include:
  cloudflare-radar, dataverse, grpc, gtfs-rt, here-traffic, http, ...

source/mock resolves to 0.2.7 for aarch64-apple-darwin
installed to /tmp/drasi-python-plugins/plugin-demo/libdrasi_source_mock.dylib
signature: unsigned

counter rows: [{'value': 1}]
```

The plugin is downloaded to a temporary directory, so the first run needs
network access and later runs re-download it.

### `postgres_cdc.py`

Installs the `source/postgres` plugin, points it at a database, and prints what
the query sees as rows change via plain SQL.

Starting the database is scaffolding rather than the point, so it lives in
[`_throwaway_postgres.py`](./_throwaway_postgres.py). To run against your own
database, pass your connection details to `add_source` and ignore that file.

```bash
make example-postgres
```

or, doing it by hand:

```bash
uv pip install --python .venv/bin/python "testcontainers>=4.15" "psycopg[binary]"
.venv/bin/python examples/postgres_cdc.py
```

`make venv` builds the environment with [uv](https://docs.astral.sh/uv/), which
deliberately does not install `pip` into it — hence `uv pip install --python`
rather than `.venv/bin/pip`.

```
starting postgres (first run pulls the image)
installing the postgres source plugin

inserting two orders
  + {'customer': 'Ada', 'id': 1}
  + {'customer': 'Grace', 'id': 2}
shipping order 1 — it should leave the result set
  - {'customer': 'Ada', 'id': 1}
deleting order 2
  - {'customer': 'Grace', 'id': 2}

still open: []
```

The container is removed when the example exits.

## Seeing what the engine is doing

The engine logs at `INFO`, which buries an example's own output, so the examples
default to `warn`. Override it to watch queries subscribe, plugins load and
changes propagate:

```bash
RUST_LOG=info .venv/bin/python examples/python_source.py
```

## Things that trip people up

These fail quietly rather than loudly, so they are worth knowing up front.

**Cypher string literals are single-quoted.** `WHERE o.status = "open"` is a
parse error; use `'open'`.

**A change's `id` is the graph key, not a property.** A query selecting `o.id`
reads a *property* named `id`, so your source has to emit it:

```python
await drasi.push_change(
    "orders",
    {
        "op": "insert",
        "id": "o1",  # the graph key
        "labels": ["Order"],
        "properties": {"id": "o1", "status": "open"},  # ...and the property
    },
)
```

Get this wrong and rows come back with `{'id': None}` rather than an error.

**Start the engine before adding components.** They auto-start individually.
Adding everything first and then calling `start()` also works, but logs a
spurious "already running" error for each one.

**`add_query` returns before the query is running.** It finishes starting in the
background, so reading results immediately can raise "is not running". Await
`wait_for_query(id)` when you need to read straight away.

**Plugin config keys belong to the plugin.** Drasi's own API is snake_case, but
a plugin that declares `intervalMs` wants exactly that. Ask it what it accepts:

```python
schema = await drasi.source_config_schema("postgres")
print(schema["name"], schema["schema"])
```

See [`docs/plugins.md`](../docs/plugins.md) for more, including a sharp edge in
the Postgres source's `tableKeys`.

## Writing your own

The [`tests/e2e/`](../tests/e2e) directory is the most complete set of worked
examples — queries with joins, relations, GQL, signature verification, plugin
compatibility failures and change-data-capture against a real database.
