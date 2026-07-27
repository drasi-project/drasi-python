# Contributing to drasi-python

Thanks for your interest in improving the Drasi Python bindings.

## Developer Certificate of Origin

All commits must be signed off under the
[Developer Certificate of Origin](https://developercertificate.org/):

```bash
git commit -s -m "your message"
```

This adds a `Signed-off-by:` trailer certifying that you wrote the patch, or
otherwise have the right to submit it under the project's Apache-2.0 license.

## Prerequisites

- **Rust** — stable toolchain (see `rust-toolchain.toml`).
- **Python 3.10+** — the extension is built against the abi3 stable ABI, so the
  build interpreter must be at least 3.10.
- **[uv](https://docs.astral.sh/uv/)** — used to provision Python and the venv.
- **A C++ toolchain and `libclang`** — only for the optional `rocksdb` feature,
  which builds `librocksdb-sys` via `bindgen`:
  - Linux: `sudo apt-get install -y clang libclang-dev`
  - Windows: install LLVM and set `LIBCLANG_PATH` to its `bin` directory
  - macOS: ships with the Xcode Command Line Tools
- **Docker** — only for tier 3 tests.

## Getting started

```bash
make venv       # create .venv with a managed Python and the dev tooling
make develop    # build the native extension and install it editable
make test       # unit tests + hermetic end-to-end tests
```

`make help` lists every target.

## Project layout

| Path | Contents |
| --- | --- |
| `src/` | The PyO3 binding layer (Rust) |
| `python/drasi/` | The Python facade, type stubs and `py.typed` |
| `tests/unit/` | Offline tests that do not start an engine |
| `tests/e2e/` | End-to-end tests, organised by tier |
| `scripts/` | Plugin build helper and the registry pin guard |

## Test tiers

Tests are separated by what they require, so the fast ones stay fast:

| Tier | Marker | Requires | Command |
| --- | --- | --- | --- |
| unit | — | nothing | `make test` |
| 1 — hermetic | — | nothing | `make test` |
| 2a — local plugins | `plugins` | a cargo build of the test plugins | `make test-plugins` |
| 2b/2c — OCI | `oci` | network access to `ghcr.io` | `make test-oci` |
| 3 — real services | `docker` | a running Docker daemon | `make test-docker` |

`make test-all` runs everything.

## Conventions

- **Never add a custom global allocator.** The host and any loaded cdylib plugin
  transfer ownership of heap allocations across the FFI boundary, which is only
  sound while both sides use the process-global system allocator. Adding
  jemalloc or mimalloc would introduce cross-allocator frees.
- **Every source file carries the Apache-2.0 header.**
- **Errors carry a stable `code`.** Raise typed exceptions from `src/errors.rs`
  rather than bare `RuntimeError`, from async paths as well as sync ones.
- **The Python API is snake_case**, including dictionary keys, while camelCase
  keys from the Node.js API are accepted as input aliases.

## Changing the Drasi crate pins

The `drasi-core`, `drasi-lib` and `drasi-plugin-sdk` versions in `Cargo.toml` are
pinned exactly, and are **not** a free choice — see
[`docs/plugins.md`](./docs/plugins.md). Published plugins record the versions
they were built against, and this host rejects any plugin that does not match on
`major.minor`. Bumping a pin without a corresponding plugin release makes every
published plugin uninstallable.

Before changing a pin, run:

```bash
make check-pins
```

CI runs the same check.

## Before opening a pull request

```bash
make fmt lint typecheck test
```
